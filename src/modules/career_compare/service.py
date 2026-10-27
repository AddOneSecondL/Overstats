from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from ...constants import iter_hero_alias_pairs
from ..bnet_search import bnet_search_module
from ..dashen_hero_treemap.mini_program import (
    MODE_TYPES, MiniProgramHeroTreemap, resolve_account_id, validate_xcxtoken,
)
from ..dashen_hero_treemap.requests import normalize_treemap_mode
from ..errors import ModuleError
from .metrics import collect_metrics, compare_radar, hero_hours, number, radar_dimensions, rows


@dataclass(frozen=True)
class CareerCompareQuery:
    player1: str
    player2: str = ""
    xcxtoken: str = field(default="", repr=False)
    hero: str = ""
    mode: str = "quick"


@dataclass(frozen=True)
class CareerCompareOutput:
    data: dict
    image: Any = None

    def to_dict(self):
        return self.data


def _identity(data, encoded, target, account_id):
    basic = data.get("basic_info")
    if not isinstance(basic, dict) or basic.get("account_id") != encoded:
        raise ModuleError(error="mini_program_target_mismatch",
                          message="小程序返回的玩家身份与查询目标不一致。", status_code=502)
    name = str(basic.get("battle_name") or target)
    suffix = str(basic.get("battle_tag_num") or "").lstrip("#")
    if suffix and "#" not in name:
        name += "#" + suffix
    return {"display_name": name, "bnet_id": account_id}


def _top_hero(hero):
    # Only use the upstream population benchmark; never substitute player values or maxima.
    chart = hero.get("hexagon_chart") or {}
    dimensions = [{**d, "value": d.get("top20")} for d in rows(chart.get("dimensions"))]
    radar_top20 = {d.get("title"): number(d.get("top20")) for d in dimensions}
    per_ten_axes = {"消灭": "消灭", "助攻": "助攻", "对英雄伤害量": "伤害", "治疗量": "治疗"}

    def benchmark_item(item, field):
        value = item.get("top20")
        # These four radar axes match the hero's per-ten-minute summary rows.
        # Do not apply them to lifetime totals, maxima or hero-specific statistics.
        if value is None and field == "summary" and str(item.get("item_type")) == "3":
            label = str(item.get("item_name") or "").strip()
            label = label.removeprefix("每10分钟").removeprefix("每十分钟")
            fallback = radar_top20.get(per_ten_axes.get(label))
            if fallback is not None and fallback >= 0:
                value = f"{fallback:.2f}"
        # Player-only comments (e.g. wins/played) do not describe the benchmark.
        return {**item, "item_value": value, "item_comment": ""}

    return {"hero_id": hero.get("hero_id"), "hero_name": hero.get("hero_name"),
            "hero_role_type": hero.get("hero_role_type"),
            "hexagon_chart": {"dimensions": dimensions},
            **{field: [benchmark_item(item, field) for item in rows(hero.get(field))]
               for field in ("simple_summary", "summary", "hero_specific_summary")}}


