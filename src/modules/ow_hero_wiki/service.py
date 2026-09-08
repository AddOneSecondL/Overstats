from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import html
import json
import re
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

try:
    from overstats.src.constants import CHARA_NAME, iter_hero_alias_pairs
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
except ModuleNotFoundError:
    from src.constants import CHARA_NAME, iter_hero_alias_pairs
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool

from .render import RenderedImage, render_hero_wiki_overview
from .retrieval import retrieve, evidence_context, extractive_answer
from .cache_store import IMAGE_CACHE_DIR, STRUCTURED_CACHE_DIR, build_cache_file_path, hash_text, read_bytes_file, read_json_file, write_bytes_atomic, write_json_atomic
from .requests import (
    OWHeroWikiPage,
    OWHeroWikiQuery,
    PAGE_CACHE_TTL_SECONDS,
    WikiRequests,
    normalize_hero_query,
    normalize_question,
)


HERO_WIKI_UNAVAILABLE_MESSAGE = "当前暂时无法获取英雄维基资料。"
QUESTION_UNAVAILABLE_MESSAGE = "当前问答不可用，请稍后重试。"
STRUCTURED_CACHE_TTL_SECONDS = PAGE_CACHE_TTL_SECONDS
STRUCTURED_CACHE_VERSION = 1
STRUCTURED_PAYLOAD_VERSION = "v4"
RENDER_CACHE_VERSION = "v4"
FANDOM_TITLE_OVERRIDES = {
    "junkerqueen": "Junker_Queen",
    "wreckingball": "Wrecking_Ball",
    "soldier76": "Soldier:_76",
    "dva": "D.Va",
    "torbjorn": "Torbjörn",
    "lucio": "Lúcio",
    "jetpackcat": "Jetpack_Cat",
}
ROLE_LABELS = {
    "tank": "重装",
    "damage": "输出",
    "dps": "输出",
    "support": "支援",
    "healer": "支援",
}
SECTION_STYLE_MAP = {
    "passive abilities": {"title": "被动", "accent": (102, 210, 255)},
    "passive ability": {"title": "被动", "accent": (102, 210, 255)},
    "passives": {"title": "被动", "accent": (102, 210, 255)},
    "weapons": {"title": "武器", "accent": (255, 162, 88)},
    "weapon": {"title": "武器", "accent": (255, 162, 88)},
    "special abilities": {"title": "技能", "accent": (96, 191, 255)},
    "abilities": {"title": "技能", "accent": (96, 191, 255)},
    "ultimate ability": {"title": "终极技能", "accent": (255, 208, 92)},
    "ultimate abilities": {"title": "终极技能", "accent": (255, 208, 92)},
    "minor perks": {"title": "次级威能", "accent": (117, 223, 174)},
    "major perks": {"title": "主要威能", "accent": (255, 158, 198)},
    "perks": {"title": "威能", "accent": (192, 154, 255)},
}
FIELD_LABELS = {
    "view_angle": "视角",
    "mspeed_pen": "移速惩罚",
    "kbmod": "击退抗性",
    "damage": "伤害",
    "heal": "治疗",
    "cooldown": "冷却",
    "duration": "持续",
    "ult_req": "充能",
    "range": "范围",
    "radius": "半径",
    "width": "宽度",
    "height": "高度",
    "fire_rate": "射速",
    "ammo": "弹药",
    "ammo_drain": "耗弹",
    "reload_time": "装弹",
    "pellets": "弹丸",
    "pspeed": "飞行速度",
    "pradius": "弹体半径",
    "spread": "扩散",
    "mspeed": "移速",
    "mspeed_buff": "移速加成",
    "mspeed_slow": "减速",
    "damage_amp": "伤害增幅",
    "damage_red": "减伤",
    "healing_mod": "治疗修正",
    "shot_type": "攻击类型",
    "cast_time": "施放",
    "charges": "充能次数",
    "barrier_health": "屏障生命",
    "armor": "护甲",
    "health": "生命",
    "overhealth": "额外生命",
    "dps": "DPS",
    "hps": "HPS",
    "kbspeed": "击退速度",
    "headshot_mod": "爆头倍率",
}
FIELD_ORDER = (
    "damage",
    "heal",
    "cooldown",
    "duration",
    "ult_req",
    "range",
    "radius",
    "view_angle",
    "width",
    "height",
    "fire_rate",
    "ammo",
    "ammo_drain",
    "reload_time",
    "pellets",
    "pspeed",
    "pradius",
    "spread",
    "mspeed",
    "mspeed_pen",
    "mspeed_buff",
    "mspeed_slow",
    "damage_amp",
    "damage_red",
    "healing_mod",
    "shot_type",
    "cast_time",
    "charges",
    "barrier_health",
    "armor",
    "health",
    "overhealth",
    "dps",
    "hps",
    "kbspeed",
    "kbmod",
    "headshot_mod",
)
TAG_FIELD_LABELS = {
    "ignores_barrier": "穿盾",
    "ignores_matrix": "无视矩阵吸收",
    "ignores_deflect": "无法反弹",
    "ignores_boost": "无视增伤",
    "ignores_window": "无视矩阵加成",
    "ignores_speedcap": "无视移速上限",
}
KEY_LABELS = {
    "primary fire": "主攻击",
    "secondary fire": "副攻击",
    "ability 1": "技能 1",
    "ability 2": "技能 2",
    "ability 3": "技能 3",
    "ultimate": "终极技能",
    "ultimate ability": "终极技能",
    "passive": "被动",
    "jump": "跳跃",
    "crouch": "蹲下",
    "melee": "近战",
}
DISPLAY_TEXT_MAP = {
    "barrier piercing": "穿透屏障",
    "barrier": "屏障",
    "deployable": "可部署",
    "collide": "碰撞",
    "break": "破坏",
    "displace": "位移控制",
    "shockwave": "冲击波",
    "knockdown": "击倒",
    "ability critical": "技能暴击",
    "excl unstoppable": "对非霸体生效",
    "ultimate ability": "终极技能",
    "passive ability": "被动技能",
    "minor perk": "次级威能",
    "major perk": "主要威能",
    "primary fire": "主攻击",
    "secondary fire": "副攻击",
    "projectile": "投射物",
    "proj": "投射物",
    "hitscan": "即时命中",
    "melee": "近战",
    "travel time": "飞行时间",
    "critical": "暴击",
    "evasive": "机动",
    "invulnerable": "无敌",
    "phased": "相位",
    "greater cleanse": "强净化",
    "targeted": "指向",
    "arc": "抛物线",
    "aoe": "范围",
    "spherical": "球形",
    "channeled": "持续引导",
    "negate projectile": "抵挡弹道",
    "weapon": "武器",
    "ability": "技能",
    "passive": "被动",
    "ultimate": "终极技能",
    "damage": "输出",
    "support": "支援",
    "tank": "重装",
    "headshot": "爆头",
    "instant": "立即",
}
CATEGORY_MAP = {
    "ultimateability": "ultimate",
    "ultimate ability": "ultimate",
    "ultimate": "ultimate",
    "weapon": "weapon",
    "passiveability": "passive",
    "passive ability": "passive",
    "passive": "passive",
    "ability": "ability",
    "perk": "perk",
}
CATEGORY_LABELS = {
    "ultimate": "终极技能",
    "weapon": "武器",
    "passive": "被动技能",
    "ability": "技能",
    "perk": "威能",
}


