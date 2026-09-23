from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
    from overstats.src.modules.season_config import get_dashen_current_season, get_dashen_season_rollover_at
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client
    from src.modules.season_config import get_dashen_current_season, get_dashen_season_rollover_at


DASHEN_SEASON_ROLLOVER_AT = get_dashen_season_rollover_at()
DASHEN_SEASON_AFTER_ROLLOVER = get_dashen_current_season()
DASHEN_SEASON_BEFORE_ROLLOVER = max(DASHEN_SEASON_AFTER_ROLLOVER - 1, 1)
CANONICAL_ROLE_TYPES = {"tank", "dps", "healer", "open"}
MAX_COMPETITIVE_LOOKBACK = 1


@dataclass(frozen=True)
class DashenQuickStrengthQuery:
    customer_token: str = ""
    bnet_id: str = ""
    limit: int = 12
    include_previous_season: bool = True


def get_live_dashen_season(now: Optional[dt.datetime] = None) -> int:
    return int(get_dashen_current_season())


def get_recent_dashen_seasons(current_season: Optional[int] = None, include_previous: bool = True) -> List[int]:
    current = int(current_season or get_live_dashen_season())
    seasons = [current]
    if include_previous and current > 1:
        seasons.append(current - 1)
    return seasons


def iter_dashen_season_request_values(season: Optional[int]) -> Iterable[Optional[int]]:
    if season is None:
        yield None
        return
    if int(season) == get_live_dashen_season():
        yield None
    yield int(season)