class CareerCompareModule:
    def __init__(self, *, search_module=None, transport=None, icons=None):
        self.search_module = search_module or bnet_search_module
        self.adapter = MiniProgramHeroTreemap(search_module=self.search_module, transport=transport, icons=icons)
        self.transport = transport

    async def _player(self, client, target, token, mode):
        target, account_id, encoded = await resolve_account_id(self.search_module, target)
        params = {"account_id": encoded, "season_id": "total", "type": MODE_TYPES[mode]}
        summary = await self.adapter._get_data(client, "/season/total/summary", params, token)
        if summary.get("found_no_data"):
            raise ModuleError(error="career_compare_empty", message="有玩家在所选模式没有生涯数据。", status_code=404)
        identity = _identity(summary, encoded, target, account_id)
        payload = await self.adapter._get_data(client, "/season/total/heroes/summary", {**params, "mode": 0}, token)
        if not isinstance(payload.get("hero_summaries"), list):
            raise ModuleError(error="mini_program_invalid_response", message="小程序未返回英雄生涯列表。", status_code=502)
        heroes = rows(payload["hero_summaries"])
        # Older profile responses provide the detailed hero metrics and six-axis chart.
        # Quick play there is lifetime; competitive entries are often individual seasons.
        # Only explicitly total competitive entries may supplement a lifetime comparison.
        notes = []
        if mode in {"quick", "competitive"} and heroes and any(not h.get("hexagon_chart") or not h.get("summary") for h in heroes):
            try:
                legacy = await self.adapter._get_data(client, "/profile", {"account_id": encoded}, token)
                _identity(legacy, encoded, target, account_id)
                detail = legacy.get("quick_play") if mode == "quick" else None
                if mode == "competitive":
                    detail = next((item for item in rows(legacy.get("competitive_plays"))
                                   if str(item.get("season_id")) == "total"), None)
                detail = detail if isinstance(detail, dict) else {}
                supplemental = {str(h.get("hero_id")): h for h in rows(detail.get("hero_summaries"))}
                heroes = [dict(h) for h in heroes]
                for hero in heroes:
                    extra = supplemental.get(str(hero.get("hero_id")), {})
                    for key in ("summary", "hero_specific_summary", "hexagon_chart"):
                        if not hero.get(key) and extra.get(key):
                            hero[key] = extra[key]
            except ModuleError as exc:
                if exc.status_code == 401 or exc.error == "mini_program_target_mismatch":
                    raise
                notes.append("详细统计暂不可用，仅显示已返回的生涯统计。")
        return {"player": identity, "heroes_raw": heroes, "notes": notes}

    async def query_compare(self, query: CareerCompareQuery, *, render=False):
        token = validate_xcxtoken(query.xcxtoken)
        if not str(query.player1).strip():
            raise ModuleError(error="missing_players", message="生涯对比需要至少一名玩家。", status_code=400)
        try:
            mode = normalize_treemap_mode(query.mode, allow_stadium=True)
        except ValueError:
            raise ModuleError(error="invalid_career_compare_mode", message="未知生涯对比模式。", status_code=400) from None
        if mode not in MODE_TYPES:
            raise ModuleError(error="invalid_career_compare_mode", message="生涯对比支持快速、竞技、角斗快速和角斗竞技。", status_code=400)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                     transport=self.transport, headers={"Accept-Encoding": "gzip, deflate"}) as client:
            sides = await asyncio.gather(*(self._player(client, target, token, mode)
                                           for target in ((query.player1, query.player2) if query.player2.strip() else (query.player1,))), return_exceptions=True)
            for side in sides:
                if isinstance(side, BaseException):
                    raise side
            icons = await self.adapter._icons(client) if render else {}
        benchmark = not query.player2.strip()
        if benchmark:
            sides.append({"player": {"display_name": "全服 Top 20%", "benchmark": "top20"},
                          "heroes_raw": [_top_hero(h) for h in sides[0]["heroes_raw"]], "notes": []})
        maps = [{str(h["hero_id"]): h for h in side["heroes_raw"] if h.get("hero_id")} for side in sides]
        keys = list(dict.fromkeys([*maps[0], *maps[1]]))
        if query.hero.strip():
            hero = query.hero.strip().casefold()
            aliases = {str(a).casefold(): str(b).casefold() for a, b in iter_hero_alias_pairs()}
            hero = aliases.get(hero, hero)
            selected = [key for key in keys if hero == key.casefold() or any(
                str(mapping.get(key, {}).get("hero_name", "")).casefold() == hero for mapping in maps)]
            if not selected:
                raise ModuleError(error="career_compare_hero_not_found", message="两名玩家的生涯记录中均未找到该英雄。", status_code=404)
            selected = selected[:1]
        else:
            selected = sorted(keys, key=lambda key: (-sum(hero_hours(m.get(key, {})) for m in maps), key))[:3]
        if not selected:
            raise ModuleError(error="career_compare_empty", message="所选模式没有可对比的英雄生涯记录。", status_code=404)
        sections = []
        for key in selected:
            compared = []
            for mapping in maps:
                raw = mapping.get(key)
                compared.append(None if raw is None else {
                    "hero_id": key, "hero_name": str(raw.get("hero_name") or key),
                    "role": str(raw.get("hero_role_type") or ""), "hours": hero_hours(raw),
                    "icon_url": icons.get(key, ""), "metrics": collect_metrics(raw),
                    "radar": radar_dimensions(raw),
                })
            sections.append({"hero_id": key, "hero_name": next(h["hero_name"] for h in compared if h),
                             "players": compared, "radar": compare_radar(*compared)})
        data = {"ok": True, "data_source": "mini_program", "scope": "total", "mode": mode,
                "comparison": "top20" if benchmark else "players",
                "selection": "specified_hero" if query.hero.strip() else "combined_top3",
                "players": [s["player"] for s in sides], "sections": sections,
                "notes": list(dict.fromkeys(note for s in sides for note in s["notes"]))}
        image = None
        if render:
            # Use the existing public-image cache, never attach xcxtoken to asset downloads.
            from ..dashen_hero_treemap.service import _prefetch_hero_icons
            from types import SimpleNamespace
            await _prefetch_hero_icons([SimpleNamespace(icon_url=h["icon_url"], recent_perks=()) for section in sections
                                       for h in section["players"] if h and h["icon_url"]])
            from .render import render_career_compare
            image = render_career_compare(data)
        return CareerCompareOutput(data, image)


career_compare_module = CareerCompareModule()
