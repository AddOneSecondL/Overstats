from __future__ import annotations

import asyncio
import datetime as dt
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ....constants.ranks import get_rank_score, raw_rank_score_to_strength

try:
    from overstats.src.client.apiclient import (
        dashen_api_client,
    )
    from overstats.src.modules.season_config import (
        get_dashen_current_season as resolve_dashen_current_season,
        get_dashen_season_rollover_at,
    )
except ModuleNotFoundError:
    from src.client.apiclient import (  # type: ignore[no-redef]
        dashen_api_client,
    )
    from src.modules.season_config import (
        get_dashen_current_season as resolve_dashen_current_season,
        get_dashen_season_rollover_at,
    )

from .db import IDPoolDB


DASHEN_SEASON_ROLLOVER_AT = get_dashen_season_rollover_at()
DASHEN_SEASON_AFTER_ROLLOVER = resolve_dashen_current_season()
DASHEN_SEASON_BEFORE_ROLLOVER = max(DASHEN_SEASON_AFTER_ROLLOVER - 1, 1)

_DASHEN_SEASON_OVERRIDE: Optional[int] = None
_OVERRIDE_RAW = str(os.getenv("OVERSTATS_DASHEN_SEASON_OVERRIDE", "") or "").strip()
if _OVERRIDE_RAW:
    try:
        _DASHEN_SEASON_OVERRIDE = int(_OVERRIDE_RAW)
    except (TypeError, ValueError):
        _DASHEN_SEASON_OVERRIDE = None

db = IDPoolDB()
DEFAULT_SUMMARY_REQUEST_CONCURRENCY = 4
DEFAULT_NORMAL_PAGE_BATCH = 2
SUMMARY_REQUEST_CONCURRENCY = max(
    1,
    int(os.getenv("OVERSTATS_SUMMARY_REQUEST_CONCURRENCY", str(DEFAULT_SUMMARY_REQUEST_CONCURRENCY)) or DEFAULT_SUMMARY_REQUEST_CONCURRENCY),
)
SUMMARY_NORMAL_PAGE_BATCH = max(
    1,
    int(os.getenv("OVERSTATS_SUMMARY_NORMAL_PAGE_BATCH", str(DEFAULT_NORMAL_PAGE_BATCH)) or DEFAULT_NORMAL_PAGE_BATCH),
)
_summary_request_semaphore: Optional[asyncio.Semaphore] = None


def set_dashen_season_override(season_num: Optional[int] = None) -> Optional[int]:
    global _DASHEN_SEASON_OVERRIDE
    if season_num in (None, "", "auto", "AUTO", "自动"):
        _DASHEN_SEASON_OVERRIDE = None
        return None
    _DASHEN_SEASON_OVERRIDE = int(season_num)
    return _DASHEN_SEASON_OVERRIDE


def get_dashen_season_override() -> Optional[int]:
    return _DASHEN_SEASON_OVERRIDE


def get_live_dashen_season(now: Optional[dt.datetime] = None) -> int:
    return int(resolve_dashen_current_season())


def get_current_dashen_season(now: Optional[dt.datetime] = None) -> int:
    if _DASHEN_SEASON_OVERRIDE is not None:
        return int(_DASHEN_SEASON_OVERRIDE)
    return int(resolve_dashen_current_season())


class _DashenSeason:
    def __int__(self) -> int:
        return get_current_dashen_season()

    def __index__(self) -> int:
        return int(self)

    def __str__(self) -> str:
        return str(int(self))

    def __repr__(self) -> str:
        return str(int(self))

    def __format__(self, format_spec: str) -> str:
        return format(int(self), format_spec)

    def __eq__(self, other: object) -> bool:
        try:
            return int(self) == int(other)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    def __lt__(self, other: object) -> bool:
        return int(self) < int(other)  # type: ignore[arg-type]

    def __le__(self, other: object) -> bool:
        return int(self) <= int(other)  # type: ignore[arg-type]

    def __gt__(self, other: object) -> bool:
        return int(self) > int(other)  # type: ignore[arg-type]

    def __ge__(self, other: object) -> bool:
        return int(self) >= int(other)  # type: ignore[arg-type]

    def __add__(self, other: int) -> int:
        return int(self) + other

    def __radd__(self, other: int) -> int:
        return other + int(self)

    def __sub__(self, other: int) -> int:
        return int(self) - other

    def __rsub__(self, other: int) -> int:
        return other - int(self)


season = _DashenSeason()


def _get_summary_request_semaphore() -> asyncio.Semaphore:
    global _summary_request_semaphore
    if _summary_request_semaphore is None:
        _summary_request_semaphore = asyncio.Semaphore(SUMMARY_REQUEST_CONCURRENCY)
    return _summary_request_semaphore


async def _run_summary_request(awaitable: Any) -> Any:
    async with _get_summary_request_semaphore():
        return await awaitable


