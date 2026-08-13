from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence

try:
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
    from overstats.src.modules.dashen_profile.requests import DashenProfileBundle
    from overstats.src.modules.risk_status import RiskStatus, parse_risk_status
except ModuleNotFoundError:
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool
    from src.modules.dashen_profile.requests import DashenProfileBundle
    from src.modules.risk_status import RiskStatus, parse_risk_status

from .requests import MODE_QUICK


ROLE_OPEN = "open"
ROLE_LABELS = {
    "tank": "重装",
    "dps": "输出",
    "damage": "输出",
    "healer": "支援",
    "support": "支援",
    ROLE_OPEN: "开放",
}


@dataclass(frozen=True)
class DashenHeroTreemapPlayer:
    display_name: str
    bnet_id: str
    level: int
    title: str
    risk_status: Optional[RiskStatus] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "bnet_id": self.bnet_id,
            "level": int(self.level),
            "title": self.title,
            "risk_status": self.risk_status.to_dict() if self.risk_status else None,
        }


@dataclass(frozen=True)
class DashenHeroTreemapSeason:
    logical: Optional[int]
    request: Optional[int]
    include_previous_season: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logical": self.logical,
            "request": self.request,
            "include_previous_season": bool(self.include_previous_season),
        }


@dataclass(frozen=True)
class DashenHeroTreemapHero:
    hero_guid: str
    hero_name: str
    hero_role: str
    hero_level: int
    match_sum: int
    win_sum: int
    loss_sum: int
    win_rate: float
    win_rate_delta: float
    game_time_sec: float
    game_time_text: str
    icon_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hero_guid": self.hero_guid,
            "hero_name": self.hero_name,
            "hero_role": self.hero_role,
            "hero_level": int(self.hero_level),
            "match_sum": int(self.match_sum),
            "win_sum": int(self.win_sum),
            "loss_sum": int(self.loss_sum),
            "win_rate": float(self.win_rate),
            "win_rate_delta": float(self.win_rate_delta),
            "game_time_sec": float(self.game_time_sec),
            "game_time_text": self.game_time_text,
            "icon_url": self.icon_url,
        }


def _payload_data(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _list_dicts(value: Any) -> list[Dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_role(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"tank", "dps", "damage", "healer", "support"}:
        return "healer" if normalized == "support" else ("dps" if normalized == "damage" else normalized)
    return ROLE_OPEN


def _readable_playtime(game_time_sec: float) -> str:
    if game_time_sec < 60:
        return "<1M"
    if game_time_sec < 3600:
        return f"{int(game_time_sec / 60)}M"
    return f"{int(game_time_sec / 3600)}H"


class DashenHeroTreemapEngine:
    def __init__(self, *, config_loader: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        self.config_loader = config_loader or load_query_tool

    def build_output(
        self,
        bundle: DashenProfileBundle,
        *,
        mode: str,
        resolved_name: str = "",
    ) -> tuple[DashenHeroTreemapPlayer, DashenHeroTreemapSeason, tuple[DashenHeroTreemapHero, ...]]:
        config = self._load_ow_config()
        hero_lookup = self._build_hero_lookup(config)
        card_data = _payload_data(bundle.profile_card)
        payload = _payload_data(bundle.leisure if mode == MODE_QUICK else bundle.sport)
        hero_rows = self._resolve_hero_payload_rows(payload, mode=mode)

        heroes: list[DashenHeroTreemapHero] = []
        for item in hero_rows:
            hero_guid = str(item.get("heroGuid") or item.get("heroId") or "").strip()
            game_time_sec = _safe_float(item.get("gameTime"))
            if not hero_guid or game_time_sec <= 0:
                continue

            hero_info = hero_lookup.get(hero_guid, {})
            hero_name = (
                str(hero_info.get("name") or "").strip()
                or str(item.get("heroName") or "").strip()
                or hero_guid
            )
            hero_role = _normalize_role(hero_info.get("roleType") or item.get("roleType"))
            match_sum = _safe_int(item.get("matchSum"))
            win_sum = _safe_int(item.get("winSum"))
            win_rate = _safe_float(item.get("winRate"))
            loss_sum = max(match_sum - win_sum, 0)
            heroes.append(
                DashenHeroTreemapHero(
                    hero_guid=hero_guid,
                    hero_name=hero_name,
                    hero_role=hero_role,
                    hero_level=_safe_int(item.get("heroLevel")),
                    match_sum=match_sum,
                    win_sum=win_sum,
                    loss_sum=loss_sum,
                    win_rate=win_rate,
                    win_rate_delta=win_rate - 50.0,
                    game_time_sec=game_time_sec,
                    game_time_text=_readable_playtime(game_time_sec),
                    icon_url=self._hero_icon_url(hero_info) or str(item.get("heroIcon") or "").strip(),
                )
            )

        heroes.sort(key=lambda item: (-item.game_time_sec, item.hero_guid))
        if not heroes:
            raise ModuleError(
                error="hero_treemap_empty",
                message="No hero usage data found for the requested mode.",
                status_code=404,
                details={
                    "mode": mode,
                    "logical_season": bundle.logical_season,
                    "request_season": bundle.request_season,
                },
            )

        player = DashenHeroTreemapPlayer(
            display_name=str(card_data.get("name") or resolved_name or "").strip() or "未知玩家",
            bnet_id=str(card_data.get("bnetId") or "").strip(),
            level=_safe_int(card_data.get("level")),
            title=str(card_data.get("title") or "").strip(),
            risk_status=parse_risk_status(card_data),
        )
        season = DashenHeroTreemapSeason(
            logical=bundle.logical_season,
            request=bundle.request_season,
            include_previous_season=bundle.include_previous_season,
        )
        return player, season, tuple(heroes)

    def _load_ow_config(self) -> Dict[str, Any]:
        config = self.config_loader()
        return config if isinstance(config, dict) else {}

    def _build_hero_lookup(self, config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        for item in list(config.get("heroList") or []):
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("heroGuid") or item.get("hero_id") or item.get("heroId") or "").strip()
            if not hero_guid:
                continue
            lookup[hero_guid] = item
        return lookup

    def _resolve_hero_payload_rows(self, payload_data: Dict[str, Any], *, mode: str) -> list[Dict[str, Any]]:
        if mode == MODE_QUICK:
            hero_rows = (
                _list_dicts(payload_data.get("presetsHeroUseSummaryList"))
                or _list_dicts(payload_data.get("presetsyList"))
                or _list_dicts(payload_data.get("v6HeroUseSummaryList"))
                or _list_dicts(payload_data.get("openHeroUseSummaryList"))
                or _list_dicts(payload_data.get("openHeroList"))
            )
        else:
            hero_rows = (
                _list_dicts(payload_data.get("presetsHeroUseSummaryList"))
                or _list_dicts(payload_data.get("presetsHeroList"))
                or _list_dicts(payload_data.get("openHeroUseSummaryList"))
                or _list_dicts(payload_data.get("openHeroList"))
            )
        hero_rows.sort(
            key=lambda item: (-_safe_float(item.get("gameTime")), str(item.get("heroGuid") or item.get("heroId") or "")),
        )
        return hero_rows

    def _hero_icon_url(self, item: Dict[str, Any]) -> str:
        for key in ("smallIconUrl", "ddHeroIcon", "icon", "circleIcon", "portrait", "avatar"):
            text = str(item.get(key) or "").strip()
            if text:
                return text
        return ""


__all__ = [
    "DashenHeroTreemapEngine",
    "DashenHeroTreemapHero",
    "DashenHeroTreemapPlayer",
    "DashenHeroTreemapSeason",
    "ROLE_LABELS",
]
