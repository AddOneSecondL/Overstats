from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from overstats.src.constants.ranks import get_rank_score, raw_rank_score_to_strength, strength_score_to_rank
    from overstats.src.modules.personal_data_percentile import calculate_personal_data_ranking
except ModuleNotFoundError:
    from src.constants.ranks import get_rank_score, raw_rank_score_to_strength, strength_score_to_rank
    from src.modules.personal_data_percentile import calculate_personal_data_ranking

from .requests import DashenQuickStrengthRequests, get_live_dashen_season


DEFAULT_MATCH_LIMIT = 12
MIN_MATCH_LIMIT = 3
MAX_MATCH_LIMIT = 12
MAX_SCORE_LOOKBACK = 1
DEFAULT_SCORE_LOOKBACK = MAX_SCORE_LOOKBACK
DEFAULT_STREAK_HISTORY_PAGES = 1
DEFAULT_MATCH_CONCURRENCY = 4

def normalize_limit(value: Any) -> int:
    try:
        limit = int(value or DEFAULT_MATCH_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_MATCH_LIMIT
    return max(MIN_MATCH_LIMIT, min(MAX_MATCH_LIMIT, limit))


def normalize_role_type(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def convert_rank_score(score: Any) -> Optional[int]:
    return raw_rank_score_to_strength(score)


def score_to_rank(score: Any) -> str:
    return strength_score_to_rank(score)


def jitter_scores(scores: Sequence[Any], y_offset_step: int = 60) -> List[float]:
    valid_scores: List[int] = []
    for value in scores or []:
        try:
            score_num = int(float(value))
        except (TypeError, ValueError):
            continue
        if score_num <= 0:
            continue
        valid_scores.append(score_num)

    valid_scores.sort()
    adjusted_scores: List[float] = []
    count_map: Dict[int, int] = {}
    for score_num in valid_scores:
        repeated_count = count_map.get(score_num, 0)
        adjusted_scores.append(float(score_num + repeated_count * y_offset_step))
        count_map[score_num] = repeated_count + 1
    return adjusted_scores


def calculate_pre_match_streak(history: Sequence[Dict[str, Any]], target_match_id: str) -> int:
    if not history or not target_match_id:
        return 0

    index = None
    for idx, match in enumerate(history):
        if str(match.get("matchId") or "") == str(target_match_id):
            index = idx
            break
    if index is None:
        return 0

    older_matches = list(history[index + 1 :])
    if not older_matches:
        return 0

    streak = 0
    last_result: Optional[int] = None
    for match in older_matches:
        try:
            result = int(match.get("matchRet"))
        except (TypeError, ValueError):
            break
        if result == 1:
            if last_result in (1, None):
                streak += 1
                last_result = 1
                continue
            break
        if result == -1:
            if last_result in (-1, None):
                streak -= 1
                last_result = -1
                continue
            break
        break
    return streak


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _range_dict(scores: Iterable[Any]) -> Dict[str, int]:
    values: List[int] = []
    for value in scores:
        try:
            score_num = int(value)
        except (TypeError, ValueError):
            continue
        if score_num > 0:
            values.append(score_num)
    if not values:
        return {"min": 0, "max": 0}
    return {"min": min(values), "max": max(values)}


def _get_season_payload(
    recent_payloads: Sequence[tuple[int, List[Dict[str, Any]]]],
    target_season: int,
) -> List[Dict[str, Any]]:
    for season_num, guide_count_data in recent_payloads:
        if int(season_num) == int(target_season):
            return list(guide_count_data or [])
    return []


def _build_player_competitive_meta(
    recent_payloads: Sequence[tuple[int, List[Dict[str, Any]]]],
    *,
    live_season: int,
) -> Dict[str, Any]:
    latest_role_scores: Dict[str, int] = {}
    latest_role_seasons: Dict[str, int] = {}
    current_role_scores: Dict[str, int] = {}

    current_payload = _get_season_payload(recent_payloads, live_season)
    for row in current_payload:
        if not isinstance(row, dict):
            continue
        role_type = normalize_role_type(row.get("roleType"))
        score = convert_rank_score(get_rank_score(row.get("lastRankInfo") or row.get("last_rank_info") or {}))
        if role_type and score is not None:
            current_role_scores[role_type] = score

    for season_num, guide_count_data in recent_payloads:
        for row in guide_count_data:
            if not isinstance(row, dict):
                continue
            role_type = normalize_role_type(row.get("roleType"))
            if not role_type or role_type in latest_role_scores:
                continue
            score = convert_rank_score(get_rank_score(row.get("lastRankInfo") or row.get("last_rank_info") or {}))
            if score is None:
                continue
            latest_role_scores[role_type] = score
            latest_role_seasons[role_type] = int(season_num)

    return {
        "recent_payloads": list(recent_payloads),
        "latest_role_scores": latest_role_scores,
        "latest_role_seasons": latest_role_seasons,
        "current_role_scores": current_role_scores,
    }


class DashenQuickStrengthEngine:
    def __init__(
        self,
        requests: DashenQuickStrengthRequests,
        *,
        score_lookback: int = DEFAULT_SCORE_LOOKBACK,
        streak_history_pages: int = DEFAULT_STREAK_HISTORY_PAGES,
        match_concurrency: int = DEFAULT_MATCH_CONCURRENCY,
    ) -> None:
        self.requests = requests
        self.score_lookback = max(0, min(MAX_SCORE_LOOKBACK, int(score_lookback)))
        self.streak_history_pages = max(1, int(streak_history_pages))
        self.match_concurrency = max(1, int(match_concurrency))

    async def build(
        self,
        *,
        customer_token: str,
        limit: int,
        include_previous_season: bool,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        match_limit = normalize_limit(limit)
        live_season = int(get_live_dashen_season())
        recent_matches = await self.requests.list_recent_quick_matches(
            customer_token,
            limit=match_limit,
            include_previous_season=include_previous_season,
        )
        if not recent_matches:
            return {
                "summary": {
                    "match_count": 0,
                    "overall_avg_score": 0.0,
                    "overall_avg_rank": "Unranked",
                    "score_range": {"min": 0, "max": 0},
                    "used_previous_season_fallback": False,
                    "personal_data_exceeded_percent": None,
                    "personal_data_top_percent": None,
                    "personal_data_metric_count": 0,
                },
                "matches": [],
            }

        hero_role_map = self._build_hero_role_map(config)
        match_detail_cache: Dict[str, Dict[str, Any]] = {}
        match_detail_tasks: Dict[str, asyncio.Task[Dict[str, Any]]] = {}
        player_competitive_cache: Dict[tuple[str, str], Dict[str, Any]] = {}
        player_competitive_tasks: Dict[tuple[str, str], asyncio.Task[Dict[str, Any]]] = {}
        semaphore = asyncio.Semaphore(self.match_concurrency)

        async def get_match_detail(match_id: str) -> Dict[str, Any]:
            cache_key = str(match_id or "")
            if cache_key in match_detail_cache:
                return match_detail_cache[cache_key]
            task = match_detail_tasks.get(cache_key)
            if task is None:
                task = asyncio.create_task(self.requests.get_match_detail(customer_token, cache_key))
                match_detail_tasks[cache_key] = task
            try:
                match_detail_cache[cache_key] = await task
            finally:
                match_detail_tasks.pop(cache_key, None)
            return match_detail_cache[cache_key]

        async def get_player_competitive_meta(player_token: str, role_type: str) -> Dict[str, Any]:
            cache_key = (str(player_token or ""), normalize_role_type(role_type))
            if cache_key in player_competitive_cache:
                return player_competitive_cache[cache_key]
            task = player_competitive_tasks.get(cache_key)
            if task is None:
                async def _load_competitive_meta() -> Dict[str, Any]:
                    recent_payloads = await self.requests.list_recent_competitive_payloads(
                        cache_key[0],
                        current_season=live_season,
                        max_lookback=self.score_lookback,
                        required_role=cache_key[1],
                    )
                    return _build_player_competitive_meta(
                        recent_payloads,
                        live_season=live_season,
                    )
                task = asyncio.create_task(_load_competitive_meta())
                player_competitive_tasks[cache_key] = task
            try:
                player_competitive_cache[cache_key] = await task
            finally:
                player_competitive_tasks.pop(cache_key, None)
            return player_competitive_cache[cache_key]

        async def build_one(source_match: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self._build_match_point(
                    source_match=source_match,
                    live_season=live_season,
                    hero_role_map=hero_role_map,
                    get_match_detail=get_match_detail,
                    get_player_competitive_meta=get_player_competitive_meta,
                )

        results = await asyncio.gather(*(build_one(match) for match in recent_matches), return_exceptions=True)

        match_points_desc: List[Dict[str, Any]] = []
        used_previous_fallback = False
        for source_match, result in zip(recent_matches, results):
            if isinstance(result, Exception) or not isinstance(result, dict):
                point = self._empty_match_point(source_match)
            else:
                point = result
            logical_season = _safe_int(source_match.get("_dashenSeason"))
            if logical_season and logical_season < live_season:
                point["_used_previous_season_fallback"] = True
            if bool(point.get("_used_previous_season_fallback")):
                used_previous_fallback = True
            match_points_desc.append(point)

        match_points = list(reversed(match_points_desc))
        valid_avg_scores = [
            _safe_float(point.get("avg_score"))
            for point in match_points
            if _safe_float(point.get("avg_score")) > 0
        ]
        summary_score_range = _range_dict(int(round(score)) for score in valid_avg_scores)
        overall_avg_score = round(sum(valid_avg_scores) / len(valid_avg_scores), 1) if valid_avg_scores else 0.0
        personal_data_ranking = await asyncio.to_thread(
            calculate_personal_data_ranking,
            config,
            list(match_detail_cache.values()),
        )

        for point in match_points:
            point.pop("_used_previous_season_fallback", None)

        return {
            "summary": {
                "match_count": len(match_points),
                "overall_avg_score": overall_avg_score,
                "overall_avg_rank": score_to_rank(overall_avg_score) if overall_avg_score > 0 else "Unranked",
                "score_range": summary_score_range,
                "used_previous_season_fallback": used_previous_fallback,
                "personal_data_exceeded_percent": (
                    personal_data_ranking.exceeded_percent if personal_data_ranking else None
                ),
                "personal_data_top_percent": (
                    personal_data_ranking.top_percent if personal_data_ranking else None
                ),
                "personal_data_metric_count": (
                    personal_data_ranking.metric_count if personal_data_ranking else 0
                ),
            },
            "matches": match_points,
        }

    async def _build_match_point(
        self,
        *,
        source_match: Dict[str, Any],
        live_season: int,
        hero_role_map: Dict[str, str],
        get_match_detail: Any,
        get_player_competitive_meta: Any,
    ) -> Dict[str, Any]:
        match_id = str(source_match.get("matchId") or "")
        detail_payload = await get_match_detail(match_id)
        if not isinstance(detail_payload, dict) or detail_payload.get("code") != 0:
            return self._empty_match_point(source_match)

        data = detail_payload.get("data") if isinstance(detail_payload.get("data"), dict) else {}
        participants: List[Dict[str, Any]] = []
        for team_key, side in (("teammateList", "team"), ("enemyList", "enemy")):
            for player in data.get(team_key, []) or []:
                if not isinstance(player, dict):
                    continue
                player_token = str(player.get("customerToken") or "").strip()
                if not player_token:
                    continue
                hero_guid = str(player.get("heroGuid") or "").strip()
                role_type = hero_role_map.get(hero_guid) or normalize_role_type(player.get("roleType"))
                if not role_type:
                    continue
                participants.append(
                    {
                        "side": side,
                        "player_token": player_token,
                        "role_type": role_type,
                    }
                )

        if not participants:
            return self._empty_match_point(source_match)

        meta_results = await asyncio.gather(
            *(
                get_player_competitive_meta(
                    item["player_token"],
                    item["role_type"],
                )
                for item in participants
            ),
            return_exceptions=True,
        )
        team_scores: List[int] = []
        enemy_scores: List[int] = []
        latest_role_scores: List[int] = []
        latest_all_role_scores: List[int] = []
        current_role_scores: List[int] = []
        current_all_role_scores: List[int] = []
        used_previous_fallback = False

        for participant, player_meta in zip(participants, meta_results):
            if isinstance(player_meta, Exception) or not isinstance(player_meta, dict):
                continue

            role_type = participant["role_type"]
            score_bucket = team_scores if participant["side"] == "team" else enemy_scores

            latest_score = player_meta.get("latest_role_scores", {}).get(role_type)
            latest_season = player_meta.get("latest_role_seasons", {}).get(role_type)
            if isinstance(latest_score, int) and latest_score > 0:
                latest_role_scores.append(latest_score)
                score_bucket.append(latest_score)
                if latest_season is not None and int(latest_season) < live_season:
                    used_previous_fallback = True

            all_role_scores = [
                int(score)
                for score in player_meta.get("latest_role_scores", {}).values()
                if isinstance(score, int) and score > 0
            ]
            latest_all_role_scores.extend(all_role_scores)
            if any(
                int(season_num) < live_season
                for season_num in player_meta.get("latest_role_seasons", {}).values()
            ):
                used_previous_fallback = True

            current_score = player_meta.get("current_role_scores", {}).get(role_type)
            if isinstance(current_score, int) and current_score > 0:
                current_role_scores.append(current_score)

            current_all_scores = [
                int(score)
                for score in player_meta.get("current_role_scores", {}).values()
                if isinstance(score, int) and score > 0
            ]
            current_all_role_scores.extend(current_all_scores)

        avg_score = round(sum(latest_role_scores) / len(latest_role_scores), 1) if latest_role_scores else 0.0

        return {
            "match_id": match_id,
            "begin_ts": _safe_int(source_match.get("beginTs")),
            "result": _safe_int(data.get("matchRet", source_match.get("matchRet"))),
            "map_guid": str(source_match.get("mapGuid") or data.get("mapGuid") or ""),
            "avg_score": avg_score,
            "avg_rank": score_to_rank(avg_score) if avg_score > 0 else "Unranked",
            "role_range": _range_dict(latest_role_scores),
            "all_role_range": _range_dict(latest_all_role_scores),
            "current_role_range": _range_dict(current_role_scores),
            "current_all_role_range": _range_dict(current_all_role_scores),
            "team_scores": list(team_scores),
            "enemy_scores": list(enemy_scores),
            # Temporarily disabled to avoid extra quick-history fanout.
            "team_streak_avg": 0.0,
            "enemy_streak_avg": 0.0,
            "_used_previous_season_fallback": used_previous_fallback,
        }

    def _build_hero_role_map(self, config: Dict[str, Any]) -> Dict[str, str]:
        role_map: Dict[str, str] = {}
        for hero in config.get("heroList", []) or []:
            if not isinstance(hero, dict):
                continue
            hero_guid = str(
                hero.get("heroGuid")
                or hero.get("heroId")
                or hero.get("guid")
                or hero.get("id")
                or ""
            ).strip()
            if not hero_guid:
                continue
            role_type = normalize_role_type(hero.get("roleType"))
            if role_type:
                role_map[hero_guid] = role_type
        return role_map

    def _empty_match_point(self, source_match: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "match_id": str(source_match.get("matchId") or ""),
            "begin_ts": _safe_int(source_match.get("beginTs")),
            "result": _safe_int(source_match.get("matchRet")),
            "map_guid": str(source_match.get("mapGuid") or ""),
            "avg_score": 0.0,
            "avg_rank": "Unranked",
            "role_range": {"min": 0, "max": 0},
            "all_role_range": {"min": 0, "max": 0},
            "current_role_range": {"min": 0, "max": 0},
            "current_all_role_range": {"min": 0, "max": 0},
            "team_scores": [],
            "enemy_scores": [],
            "team_streak_avg": 0.0,
            "enemy_streak_avg": 0.0,
            "_used_previous_season_fallback": False,
        }
