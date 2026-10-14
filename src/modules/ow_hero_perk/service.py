from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

try:
    from overstats.src.constants import iter_hero_alias_pairs
    from overstats.src.db import IDPoolDB
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
except ModuleNotFoundError:
    from src.constants import iter_hero_alias_pairs
    from src.db import IDPoolDB
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool

from .render import RenderedImage, render_hero_perk_overview
from .requests import MAJOR_PERK_LEVEL, MINOR_PERK_LEVEL, OWHeroPerkQuery, normalize_hero_query


UNKNOWN_PERK_DESC = "暂无描述"


@dataclass(frozen=True)
class OWHeroPerkHero:
    hero_guid: str
    hero_id: str
    hero_name: str
    hero_role: str
    icon_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hero_guid": self.hero_guid,
            "hero_id": self.hero_id,
            "hero_name": self.hero_name,
            "hero_role": self.hero_role,
            "icon_url": self.icon_url,
        }


@dataclass(frozen=True)
class OWHeroPerkEntry:
    perk_guid: str
    perk_guid_hex: str
    name: str
    desc: str
    icon_url: str
    pick_count: int
    sample_count: int
    pick_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "perk_guid": self.perk_guid,
            "perk_guid_hex": self.perk_guid_hex,
            "name": self.name,
            "desc": self.desc,
            "icon_url": self.icon_url,
            "pick_count": int(self.pick_count),
            "sample_count": int(self.sample_count),
            "pick_rate": float(self.pick_rate),
        }


@dataclass(frozen=True)
class OWHeroPerkBucket:
    level: int
    title: str
    sample_count: int
    perks: Sequence[OWHeroPerkEntry]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": int(self.level),
            "title": self.title,
            "sample_count": int(self.sample_count),
            "perks": [item.to_dict() for item in self.perks],
        }


@dataclass(frozen=True)
class OWHeroPerkOutput:
    hero: OWHeroPerkHero
    minor: OWHeroPerkBucket
    major: OWHeroPerkBucket
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "hero": self.hero.to_dict(),
            "minor": self.minor.to_dict(),
            "major": self.major.to_dict(),
        }


@dataclass(frozen=True)
class _PerkContext:
    hero_perk_lookup: Dict[tuple[str, str], Dict[str, Any]]
    perk_lookup: Dict[str, Dict[str, Any]]
    mod_trait_lookup: Dict[str, Dict[str, Any]]


