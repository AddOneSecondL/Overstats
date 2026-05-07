from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    from overstats.src.constants import iter_hero_alias_pairs
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
except ModuleNotFoundError:
    from src.constants import iter_hero_alias_pairs
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool

from .render import RenderedImage, render_hero_leaderboard
from .requests import (
    DashenHeroLeaderboardQuery,
    DashenHeroLeaderboardRequests,
    MODE_LABELS,
    normalize_mode,
)
from ..dashen_rank_leaderboard.service import (
    UNRANKED_LABEL,
    rank_icon_level_for_score,
    score_to_rank,
)


@dataclass(frozen=True)
class DashenHeroLeaderboardHero:
    hero_guid: str
    hero_name: str
    hero_role: str
    icon_url: str
    accent_color: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hero_guid": self.hero_guid,
            "hero_name": self.hero_name,
            "hero_role": self.hero_role,
            "icon_url": self.icon_url,
            "accent_color": self.accent_color,
        }


@dataclass(frozen=True)
class DashenHeroLeaderboardEntry:
    rank_num: int
    user_name: str
    match_sum: int
    win_rate: float
    wins: int
    ranked_level: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank_num": int(self.rank_num),
            "user_name": str(self.user_name),
            "match_sum": int(self.match_sum),
            "win_rate": float(self.win_rate),
            "wins": int(self.wins),
            "ranked_level": int(self.ranked_level),
        }


@dataclass(frozen=True)
class DashenHeroLeaderboardGroup:
    rank_label: str
    rank_icon_level: int
    count: int
    entries: Sequence[DashenHeroLeaderboardEntry]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank_label": str(self.rank_label),
            "rank_icon_level": int(self.rank_icon_level),
            "count": int(self.count),
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True)
class DashenHeroLeaderboardOutput:
    province: str
    mode: str
    mode_label: str
    hero: DashenHeroLeaderboardHero
    entry_count: int
    groups: Sequence[DashenHeroLeaderboardGroup]
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "province": self.province,
            "mode": self.mode,
            "mode_label": self.mode_label,
            "hero": self.hero.to_dict(),
            "entry_count": int(self.entry_count),
            "groups": [item.to_dict() for item in self.groups],
        }


