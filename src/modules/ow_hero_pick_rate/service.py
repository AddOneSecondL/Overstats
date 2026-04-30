from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:
    from overstats.src.db import HERO_LEADERBOARD_CN_TABLE, OWHeroLeaderboardDB
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
    from overstats.src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        QUICK_STRENGTH_THEME,
    )
except ModuleNotFoundError:
    from src.db import HERO_LEADERBOARD_CN_TABLE, OWHeroLeaderboardDB
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool
    from src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        QUICK_STRENGTH_THEME,
    )

from .render import RenderedImage, render_pick_rate_history, render_pick_rate_ranking
from .requests import (
    GAME_MODE_COMPETITIVE,
    GAME_MODE_SOURCE_MAP,
    HISTORY_LIMIT_DEFAULT,
    MMR_SOURCE_MAP,
    OWHeroPickRateQuery,
    VIEW_HISTORY,
    VIEW_RANKING,
    normalize_game_mode,
    normalize_history_limit,
    normalize_mmr,
    normalize_view,
)


@dataclass(frozen=True)
class OWHeroPickRateSnapshot:
    season: int
    ds: str
    hero_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "season": int(self.season),
            "ds": str(self.ds),
            "hero_count": int(self.hero_count),
        }


@dataclass(frozen=True)
class OWHeroPickRateHeroRow:
    rank: int
    hero_guid: str
    hero_name: str
    hero_role: str
    selection_ratio: float
    ban_ratio: float
    win_ratio: float
    kda: float
    icon_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": int(self.rank),
            "hero_guid": self.hero_guid,
            "hero_name": self.hero_name,
            "hero_role": self.hero_role,
            "selection_ratio": float(self.selection_ratio),
            "ban_ratio": float(self.ban_ratio),
            "win_ratio": float(self.win_ratio),
            "kda": float(self.kda),
            "icon_url": self.icon_url,
        }


@dataclass(frozen=True)
class OWHeroPickRateHeroMeta:
    hero_guid: str
    hero_name: str
    hero_role: str
    icon_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hero_guid": self.hero_guid,
            "hero_name": self.hero_name,
            "hero_role": self.hero_role,
            "icon_url": self.icon_url,
        }


@dataclass(frozen=True)
class OWHeroPickRateHistoryPoint:
    season: int
    ds: str
    selection_ratio: float
    ban_ratio: float
    win_ratio: float
    kda: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "season": int(self.season),
            "ds": str(self.ds),
            "selection_ratio": float(self.selection_ratio),
            "ban_ratio": float(self.ban_ratio),
            "win_ratio": float(self.win_ratio),
            "kda": float(self.kda),
        }


@dataclass(frozen=True)
class OWHeroPickRateOutput:
    view: str
    region: str
    game_mode: str
    mmr: str
    snapshot: Optional[OWHeroPickRateSnapshot] = None
    heroes: Sequence[OWHeroPickRateHeroRow] = ()
    hero: Optional[OWHeroPickRateHeroMeta] = None
    history_limit: int = HISTORY_LIMIT_DEFAULT
    history_total: int = 0
    latest: Optional[OWHeroPickRateHistoryPoint] = None
    series: Sequence[OWHeroPickRateHistoryPoint] = ()
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": True,
            "view": self.view,
            "region": self.region,
            "game_mode": self.game_mode,
            "mmr": self.mmr,
        }
        if self.view == VIEW_RANKING:
            payload["snapshot"] = self.snapshot.to_dict() if self.snapshot else None
            payload["heroes"] = [item.to_dict() for item in self.heroes]
            return payload

        payload["hero"] = self.hero.to_dict() if self.hero else None
        payload["history_limit"] = int(self.history_limit)
        payload["history_total"] = int(self.history_total)
        payload["latest"] = self.latest.to_dict() if self.latest else None
        payload["series"] = [item.to_dict() for item in self.series]
        return payload