@dataclass(frozen=True)
class OWHeroWikiOutput:
    hero: str
    hero_cn: str
    hero_en: str
    role: str
    role_cn: str
    overview: str
    stats: Dict[str, Any]
    abilities: Sequence[Dict[str, Any]]
    perks: Sequence[Dict[str, Any]]
    source: Dict[str, Any]
    question: str = ""
    answer: str = ""
    citations: Sequence[Dict[str, Any]] = ()
    answer_mode: str = ""
    accent_color: Sequence[int] = (96, 191, 255)
    icon_url: str = ""
    image_url: str = ""
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": True,
            "hero": self.hero,
            "hero_cn": self.hero_cn,
            "hero_en": self.hero_en,
            "role": self.role,
            "role_cn": self.role_cn,
            "overview": self.overview,
            "stats": dict(self.stats),
            "abilities": [dict(item) for item in self.abilities],
            "perks": [dict(item) for item in self.perks],
            "source": dict(self.source),
            "icon_url": self.icon_url,
            "image_url": self.image_url,
        }
        if self.question:
            payload["question"] = self.question
            payload["answer"] = self.answer
            payload["citations"] = [dict(item) for item in self.citations]
            payload["answer_mode"] = self.answer_mode
        return payload


@dataclass(frozen=True)
class _HeroContext:
    hero_cn: str
    hero_en: str
    page_title: str
    role_key: str
    role_cn: str
    icon_url: str
    accent_color: tuple[int, int, int]
    hero_meta: Dict[str, Any]
    hero_config: Dict[str, Any]


@dataclass
class _CacheEntry:
    value: Dict[str, Any]
    expires_at: float


