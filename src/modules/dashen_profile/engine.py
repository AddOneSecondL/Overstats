from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime as dt
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from .requests import (
    DashenProfileBundle,
    DashenProfileRequests,
    count_unique_match_entries,
    extract_match_entries,
    get_live_dashen_season,
    get_recent_dashen_seasons,
    merge_unique_match_entries,
)


RECENT_MATCH_TARGET = 24
ROLE_ORDER = ("tank", "dps", "healer", "open")

DASHEN_RACE_PROGRESS_DISPLAY_START = dt.datetime(2026, 4, 10, 0, 0, 0)
DASHEN_RACE_PROGRESS_DISPLAY_END = dt.datetime(2026, 4, 14, 23, 59, 59)
DASHEN_RACE_PROGRESS_MATCH_START = dt.datetime(2026, 4, 10, 2, 0, 0)
DASHEN_RACE_PROGRESS_MATCH_END = dt.datetime(2026, 4, 14, 23, 59, 59)
DASHEN_RACE_PROGRESS_CHECKPOINTS = (500, 1000, 1600, 2200, 3000, 4000)
DASHEN_RACE_PROGRESS_CAP = 4000
DASHEN_RACE_PROGRESS_WIN = 210
DASHEN_RACE_PROGRESS_STADIUM_WIN = 265
DASHEN_RACE_PROGRESS_GROUP_BONUS = 50
RACE_PROGRESS_DETAIL_CONCURRENCY = 5
COMP_HISTORY_PAGE_BATCH = 5
RACE_PROGRESS_NOTE = "当前仅统计竞技与角斗竞技进度，未完成对局不会纳入估算。"
HERO_TITLE_QUICK_5V5 = "快速比赛5V5英雄使用时长"
HERO_TITLE_QUICK_6V6 = "快速比赛6V6英雄使用时长"
HERO_TITLE_COMP_5V5 = "竞技比赛5V5英雄使用时长"
HERO_TITLE_COMP_6V6 = "竞技比赛6V6英雄使用时长"


@dataclass(frozen=True)
class HeroBillboardEntry:
    hero_guid: str
    province: str
    rank_num: int
    ranked_level: int = 0


@dataclass(frozen=True)
class HeroRankOverlay:
    rank_level: int
    ranked_level: int
    fill: tuple[int, int, int, int]


@dataclass(frozen=True)
class HeroUsageRow:
    payload: Dict[str, Any]
    hero_guid: str
    hero_level: int
    game_time: float
    match_sum: int
    win_sum: int
    win_rate: float
    rank_overlay: Optional[HeroRankOverlay] = None
    billboards: tuple[HeroBillboardEntry, ...] = ()


@dataclass(frozen=True)
class RolePanelEntry:
    role_type: str
    score: int
    tier: str
    max_score: int
    max_tier: str
    match_sum: int
    win_sum: int
    is_history: bool = False
    history_season: str = ""


@dataclass(frozen=True)
class ProfileRenderContext:
    profile_card: Dict[str, Any]
    sport_payload: Dict[str, Any]
    leisure_payload: Dict[str, Any]
    resolved_name: str
    battletag: str
    battlenum: str
    title: str
    level: int
    game_time: float
    logical_season: Optional[int]
    quick_mode: bool
    avatar_bytes: Optional[bytes]
    selected_payload: Dict[str, Any]
    role_entries: tuple[RolePanelEntry, ...]
    hero_title: str
    hero_rows: tuple[HeroUsageRow, ...]
    top_heroes: tuple[HeroUsageRow, ...]
    recent_matches: tuple[Dict[str, Any], ...]
    leftover_open_billboards: tuple[HeroBillboardEntry, ...]
    leftover_preset_billboards: tuple[HeroBillboardEntry, ...]
    race_progress: Optional[Dict[str, Any]] = None


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


def _safe_begin_ts(match: Dict[str, Any]) -> int:
    try:
        return int((match or {}).get("beginTs") or 0)
    except (TypeError, ValueError):
        return 0


def _local_datetime_to_ts_ms(value: dt.datetime) -> int:
    return int(time.mktime(value.timetuple()) * 1000)


def _is_dashen_race_progress_active(now: Optional[dt.datetime] = None) -> bool:
    current = now or dt.datetime.now()
    return DASHEN_RACE_PROGRESS_DISPLAY_START <= current <= DASHEN_RACE_PROGRESS_DISPLAY_END