class OWHeroPickRateModule:
    def __init__(
        self,
        db: Optional[OWHeroLeaderboardDB] = None,
        *,
        config_loader: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self.db = db or OWHeroLeaderboardDB()
        self.config_loader = config_loader or load_query_tool

    async def query_pick_rate(
        self,
        query: OWHeroPickRateQuery,
        *,
        render: bool = False,
    ) -> OWHeroPickRateOutput:
        resolved_query = self._normalize_query(query)
        config = self._load_ow_config()
        if resolved_query.view == VIEW_RANKING:
            output = self._query_ranking(resolved_query, config)
            if render:
                theme = self._theme_for_game_mode(resolved_query.game_mode)
                image = render_pick_rate_ranking(
                    game_mode=resolved_query.game_mode,
                    mmr=resolved_query.mmr,
                    snapshot=output.snapshot.to_dict() if output.snapshot else {},
                    heroes=[item.to_dict() for item in output.heroes],
                    theme=theme,
                )
                output = OWHeroPickRateOutput(
                    view=output.view,
                    region=output.region,
                    game_mode=output.game_mode,
                    mmr=output.mmr,
                    snapshot=output.snapshot,
                    heroes=output.heroes,
                    image=image,
                )
            return output

        output = self._query_history(resolved_query, config)
        if render:
            theme = self._theme_for_game_mode(resolved_query.game_mode)
            image = render_pick_rate_history(
                game_mode=resolved_query.game_mode,
                mmr=resolved_query.mmr,
                hero=output.hero.to_dict() if output.hero else {},
                latest=output.latest.to_dict() if output.latest else {},
                history_total=output.history_total,
                history_limit=output.history_limit,
                series=[item.to_dict() for item in output.series],
                theme=theme,
            )
            output = OWHeroPickRateOutput(
                view=output.view,
                region=output.region,
                game_mode=output.game_mode,
                mmr=output.mmr,
                hero=output.hero,
                history_limit=output.history_limit,
                history_total=output.history_total,
                latest=output.latest,
                series=output.series,
                image=image,
            )
        return output

    def _query_ranking(self, query: OWHeroPickRateQuery, config: Dict[str, Any]) -> OWHeroPickRateOutput:
        source_mode = GAME_MODE_SOURCE_MAP[query.game_mode]
        source_mmr = MMR_SOURCE_MAP[query.mmr]
        rows = self.db.fetch_rows(
            HERO_LEADERBOARD_CN_TABLE,
            game_mode=source_mode,
            mmr=source_mmr,
        )
        if not rows:
            raise ModuleError(
                error="hero_pick_rate_empty",
                message="No hero pick-rate snapshot found for the requested mode.",
                status_code=404,
                details={"game_mode": query.game_mode, "mmr": query.mmr},
            )

        latest_season, latest_ds = max(
            (self._safe_int(row.get("season")), str(row.get("ds") or ""))
            for row in rows
        )
        latest_rows = [
            row
            for row in rows
            if self._safe_int(row.get("season")) == latest_season and str(row.get("ds") or "") == latest_ds
        ]
        if not latest_rows:
            raise ModuleError(
                error="hero_pick_rate_empty",
                message="No hero pick-rate snapshot found for the requested mode.",
                status_code=404,
                details={"game_mode": query.game_mode, "mmr": query.mmr},
            )

        hero_lookup = self._build_hero_lookup(config)
        sorted_rows = sorted(
            latest_rows,
            key=lambda item: (-self._safe_float(item.get("selection_ratio")), str(item.get("hero_id") or "")),
        )
        heroes = tuple(
            self._to_ranked_hero_row(index + 1, row, hero_lookup)
            for index, row in enumerate(sorted_rows)
        )
        snapshot = OWHeroPickRateSnapshot(
            season=latest_season,
            ds=latest_ds,
            hero_count=len(heroes),
        )
        return OWHeroPickRateOutput(
            view=VIEW_RANKING,
            region="cn",
            game_mode=query.game_mode,
            mmr=query.mmr,
            snapshot=snapshot,
            heroes=heroes,
        )

    def _query_history(self, query: OWHeroPickRateQuery, config: Dict[str, Any]) -> OWHeroPickRateOutput:
        if not str(query.hero or "").strip():
            raise ModuleError(
                error="hero_pick_rate_missing_hero",
                message="history view requires a hero parameter.",
                status_code=400,
                hint='Example: {"view":"history","hero":"安娜"}',
            )

        hero_lookup = self._build_hero_lookup(config)
        hero_meta = self._resolve_hero_meta(query.hero, hero_lookup)
        if hero_meta is None:
            raise ModuleError(
                error="hero_pick_rate_hero_not_found",
                message=f"Could not resolve hero: {query.hero}",
                status_code=404,
                details={"hero": query.hero},
            )

        source_mode = GAME_MODE_SOURCE_MAP[query.game_mode]
        source_mmr = MMR_SOURCE_MAP[query.mmr]
        rows = self.db.fetch_rows(
            HERO_LEADERBOARD_CN_TABLE,
            game_mode=source_mode,
            mmr=source_mmr,
            hero_id=hero_meta.hero_guid,
        )
        if not rows:
            raise ModuleError(
                error="hero_pick_rate_history_empty",
                message="No hero pick-rate history found for the requested hero.",
                status_code=404,
                details={"hero": hero_meta.hero_guid, "game_mode": query.game_mode, "mmr": query.mmr},
            )

        sorted_rows = sorted(
            rows,
            key=lambda item: (self._safe_int(item.get("season")), str(item.get("ds") or "")),
        )
        history_total = len(sorted_rows)
        limited_rows = sorted_rows[-query.history_limit :]
        series = tuple(self._to_history_point(row) for row in limited_rows)
        latest = self._to_history_point(sorted_rows[-1])
        return OWHeroPickRateOutput(
            view=VIEW_HISTORY,
            region="cn",
            game_mode=query.game_mode,
            mmr=query.mmr,
            hero=hero_meta,
            history_limit=query.history_limit,
            history_total=history_total,
            latest=latest,
            series=series,
        )

    def _normalize_query(self, query: OWHeroPickRateQuery) -> OWHeroPickRateQuery:
        try:
            view = normalize_view(query.view)
            game_mode = normalize_game_mode(query.game_mode)
            mmr = normalize_mmr(query.mmr)
            history_limit = normalize_history_limit(query.history_limit)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_pick_rate_query",
                message=str(exc),
                status_code=400,
                details={
                    "view": query.view,
                    "game_mode": query.game_mode,
                    "mmr": query.mmr,
                    "history_limit": query.history_limit,
                },
            ) from exc
        return OWHeroPickRateQuery(
            view=view,
            game_mode=game_mode,
            mmr=mmr,
            hero=str(query.hero or "").strip(),
            history_limit=history_limit,
        )

    def _load_ow_config(self) -> Dict[str, Any]:
        config = self.config_loader()
        return config if isinstance(config, dict) else {}

    def _build_hero_lookup(self, config: Dict[str, Any]) -> Dict[str, Dict[str, OWHeroPickRateHeroMeta]]:
        by_guid: Dict[str, OWHeroPickRateHeroMeta] = {}
        by_name: Dict[str, OWHeroPickRateHeroMeta] = {}
        for item in list(config.get("heroList") or []):
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("heroGuid") or item.get("hero_id") or item.get("id") or "").strip()
            if not hero_guid:
                continue
            hero_name = str(item.get("name") or hero_guid).strip()
            icon_url = self._hero_icon_url(item)
            hero_meta = OWHeroPickRateHeroMeta(
                hero_guid=hero_guid,
                hero_name=hero_name,
                hero_role=str(item.get("roleType") or "").strip(),
                icon_url=icon_url,
            )
            by_guid[hero_guid] = hero_meta
            if hero_name:
                by_name[self._normalize_hero_name(hero_name)] = hero_meta
        return {"by_guid": by_guid, "by_name": by_name}

    def _resolve_hero_meta(
        self,
        hero_query: str,
        hero_lookup: Dict[str, Dict[str, OWHeroPickRateHeroMeta]],
    ) -> Optional[OWHeroPickRateHeroMeta]:
        normalized = str(hero_query or "").strip()
        if not normalized:
            return None
        by_guid = hero_lookup.get("by_guid") or {}
        by_name = hero_lookup.get("by_name") or {}
        if normalized in by_guid:
            return by_guid[normalized]
        return by_name.get(self._normalize_hero_name(normalized))

    def _to_ranked_hero_row(
        self,
        rank: int,
        row: Dict[str, Any],
        hero_lookup: Dict[str, Dict[str, OWHeroPickRateHeroMeta]],
    ) -> OWHeroPickRateHeroRow:
        hero_guid = str(row.get("hero_id") or "").strip()
        hero_meta = (hero_lookup.get("by_guid") or {}).get(hero_guid)
        return OWHeroPickRateHeroRow(
            rank=rank,
            hero_guid=hero_guid,
            hero_name=hero_meta.hero_name if hero_meta is not None else hero_guid or "未知英雄",
            hero_role=hero_meta.hero_role if hero_meta is not None else "",
            selection_ratio=self._safe_float(row.get("selection_ratio")),
            ban_ratio=self._safe_float(row.get("ban_ratio")),
            win_ratio=self._safe_float(row.get("win_ratio")),
            kda=self._safe_float(row.get("kda")),
            icon_url=hero_meta.icon_url if hero_meta is not None else "",
        )

    def _to_history_point(self, row: Dict[str, Any]) -> OWHeroPickRateHistoryPoint:
        return OWHeroPickRateHistoryPoint(
            season=self._safe_int(row.get("season")),
            ds=str(row.get("ds") or ""),
            selection_ratio=self._safe_float(row.get("selection_ratio")),
            ban_ratio=self._safe_float(row.get("ban_ratio")),
            win_ratio=self._safe_float(row.get("win_ratio")),
            kda=self._safe_float(row.get("kda")),
        )

    def _theme_for_game_mode(self, game_mode: str) -> Dict[str, Any]:
        if str(game_mode or "").strip().lower() == GAME_MODE_COMPETITIVE:
            return dict(COMPETITIVE_STRENGTH_THEME)
        return dict(QUICK_STRENGTH_THEME)

    def _hero_icon_url(self, item: Dict[str, Any]) -> str:
        for key in ("smallIconUrl", "ddHeroIcon", "icon"):
            text = str(item.get(key) or "").strip()
            if text:
                return text
        return ""

    def _normalize_hero_name(self, text: str) -> str:
        return str(text or "").strip().lower()

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


ow_hero_pick_rate_module = OWHeroPickRateModule()


__all__ = [
    "HISTORY_LIMIT_DEFAULT",
    "OWHeroPickRateHeroMeta",
    "OWHeroPickRateHeroRow",
    "OWHeroPickRateHistoryPoint",
    "OWHeroPickRateModule",
    "OWHeroPickRateOutput",
    "OWHeroPickRateSnapshot",
    "ow_hero_pick_rate_module",
]