class OWHeroPerkModule:
    def __init__(
        self,
        db: Optional[IDPoolDB] = None,
        *,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.db = db or IDPoolDB()
        self.config_loader = config_loader or load_query_tool

    async def query_perk(
        self,
        query: OWHeroPerkQuery,
        *,
        render: bool = False,
    ) -> OWHeroPerkOutput:
        resolved_query = self._normalize_query(query)
        config = self._load_ow_config()
        hero_lookup = self._build_hero_lookup(config)
        hero_meta = self._resolve_hero_meta(resolved_query.hero, hero_lookup)
        if hero_meta is None:
            raise ModuleError(
                error="hero_perk_hero_not_found",
                message=f"Could not resolve hero: {resolved_query.hero}",
                status_code=404,
                details={"hero": resolved_query.hero},
            )

        perk_context = self._build_perk_context(config)
        minor_bucket = self._query_bucket(hero_meta, MINOR_PERK_LEVEL, perk_context)
        major_bucket = self._query_bucket(hero_meta, MAJOR_PERK_LEVEL, perk_context)
        if minor_bucket.sample_count <= 0 and major_bucket.sample_count <= 0:
            raise ModuleError(
                error="hero_perk_empty",
                message="该英雄暂无匿名威能样本；查询含该英雄的对局详情后会逐步积累统计。",
                status_code=404,
                details={"hero_guid": hero_meta.hero_guid},
            )

        output = OWHeroPerkOutput(
            hero=hero_meta,
            minor=minor_bucket,
            major=major_bucket,
        )
        if not render:
            return output

        image = render_hero_perk_overview(
            hero=output.hero.to_dict(),
            minor=output.minor.to_dict(),
            major=output.major.to_dict(),
        )
        return OWHeroPerkOutput(
            hero=output.hero,
            minor=output.minor,
            major=output.major,
            image=image,
        )

    def _normalize_query(self, query: OWHeroPerkQuery) -> OWHeroPerkQuery:
        try:
            hero = normalize_hero_query(query.hero)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_hero_perk_query",
                message=str(exc),
                status_code=400,
                hint='Example: {"hero":"安娜"}',
            ) from exc
        return OWHeroPerkQuery(hero=hero)

    def _load_ow_config(self) -> Dict[str, Any]:
        config = self.config_loader()
        return config if isinstance(config, dict) else {}

    def _build_hero_lookup(self, config: Dict[str, Any]) -> Dict[str, Dict[str, OWHeroPerkHero]]:
        by_guid: Dict[str, OWHeroPerkHero] = {}
        by_id: Dict[str, OWHeroPerkHero] = {}
        by_name: Dict[str, OWHeroPerkHero] = {}
        alias_to_name = {
            self._normalize_text(alias): canonical_name
            for alias, canonical_name in iter_hero_alias_pairs()
            if str(alias or "").strip()
        }
        for item in list(config.get("heroList") or []):
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("heroGuid") or item.get("hero_id") or item.get("heroId") or "").strip()
            hero_id = str(item.get("id") or item.get("heroId") or hero_guid).strip()
            if not hero_guid:
                continue
            hero_name = str(item.get("name") or hero_guid).strip()
            hero = OWHeroPerkHero(
                hero_guid=hero_guid,
                hero_id=hero_id,
                hero_name=hero_name,
                hero_role=str(item.get("roleType") or item.get("heroRole") or "").strip(),
                icon_url=self._hero_icon_url(item),
            )
            by_guid[hero_guid] = hero
            if hero_id:
                by_id[hero_id] = hero
            if hero_name:
                by_name[self._normalize_text(hero_name)] = hero

        for alias, canonical_name in alias_to_name.items():
            hero = by_name.get(self._normalize_text(canonical_name))
            if hero is not None:
                by_name[alias] = hero
        return {"by_guid": by_guid, "by_id": by_id, "by_name": by_name}

    def _resolve_hero_meta(
        self,
        hero_query: str,
        hero_lookup: Dict[str, Dict[str, OWHeroPerkHero]],
    ) -> Optional[OWHeroPerkHero]:
        normalized = str(hero_query or "").strip()
        if not normalized:
            return None
        by_guid = hero_lookup.get("by_guid") or {}
        by_id = hero_lookup.get("by_id") or {}
        by_name = hero_lookup.get("by_name") or {}
        if normalized in by_guid:
            return by_guid[normalized]
        if normalized in by_id:
            return by_id[normalized]
        return by_name.get(self._normalize_text(normalized))

    def _build_perk_context(self, config: Dict[str, Any]) -> _PerkContext:
        hero_perk_lookup: Dict[tuple[str, str], Dict[str, Any]] = {}
        raw_hero_perk_list = config.get("heroPerkList") or {}
        if isinstance(raw_hero_perk_list, dict):
            hero_groups = raw_hero_perk_list.items()
        else:
            hero_groups = []
        for hero_id, items in hero_groups:
            if not isinstance(items, list):
                continue
            normalized_hero_id = str(hero_id or "").strip()
            for item in items:
                if not isinstance(item, dict):
                    continue
                for candidate in self._perk_guid_candidates(item):
                    hero_perk_lookup[(normalized_hero_id, candidate)] = item

        perk_lookup = self._build_global_perk_lookup(config.get("perkList"))
        mod_trait_lookup = self._build_global_perk_lookup(config.get("modTrait"))
        return _PerkContext(
            hero_perk_lookup=hero_perk_lookup,
            perk_lookup=perk_lookup,
            mod_trait_lookup=mod_trait_lookup,
        )

    def _build_global_perk_lookup(self, raw_value: Any) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_value, dict):
            iterable: Iterable[Any] = raw_value.values()
        elif isinstance(raw_value, list):
            iterable = raw_value
        else:
            iterable = ()

        for value in iterable:
            if isinstance(value, list):
                items = value
            else:
                items = [value]
            for item in items:
                if not isinstance(item, dict):
                    continue
                for candidate in self._perk_guid_candidates(item):
                    lookup[candidate] = item
        return lookup

    def _query_bucket(
        self,
        hero_meta: OWHeroPerkHero,
        perk_level: int,
        perk_context: _PerkContext,
    ) -> OWHeroPerkBucket:
        summary = self.db.get_perk_pick_summary(hero_meta.hero_guid, perk_level, include_overall=True)
        bucket = self._overall_bucket(summary)
        if not bucket or not bucket.get("perks"):
            summary = self.db.get_perk_pick_summary_from_raw(hero_meta.hero_guid, perk_level, include_overall=True)
            bucket = self._overall_bucket(summary)

        sample_count = self._safe_int((bucket or {}).get("sample_count"))
        entries = []
        perks = dict((bucket or {}).get("perks") or {})
        for perk_guid, payload in perks.items():
            pick_count = self._safe_int(payload.get("pick_count"))
            actual_sample_count = max(sample_count, self._safe_int(payload.get("sample_count")))
            if pick_count <= 0 or actual_sample_count <= 0:
                continue
            metadata = self._resolve_perk_meta(hero_meta, perk_guid, perk_context)
            entries.append(
                OWHeroPerkEntry(
                    perk_guid=str(perk_guid),
                    perk_guid_hex=self._format_guid_hex(perk_guid),
                    name=str(metadata.get("name") or f"未知威能({self._format_guid_hex(perk_guid)})"),
                    desc=str(metadata.get("desc") or UNKNOWN_PERK_DESC),
                    icon_url=str(metadata.get("icon_url") or ""),
                    pick_count=pick_count,
                    sample_count=actual_sample_count,
                    pick_rate=float(pick_count / actual_sample_count) if actual_sample_count > 0 else 0.0,
                )
            )

        entries.sort(key=lambda item: (-item.pick_count, item.perk_guid_hex))
        return OWHeroPerkBucket(
            level=int(perk_level),
            title="次级威能" if int(perk_level) == MINOR_PERK_LEVEL else "主要威能",
            sample_count=sample_count,
            perks=tuple(entries),
        )

    def _overall_bucket(self, summary: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(summary, dict):
            return {}
        bucket = summary.get(None)
        return bucket if isinstance(bucket, dict) else {}

    def _resolve_perk_meta(
        self,
        hero_meta: OWHeroPerkHero,
        perk_guid: Any,
        perk_context: _PerkContext,
    ) -> Dict[str, str]:
        primary: Dict[str, Any] = {}
        secondary: Dict[str, Any] = {}
        trait: Dict[str, Any] = {}
        for candidate in self._perk_guid_candidates(perk_guid):
            if not primary:
                primary = perk_context.hero_perk_lookup.get((hero_meta.hero_id, candidate), {})
            if not secondary:
                secondary = perk_context.perk_lookup.get(candidate, {})
            if not trait:
                trait = perk_context.mod_trait_lookup.get(candidate, {})
            if primary and secondary and trait:
                break

        name, desc = self._extract_name_desc(primary)
        fallback_name, fallback_desc = self._extract_name_desc(secondary)
        trait_name, trait_desc = self._extract_name_desc(trait)
        resolved_name = name or fallback_name or trait_name or f"未知威能({self._format_guid_hex(perk_guid)})"
        resolved_desc = trait_desc or desc or fallback_desc or UNKNOWN_PERK_DESC
        icon_url = (
            str(primary.get("icon") or "").strip()
            or str(secondary.get("icon") or "").strip()
            or str(trait.get("icon") or "").strip()
        )
        return {
            "name": resolved_name,
            "desc": resolved_desc,
            "icon_url": icon_url,
        }

    def _extract_name_desc(self, item: Dict[str, Any]) -> tuple[str, str]:
        if not isinstance(item, dict):
            return "", ""
        raw_name = str(item.get("name") or "").strip()
        raw_desc = str(item.get("desc") or item.get("description") or "").strip()
        if raw_name:
            parts = [part.strip() for part in re.split(r"<br\s*/?>", raw_name) if part.strip()]
            if parts:
                if not raw_desc and len(parts) > 1:
                    raw_desc = " ".join(parts[1:]).strip()
                raw_name = parts[0]
        return raw_name, raw_desc

    def _perk_guid_candidates(self, perk: Any) -> list[str]:
        if isinstance(perk, dict):
            raw_values = [
                perk.get("guid"),
                perk.get("id"),
                perk.get("perkGuid"),
                perk.get("value"),
            ]
        else:
            raw_values = [perk]

        candidates: list[str] = []
        for raw in raw_values:
            text = str(raw or "").strip()
            if not text:
                continue
            candidates.append(text)
            try:
                number = int(text, 16) if text.lower().startswith("0x") else int(text)
            except ValueError:
                continue
            candidates.append(str(number))
            candidates.append(f"0x{number:016X}")
            candidates.append(f"0x0{number:015X}")
        return list(dict.fromkeys(candidates))

    def _format_guid_hex(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "UNKNOWN"
        try:
            number = int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return text
        return f"0x{number:016X}"

    def _hero_icon_url(self, item: Dict[str, Any]) -> str:
        for key in ("smallIconUrl", "ddHeroIcon", "icon", "circleIcon", "portrait", "avatar"):
            text = str(item.get(key) or "").strip()
            if text:
                return text
        return ""

    def _normalize_text(self, text: Any) -> str:
        return str(text or "").strip().lower()

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0


ow_hero_perk_module = OWHeroPerkModule()


__all__ = [
    "OWHeroPerkBucket",
    "OWHeroPerkEntry",
    "OWHeroPerkHero",
    "OWHeroPerkModule",
    "OWHeroPerkOutput",
    "ow_hero_perk_module",
]