class DashenHeroLeaderboardModule:
    def __init__(
        self,
        requests: Optional[DashenHeroLeaderboardRequests] = None,
        *,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.requests = requests or DashenHeroLeaderboardRequests()
        self.config_loader = config_loader or load_query_tool

    async def query_hero_leaderboard(
        self,
        query: DashenHeroLeaderboardQuery,
        *,
        render: bool = False,
    ) -> DashenHeroLeaderboardOutput:
        resolved_query = self._normalize_query(query)
        config = self._load_ow_config()
        hero_lookup = self._build_hero_lookup(config)
        hero_meta = self._resolve_hero_meta(resolved_query.hero, hero_lookup)
        if hero_meta is None:
            raise ModuleError(
                error="hero_leaderboard_hero_not_found",
                message=f"Could not resolve hero: {resolved_query.hero}",
                status_code=404,
                details={"hero": resolved_query.hero},
            )

        try:
            data = await self.requests.query_hero_leaderboard(
                resolved_query.province,
                resolved_query.mode,
                hero_meta.hero_guid,
            )
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(
                error="hero_leaderboard_upstream_error",
                message="Failed to fetch Dashen hero leaderboard data.",
                status_code=502,
                details={
                    "province": resolved_query.province,
                    "mode": resolved_query.mode,
                    "hero_guid": hero_meta.hero_guid,
                    "exception": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc

        rows = [item for item in list(data.get("itemList") or []) if isinstance(item, dict)]
        if not rows:
            raise ModuleError(
                error="dashen_hero_leaderboard_empty",
                message="No Dashen hero leaderboard data found for the requested filters.",
                status_code=404,
                details={
                    "province": resolved_query.province,
                    "mode": resolved_query.mode,
                    "hero_guid": hero_meta.hero_guid,
                },
            )

        entries = sorted(
            (self._to_entry(item) for item in rows),
            key=lambda item: (
                -item.ranked_level,
                item.rank_num if item.rank_num > 0 else 999999,
                item.user_name.lower(),
            ),
        )
        groups = self._group_entries(entries)
        output = DashenHeroLeaderboardOutput(
            province=resolved_query.province,
            mode=resolved_query.mode,
            mode_label=MODE_LABELS[resolved_query.mode],
            hero=hero_meta,
            entry_count=len(entries),
            groups=groups,
        )
        if not render:
            return output

        image = render_hero_leaderboard(
            province=output.province,
            hero=output.hero.to_dict(),
            mode_label=output.mode_label,
            entry_count=output.entry_count,
            groups=[item.to_dict() for item in output.groups],
        )
        return DashenHeroLeaderboardOutput(
            province=output.province,
            mode=output.mode,
            mode_label=output.mode_label,
            hero=output.hero,
            entry_count=output.entry_count,
            groups=output.groups,
            image=image,
        )

    def _normalize_query(self, query: DashenHeroLeaderboardQuery) -> DashenHeroLeaderboardQuery:
        province = str(query.province or "").strip()
        hero = str(query.hero or "").strip()
        if not province:
            raise ModuleError(
                error="missing_province",
                message="province is required.",
                status_code=400,
                hint='Example: {"province":"北京","hero":"猎空","mode":"preset"}',
            )
        if not hero:
            raise ModuleError(
                error="missing_hero",
                message="hero is required.",
                status_code=400,
                hint='Example: {"province":"北京","hero":"猎空","mode":"preset"}',
            )
        try:
            mode = normalize_mode(query.mode)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_mode",
                message=str(exc),
                status_code=400,
                details={"mode": query.mode},
            ) from exc
        return DashenHeroLeaderboardQuery(
            province=province,
            hero=hero,
            mode=mode,
        )

    def _load_ow_config(self) -> Dict[str, Any]:
        config = self.config_loader()
        return config if isinstance(config, dict) else {}

    def _build_hero_lookup(self, config: Dict[str, Any]) -> Dict[str, Dict[str, DashenHeroLeaderboardHero]]:
        by_guid: Dict[str, DashenHeroLeaderboardHero] = {}
        by_name: Dict[str, DashenHeroLeaderboardHero] = {}
        alias_to_name = {
            self._normalize_text(alias): canonical_name
            for alias, canonical_name in iter_hero_alias_pairs()
            if str(alias or "").strip()
        }
        color_lookup = self._build_color_lookup(config)
        for item in list(config.get("heroList") or []):
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("heroGuid") or item.get("hero_id") or item.get("id") or "").strip()
            if not hero_guid:
                continue
            hero_name = str(item.get("name") or hero_guid).strip()
            hero = DashenHeroLeaderboardHero(
                hero_guid=hero_guid,
                hero_name=hero_name,
                hero_role=str(item.get("roleType") or item.get("heroRole") or "").strip(),
                icon_url=self._hero_icon_url(item),
                accent_color=color_lookup.get(hero_name, "#5E001AFF"),
            )
            by_guid[self._normalize_text(hero_guid)] = hero
            by_name[self._normalize_text(hero_name)] = hero
        return {
            "by_guid": by_guid,
            "by_name": by_name,
            "alias_to_name": alias_to_name,
        }

    def _build_color_lookup(self, config: Dict[str, Any]) -> Dict[str, str]:
        lookup: Dict[str, str] = {}
        hero_config = config.get("heroConfig")
        if not isinstance(hero_config, dict):
            return lookup
        for item in hero_config.values():
            if not isinstance(item, dict):
                continue
            hero_name = str(item.get("Name") or "").strip()
            color = str(item.get("Color") or "").strip()
            if hero_name and color:
                lookup[hero_name] = color
        return lookup

    def _resolve_hero_meta(
        self,
        hero_query: str,
        lookup: Dict[str, Dict[str, DashenHeroLeaderboardHero]],
    ) -> Optional[DashenHeroLeaderboardHero]:
        normalized = self._normalize_text(hero_query)
        if not normalized:
            return None
        by_guid = lookup.get("by_guid") or {}
        by_name = lookup.get("by_name") or {}
        alias_to_name = lookup.get("alias_to_name") or {}
        if normalized in by_guid:
            return by_guid[normalized]
        hero = by_name.get(normalized)
        if hero is not None:
            return hero
        canonical_name = alias_to_name.get(normalized)
        if canonical_name:
            return by_name.get(self._normalize_text(canonical_name))
        return None

    def _hero_icon_url(self, item: Dict[str, Any]) -> str:
        for key in ("smallIconUrl", "ddHeroIcon", "icon"):
            text = str(item.get(key) or "").strip()
            if text:
                return text
        return ""

    def _to_entry(self, payload: Dict[str, Any]) -> DashenHeroLeaderboardEntry:
        match_sum = self._safe_int(payload.get("matchSum"))
        win_rate = self._safe_float(payload.get("winRate"))
        wins = round(win_rate / 100.0 * match_sum) if match_sum > 0 else 0
        return DashenHeroLeaderboardEntry(
            rank_num=self._safe_int(payload.get("rankNum")),
            user_name=str(payload.get("userName") or payload.get("name") or "-"),
            match_sum=match_sum,
            win_rate=win_rate,
            wins=wins,
            ranked_level=self._safe_int(payload.get("rankedLevel")),
        )

    def _group_entries(self, entries: Sequence[DashenHeroLeaderboardEntry]) -> tuple[DashenHeroLeaderboardGroup, ...]:
        groups: List[DashenHeroLeaderboardGroup] = []
        current_label: Optional[str] = None
        current_icon_level = 0
        current_entries: List[DashenHeroLeaderboardEntry] = []
        for entry in entries:
            rank_label = score_to_rank(entry.ranked_level)
            rank_icon_level = rank_icon_level_for_score(entry.ranked_level)
            if current_label != rank_label:
                if current_entries:
                    groups.append(
                        DashenHeroLeaderboardGroup(
                            rank_label=str(current_label or UNRANKED_LABEL),
                            rank_icon_level=current_icon_level,
                            count=len(current_entries),
                            entries=tuple(current_entries),
                        )
                    )
                current_label = rank_label
                current_icon_level = rank_icon_level
                current_entries = []
            current_entries.append(entry)
        if current_entries:
            groups.append(
                DashenHeroLeaderboardGroup(
                    rank_label=str(current_label or UNRANKED_LABEL),
                    rank_icon_level=current_icon_level,
                    count=len(current_entries),
                    entries=tuple(current_entries),
                )
            )
        return tuple(groups)

    def _normalize_text(self, text: Any) -> str:
        return str(text or "").strip().lower()

    def _safe_int(self, value: Any) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


dashen_hero_leaderboard_module = DashenHeroLeaderboardModule()


__all__ = [
    "DashenHeroLeaderboardEntry",
    "DashenHeroLeaderboardGroup",
    "DashenHeroLeaderboardHero",
    "DashenHeroLeaderboardModule",
    "DashenHeroLeaderboardOutput",
    "dashen_hero_leaderboard_module",
]
