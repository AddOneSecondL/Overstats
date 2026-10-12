"""Read-only adapter for Overwatch Assistant's authenticated combat-log API.

No credentials or player responses are cached. The XOR key is a public wire
format constant, not an authentication secret. Only nine-digit IDs are verified.
"""
from __future__ import annotations

import base64
import json
import math
import re
import time
from typing import Any

import httpx

from ..errors import ModuleError
from .engine import DashenHeroTreemapHero, DashenHeroTreemapPlayer, DashenHeroTreemapSeason
from .requests import normalize_treemap_mode

try:
    from overstats.config import config as app_config
except ModuleNotFoundError:
    from config import config as app_config


BASE_URL = "https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog"
HERO_CONFIG_URL = "https://ld5.res.netease.com/pc/zt/20241115153332/static/heroConfigs.json"
ID_XOR_KEY = b"SyC9B6eBOqQ"
MODE_TYPES = {"quick": 1, "competitive": 2, "stadium_competitive": 3, "stadium_quick": 4}
_hero_icons: dict[str, str] = {}
_hero_icons_until = 0.0


def get_hero_module_mode() -> int:
    value = getattr(app_config, "HERO_MODULE_MODE", 0)
    if value in (None, "", 0, "0"):
        return 0
    if value in (1, "1"):
        return 1
    raise ModuleError(error="invalid_hero_module_mode", message="HERO_MODULE_MODE 必须为 0 或 1。", status_code=500)


def encode_account_id(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{9}", text):
        raise ModuleError(error="invalid_mini_program_id", message="小程序查询目前只验证了 9 位数字 bnetID。", status_code=400)
    plain = json.dumps(text).encode("ascii")
    return base64.b64encode(bytes(a ^ b for a, b in zip(plain, ID_XOR_KEY))).decode("ascii")


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).strip().rstrip("%"))
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def parse_heroes(rows: list, icons: dict[str, str]) -> tuple[DashenHeroTreemapHero, ...]:
    heroes = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        hero_id = str(row.get("hero_id") or "")
        simple_summary = row.get("simple_summary")
        if not isinstance(simple_summary, list):
            raise ModuleError(error="mini_program_invalid_stats", message="小程序英雄统计格式不完整。", status_code=502)
        stats = {s.get("item_name"): s for s in simple_summary if isinstance(s, dict)}
        hours = _number(stats.get("游戏时间", {}).get("item_value"))
        # Zero rounded hours cannot supply an honest area for a time-based cloud.
        if not hero_id or hero_id in seen or hours is None or hours <= 0:
            continue
        win = stats.get("胜率", {})
        counts = re.fullmatch(r"(\d+)\s*/\s*(\d+)", str(win.get("item_comment") or ""))
        win_rate = _number(win.get("item_value"))
        if counts is None or win_rate is None or win_rate > 100:
            raise ModuleError(error="mini_program_invalid_stats", message="小程序英雄统计格式不完整。", status_code=502)
        wins, matches = map(int, counts.groups())
        if wins > matches:
            raise ModuleError(error="mini_program_invalid_stats", message="小程序英雄场次统计不一致。", status_code=502)
        seen.add(hero_id)
        heroes.append(DashenHeroTreemapHero(
            hero_guid=hero_id, hero_name=str(row.get("hero_name") or hero_id),
            hero_role={"Tank": "tank", "Damage": "dps", "Support": "healer"}.get(row.get("hero_role_type"), "open"),
            # The API provides wins/played but not losses versus draws.
            hero_level=0, match_sum=matches, win_sum=wins, loss_sum=None,
            win_rate=win_rate, win_rate_delta=win_rate - 50,
            game_time_sec=hours * 3600, game_time_text=f"{hours:g}H",
            icon_url=icons.get(hero_id, ""), kda=_number(stats.get("KDA", {}).get("item_value")),
        ))
    heroes.sort(key=lambda item: (-item.game_time_sec, item.hero_guid))
    return tuple(heroes)