def _safe_begin_ts(match: Dict[str, Any]) -> int:
    try:
        return int((match or {}).get("beginTs") or 0)
    except (TypeError, ValueError):
        return 0


def _extract_match_entries(payload: Any, *preferred_keys: str) -> List[Dict[str, Any]]:
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


def _count_unique_dashen_matches(matches: Sequence[Dict[str, Any]]) -> int:
    seen_ids = set()
    count = 0
    for match in matches or []:
        match_id = str(match.get("matchId") or "").strip()
        if match_id:
            if match_id in seen_ids:
                continue
            seen_ids.add(match_id)
        count += 1
    return count


def _merge_unique_dashen_matches(
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
    merged_entries.sort(key=_safe_begin_ts, reverse=True)
    return merged_entries


def get_recent_dashen_seasons(current_season: Optional[int] = None, include_previous: bool = True) -> List[int]:
    current = int(current_season if current_season is not None else season)
    seasons = [current]
    if _DASHEN_SEASON_OVERRIDE is not None and current == int(_DASHEN_SEASON_OVERRIDE):
        return seasons
    if include_previous and current > 1:
        seasons.append(current - 1)
    return seasons


def get_recent_dashen_fill_seasons(current_season: Optional[int] = None) -> List[int]:
    current = int(current_season if current_season is not None else season)
    seasons = [current]
    if current > 1:
        seasons.append(current - 1)
    return seasons


def _normalize_dashen_logical_season(season_c: Optional[int] = None) -> Optional[int]:
    if season_c in (None, "", 0, "0"):
        return int(season)
    try:
        return int(season_c)
    except (TypeError, ValueError):
        return None


def iter_dashen_season_request_values(season_c: Optional[int] = None) -> Iterable[Optional[int]]:
    logical_season = _normalize_dashen_logical_season(season_c)
    if logical_season is None:
        yield season_c
        return

    candidates: List[Optional[int]] = []
    if logical_season == get_live_dashen_season():
        candidates.append(None)
    candidates.append(logical_season)

    seen = set()
    for candidate in candidates:
        key = "__current__" if candidate is None else candidate
        if key in seen:
            continue
        seen.add(key)
        yield candidate


async def ds_get_single_match(token: str, match_id: str, mode: int = 0) -> Dict[str, Any]:
    return await _run_summary_request(dashen_api_client.query_match_info(token, str(match_id)))


async def ds_get_single_fight_match(token: str, match_id: str) -> Dict[str, Any]:
    return await _run_summary_request(dashen_api_client.fight_query_match_info(token, str(match_id)))


async def get_fight_match_list(
    token: str,
    game_mode: str = "SportFight",
    page: int = 1,
    season_c: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    for request_season in iter_dashen_season_request_values(season_c):
        try:
            payload = await _run_summary_request(
                dashen_api_client.fight_query_match_list(
                    token,
                    game_mode=game_mode,
                    page=int(page),
                    season=request_season,
                )
            )
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("code") == 0:
            if _extract_match_entries(payload, "matchList", "recentMatchList"):
                return payload
    return None


async def _get_history_matchK(
    token: str,
    game_mode: str,
    *,
    season_c: Optional[int] = None,
    minimum_match_count: int = 0,
    merge_all_recent_seasons: bool = False,
    min_begin_ts: Optional[int] = None,
    batch_size: int = SUMMARY_NORMAL_PAGE_BATCH,
) -> List[Dict[str, Any]]:
    match_list: List[Dict[str, Any]] = []
    season_candidates = (
        get_recent_dashen_fill_seasons(season_c)
        if merge_all_recent_seasons or minimum_match_count > 0
        else get_recent_dashen_seasons(season_c)
    )
    for logical_season in season_candidates:
        season_match_list: List[Dict[str, Any]] = []
        for request_season in iter_dashen_season_request_values(logical_season):
            page = 1
            while True:
                tasks = [
                    _run_summary_request(
                        dashen_api_client.query_match_list(
                            token,
                            game_mode,
                            page=page + offset,
                            season=request_season,
                        )
                    )
                    for offset in range(batch_size)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                batch_has_data = False
                batch_max_begin_ts = 0
                for payload in results:
                    if isinstance(payload, Exception) or not isinstance(payload, dict):
                        continue
                    if payload.get("code") != 0:
                        continue
                    entries = _extract_match_entries(payload, "matchList", "recentMatchList")
                    if not entries:
                        continue
                    batch_has_data = True
                    for item in entries:
                        entry = dict(item)
                        entry["_dashenSeason"] = logical_season
                        entry.setdefault("gameMode", game_mode)
                        begin_ts = _safe_begin_ts(entry)
                        batch_max_begin_ts = max(batch_max_begin_ts, begin_ts)
                        if min_begin_ts is not None and begin_ts < int(min_begin_ts):
                            continue
                        season_match_list.append(entry)

                if not batch_has_data:
                    break
                if min_begin_ts is not None and batch_max_begin_ts and batch_max_begin_ts < int(min_begin_ts):
                    break
                page += batch_size

            if season_match_list:
                break

        if season_match_list:
            match_list = _merge_unique_dashen_matches(match_list, season_match_list)
            if not merge_all_recent_seasons and (
                minimum_match_count <= 0 or _count_unique_dashen_matches(match_list) >= minimum_match_count
            ):
                break

    return match_list


async def get_history_comp_matchK(
    token: str,
    season_c: Optional[int] = None,
    minimum_match_count: int = 0,
    merge_all_recent_seasons: bool = False,
    min_begin_ts: Optional[int] = None,
) -> List[Dict[str, Any]]:
    return await _get_history_matchK(
        token,
        "sport",
        season_c=season_c,
        minimum_match_count=minimum_match_count,
        merge_all_recent_seasons=merge_all_recent_seasons,
        min_begin_ts=min_begin_ts,
    )


async def get_history_leis_matchK(
    token: str,
    season_c: Optional[int] = None,
    minimum_match_count: int = 0,
    merge_all_recent_seasons: bool = False,
    min_begin_ts: Optional[int] = None,
) -> List[Dict[str, Any]]:
    return await _get_history_matchK(
        token,
        "leisure",
        season_c=season_c,
        minimum_match_count=minimum_match_count,
        merge_all_recent_seasons=merge_all_recent_seasons,
        min_begin_ts=min_begin_ts,
    )


async def get_history_comp_match(
    token: str,
    season_c: Optional[int] = None,
    minimum_match_count: int = 0,
    merge_all_recent_seasons: bool = False,
) -> List[Dict[str, Any]]:
    return await get_history_comp_matchK(
        token,
        season_c=season_c,
        minimum_match_count=minimum_match_count,
        merge_all_recent_seasons=merge_all_recent_seasons,
    )


async def get_history_leis_match(
    token: str,
    season_c: Optional[int] = None,
    minimum_match_count: int = 0,
    merge_all_recent_seasons: bool = False,
) -> List[Dict[str, Any]]:
    return await get_history_leis_matchK(
        token,
        season_c=season_c,
        minimum_match_count=minimum_match_count,
        merge_all_recent_seasons=merge_all_recent_seasons,
    )


async def get_icon(url: str) -> bytes:
    return await dashen_api_client.get_icon(url)


async def ranking_dist2(st: int = 0) -> Optional[tuple[int, List[int]]]:
    rows = db.get_all_rank()
    if not rows:
        return None

    rank_scores: List[int] = []
    missing_count = 0
    bucket_fields = {
        0: ("tank", "dps", "healer"),
        1: ("tank",),
        2: ("dps",),
        3: ("healer",),
        4: ("tank",),
    }.get(int(st), ("tank", "dps", "healer"))

    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in bucket_fields:
            try:
                score = int(row.get(field) or 0)
            except (TypeError, ValueError):
                score = 0
            if score:
                rank_scores.append(score)
            else:
                missing_count += 1
    return missing_count, rank_scores


def _coerce_rank_score(value: Any) -> Optional[float]:
    score = raw_rank_score_to_strength(value)
    if score is None:
        return None
    return float(score)


async def match_rating_recent(match_id: str, token: str, config: Dict[str, Any]) -> tuple[Any, ...]:
    try:
        payload = await dashen_api_client.query_match_info(token, str(match_id))
    except Exception:
        return (-1, 0, 0, 0, 0, 0, 0, 0, [], [], 0, 0, 0, 0)

    if not isinstance(payload, dict) or payload.get("code") != 0:
        return (-1, 0, 0, 0, 0, 0, 0, 0, [], [], 0, 0, 0, 0)

    data = payload.get("data") or {}
    scores: List[float] = []
    team_scores: List[float] = []
    enemy_scores: List[float] = []

    for side, bucket in (("team", team_scores), ("enemy", enemy_scores)):
        for player in data.get("teammateList" if side == "team" else "enemyList", []) or []:
            if not isinstance(player, dict):
                continue
            rank_info = player.get("rankInfo") or player.get("rank_info") or {}
            score = _coerce_rank_score(get_rank_score(rank_info, None))
            if score is None:
                last_rank_info = (
                    player.get("lastRankInfo")
                    or player.get("last_rank_info")
                    or rank_info.get("lastRankInfo")
                    or rank_info.get("last_rank_info")
                    or {}
                )
                score = _coerce_rank_score(get_rank_score(last_rank_info, None))
            if score is None:
                continue
            scores.append(score)
            bucket.append(score)

    high = max(scores) if scores else 0
    low = min(scores) if scores else 0
    avg = sum(scores) / len(scores) if scores else 0
    team_high = max(team_scores) if team_scores else 0
    team_low = min(team_scores) if team_scores else 0

    return (
        data.get("matchRet", -1),
        high,
        low,
        avg,
        high,
        low,
        0,
        0,
        team_scores,
        enemy_scores,
        team_high,
        team_low,
        high,
        low,
    )