class OWHeroWikiModule:
    def __init__(
        self,
        requests: Optional[WikiRequests] = None,
        *,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
        structured_cache_ttl: float = STRUCTURED_CACHE_TTL_SECONDS,
    ) -> None:
        self.requests = requests or WikiRequests()
        self.config_loader = config_loader or load_query_tool
        self.structured_cache_ttl = float(structured_cache_ttl)
        self._structured_cache: Dict[str, _CacheEntry] = {}

    async def query_hero(
        self,
        query: OWHeroWikiQuery,
        *,
        render: bool = False,
    ) -> OWHeroWikiOutput:
        resolved_query = self._normalize_query(query)
        config = self._load_ow_config()
        hero_context = self._resolve_hero_context(resolved_query.hero, config)
        if hero_context is None:
            raise ModuleError(
                error="hero_wiki_hero_not_found",
                message=f"Could not resolve hero: {resolved_query.hero}",
                status_code=404,
                details={"hero": resolved_query.hero},
            )

        structured_payload = await self._load_structured_payload(
            hero_context,
        )

        answer = ""
        citations = []
        answer_mode = ""
        if resolved_query.question:
            citations = retrieve(structured_payload, resolved_query.question)
            answer = extractive_answer(citations, resolved_query.question)
            answer_mode = "extractive" if citations else "insufficient_evidence"
            try:
                generated = await self._answer_question(
                    hero_context=hero_context,
                    structured_payload=structured_payload,
                    question=resolved_query.question,
                    hits=citations,
                ) if citations else ""
                # Require valid citations before presenting model prose as grounded.
                ids = {int(value) for value in re.findall(r"\[(\d+)\]", generated)}
                if generated and ids and ids <= {hit["id"] for hit in citations}:
                    answer = generated
                    answer_mode = "generated"
            except Exception as exc:
                print(f"[overstats] hero wiki question answering failed: {type(exc).__name__}")

        output = OWHeroWikiOutput(
            hero=hero_context.hero_cn,
            hero_cn=hero_context.hero_cn,
            hero_en=str(structured_payload.get("hero_en") or hero_context.hero_en),
            role=str(structured_payload.get("role") or hero_context.role_key),
            role_cn=str(structured_payload.get("role_cn") or hero_context.role_cn),
            overview=str(structured_payload.get("overview") or ""),
            stats=dict(structured_payload.get("stats") or {}),
            abilities=tuple(dict(item) for item in list(structured_payload.get("abilities") or [])),
            perks=tuple(dict(item) for item in list(structured_payload.get("perks") or [])),
            source=dict(structured_payload.get("source") or {}),
            question=resolved_query.question,
            answer=answer,
            citations=tuple(citations),
            answer_mode=answer_mode,
            accent_color=tuple(structured_payload.get("accent_color") or hero_context.accent_color),
            icon_url=str(structured_payload.get("icon_url") or hero_context.icon_url),
            image_url=str(structured_payload.get("image_url") or ""),
        )
        if not render:
            return output

        render_cache_key = self._build_render_cache_key(output, structured_payload=structured_payload)
        cached_image = self._load_rendered_image(render_cache_key)
        if cached_image is None:
            image = render_hero_wiki_overview(
                output.to_dict(),
                accent_color=output.accent_color,
                icon_url=output.icon_url,
                image_url=output.image_url,
            )
            self._store_rendered_image(render_cache_key, image.content)
        else:
            image = RenderedImage(content=cached_image)
        return OWHeroWikiOutput(
            hero=output.hero,
            hero_cn=output.hero_cn,
            hero_en=output.hero_en,
            role=output.role,
            role_cn=output.role_cn,
            overview=output.overview,
            stats=output.stats,
            abilities=output.abilities,
            perks=output.perks,
            source=output.source,
            question=output.question,
            answer=output.answer,
            citations=output.citations,
            answer_mode=output.answer_mode,
            accent_color=output.accent_color,
            icon_url=output.icon_url,
            image_url=output.image_url,
            image=image,
        )

    async def _load_structured_payload(
        self,
        hero_context: _HeroContext,
    ) -> Dict[str, Any]:
        cache_key = self._build_cache_key(hero_context)
        now = time.time()
        cached = self._structured_cache.get(cache_key)
        if cached and cached.expires_at > now:
            return deepcopy(cached.value)

        disk_cached = self._load_structured_payload_from_disk(hero_context)
        disk_payload: Dict[str, Any] | None = None
        disk_page_hash = ""
        disk_expires_at = 0.0
        disk_created_at = now
        if disk_cached is not None:
            disk_payload, disk_page_hash, disk_expires_at, disk_created_at = disk_cached
            self._structured_cache[cache_key] = _CacheEntry(value=deepcopy(disk_payload), expires_at=disk_expires_at)
            if disk_expires_at > now:
                return deepcopy(disk_payload)

        try:
            page = await self.requests.fetch_page(hero_context.page_title)
        except ValueError as exc:
            raise ModuleError(
                error="hero_wiki_page_not_found",
                message=str(exc),
                status_code=404,
                details={"hero": hero_context.hero_cn, "page_title": hero_context.page_title},
            ) from exc
        except Exception as exc:
            raise ModuleError(
                error="hero_wiki_fetch_failed",
                message=HERO_WIKI_UNAVAILABLE_MESSAGE,
                status_code=502,
                details={"hero": hero_context.hero_cn, "page_title": hero_context.page_title, "exception": type(exc).__name__},
            ) from exc

        expires_at = now + self.structured_cache_ttl
        if disk_payload is not None and disk_page_hash and disk_page_hash == page.wikitext_hash:
            reused_payload = deepcopy(disk_payload)
            reused_payload["_page_hash"] = page.wikitext_hash
            source_payload = reused_payload.get("source")
            if isinstance(source_payload, dict):
                source_payload["fandom_page_title"] = page.page_title
                source_payload["fandom_page_id"] = page.page_id
                source_payload["fandom_url"] = page.source_url
                source_payload["image_url"] = page.image_url
            reused_payload["image_url"] = page.image_url
            self._store_structured_payload_to_disk(
                hero_context,
                reused_payload,
                page_hash=page.wikitext_hash,
                created_at=disk_created_at,
                expires_at=expires_at,
                validated_at=now,
            )
            self._structured_cache[cache_key] = _CacheEntry(value=deepcopy(reused_payload), expires_at=expires_at)
            return reused_payload

        structured_payload = await self._build_structured_payload(hero_context, page)
        structured_payload["_page_hash"] = page.wikitext_hash
        self._store_structured_payload_to_disk(
            hero_context,
            structured_payload,
            page_hash=page.wikitext_hash,
            created_at=now,
            expires_at=expires_at,
            validated_at=now,
        )
        self._structured_cache[cache_key] = _CacheEntry(
            value=deepcopy(structured_payload),
            expires_at=expires_at,
        )
        return deepcopy(structured_payload)

    async def _build_structured_payload(self, hero_context: _HeroContext, page: OWHeroWikiPage) -> Dict[str, Any]:
        variables = _extract_variables(page.wikitext)
        infobox = _parse_infobox(page.wikitext, variables=variables)
        abilities = _extract_section_cards(page.wikitext, "Abilities", variables=variables)
        perks = _extract_section_cards(page.wikitext, "Perks", variables=variables)

        if not abilities and not perks:
            raise ModuleError(
                error="hero_wiki_parse_failed",
                message="The wiki page did not expose readable hero abilities or perks.",
                status_code=502,
                details={"hero": hero_context.hero_cn, "page_title": page.page_title},
            )

        overview = _clean_query_tool_text(hero_context.hero_config.get("Description")) or _extract_overview_text(page.wikitext, variables=variables)
        role_key = _normalize_role_key(hero_context.role_key or infobox.get("role"))
        role_cn = ROLE_LABELS.get(role_key, hero_context.role_cn or _localize_inline_text(str(infobox.get("role") or "")))
        stats = {
            "health": int(infobox.get("health") or 0),
            "armor": int(infobox.get("armor") or 0),
            "shield": int(infobox.get("shield") or 0),
            "total_hp": int(infobox.get("total_hp") or 0),
            "health_6v6": int(infobox.get("health_6v6") or 0),
            "armor_6v6": int(infobox.get("armor_6v6") or 0),
            "shield_6v6": int(infobox.get("shield_6v6") or 0),
            "total_hp_6v6": int(infobox.get("total_hp_6v6") or 0),
            "minor_perk_xp": int(infobox.get("minor_perk_xp") or 0),
            "major_perk_xp": int(infobox.get("major_perk_xp") or 0),
            "preset_bonus_hp": 150 if role_key == "tank" else 0,
        }
        stats["preset_mode_total_hp"] = int(stats.get("total_hp") or 0) + int(stats.get("preset_bonus_hp") or 0)

        structured = {
            "hero_cn": hero_context.hero_cn,
            "hero_en": str(infobox.get("name_en") or hero_context.hero_en).replace("_", " "),
            "role": role_key,
            "role_cn": role_cn,
            "overview": _clean_localized_text(overview),
            "stats": stats,
            "abilities": self._localize_ability_cards(abilities, hero_context),
            "perks": self._localize_perk_cards(perks, hero_context),
            "source": {
                "fandom_page_title": page.page_title,
                "fandom_page_id": page.page_id,
                "fandom_url": page.source_url,
                "image_url": page.image_url,
                "content_hash": page.wikitext_hash,
            },
            "accent_color": hero_context.accent_color,
            "icon_url": hero_context.icon_url,
            "image_url": page.image_url,
        }

        await self._translate_free_text_fields(structured)
        return structured

    async def _translate_free_text_fields(self, payload: Dict[str, Any]) -> None:
        targets: list[tuple[tuple[Any, ...], str]] = []
        if _needs_translation(payload.get("overview")):
            targets.append((("overview",), str(payload.get("overview") or "")))

        for section_name in ("abilities", "perks"):
            for index, card in enumerate(list(payload.get(section_name) or [])):
                if not isinstance(card, dict):
                    continue
                if not card.get("name_cn") and _needs_translation(card.get("name_en")):
                    targets.append(((section_name, index, "name_cn"), str(card["name_en"])))
                if _needs_translation(card.get("description")):
                    targets.append(((section_name, index, "description"), str(card.get("description") or "")))
                for stat_index, stat in enumerate(card.get("stats") or []):
                    if re.search(r"[A-Za-z]{3,}", str(stat.get("value") or "")):
                        targets.append(((section_name, index, "stats", stat_index, "value"), str(stat["value"])))
                for note_index, note in enumerate(list(card.get("notes") or [])):
                    if _needs_translation(note):
                        targets.append(((section_name, index, "notes", note_index), str(note or "")))
                for note_index, note in enumerate(list(card.get("mode_notes") or [])):
                    if _needs_translation(note):
                        targets.append(((section_name, index, "mode_notes", note_index), str(note or "")))

        if not targets:
            return

        glossary = _build_translation_glossary(payload)
        try:
            translated_texts = await self.requests.translate_texts([text for _, text in targets], glossary=glossary)
        except Exception as exc:
            print(f"[overstats] hero wiki translation failed: {type(exc).__name__}: {exc}")
            return
        if not translated_texts:
            return

        for (path, original), translated_text in zip(targets, translated_texts):
            if "stats" in path:
                if re.findall(r"\d+(?:\.\d+)?", original) != re.findall(r"\d+(?:\.\d+)?", translated_text):
                    continue
            _set_nested_value(payload, path, _clean_localized_text(translated_text))

    async def _answer_question(
        self,
        *,
        hero_context: _HeroContext,
        structured_payload: Mapping[str, Any],
        question: str,
        hits: list[Dict[str, Any]],
    ) -> str:
        glossary = _build_translation_glossary(structured_payload)
        context_text = evidence_context(hits)
        answer = await self.requests.answer_question(
            hero_cn=hero_context.hero_cn,
            hero_en=str(structured_payload.get("hero_en") or hero_context.hero_en),
            question=question,
            context_text=context_text,
            glossary=glossary,
        )
        answer = _clean_localized_text(answer or "")
        return answer or QUESTION_UNAVAILABLE_MESSAGE

    def _structured_cache_path(self, hero_context: _HeroContext) -> Any:
        cache_key = self._build_cache_key(hero_context)
        label = hero_context.hero_en or hero_context.hero_cn
        return build_cache_file_path(STRUCTURED_CACHE_DIR, cache_key, extension=".json", label=label)

    def _load_structured_payload_from_disk(self, hero_context: _HeroContext) -> tuple[Dict[str, Any], str, float, float] | None:
        payload = read_json_file(self._structured_cache_path(hero_context))
        if not isinstance(payload, dict):
            return None
        if int(payload.get("cache_version") or 0) != STRUCTURED_CACHE_VERSION:
            return None
        if str(payload.get("payload_version") or "") != STRUCTURED_PAYLOAD_VERSION:
            return None
        structured_payload = payload.get("payload")
        if not isinstance(structured_payload, dict):
            return None
        page_hash = str(payload.get("page_hash") or structured_payload.get("_page_hash") or "")
        structured_copy = deepcopy(structured_payload)
        if page_hash:
            structured_copy["_page_hash"] = page_hash
        return (
            structured_copy,
            page_hash,
            float(payload.get("expires_at") or 0.0),
            float(payload.get("created_at") or 0.0),
        )

    def _store_structured_payload_to_disk(
        self,
        hero_context: _HeroContext,
        payload: Mapping[str, Any],
        *,
        page_hash: str,
        created_at: float,
        expires_at: float,
        validated_at: float,
    ) -> None:
        write_json_atomic(
            self._structured_cache_path(hero_context),
            {
                "cache_version": STRUCTURED_CACHE_VERSION,
                "payload_version": STRUCTURED_PAYLOAD_VERSION,
                "hero_cn": hero_context.hero_cn,
                "hero_en": hero_context.hero_en,
                "page_title": hero_context.page_title,
                "page_hash": page_hash,
                "payload": dict(payload),
                "created_at": float(created_at),
                "validated_at": float(validated_at),
                "expires_at": float(expires_at),
            },
        )

    def _build_render_cache_key(self, output: OWHeroWikiOutput, *, structured_payload: Mapping[str, Any]) -> str:
        render_payload = {
            "render_version": RENDER_CACHE_VERSION,
            "hero": output.hero,
            "hero_cn": output.hero_cn,
            "hero_en": output.hero_en,
            "role": output.role,
            "role_cn": output.role_cn,
            "overview": output.overview,
            "stats": dict(output.stats),
            "abilities": [dict(item) for item in output.abilities],
            "perks": [dict(item) for item in output.perks],
            "question": output.question,
            "answer": output.answer,
            "citations": list(output.citations),
            "answer_mode": output.answer_mode,
            "accent_color": list(output.accent_color),
            "icon_url": output.icon_url,
            "image_url": output.image_url,
            "page_hash": str(structured_payload.get("_page_hash") or ""),
        }
        return hash_text(json.dumps(render_payload, ensure_ascii=False, sort_keys=True))

    def _rendered_image_path(self, render_cache_key: str) -> Any:
        return build_cache_file_path(IMAGE_CACHE_DIR, render_cache_key, extension=".png", label="hero-wiki")

    def _load_rendered_image(self, render_cache_key: str) -> bytes | None:
        return read_bytes_file(self._rendered_image_path(render_cache_key))

    def _store_rendered_image(self, render_cache_key: str, body: bytes) -> None:
        if not body:
            return
        write_bytes_atomic(self._rendered_image_path(render_cache_key), body)

    def _localize_ability_cards(self, cards: Sequence[Mapping[str, Any]], hero_context: _HeroContext) -> list[Dict[str, Any]]:
        loadouts = [item for item in list(hero_context.hero_config.get("Loadouts") or []) if isinstance(item, dict)]
        buckets = _bucket_query_tool_items(loadouts)
        matched_items = _match_cards_to_query_tool_items(cards, buckets)
        localized_cards = []
        for index, card in enumerate(cards):
            group_key = _card_group_key(card)
            matched_item = matched_items.get(index, {})
            name_cn = _clean_query_tool_text(matched_item.get("Name")) if matched_item else ""
            description_cn = _clean_query_tool_text(matched_item.get("Description")) if matched_item else ""
            if _contains_placeholder(description_cn):
                description_cn = ""

            name_en = _clean_localized_text(card.get("ability_name") or "")
            description_en = _clean_localized_text(card.get("official_description") or card.get("old_description") or "")
            key_raw = _clean_localized_text(card.get("key") or "")
            ability_type_raw = _clean_localized_text(card.get("ability_type") or "")
            style = _section_style(card.get("_group_title") or ability_type_raw or "Abilities")
            localized_cards.append(
                {
                    "name": name_cn or name_en,
                    "name_cn": name_cn or "",
                    "name_en": name_en,
                    "description": description_cn or description_en,
                    "description_en": description_en,
                    "key": key_raw,
                    "key_cn": _localize_key_label(key_raw),
                    "category": group_key,
                    "category_cn": _localize_category_label(group_key, ability_type_raw),
                    "group_title": str(card.get("_group_title") or ""),
                    "group_title_cn": style["title"],
                    "accent": style["accent"],
                    "stats": _build_card_stats(card),
                    "tags": _build_card_tags(card),
                    "notes": _build_card_notes(card),
                    "mode_notes": _build_card_mode_notes(card),
                }
            )
        return localized_cards

    def _localize_perk_cards(self, cards: Sequence[Mapping[str, Any]], hero_context: _HeroContext) -> list[Dict[str, Any]]:
        perks = [item for item in list(hero_context.hero_config.get("Perks") or []) if isinstance(item, dict)]
        localized_cards = []
        for index, card in enumerate(cards):
            wiki_name = _normalize_query_key(card.get("ability_name"))
            # Local configuration and Wiki can have different perk sets/order.
            # Only explicit name matches are safe; do not infer by list position.
            matched_item = next((item for item in perks if wiki_name and any(
                _normalize_query_key(item.get(key)) == wiki_name
                for key in ("Name", "NameEN", "name_en", "WikiName")
            )), {})
            name_cn = _clean_query_tool_text(matched_item.get("Name")) if isinstance(matched_item, dict) else ""
            description_cn = _clean_query_tool_text(matched_item.get("Description")) if isinstance(matched_item, dict) else ""
            if _contains_placeholder(description_cn):
                description_cn = ""

            name_en = _clean_localized_text(card.get("ability_name") or "")
            description_en = _clean_localized_text(card.get("official_description") or card.get("old_description") or "")
            style = _section_style(card.get("_group_title") or "Perks")
            localized_cards.append(
                {
                    "name": name_cn or name_en,
                    "name_cn": name_cn or "",
                    "name_en": name_en,
                    "description": description_cn or description_en,
                    "description_en": description_en,
                    "key": _clean_localized_text(card.get("key") or ""),
                    "key_cn": _localize_key_label(card.get("key") or ""),
                    "category": "perk",
                    "category_cn": "威能",
                    "group_title": str(card.get("_group_title") or ""),
                    "group_title_cn": style["title"],
                    "accent": style["accent"],
                    "stats": _build_card_stats(card),
                    "tags": _build_card_tags(card),
                    "notes": _build_card_notes(card),
                    "mode_notes": _build_card_mode_notes(card),
                }
            )
        return localized_cards

    def _normalize_query(self, query: OWHeroWikiQuery) -> OWHeroWikiQuery:
        try:
            hero = normalize_hero_query(query.hero)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_hero_wiki_query",
                message=str(exc),
                status_code=400,
                hint='Example: {"hero":"猎空"}',
            ) from exc
        question = normalize_question(query.question)
        if not question:
            for delimiter in ("?", "？"):
                if delimiter in hero:
                    hero_text, question_text = hero.split(delimiter, 1)
                    hero = hero_text.strip()
                    question = question_text.strip()
                    break
        try:
            hero = normalize_hero_query(hero)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_hero_wiki_query",
                message=str(exc),
                status_code=400,
                hint='Example: {"hero":"猎空"}',
            ) from exc
        return OWHeroWikiQuery(hero=hero, question=question)

    def _load_ow_config(self) -> Dict[str, Any]:
        try:
            config = self.config_loader()
        except Exception as exc:
            print(f"[overstats] failed to load query_tool for hero wiki: {type(exc).__name__}: {exc}")
            return {}
        return config if isinstance(config, dict) else {}

    def _resolve_hero_context(self, hero_query: str, config: Mapping[str, Any]) -> Optional[_HeroContext]:
        normalized_query = _normalize_query_key(hero_query)
        if not normalized_query:
            return None

        hero_cn = _build_alias_lookup().get(normalized_query)
        if not hero_cn:
            hero_cn = _resolve_hero_name_from_query_tool(hero_query, config)
        if not hero_cn:
            return None

        hero_aliases = CHARA_NAME.get(hero_cn) or []
        hero_en = str(hero_aliases[1] if len(hero_aliases) > 1 else hero_cn)
        page_title = _normalize_fandom_title(hero_en)
        hero_meta = _find_hero_meta(config, hero_cn)
        hero_config = _find_hero_config(config, hero_cn)
        role_key = _normalize_role_key(
            hero_meta.get("roleType")
            or hero_meta.get("heroRole")
            or hero_config.get("Class")
            or ""
        )
        role_cn = ROLE_LABELS.get(role_key, "")
        icon_url = ""
        for key in ("smallIconUrl", "ddHeroIcon", "icon", "cover"):
            candidate = str(hero_meta.get(key) or "").strip()
            if candidate:
                icon_url = candidate
                break
        accent_color = _parse_color(hero_config.get("Color")) or _parse_color(hero_config.get("sRGBColor")) or (96, 191, 255)
        return _HeroContext(
            hero_cn=hero_cn,
            hero_en=hero_en,
            page_title=page_title,
            role_key=role_key,
            role_cn=role_cn,
            icon_url=icon_url,
            accent_color=accent_color,
            hero_meta=hero_meta,
            hero_config=hero_config,
        )

    def _build_cache_key(self, hero_context: _HeroContext) -> str:
        return f"{hero_context.hero_cn}\t{hero_context.page_title}"