def _get_dashen_race_progress_loss(score: int, match_mode: str = "normal") -> int:
    score = _safe_int(score)
    if match_mode == "stadium":
        if 500 <= score < 1000:
            return 27
        if 1000 <= score < 1500:
            return 53
        if score >= 1500:
            return 80
        return 63

    if 500 <= score < 1000:
        return 21
    if 1000 <= score < 1600:
        return 42
    return 63


def _normalize_progress_match_result(match: Dict[str, Any]) -> int:
    match_ret = match.get("matchRet")
    try:
        return int(match_ret)
    except (TypeError, ValueError):
        pass

    team_score = _safe_int(match.get("teamScore"))
    opponent_score = _safe_int(match.get("opponentScore"))
    if team_score > opponent_score:
        return 1
    if team_score < opponent_score:
        return -1
    return 0


def _normalize_recent_match_entries(
    entries: Sequence[Dict[str, Any]],
    *,
    season_label: Optional[int] = None,
    game_mode: str = "",
    instance_type: str = "",
) -> list[Dict[str, Any]]:
    normalized_entries: list[Dict[str, Any]] = []
    for match in entries or []:
        if not isinstance(match, dict):
            continue
        item = dict(match)
        if season_label is not None:
            item["_dashenSeason"] = season_label
        if game_mode and not item.get("gameMode"):
            item["gameMode"] = game_mode
        if instance_type and not item.get("instanceType"):
            item["instanceType"] = instance_type
        normalized_entries.append(item)
    return normalized_entries