def extract_match_entries(payload: Any, *preferred_keys: str) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    data = payload.get("data", payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    keys = preferred_keys or ("matchList", "recentMatchList")
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def normalize_role_type(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def _match_begin_ts(match: Dict[str, Any]) -> int:
    try:
        return int(match.get("beginTs") or 0)
    except (TypeError, ValueError):
        return 0


def count_unique_match_entries(entries: Sequence[Dict[str, Any]]) -> int:
    seen_ids = set()
    count = 0
    for match in entries or []:
        match_id = str(match.get("matchId") or "").strip()
        if match_id:
            if match_id in seen_ids:
                continue
            seen_ids.add(match_id)
        count += 1
    return count


def merge_unique_match_entries(
    existing_entries: Sequence[Dict[str, Any]],
    new_entries: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged_entries: List[Dict[str, Any]] = []
    seen_ids = set()
    for source in (existing_entries or [], new_entries or []):
        for match in source:
            if not isinstance(match, dict):
                continue
            item = dict(match)
            match_id = str(item.get("matchId") or "").strip()
            if match_id:
                if match_id in seen_ids:
                    continue
                seen_ids.add(match_id)
            merged_entries.append(item)
    merged_entries.sort(key=_match_begin_ts, reverse=True)
    return merged_entries


class DashenQuickStrengthRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def list_recent_quick_matches(
        self,
        customer_token: str,
        *,
        limit: int,
        include_previous_season: bool,
        pages_per_batch: int = 1,
    ) -> List[Dict[str, Any]]:
        seasons = get_recent_dashen_seasons(include_previous=include_previous_season)
        matches: List[Dict[str, Any]] = []
        for logical_season in seasons:
            season_matches: List[Dict[str, Any]] = []
            for request_season in iter_dashen_season_request_values(logical_season):
                page = 1
                while count_unique_match_entries(season_matches) < int(limit):
                    previous_count = count_unique_match_entries(season_matches)
                    tasks = [
                        self.api_client.query_match_list(
                            customer_token,
                            "leisure",
                            page=page + offset,
                            season=request_season,
                        )
                        for offset in range(max(1, int(pages_per_batch)))
                    ]
                    payloads = await asyncio.gather(*tasks, return_exceptions=True)
                    batch_has_data = False
                    for payload in payloads:
                        if isinstance(payload, Exception) or not isinstance(payload, dict):
                            continue
                        if payload.get("code") != 0:
                            continue
                        entries = extract_match_entries(payload, "matchList", "recentMatchList")
                        if not entries:
                            continue
                        batch_has_data = True
                        for match in entries:
                            item = dict(match)
                            item["_dashenSeason"] = logical_season
                            item.setdefault("gameMode", "leisure")
                            season_matches.append(item)
                    season_matches = merge_unique_match_entries([], season_matches)
                    if not batch_has_data or count_unique_match_entries(season_matches) <= previous_count:
                        break
                    page += max(1, int(pages_per_batch))
                if season_matches:
                    break
            matches = merge_unique_match_entries(matches, season_matches)
            if count_unique_match_entries(matches) >= int(limit):
                break
        return list(matches[: int(limit)])

    async def get_match_detail(self, customer_token: str, match_id: str) -> Dict[str, Any]:
        return await self.api_client.query_match_info(customer_token, str(match_id))

    async def list_recent_competitive_payloads(
        self,
        customer_token: str,
        *,
        current_season: Optional[int] = None,
        max_lookback: int = MAX_COMPETITIVE_LOOKBACK,
        required_role: str = "",
    ) -> List[tuple[int, List[Dict[str, Any]]]]:
        live_season = int(current_season or get_live_dashen_season())
        normalized_lookback = max(0, min(MAX_COMPETITIVE_LOOKBACK, int(max_lookback)))
        min_season = max(live_season - normalized_lookback, 1)
        payloads: List[tuple[int, List[Dict[str, Any]]]] = []
        observed_roles = set()
        required_role_type = normalize_role_type(required_role)
        found_required_role = not required_role_type
        for logical_season in range(live_season, min_season - 1, -1):
            found_any = False
            for request_season in iter_dashen_season_request_values(logical_season):
                try:
                    payload = await self.api_client.query_count_info(
                        customer_token,
                        "sport",
                        season=request_season,
                    )
                except Exception:
                    continue
                if not isinstance(payload, dict) or payload.get("code") != 0:
                    continue
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                guide_count_data = data.get("guideCountData")
                rows = [item for item in list(guide_count_data or []) if isinstance(item, dict)]
                payloads.append((logical_season, rows))
                for item in rows:
                    role_type = normalize_role_type(item.get("roleType"))
                    if role_type:
                        observed_roles.add(role_type)
                        if role_type == required_role_type:
                            found_required_role = True
                found_any = True
                break
            if not found_any:
                payloads.append((logical_season, []))
            if found_required_role:
                break
            if observed_roles >= CANONICAL_ROLE_TYPES:
                break
        return payloads

    async def list_quick_history_pages(
        self,
        customer_token: str,
        *,
        logical_season: Optional[int],
        target_match_id: str = "",
        start_page: int = 1,
        max_pages: int = 5,
    ) -> Dict[str, Any]:
        history: List[Dict[str, Any]] = []
        last_page = max(0, int(start_page) - 1)
        found_target = False
        completed = False
        start_page_num = max(1, int(start_page))
        max_page_num = max(1, int(max_pages))
        if start_page_num > max_page_num:
            return {
                "history": [],
                "last_page": last_page,
                "found_target": False,
                "completed": True,
            }
        for request_season in iter_dashen_season_request_values(logical_season):
            season_history: List[Dict[str, Any]] = []
            for page in range(start_page_num, max_page_num + 1):
                last_page = page
                try:
                    payload = await self.api_client.query_match_list(
                        customer_token,
                        "leisure",
                        page=page,
                        season=request_season,
                    )
                except Exception:
                    break
                if not isinstance(payload, dict) or payload.get("code") != 0:
                    break
                entries = extract_match_entries(payload, "matchList", "recentMatchList")
                if not entries:
                    completed = True
                    break
                batch_found_target = False
                for match in entries:
                    item = dict(match)
                    if logical_season is not None:
                        item["_dashenSeason"] = logical_season
                    item.setdefault("gameMode", "leisure")
                    season_history.append(item)
                    if target_match_id and str(item.get("matchId") or "") == str(target_match_id):
                        batch_found_target = True
                if batch_found_target:
                    found_target = True
                    break
            if season_history:
                history = merge_unique_match_entries(history, season_history)
            if season_history or found_target or completed:
                break
        return {
            "history": history,
            "last_page": last_page,
            "found_target": found_target,
            "completed": completed,
        }