def _normalize_query_key(text: Any) -> str:
    normalized = str(text or "").strip().lower().replace("：", ":")
    return re.sub(r"[^0-9a-z一-鿿]+", "", normalized)


def _normalize_role_key(text: Any) -> str:
    normalized = _normalize_field_key(text)
    if normalized == "healer":
        return "support"
    if normalized == "dps":
        return "damage"
    return normalized


def _normalize_field_key(text: Any) -> str:
    raw = str(text or "").strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^0-9a-z_]+", "", raw)


def _normalize_free_key(text: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return re.sub(r"[^0-9a-z]+", " ", normalized).strip()


def _build_alias_lookup() -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for alias, hero_name in iter_hero_alias_pairs():
        normalized = _normalize_query_key(alias)
        if normalized:
            lookup[normalized] = hero_name
    return lookup


def _resolve_hero_name_from_query_tool(hero_query: str, config: Mapping[str, Any]) -> str:
    normalized_query = _normalize_query_key(hero_query)
    for item in list(config.get("heroList") or []):
        if not isinstance(item, dict):
            continue
        hero_name = str(item.get("name") or "").strip()
        if hero_name and _normalize_query_key(hero_name) == normalized_query:
            return hero_name
    return ""


def _normalize_fandom_title(hero_en: str) -> str:
    key = _normalize_query_key(hero_en)
    override = FANDOM_TITLE_OVERRIDES.get(key)
    if override:
        return override
    return str(hero_en or "").replace(" ", "_")


def _find_hero_meta(config: Mapping[str, Any], hero_cn: str) -> Dict[str, Any]:
    for item in list(config.get("heroList") or []):
        if isinstance(item, dict) and str(item.get("name") or "").strip() == hero_cn:
            return dict(item)
    return {}


def _find_hero_config(config: Mapping[str, Any], hero_cn: str) -> Dict[str, Any]:
    hero_config = config.get("heroConfig")
    if not isinstance(hero_config, dict):
        return {}
    for item in hero_config.values():
        if isinstance(item, dict) and str(item.get("Name") or "").strip() == hero_cn:
            return dict(item)
    return {}


def _parse_color(value: Any) -> tuple[int, int, int] | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) not in {6, 8}:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _contains_placeholder(text: Any) -> bool:
    return bool(re.search(r"%\d+\$s", str(text or "")))