class MiniProgramHeroTreemap:
    def __init__(self, *, search_module, transport=None, icons=None):
        self.search_module = search_module
        self.transport = transport
        self.icons = icons

    async def _get_data(self, client, path, params, token):
        try:
            response = await client.get(BASE_URL + path, params=params, headers={"xcxtoken": token})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = 401 if exc.response.status_code in (401, 403) else 502
            raise ModuleError(error="mini_program_http_error", message="小程序接口请求失败，请检查 xcxtoken 或稍后重试。", status_code=status) from None
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ModuleError(error="mini_program_unavailable", message="小程序接口暂不可用。", status_code=502) from None
        if not isinstance(payload, dict):
            raise ModuleError(error="mini_program_invalid_response", message="小程序返回格式异常。", status_code=502)
        code = payload.get("code")
        if code != 0:
            # Do not echo upstream messages, response bodies, request URLs or headers.
            if code in (401, 403, 20000):
                raise ModuleError(error="mini_program_not_logged_in", message="xcxtoken 已失效或未完成账号登录。", status_code=401)
            raise ModuleError(error="mini_program_query_rejected", message="小程序拒绝查询；请检查目标隐私设置和账号权限。", status_code=502)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ModuleError(error="mini_program_invalid_response", message="小程序未返回统计数据。", status_code=502)
        return data

    async def _icons(self, client):
        global _hero_icons, _hero_icons_until
        if self.icons is not None:
            return self.icons
        if time.monotonic() < _hero_icons_until:
            return _hero_icons
        try:
            response = await client.get(HERO_CONFIG_URL)
            response.raise_for_status()
            rows = response.json().get("heroConfigs", [])
            _hero_icons = {str(row["id"]): row["headSrc"] for row in rows
                           if isinstance(row, dict) and row.get("id") and
                           str(row.get("headSrc", "")).startswith("https://ld5.res.netease.com/")}
            _hero_icons_until = time.monotonic() + 3600
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            pass  # Optional portraits never prevent a statistics query.
        return _hero_icons

    async def query(self, query):
        try:
            mode = normalize_treemap_mode(query.mode, allow_stadium=True)
        except ValueError:
            raise ModuleError(error="invalid_treemap_query", message="未知英雄云图模式。", status_code=400) from None
        if mode not in MODE_TYPES:
            raise ModuleError(error="unsupported_mini_program_mode", message="小程序支持 quick、competitive、stadium_quick、stadium_competitive；不映射开放或 6v6 队列。", status_code=400)
        if query.season is not None:
            raise ModuleError(error="unsupported_mini_program_season", message="小程序英雄云图目前仅支持生涯累计，请省略 season。", status_code=400)
        token = str(query.xcxtoken or "").strip()
        if not token or not token.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in token):
            raise ModuleError(error="missing_xcxtoken", message="小程序模式需要有效的 xcxtoken 请求参数。", status_code=400)
        target = str(query.bnet_id or "").replace("＃", "#").strip()
        if not target:
            raise ModuleError(error="missing_target", message="请提供数字 bnetID 或完整战网名称。", status_code=400)
        account_id = target
        if not re.fullmatch(r"[0-9]+", target):
            try:
                result = (await self.search_module.search(target, render=False)).result
                account_id = result.bnet_id
            except Exception:
                raise ModuleError(error="bnet_search_failed", message="战网名称解析失败，可改用数字 bnetID。", status_code=502) from None
            if not account_id:
                raise ModuleError(error="bnet_not_found", message="未找到对应的数字 bnetID，请检查完整战网名称。", status_code=404)
        encoded = encode_account_id(account_id)
        params = {"type": MODE_TYPES[mode], "season_id": "total", "account_id": encoded}
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                     transport=self.transport, headers={"Accept-Encoding": "gzip, deflate"}) as client:
            summary = await self._get_data(client, "/season/total/summary", params, token)
            if summary.get("found_no_data"):
                raise ModuleError(error="hero_treemap_empty", message="该玩家在所选模式没有可用数据。", status_code=404)
            basic = summary.get("basic_info")
            if not isinstance(basic, dict) or basic.get("account_id") != encoded:
                raise ModuleError(error="mini_program_target_mismatch", message="小程序返回的玩家身份与查询目标不一致。", status_code=502)
            # Summary only includes the top three. Request the full hero list.
            data = await self._get_data(client, "/season/total/heroes/summary", {**params, "mode": 0}, token)
            rows = data.get("hero_summaries")
            if not isinstance(rows, list):
                raise ModuleError(error="mini_program_invalid_response", message="小程序未返回英雄列表。", status_code=502)
            heroes = parse_heroes(rows, await self._icons(client))
        if not heroes:
            raise ModuleError(error="hero_treemap_empty", message="该模式没有正小时数的英雄记录；小程序时长按小时取整。", status_code=404)
        name = str(basic.get("battle_name") or target)
        suffix = str(basic.get("battle_tag_num") or "").lstrip("#")
        if suffix and "#" not in name:
            name += "#" + suffix
        # Endorsement level is not player level; do not substitute it.
        player = DashenHeroTreemapPlayer(name, str(account_id), 0, "")
        season = DashenHeroTreemapSeason(None, None, False, scope="total")
        return player, season, heroes, mode
