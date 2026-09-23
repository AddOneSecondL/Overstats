from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

try:
    from overstats.src.modules.dashen_profile.requests import (
        DashenProfileBundle,
        DashenProfileQuery,
        DashenProfileRequests,
        build_empty_count_payload,
        get_recent_dashen_seasons,
        payload_has_profile_content,
    )
except ModuleNotFoundError:
    from src.modules.dashen_profile.requests import (
        DashenProfileBundle,
        DashenProfileQuery,
        DashenProfileRequests,
        build_empty_count_payload,
        get_recent_dashen_seasons,
        payload_has_profile_content,
    )


MODE_COMPETITIVE = "competitive"
MODE_QUICK = "quick"
SUPPORTED_TREEMAP_MODES = (MODE_COMPETITIVE, MODE_QUICK, "quick6v6", "competitive6v6", "open", "competitive_open")

def is_quick(mode):
    return mode in (MODE_QUICK, "quick6v6", "open")

def hero_queue_keys(mode):
    if mode in ("open", "competitive_open"):
        return ("openHeroUseSummaryList", "openHeroList")
    if mode.endswith("6v6"):
        return ("v6HeroUseSummaryList",)
    return ("presetsHeroUseSummaryList", "presetsyList" if is_quick(mode) else "presetsHeroList")


@dataclass(frozen=True)
class DashenHeroTreemapQuery:
    customer_token: str = ""
    bnet_id: str = ""
    season: Optional[int] = None
    include_previous_season: bool = True
    mode: str = MODE_QUICK


def normalize_treemap_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"quick6v6", "competitive6v6", "open", "competitive_open"}:
        return normalized
    if normalized in {"competitive", "comp", "ranked"}:
        return MODE_COMPETITIVE
    if normalized in {"quick", "overview"}:
        return MODE_QUICK
    if not normalized:
        return MODE_QUICK
    raise ValueError(f"Unsupported mode: {value}")


def build_profile_query(query: DashenHeroTreemapQuery) -> DashenProfileQuery:
    return DashenProfileQuery(
        customer_token=query.customer_token,
        bnet_id=query.bnet_id,
        season=query.season,
        include_previous_season=query.include_previous_season,
    )


class DashenHeroTreemapRequests:
    def __init__(self, profile_requests: Optional[DashenProfileRequests] = None) -> None:
        self.profile_requests = profile_requests or DashenProfileRequests()
        self.api_client = self.profile_requests.api_client

    async def get_treemap_bundle(self, query: DashenHeroTreemapQuery) -> DashenProfileBundle:
        card = await self.api_client.query_card(query.customer_token)
        logical_seasons = (
            [int(query.season)]
            if query.season is not None
            else get_recent_dashen_seasons(include_previous=query.include_previous_season)
        )

        last_sport = build_empty_count_payload("sport")
        last_leisure = build_empty_count_payload("leisure")
        last_logical_season: Optional[int] = logical_seasons[0] if logical_seasons else None
        last_request_season: Optional[int] = None

        for logical_season in logical_seasons:
            sport_payload, leisure_payload, request_season = await self.profile_requests.get_count_payload_pair(
                query.customer_token,
                logical_season=logical_season,
            )
            last_sport = sport_payload
            last_leisure = leisure_payload
            last_logical_season = logical_season
            last_request_season = request_season

            target_payload = leisure_payload if is_quick(query.mode) else sport_payload
            if any((target_payload.get("data") or {}).get(key) for key in hero_queue_keys(query.mode)):
                return DashenProfileBundle(
                    customer_token=query.customer_token,
                    profile_card=card,
                    sport=sport_payload,
                    leisure=leisure_payload,
                    logical_season=logical_season,
                    request_season=request_season,
                    include_previous_season=query.include_previous_season,
                )

        return DashenProfileBundle(
            customer_token=query.customer_token,
            profile_card=card,
            sport=last_sport,
            leisure=last_leisure,
            logical_season=last_logical_season,
            request_season=last_request_season,
            include_previous_season=query.include_previous_season,
        )


__all__ = [
    "DashenHeroTreemapQuery",
    "DashenHeroTreemapRequests",
    "MODE_COMPETITIVE",
    "MODE_QUICK",
    "SUPPORTED_TREEMAP_MODES",
    "build_profile_query",
    "normalize_treemap_mode",
]