def _extend_match_pool_unique(
    target_pool: list[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
    *,
    limit: Optional[int] = None,
) -> None:
    existing_ids = {
        str(match.get("matchId") or "").strip()
        for match in target_pool
        if isinstance(match, dict) and str(match.get("matchId") or "").strip()
    }
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        match_id = str(item.get("matchId") or "").strip()
        if match_id and match_id in existing_ids:
            continue
        if match_id:
            existing_ids.add(match_id)
        target_pool.append(dict(item))
        if limit is not None and count_unique_match_entries(target_pool) >= limit:
            break


def build_role_panel_entries(
    current_guide_rows: Sequence[Dict[str, Any]],
    historical_guide_rows: Sequence[tuple[int, Sequence[Dict[str, Any]]]],
) -> tuple[RolePanelEntry, ...]:
    current_map = {
        str(item.get("roleType") or ""): item
        for item in current_guide_rows
        if isinstance(item, dict)
    }
    historical_maps = [
        (
            season_id,
            {
                str(item.get("roleType") or ""): item
                for item in guide_rows
                if isinstance(item, dict)
            },
        )
        for season_id, guide_rows in historical_guide_rows
    ]

    entries: list[RolePanelEntry] = []
    for role_type in ROLE_ORDER:
        current_role_data = current_map.get(role_type)
        current_rank_score = _safe_int(((current_role_data or {}).get("lastRankInfo") or {}).get("rankScore"))
        final_data = dict(current_role_data or {})
        is_history = False
        history_season = ""

        if current_rank_score <= 0:
            ranked_history: Optional[tuple[int, Dict[str, Any]]] = None
            unranked_history: Optional[tuple[int, Dict[str, Any]]] = None
            for season_id, guide_map in historical_maps:
                history_item = guide_map.get(role_type)
                if not history_item:
                    continue
                score = _safe_int(((history_item.get("lastRankInfo") or {}).get("rankScore")))
                if score > 0:
                    ranked_history = (season_id, history_item)
                    break
                if unranked_history is None:
                    unranked_history = (season_id, history_item)

            if ranked_history is not None:
                final_data = dict(ranked_history[1])
                is_history = True
                history_season = f"S{ranked_history[0]}"
            elif unranked_history is not None:
                final_data = dict(unranked_history[1])
                is_history = True
                history_season = f"S{unranked_history[0]}"

        last_rank_info = final_data.get("lastRankInfo") if isinstance(final_data.get("lastRankInfo"), dict) else {}
        max_rank_info = final_data.get("maxRankInfo") if isinstance(final_data.get("maxRankInfo"), dict) else {}
        match_sum = _safe_int(final_data.get("matchSum"))
        win_rate = _safe_float(final_data.get("winRate"))
        entries.append(
            RolePanelEntry(
                role_type=role_type,
                score=_safe_int(last_rank_info.get("rankScore")),
                tier=str(last_rank_info.get("rankSubTier") or ""),
                max_score=_safe_int(max_rank_info.get("rankScore")),
                max_tier=str(max_rank_info.get("rankSubTier") or ""),
                match_sum=match_sum,
                win_sum=int(match_sum * win_rate / 100) if match_sum > 0 else 0,
                is_history=is_history,
                history_season=history_season,
            )
        )
    return tuple(entries)


class DashenProfileEngine:
    def __init__(self, requests: DashenProfileRequests) -> None:
        self.requests = requests

    async def build_render_context(
        self,
        bundle: DashenProfileBundle,
        *,
        resolved_name: str = "",
        avatar_bytes: Optional[bytes] = None,
        render_mode: str = "quick",
    ) -> ProfileRenderContext:
        card_data = _payload_data(bundle.profile_card)
        sport_data = _payload_data(bundle.sport)
        leisure_data = _payload_data(bundle.leisure)
        logical_season = int(bundle.logical_season or get_live_dashen_season())
        quick_mode = str(render_mode or "quick").lower() != "competitive"
        selected_payload = leisure_data if quick_mode else sport_data

        tasks: list[Awaitable[Any]] = [
            self._build_recent_match_pool(bundle, sport_data=sport_data, leisure_data=leisure_data),
            self._build_role_panel_entries(bundle, sport_data=sport_data),
            self.requests.get_billboard_user(bundle.customer_token),
        ]
        if _is_dashen_race_progress_active():
            tasks.append(
                self._build_dashen_race_progress(
                    bundle.customer_token,
                    logical_season=logical_season,
                    include_previous_season=bundle.include_previous_season,
                    target_bnet_id=str(card_data.get("bnetId") or ""),
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        recent_matches = ()
        if len(results) > 0 and not isinstance(results[0], Exception):
            recent_matches = tuple(results[0] or ())

        role_entries = ()
        if len(results) > 1 and not isinstance(results[1], Exception):
            role_entries = tuple(results[1] or ())

        billboard_payload = None
        if len(results) > 2 and not isinstance(results[2], Exception) and isinstance(results[2], dict):
            billboard_payload = results[2]

        race_progress = None
        if len(results) > 3 and not isinstance(results[3], Exception) and isinstance(results[3], dict):
            race_progress = results[3]

        hero_title, hero_rows, top_heroes, leftover_open, leftover_preset = self._build_hero_usage_rows(
            selected_payload,
            sport_data=sport_data,
            billboard_payload=billboard_payload,
            quick_mode=quick_mode,
        )

        display_name = str(card_data.get("name") or resolved_name or "").strip()
        battletag, battlenum = _split_battletag(display_name)
        return ProfileRenderContext(
            profile_card=bundle.profile_card,
            sport_payload=bundle.sport,
            leisure_payload=bundle.leisure,
            resolved_name=resolved_name,
            battletag=battletag,
            battlenum=battlenum,
            title=str(card_data.get("title") or "").strip(),
            level=_safe_int(card_data.get("level")),
            game_time=_safe_float(card_data.get("gameTime")),
            logical_season=bundle.logical_season,
            quick_mode=quick_mode,
            avatar_bytes=avatar_bytes,
            selected_payload=selected_payload,
            role_entries=role_entries,
            hero_title=hero_title,
            hero_rows=hero_rows,
            top_heroes=top_heroes,
            recent_matches=recent_matches,
            leftover_open_billboards=leftover_open,
            leftover_preset_billboards=leftover_preset,
            race_progress=race_progress,
        )

    async def _build_recent_match_pool(
        self,
        bundle: DashenProfileBundle,
        *,
        sport_data: Dict[str, Any],
        leisure_data: Dict[str, Any],
    ) -> tuple[Dict[str, Any], ...]:
        logical_season = int(bundle.logical_season or get_live_dashen_season())
        season_candidates = get_recent_dashen_seasons(
            logical_season,
            include_previous=bundle.include_previous_season,
        )
        match_pool: list[Dict[str, Any]] = []
        season_payload_cache: dict[int, tuple[Dict[str, Any], Dict[str, Any]]] = {
            logical_season: (bundle.sport, bundle.leisure),
        }

        async def get_season_payload_pair(season_id: int) -> tuple[Dict[str, Any], Dict[str, Any]]:
            cached = season_payload_cache.get(season_id)
            if cached is not None:
                return cached
            sport_payload, leisure_payload, _ = await self.requests.get_count_payload_pair(
                bundle.customer_token,
                logical_season=season_id,
            )
            season_payload_cache[season_id] = (sport_payload, leisure_payload)
            return sport_payload, leisure_payload

        for season_id in season_candidates:
            stadium_leisure_payload, stadium_sport_payload = await asyncio.gather(
                self.requests.get_stadium_leisure_role_card(bundle.customer_token, logical_season=season_id),
                self.requests.get_stadium_count(bundle.customer_token, logical_season=season_id),
            )
            stadium_pool = _normalize_recent_match_entries(
                extract_match_entries(stadium_leisure_payload, "recentMatchList", "matchList"),
                season_label=season_id,
                game_mode="LeisureFight",
            )
            stadium_pool.extend(
                _normalize_recent_match_entries(
                    extract_match_entries(stadium_sport_payload, "matchList", "recentMatchList"),
                    season_label=season_id,
                    game_mode="SportFight",
                )
            )
            if stadium_pool:
                match_pool = merge_unique_match_entries(match_pool, stadium_pool)
                break

        sport_match_list = _normalize_recent_match_entries(
            extract_match_entries(sport_data, "matchList", "recentMatchList"),
            season_label=logical_season,
            game_mode="sport",
        )
        _extend_match_pool_unique(match_pool, sport_match_list)
        if len(sport_match_list) >= 12:
            for season_id in season_candidates:
                extra_match = await self.requests.get_extra_match_page(
                    bundle.customer_token,
                    "sport",
                    page=2,
                    logical_season=season_id,
                )
                extra_entries = _normalize_recent_match_entries(
                    extract_match_entries(extra_match, "matchList", "recentMatchList"),
                    season_label=season_id,
                    game_mode="sport",
                )
                if extra_entries:
                    _extend_match_pool_unique(match_pool, extra_entries)
                    break

        leisure_match_list = _normalize_recent_match_entries(
            extract_match_entries(leisure_data, "matchList", "recentMatchList"),
            season_label=logical_season,
            game_mode="leisure",
            instance_type="IT_UNRANKED",
        )
        _extend_match_pool_unique(match_pool, leisure_match_list)
        if len(leisure_match_list) >= 12:
            for season_id in season_candidates:
                extra_match = await self.requests.get_extra_match_page(
                    bundle.customer_token,
                    "leisure",
                    page=2,
                    logical_season=season_id,
                )
                extra_entries = _normalize_recent_match_entries(
                    extract_match_entries(extra_match, "matchList", "recentMatchList"),
                    season_label=season_id,
                    game_mode="leisure",
                    instance_type="IT_UNRANKED",
                )
                if extra_entries:
                    _extend_match_pool_unique(match_pool, extra_entries)
                    break

        if bundle.include_previous_season:
            await self._fill_recent_match_pool_from_previous_season(
                bundle.customer_token,
                logical_season=logical_season,
                target_pool=match_pool,
                get_season_payload_pair=get_season_payload_pair,
            )

        match_pool = merge_unique_match_entries([], match_pool)
        return tuple(match_pool[:RECENT_MATCH_TARGET])

    async def _fill_recent_match_pool_from_previous_season(
        self,
        customer_token: str,
        *,
        logical_season: int,
        target_pool: list[Dict[str, Any]],
        get_season_payload_pair: Callable[[int], Awaitable[tuple[Dict[str, Any], Dict[str, Any]]]],
    ) -> None:
        if count_unique_match_entries(target_pool) >= RECENT_MATCH_TARGET:
            return

        previous_season = logical_season - 1
        if previous_season <= 0:
            return

        stadium_leisure_payload, stadium_sport_payload = await asyncio.gather(
            self.requests.get_stadium_leisure_role_card(customer_token, logical_season=previous_season),
            self.requests.get_stadium_count(customer_token, logical_season=previous_season),
        )
        _extend_match_pool_unique(
            target_pool,
            _normalize_recent_match_entries(
                extract_match_entries(stadium_leisure_payload, "recentMatchList", "matchList"),
                season_label=previous_season,
                game_mode="LeisureFight",
            ),
            limit=RECENT_MATCH_TARGET,
        )
        _extend_match_pool_unique(
            target_pool,
            _normalize_recent_match_entries(
                extract_match_entries(stadium_sport_payload, "matchList", "recentMatchList"),
                season_label=previous_season,
                game_mode="SportFight",
            ),
            limit=RECENT_MATCH_TARGET,
        )

        if count_unique_match_entries(target_pool) >= RECENT_MATCH_TARGET:
            return

        sport_payload, leisure_payload = await get_season_payload_pair(previous_season)
        sport_data = _payload_data(sport_payload)
        leisure_data = _payload_data(leisure_payload)

        sport_entries = _normalize_recent_match_entries(
            extract_match_entries(sport_data, "matchList", "recentMatchList"),
            season_label=previous_season,
            game_mode="sport",
        )
        _extend_match_pool_unique(target_pool, sport_entries, limit=RECENT_MATCH_TARGET)
        if count_unique_match_entries(target_pool) < RECENT_MATCH_TARGET and len(sport_entries) >= 12:
            extra_match = await self.requests.get_extra_match_page(
                customer_token,
                "sport",
                page=2,
                logical_season=previous_season,
            )
            _extend_match_pool_unique(
                target_pool,
                _normalize_recent_match_entries(
                    extract_match_entries(extra_match, "matchList", "recentMatchList"),
                    season_label=previous_season,
                    game_mode="sport",
                ),
                limit=RECENT_MATCH_TARGET,
            )

        if count_unique_match_entries(target_pool) >= RECENT_MATCH_TARGET:
            return

        leisure_entries = _normalize_recent_match_entries(
            extract_match_entries(leisure_data, "matchList", "recentMatchList"),
            season_label=previous_season,
            game_mode="leisure",
            instance_type="IT_UNRANKED",
        )
        _extend_match_pool_unique(target_pool, leisure_entries, limit=RECENT_MATCH_TARGET)
        if count_unique_match_entries(target_pool) < RECENT_MATCH_TARGET and len(leisure_entries) >= 12:
            extra_match = await self.requests.get_extra_match_page(
                customer_token,
                "leisure",
                page=2,
                logical_season=previous_season,
            )
            _extend_match_pool_unique(
                target_pool,
                _normalize_recent_match_entries(
                    extract_match_entries(extra_match, "matchList", "recentMatchList"),
                    season_label=previous_season,
                    game_mode="leisure",
                    instance_type="IT_UNRANKED",
                ),
                limit=RECENT_MATCH_TARGET,
            )

    async def _build_role_panel_entries(
        self,
        bundle: DashenProfileBundle,
        *,
        sport_data: Dict[str, Any],
    ) -> tuple[RolePanelEntry, ...]:
        logical_season = int(bundle.logical_season or get_live_dashen_season())
        seasons = [
            season_id
            for season_id in range(logical_season - 1, max(0, logical_season - 4), -1)
            if season_id > 0
        ]
        tasks = [
            self.requests.get_count_payload_pair(bundle.customer_token, logical_season=season_id)
            for season_id in seasons
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        historical_rows: list[tuple[int, Sequence[Dict[str, Any]]]] = []
        for season_id, result in zip(seasons, results):
            if isinstance(result, Exception):
                continue
            sport_payload, _, _ = result
            historical_rows.append((season_id, _list_dicts(_payload_data(sport_payload).get("guideCountData"))))

        return build_role_panel_entries(_list_dicts(sport_data.get("guideCountData")), historical_rows)

    def _build_hero_usage_rows(
        self,
        selected_payload: Dict[str, Any],
        *,
        sport_data: Dict[str, Any],
        billboard_payload: Optional[Dict[str, Any]],
        quick_mode: bool,
    ) -> tuple[str, tuple[HeroUsageRow, ...], tuple[HeroUsageRow, ...], tuple[HeroBillboardEntry, ...], tuple[HeroBillboardEntry, ...]]:
        hero_title, hero_payload_rows = _resolve_hero_payload_rows(selected_payload, quick_mode=quick_mode)
        overlay_lookup = _build_hero_rank_overlay_lookup(sport_data)

        billboard_data = {}
        if isinstance(billboard_payload, dict) and isinstance(billboard_payload.get("data"), dict):
            billboard_data = billboard_payload["data"]

        open_billboards = [
            entry
            for entry in (_to_billboard_entry(item) for item in _list_dicts(billboard_data.get("sportOpenHeroBillboardList")))
            if entry is not None
        ]
        preset_billboards = [
            entry
            for entry in (_to_billboard_entry(item) for item in _list_dicts(billboard_data.get("sportPresetHeroBillboardList")))
            if entry is not None
        ]

        used_open_indices: set[int] = set()
        used_preset_indices: set[int] = set()
        hero_rows: list[HeroUsageRow] = []

        for item in hero_payload_rows[:10]:
            hero_guid = str(item.get("heroGuid") or item.get("heroId") or "")
            matched_billboards: list[HeroBillboardEntry] = []

            for index, billboard in enumerate(open_billboards):
                if index in used_open_indices or billboard.hero_guid != hero_guid:
                    continue
                used_open_indices.add(index)
                matched_billboards.append(billboard)

            for index, billboard in enumerate(preset_billboards):
                if index in used_preset_indices or billboard.hero_guid != hero_guid:
                    continue
                used_preset_indices.add(index)
                matched_billboards.append(billboard)

            hero_rows.append(
                HeroUsageRow(
                    payload=dict(item),
                    hero_guid=hero_guid,
                    hero_level=_safe_int(item.get("heroLevel")),
                    game_time=_safe_float(item.get("gameTime")),
                    match_sum=_safe_int(item.get("matchSum")),
                    win_sum=_safe_int(item.get("winSum")),
                    win_rate=_safe_float(item.get("winRate")),
                    rank_overlay=overlay_lookup.get(hero_guid),
                    billboards=tuple(matched_billboards),
                )
            )

        leftover_open = tuple(
            billboard
            for index, billboard in enumerate(open_billboards)
            if index not in used_open_indices
        )
        leftover_preset = tuple(
            billboard
            for index, billboard in enumerate(preset_billboards)
            if index not in used_preset_indices
        )
        return hero_title, tuple(hero_rows), tuple(hero_rows[:3]), leftover_open, leftover_preset

    async def _build_dashen_race_progress(
        self,
        customer_token: str,
        *,
        logical_season: int,
        include_previous_season: bool,
        target_bnet_id: str,
    ) -> Optional[Dict[str, Any]]:
        if not customer_token:
            return None

        normal_matches, stadium_matches = await asyncio.gather(
            self._get_comp_history_matches_in_range(
                customer_token,
                _local_datetime_to_ts_ms(DASHEN_RACE_PROGRESS_MATCH_START),
                _local_datetime_to_ts_ms(DASHEN_RACE_PROGRESS_MATCH_END),
                logical_season=logical_season,
                include_previous_season=include_previous_season,
            ),
            self._get_stadium_ranked_matches_in_range(
                customer_token,
                _local_datetime_to_ts_ms(DASHEN_RACE_PROGRESS_MATCH_START),
                _local_datetime_to_ts_ms(DASHEN_RACE_PROGRESS_MATCH_END),
                logical_season=logical_season,
            ),
        )

        filtered_matches: list[Dict[str, Any]] = []
        for match in normal_matches:
            if _safe_int(((match.get("rankInfo") or {}).get("rankScore"))) <= 0:
                continue
            item = dict(match)
            item["_progress_mode"] = "normal"
            filtered_matches.append(item)

        for match in stadium_matches:
            item = dict(match)
            item["_progress_mode"] = "stadium"
            filtered_matches.append(item)

        filtered_matches.sort(key=_safe_begin_ts)
        progress = {
            "score": 0,
            "cap": DASHEN_RACE_PROGRESS_CAP,
            "checkpoints": list(DASHEN_RACE_PROGRESS_CHECKPOINTS),
            "highest_checkpoint": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "group_wins": 0,
            "match_count": len(filtered_matches),
            "note": RACE_PROGRESS_NOTE,
        }
        if not filtered_matches:
            return progress

        sem = asyncio.Semaphore(RACE_PROGRESS_DETAIL_CONCURRENCY)

        async def fetch_group_flag(match_item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            match_id = str(match_item.get("matchId") or "").strip()
            if not match_id:
                return None
            async with sem:
                try:
                    detail = await self.requests.get_match_detail(customer_token, match_id)
                except Exception:
                    return {"match_id": match_id, "is_group": False}

            data = detail.get("data") if isinstance(detail, dict) else None
            teammates = data.get("teammateList") if isinstance(data, dict) else None
            if not isinstance(teammates, list):
                return {"match_id": match_id, "is_group": False}

            me = None
            if target_bnet_id:
                me = next((player for player in teammates if str(player.get("bnetId")) == target_bnet_id), None)
            if me is None:
                me = next(
                    (player for player in teammates if str(player.get("customerToken") or "") == customer_token),
                    None,
                )
            friend_ids = me.get("friendBnetIds") if isinstance(me, dict) else []
            return {"match_id": match_id, "is_group": bool(friend_ids)}

        async def fetch_stadium_detail(match_item: Dict[str, Any]) -> Dict[str, Any]:
            match_id = str(match_item.get("matchId") or "").strip()
            if not match_id:
                return {"match_id": "", "is_group": False, "result": 0}
            async with sem:
                try:
                    payload = await self.requests.get_fight_match_detail(customer_token, match_id)
                except Exception:
                    return {"match_id": match_id, "is_group": False, "result": 0}

            data = payload.get("data") if isinstance(payload, dict) else None
            total_count = data.get("totalCount") if isinstance(data, dict) else None
            teammates = total_count.get("teammateList") if isinstance(total_count, dict) else None

            me = None
            if isinstance(teammates, list):
                if target_bnet_id:
                    me = next((player for player in teammates if str(player.get("bnetId")) == target_bnet_id), None)
                if me is None:
                    me = next(
                        (player for player in teammates if str(player.get("customerToken") or "") == customer_token),
                        None,
                    )

            friend_ids = me.get("friendBnetIds") if isinstance(me, dict) else []
            team_score = _safe_int((total_count or {}).get("teamScore"))
            opponent_score = _safe_int((total_count or {}).get("opponentScore"))
            if team_score > opponent_score:
                result = 1
            elif team_score < opponent_score:
                result = -1
            else:
                result = 0

            return {"match_id": match_id, "is_group": bool(friend_ids), "result": result}

        normal_win_matches = [
            match
            for match in filtered_matches
            if match.get("_progress_mode") != "stadium" and _normalize_progress_match_result(match) == 1
        ]
        normal_detail_rows = await asyncio.gather(*(fetch_group_flag(match) for match in normal_win_matches))
        stadium_detail_rows = await asyncio.gather(
            *(fetch_stadium_detail(match) for match in filtered_matches if match.get("_progress_mode") == "stadium")
        )

        group_flags = {
            row["match_id"]: bool(row.get("is_group"))
            for row in normal_detail_rows + stadium_detail_rows
            if isinstance(row, dict) and row.get("match_id")
        }
        result_overrides = {
            row["match_id"]: _safe_int(row.get("result"))
            for row in stadium_detail_rows
            if isinstance(row, dict) and row.get("match_id")
        }

        score = 0
        highest_checkpoint = 0
        for match in filtered_matches:
            match_id = str(match.get("matchId") or "").strip()
            is_group = group_flags.get(match_id, False)
            result = result_overrides.get(match_id, _normalize_progress_match_result(match))
            match_mode = str(match.get("_progress_mode") or "normal")

            if result == 1:
                progress["wins"] += 1
                if is_group:
                    progress["group_wins"] += 1
                score += DASHEN_RACE_PROGRESS_STADIUM_WIN if match_mode == "stadium" else DASHEN_RACE_PROGRESS_WIN
                if is_group:
                    score += DASHEN_RACE_PROGRESS_GROUP_BONUS
            elif result == 0:
                progress["ties"] += 1
            else:
                progress["losses"] += 1
                if score >= DASHEN_RACE_PROGRESS_CHECKPOINTS[0]:
                    score = max(highest_checkpoint, score - _get_dashen_race_progress_loss(score, match_mode))

            score = min(score, DASHEN_RACE_PROGRESS_CAP)
            for checkpoint in DASHEN_RACE_PROGRESS_CHECKPOINTS:
                if score >= checkpoint:
                    highest_checkpoint = max(highest_checkpoint, checkpoint)

        progress["score"] = score
        progress["highest_checkpoint"] = highest_checkpoint
        return progress

    async def _get_comp_history_matches_in_range(
        self,
        customer_token: str,
        start_ts_ms: int,
        end_ts_ms: int,
        *,
        logical_season: int,
        include_previous_season: bool,
    ) -> list[Dict[str, Any]]:
        season_candidates = get_recent_dashen_seasons(logical_season, include_previous=include_previous_season)
        collected_matches: list[Dict[str, Any]] = []

        for season_id in season_candidates:
            page = 1
            while True:
                batch = await asyncio.gather(
                    *[
                        self.requests.get_extra_match_page(
                            customer_token,
                            "sport",
                            page=page + offset,
                            logical_season=season_id,
                        )
                        for offset in range(COMP_HISTORY_PAGE_BATCH)
                    ],
                    return_exceptions=True,
                )

                batch_has_data = False
                batch_oldest_ts: Optional[int] = None
                for payload in batch:
                    if isinstance(payload, Exception) or not isinstance(payload, dict):
                        continue
                    entries = extract_match_entries(payload, "matchList", "recentMatchList")
                    if not entries:
                        continue
                    batch_has_data = True
                    for match in entries:
                        begin_ts = _safe_begin_ts(match)
                        if batch_oldest_ts is None or begin_ts < batch_oldest_ts:
                            batch_oldest_ts = begin_ts
                        if start_ts_ms <= begin_ts <= end_ts_ms:
                            collected_matches.append(dict(match))

                    if batch_oldest_ts is not None and batch_oldest_ts < start_ts_ms:
                        break

                if not batch_has_data or (batch_oldest_ts is not None and batch_oldest_ts < start_ts_ms):
                    break
                page += COMP_HISTORY_PAGE_BATCH

        collected_matches.sort(key=_safe_begin_ts)
        return collected_matches

    async def _get_stadium_ranked_matches_in_range(
        self,
        customer_token: str,
        start_ts_ms: int,
        end_ts_ms: int,
        *,
        logical_season: int,
    ) -> list[Dict[str, Any]]:
        payload = await self.requests.get_stadium_count(customer_token, logical_season=logical_season)
        filtered_matches: list[Dict[str, Any]] = []
        for match in extract_match_entries(payload, "matchList", "recentMatchList"):
            begin_ts = _safe_begin_ts(match)
            if not (start_ts_ms <= begin_ts <= end_ts_ms):
                continue
            if _safe_int(((match.get("rankInfo") or {}).get("rankScore"))) <= 0:
                continue
            filtered_matches.append(dict(match))
        filtered_matches.sort(key=_safe_begin_ts)
        return filtered_matches


def _resolve_hero_payload_rows(payload_data: Dict[str, Any], *, quick_mode: bool) -> tuple[str, list[Dict[str, Any]]]:
    if quick_mode:
        primary = _list_dicts(payload_data.get("presetsHeroUseSummaryList")) or _list_dicts(payload_data.get("presetsyList"))
        if primary:
            hero_rows = primary
            title = HERO_TITLE_QUICK_5V5
        else:
            hero_rows = (
                _list_dicts(payload_data.get("v6HeroUseSummaryList"))
                or _list_dicts(payload_data.get("openHeroUseSummaryList"))
                or _list_dicts(payload_data.get("openHeroList"))
            )
            title = HERO_TITLE_QUICK_6V6
    else:
        primary = _list_dicts(payload_data.get("presetsHeroUseSummaryList")) or _list_dicts(payload_data.get("presetsHeroList"))
        if primary:
            hero_rows = primary
            title = HERO_TITLE_COMP_5V5
        else:
            hero_rows = _list_dicts(payload_data.get("openHeroUseSummaryList")) or _list_dicts(payload_data.get("openHeroList"))
            title = HERO_TITLE_COMP_6V6

    hero_rows.sort(key=lambda item: _safe_float(item.get("gameTime")), reverse=True)
    return title, hero_rows


def _build_hero_rank_overlay_lookup(sport_data: Dict[str, Any]) -> Dict[str, HeroRankOverlay]:
    lookup: Dict[str, HeroRankOverlay] = {}
    for source_key, fill in (
        ("presetsHeroUseSummaryList", (158, 170, 202, 255)),
        ("openHeroUseSummaryList", (33, 35, 43, 255)),
    ):
        for item in _list_dicts(sport_data.get(source_key)):
            hero_guid = str(item.get("heroGuid") or item.get("heroId") or "")
            if not hero_guid or hero_guid in lookup:
                continue
            hero_rank_info = item.get("heroRankInfo")
            if not isinstance(hero_rank_info, dict):
                continue
            rank_level = _safe_int(hero_rank_info.get("rank")) + 1
            ranked_level = _safe_int(hero_rank_info.get("rankedLevel"))
            if ranked_level <= 0:
                continue
            lookup[hero_guid] = HeroRankOverlay(
                rank_level=rank_level,
                ranked_level=ranked_level,
                fill=fill,
            )
    return lookup


def _to_billboard_entry(item: Dict[str, Any]) -> Optional[HeroBillboardEntry]:
    if not isinstance(item, dict):
        return None
    hero_guid = str(item.get("heroGuid") or "")
    if not hero_guid:
        return None
    return HeroBillboardEntry(
        hero_guid=hero_guid,
        province=str(item.get("province") or ""),
        rank_num=_safe_int(item.get("rankNum")),
        ranked_level=_safe_int(item.get("rankedLevel")),
    )


def _split_battletag(text: str) -> tuple[str, str]:
    if "#" not in text:
        return text, ""
    battletag, battlenum = text.split("#", 1)
    return battletag.strip(), battlenum.strip()