def _contains_cjk(text: Any) -> bool:
    return bool(re.search(r"[㐀-鿿]", str(text or "")))


def _needs_translation(text: Any) -> bool:
    normalized = str(text or "").strip()
    if not normalized or _contains_cjk(normalized):
        return False
    alphabetic = re.findall(r"[A-Za-z]", normalized)
    return len(alphabetic) >= 3


def _clean_localized_text(text: Any) -> str:
    value = html.unescape(str(text or "").replace("\r", ""))
    value = value.replace("%%", "%")
    value = value.replace("&nbsp;", " ").replace("&#160;", " ")
    value = re.sub(r"\s+\n", "\n", value)
    value = re.sub(r"\n\s+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _clean_query_tool_text(text: Any) -> str:
    return _clean_localized_text(str(text or "").replace("\\n", "\n").replace("%%", "%"))


def _localize_inline_text(text: Any) -> str:
    result = _clean_localized_text(text)
    if not result:
        return ""
    replacements = sorted(DISPLAY_TEXT_MAP.items(), key=lambda item: len(item[0]), reverse=True)
    for source_text, target_text in replacements:
        result = re.sub(rf"\b{re.escape(source_text)}\b", target_text, result, flags=re.IGNORECASE)
    result = re.sub(r"(\d+(?:\.\d+)?)\s*seconds?\b", r"\1 秒", result, flags=re.IGNORECASE)
    result = re.sub(r"(\d+(?:\.\d+)?)\s*meters?\b", r"\1 米", result, flags=re.IGNORECASE)
    result = re.sub(r"(\d+(?:\.\d+)?)\s*points?\b", r"\1 点", result, flags=re.IGNORECASE)
    result = re.sub(r"\bper second\b", "/秒", result, flags=re.IGNORECASE)
    result = re.sub(r"\bper hit\b", "/次命中", result, flags=re.IGNORECASE)
    result = re.sub(r"\bper shot\b", "/次射击", result, flags=re.IGNORECASE)
    result = re.sub(r"\s*/\s*", " / ", result)
    return _clean_localized_text(result)


def _wiki_generic_template_to_text(inner: str) -> str:
    raw = str(inner or "").strip()
    if not raw or raw.startswith("#"):
        return ""
    parts = [part.strip() for part in raw.split("|") if part.strip()]
    if not parts:
        return ""
    named = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            named[_normalize_field_key(key)] = value.strip()
    if "text" in named:
        return named["text"]
    if len(parts) >= 2:
        return parts[1]
    return parts[0]


def _clean_markup(text: Any, *, variables: Mapping[str, str] | None = None) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\r", "")
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<ref[^>/]*/>", "", cleaned)
    cleaned = re.sub(r"<ref[^>]*?>.*?</ref>", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")
    cleaned = cleaned.replace("&nbsp;", " ").replace("&#160;", " ")

    if variables:
        def repl_var(match: re.Match[str]) -> str:
            key = _normalize_field_key(match.group(1))
            return str(variables.get(key, ""))
        cleaned = re.sub(r"\{\{#var:\s*([^}]+?)\s*\}\}", repl_var, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(
        r"\{\{#vardefine(?:echo)?\s*:\s*([^|{}]+?)\|([^{}]+?)\}\}",
        lambda match: match.group(2),
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\{\{tt\|([^|{}]+)(?:\|[^{}]*)?\}\}",
        lambda match: match.group(1),
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\{\{flag\|([^}|]+).*?\}\}",
        lambda match: match.group(1),
        cleaned,
        flags=re.IGNORECASE,
    )

    def repl_al(match: re.Match[str]) -> str:
        inner = match.group(1)
        text_match = re.search(r"\btext\s*=\s*([^|]+)", inner, flags=re.IGNORECASE)
        if text_match:
            return text_match.group(1).strip()
        parts = [part.strip() for part in inner.split("|") if part.strip()]
        return parts[-1] if parts else ""

    cleaned = re.sub(r"\{\{(?:al|Al)\|([^{}]+?)\}\}", repl_al, cleaned)

    def repl_proj(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split("|") if part.strip()]
        return " / ".join(_localize_inline_text(part) for part in parts)

    cleaned = re.sub(r"\{\{proj\|([^{}]+?)\}\}", repl_proj, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\{\{CalcDPS\|[^{}]+?\}\}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\{\{#ifeq:[^{}]+?\}\}", "", cleaned, flags=re.IGNORECASE)

    while True:
        previous = cleaned
        cleaned = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", cleaned)
        cleaned = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cleaned)
        cleaned = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", cleaned)
        cleaned = re.sub(
            r"\{\{([^{}]*?)\}\}",
            lambda match: _wiki_generic_template_to_text(match.group(1)),
            cleaned,
        )
        if cleaned == previous:
            break

    cleaned = cleaned.replace("'''", "").replace("''", "")
    cleaned = cleaned.replace(";;", " / ").replace("::", " / ")
    cleaned = cleaned.replace("✔", "可爆头").replace("✘", "不可爆头")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return _clean_localized_text(cleaned.strip(" \n|"))


def _extract_variables(text: str) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    for match in re.finditer(
        r"\{\{#vardefine(?:echo)?\s*:\s*([^|{}]+?)\|([^{}]+?)\}\}",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        variables[_normalize_field_key(match.group(1))] = _clean_markup(match.group(2))
    return variables


def _extract_template_blocks(text: str, template_pattern: str) -> list[str]:
    blocks = []
    start_re = re.compile(template_pattern, flags=re.IGNORECASE)
    collecting = False
    depth = 0
    current_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not collecting and start_re.match(stripped):
            collecting = True
            current_lines = [raw_line]
            depth = raw_line.count("{{") - raw_line.count("}}")
            if depth <= 0:
                blocks.append("\n".join(current_lines))
                collecting = False
            continue
        if collecting:
            current_lines.append(raw_line)
            depth += raw_line.count("{{") - raw_line.count("}}")
            if depth <= 0:
                blocks.append("\n".join(current_lines))
                collecting = False
    return blocks


def _parse_template_fields(block: str, *, variables: Mapping[str, str] | None = None) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    current_key: str | None = None
    for raw_line in str(block or "").splitlines()[1:]:
        stripped = raw_line.strip()
        if stripped in {"}}", "}"}:
            continue
        if stripped.startswith("|"):
            content = stripped[1:]
            if "=" in content:
                key, value = content.split("=", 1)
                current_key = _normalize_field_key(key)
                fields[current_key] = value.strip()
            else:
                current_key = None
        elif current_key is not None and stripped:
            fields[current_key] = (fields[current_key] + "\n" + stripped).strip()
    return {key: _clean_markup(value, variables=variables) for key, value in fields.items()}


def _extract_section_text(wikitext: str, title: str) -> str:
    match = re.search(
        rf"==\s*{re.escape(title)}\s*==\s*(.*?)(?=\n==[^=]|\Z)",
        str(wikitext or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _split_subsections(section_text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"===\s*(.*?)\s*===", str(section_text or "")))
    sections = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        sections.append((title, section_text[start:end].strip()))
    return sections


def _section_style(title: Any) -> Dict[str, Any]:
    normalized_title = _normalize_free_key(title)
    if normalized_title in SECTION_STYLE_MAP:
        return dict(SECTION_STYLE_MAP[normalized_title])
    localized_title = _localize_inline_text(title)
    return {"title": localized_title or str(title or "").strip(), "accent": (120, 180, 255)}


def _to_number(value: Any, default: int | float = 0) -> int | float:
    if isinstance(value, (int, float)):
        return value
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    if not match:
        return default
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _parse_infobox(wikitext: str, *, variables: Mapping[str, str] | None = None) -> Dict[str, Any]:
    blocks = _extract_template_blocks(wikitext, r"\{\{Infobox character\b")
    if not blocks:
        return {}
    raw = _parse_template_fields(blocks[0], variables=variables)
    health = int(_to_number(raw.get("health"), 0))
    armor = int(_to_number(raw.get("armor"), 0))
    shield = int(_to_number(raw.get("shield"), 0))
    health_6v6 = int(_to_number(raw.get("health6v6"), 0))
    armor_6v6 = int(_to_number(raw.get("armor6v6"), 0))
    shield_6v6 = int(_to_number(raw.get("shield6v6"), 0))
    total_hp = health + armor + shield if (health or armor or shield) else 0
    total_hp_6v6 = health_6v6 + armor_6v6 + shield_6v6 if (health_6v6 or armor_6v6 or shield_6v6) else 0
    return {
        "name_en": str(raw.get("name") or "").strip(),
        "role": str(raw.get("role") or "").strip(),
        "sub_role": str(raw.get("sub_role") or raw.get("subrole") or "").strip(),
        "health": health,
        "armor": armor,
        "shield": shield,
        "total_hp": total_hp,
        "health_6v6": health_6v6,
        "armor_6v6": armor_6v6,
        "shield_6v6": shield_6v6,
        "total_hp_6v6": total_hp_6v6,
        "minor_perk_xp": int(_to_number(raw.get("minor_perk_xp"), 0)),
        "major_perk_xp": int(_to_number(raw.get("major_perk_xp"), 0)),
    }


def _extract_overview_text(wikitext: str, *, variables: Mapping[str, str] | None = None) -> str:
    overview_text = _extract_section_text(wikitext, "Overview")
    if not overview_text:
        return ""
    lines = []
    for raw_line in overview_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("<gallery") or stripped.startswith("File:") or stripped.startswith("</gallery>"):
            continue
        if stripped.startswith("{{"):
            continue
        cleaned = _clean_markup(stripped, variables=variables)
        if cleaned:
            lines.append(cleaned)
    return _clean_localized_text(" ".join(lines[:3]))


def _parse_cards_from_text(block_text: str, *, variables: Mapping[str, str] | None = None) -> list[Dict[str, str]]:
    cards = []
    for block in _extract_template_blocks(block_text, r"\{\{Ability[_ ]details\b"):
        fields = _parse_template_fields(block, variables=variables)
        if fields.get("ability_name"):
            cards.append(fields)
    return cards


def _extract_section_cards(wikitext: str, title: str, *, variables: Mapping[str, str] | None = None) -> list[Dict[str, Any]]:
    section_text = _extract_section_text(wikitext, title)
    if not section_text:
        return []
    subsections = _split_subsections(section_text)
    if not subsections:
        subsections = [(title, section_text)]
    cards: list[Dict[str, Any]] = []
    for subsection_title, subsection_body in subsections:
        parsed_cards = _parse_cards_from_text(subsection_body, variables=variables)
        if not parsed_cards and subsection_title == title:
            parsed_cards = _parse_cards_from_text(section_text, variables=variables)
        if not parsed_cards:
            continue
        style = _section_style(subsection_title)
        for card in parsed_cards:
            enriched = dict(card)
            enriched["_group_title"] = subsection_title
            enriched["_group_title_cn"] = style["title"]
            enriched["_accent"] = style["accent"]
            cards.append(enriched)
    return cards


def _split_parts(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"\s*/\s*|\n|;;|::|,", str(value)) if part.strip()]


def _build_card_tags(fields: Mapping[str, Any]) -> list[str]:
    tags = []
    headshot = _normalize_field_key(fields.get("headshot", ""))
    if headshot:
        if headshot in {"0", "false", "no"} or "不可爆头" in str(fields.get("headshot") or ""):
            tags.append("不可爆头")
        elif headshot in {"1", "true", "yes"} or "可爆头" in str(fields.get("headshot") or ""):
            tags.append("可爆头")

    for field_name, label in TAG_FIELD_LABELS.items():
        normalized = _normalize_field_key(fields.get(field_name, ""))
        if normalized in {"1", "true", "yes"}:
            tags.append(label)
        elif normalized == "partial":
            tags.append(f"部分{label}")

    for keyword in _split_parts(fields.get("ability_keywords", "")):
        localized = _localize_inline_text(keyword)
        if localized:
            tags.append(localized)
    return _dedupe_strings(tags)[:12]


def _build_card_stats(fields: Mapping[str, Any]) -> list[Dict[str, str]]:
    items = []
    for key in FIELD_ORDER:
        value = _clean_localized_text(fields.get(key, ""))
        if not value:
            continue
        if key == "cooldown" and value in {"0", "0 second", "0 seconds"}:
            continue
        normalized = _normalize_free_key(value)
        if normalized in {"none", "n a"}:
            continue
        items.append(
            {
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "value": _localize_inline_text(value.replace("\n", " / ")),
            }
        )
    return items


def _build_card_notes(fields: Mapping[str, Any]) -> list[str]:
    notes = []
    for source_key in ("ability_details", "coop_details"):
        source = fields.get(source_key, "")
        if not source:
            continue
        for raw_line in str(source).splitlines():
            line = raw_line.strip().lstrip("*").strip()
            if not line:
                continue
            cleaned = _clean_markup(line)
            lowered = cleaned.lower()
            if not cleaned or "calcdps" in lowered or "damage per second" in lowered or "healing per second" in lowered:
                continue
            prefix = "PvE / 合作模式：" if source_key == "coop_details" else ""
            notes.append(prefix + _localize_inline_text(cleaned))
    return _dedupe_strings(notes)


def _build_card_mode_notes(fields: Mapping[str, Any]) -> list[str]:
    notes = []
    for source_key in ("6v6_details",):
        source = fields.get(source_key, "")
        if not source:
            continue
        for raw_line in str(source).splitlines():
            line = raw_line.strip().lstrip("*").strip()
            if not line:
                continue
            cleaned = _clean_markup(line)
            lowered = cleaned.lower()
            if not cleaned or "calcdps" in lowered or "damage per second" in lowered or "healing per second" in lowered:
                continue
            notes.append("6v6：" + _localize_inline_text(cleaned))
    return _dedupe_strings(notes)


def _bucket_query_tool_items(items: Sequence[Mapping[str, Any]]) -> Dict[str, list[Mapping[str, Any]]]:
    buckets: Dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        category = _normalize_query_tool_category(item.get("Category") or item.get("category") or "")
        if not category:
            continue
        buckets.setdefault(category, []).append(item)
    return buckets


def _normalize_query_tool_category(value: Any) -> str:
    raw = str(value or "").strip()
    return CATEGORY_MAP.get(_normalize_field_key(raw), CATEGORY_MAP.get(_normalize_free_key(raw), ""))


def _card_group_key(card: Mapping[str, Any]) -> str:
    ability_type = _normalize_query_tool_category(card.get("ability_type") or "")
    if ability_type:
        return ability_type
    key = _normalize_free_key(card.get("key") or "")
    if key in KEY_LABELS:
        if key.startswith("primary") or key.startswith("secondary"):
            return "weapon"
        if key.startswith("ability"):
            return "ability"
        if key.startswith("ultimate"):
            return "ultimate"
        if key == "passive":
            return "passive"
    group_title = _normalize_free_key(card.get("_group_title") or "")
    if "perk" in group_title:
        return "perk"
    return "ability"


def _match_cards_to_query_tool_items(
    cards: Sequence[Mapping[str, Any]],
    buckets: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[int, Mapping[str, Any]]:
    matched: Dict[int, Mapping[str, Any]] = {}
    grouped_cards: Dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for index, card in enumerate(cards):
        grouped_cards.setdefault(_card_group_key(card), []).append((index, card))

    for group_key, indexed_cards in grouped_cards.items():
        items = list(buckets.get(group_key) or [])
        if not items:
            continue
        sorted_cards = sorted(
            indexed_cards,
            key=lambda item: _query_tool_card_sort_key(item[1], group_key=group_key, original_index=item[0]),
        )
        for (card_index, _), matched_item in zip(sorted_cards, items):
            matched[card_index] = matched_item
    return matched


def _query_tool_card_sort_key(card: Mapping[str, Any], *, group_key: str, original_index: int) -> tuple[int, int]:
    normalized_key = _normalize_free_key(card.get("key") or "")
    if group_key == "ability":
        slot_order = {
            "ability1": 0,
            "ability2": 1,
            "ability3": 2,
            "secondaryfire": 3,
            "primaryfire": 4,
            "melee": 5,
            "jump": 6,
            "crouch": 7,
        }
        return (slot_order.get(normalized_key, 20), original_index)
    if group_key == "weapon":
        slot_order = {
            "primaryfire": 0,
            "secondaryfire": 1,
            "melee": 2,
        }
        return (slot_order.get(normalized_key, 10), original_index)
    return (0, original_index)


def _localize_category_label(group_key: str, ability_type_raw: str) -> str:
    if group_key in CATEGORY_LABELS:
        return CATEGORY_LABELS[group_key]
    localized = _localize_inline_text(ability_type_raw)
    return localized or "技能"


def _localize_key_label(value: Any) -> str:
    text = _clean_localized_text(value)
    normalized = _normalize_free_key(text)
    if normalized in KEY_LABELS:
        return KEY_LABELS[normalized]
    localized = _localize_inline_text(text)
    return localized or text


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = _clean_localized_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _build_translation_glossary(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    glossary = []
    seen = set()

    def add(source_text: Any, translated_text: Any) -> None:
        source = str(source_text or "").strip()
        translated = str(translated_text or "").strip()
        if not source or not translated:
            return
        key = (source, translated)
        if key in seen:
            return
        seen.add(key)
        glossary.append(key)

    add(payload.get("hero_en"), payload.get("hero_cn"))
    add(payload.get("role"), payload.get("role_cn"))
    for section_name in ("abilities", "perks"):
        for card in list(payload.get(section_name) or []):
            if not isinstance(card, Mapping):
                continue
            add(card.get("name_en"), card.get("name_cn"))
            add(card.get("group_title"), card.get("group_title_cn"))
    return glossary


def _build_question_context(payload: Mapping[str, Any]) -> str:
    lines = [
        f"英雄：{payload.get('hero_cn', '')} ({payload.get('hero_en', '')})",
        f"职责：{payload.get('role_cn', '')}",
    ]
    overview = str(payload.get("overview") or "").strip()
    if overview:
        lines.append(f"概览：{overview}")

    stats = payload.get("stats") or {}
    stat_parts = []
    for key in ("total_hp", "health", "armor", "shield", "preset_bonus_hp", "preset_mode_total_hp", "minor_perk_xp", "major_perk_xp"):
        value = stats.get(key)
        if isinstance(value, int) and value > 0:
            label = {
                "total_hp": "总生命",
                "health": "生命",
                "armor": "护甲",
                "shield": "护盾",
                "minor_perk_xp": "次级威能 XP",
                "major_perk_xp": "主要威能 XP",
            }.get(key, key)
            stat_parts.append(f"{label} {value}")
    if stat_parts:
        lines.append("基础属性：" + "；".join(stat_parts))

    for section_name, section_label in (("abilities", "技能"), ("perks", "威能")):
        for card in list(payload.get(section_name) or []):
            if not isinstance(card, Mapping):
                continue
            title = str(card.get("name_cn") or card.get("name_en") or "").strip()
            group_title = str(card.get("group_title_cn") or "").strip()
            description = str(card.get("description") or "").strip()
            lines.append(f"{section_label}：{title} | {group_title}")
            if description:
                lines.append(f"说明：{description}")
            stats_list = [item for item in list(card.get("stats") or []) if isinstance(item, Mapping)]
            if stats_list:
                lines.append("条目属性：" + "；".join(f"{item.get('label')} {item.get('value')}" for item in stats_list))
            notes = [str(item) for item in list(card.get("notes") or []) if str(item or "").strip()]
            if notes:
                lines.append("补充：" + "；".join(notes[:3]))
    return "\n".join(lines)


def _set_nested_value(payload: Dict[str, Any], path: Sequence[Any], value: Any) -> None:
    current: Any = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


ow_hero_wiki_module = OWHeroWikiModule()


__all__ = [
    "OWHeroWikiModule",
    "OWHeroWikiOutput",
    "OWHeroWikiQuery",
    "ow_hero_wiki_module",
]
