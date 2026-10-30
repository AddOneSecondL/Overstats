from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
    from overstats.src.modules.season_config import get_dashen_current_season, get_dashen_season_rollover_at
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client
    from src.modules.season_config import get_dashen_current_season, get_dashen_season_rollover_at


from ..query_tool import read_query_tool
from ..errors import ModuleError
from ...constants.chara import iter_hero_alias_pairs


DASHEN_SEASON_ROLLOVER_AT = get_dashen_season_rollover_at()
DASHEN_SEASON_AFTER_ROLLOVER = get_dashen_current_season()
DASHEN_SEASON_BEFORE_ROLLOVER = max(DASHEN_SEASON_AFTER_ROLLOVER - 1, 1)
DEFAULT_FIGHT_MODES = ("QuickFight", "LeisureFight", "SportFight")


@dataclass(frozen=True)
class DashenMatchQuery:
    customer_token: str = ""
    bnet_id: str = ""
    seasons: Optional[Sequence[int]] = None
    include_previous_season: bool = True
    include_fight: bool = True
    target_count: int = 20
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DashenMatchDetail:
    match_id: str
    match_kind: str
    payload: Dict[str, Any]
    source_match: Dict[str, Any] = field(default_factory=dict)


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


def is_fight_match(match: Dict[str, Any]) -> bool:
    return "fight" in str((match or {}).get("gameMode") or "").lower()


def _filter_text(value):
    return re.sub(r"[\s\-—_：:·.]", "", str(value or "")).casefold()


def _resource_id(value):
    value = str(value or "").strip()
    try:
        return str(int(value, 16 if value.lower().startswith("0x") else 10))
    except ValueError:
        return value.casefold()


def resolve_match_filters(filters):
    result = {key: value for key, value in (filters or {}).items() if key not in {"map", "hero", "search"} or str(value or "").strip()}
    mode = str(result.pop("mode", "") or "").strip().lower()
    if mode:
        modes = {"快速": "leisure", "quick": "leisure", "leisure": "leisure",
                 "竞技": "sport", "competitive": "sport", "sport": "sport"}
        if mode not in modes:
            raise ModuleError(error="invalid_match_filter", message="对局模式仅支持快速或竞技。", status_code=400)
        result["gameMode"] = modes[mode]
    if not any(result.get(key) for key in ("hero", "map", "search")):
        return result
    config = read_query_tool(default={})
    aliases = {_filter_text(a): name for a, name in iter_hero_alias_pairs()}
    def resolve(kind, value):
        text = _filter_text(value)
        name = _filter_text(aliases.get(text, value)) if kind == "hero" else text
        rows = config.get("heroList" if kind == "hero" else "mapList", [])
        ids = set()
        for row in rows:
            row_name = _filter_text(row.get("name"))
            raw_ids = [row.get(k) for k in (("heroGuid", "heroId", "id", "guid") if kind == "hero" else ("guid", "id", "mapGuid"))]
            if name == row_name or (kind == "map" and name in row_name and len(name) >= 2) or _resource_id(value) in {_resource_id(v) for v in raw_ids if v}:
                ids.update(_resource_id(v) for v in raw_ids if v)
        return ids
    for kind in ("hero", "map"):
        value = result.pop(kind, None)
        if value:
            ids = resolve(kind, value)
            if not ids:
                raise ModuleError(error="invalid_match_filter", message=f"未识别的{'英雄' if kind == 'hero' else '地图'}：{value}", status_code=400)
            result["_"+kind+"_ids"] = ids
    search = str(result.pop("search", "") or "").strip()
    for value in search.split():
        candidates = [(kind, resolve(kind, value)) for kind in ("hero", "map")]
        candidates = [(kind, ids) for kind, ids in candidates if ids]
        if len(candidates) != 1:
            raise ModuleError(error="invalid_match_filter", message=f"无法识别筛选条件：{value}，请使用 地图:名称 或 英雄:名称。", status_code=400)
        kind, ids = candidates[0]
        key = "_"+kind+"_ids"
        result[key] = result[key] & ids if key in result else ids
    return result


def _matches_filters(match: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    for key, expected in (filters or {}).items():
        if key in {"_hero_ids", "_map_ids"}:
            if key == "_map_ids":
                values = [match.get("mapGuid"), match.get("mapId")]
            else:
                values = [match.get("heroGuid"), match.get("heroId")]
                for hero in match.get("heroList") or []:
                    if isinstance(hero, dict):
                        values.extend([hero.get("heroGuid"), hero.get("heroId"), hero.get("id")])
                    else:
                        values.append(hero)
            if not {_resource_id(v) for v in values if v} & expected:
                return False
            continue
        actual = match.get(key)
        if key in {"kill", "assist", "cure", "death", "heroDamage", "resistDamage"}:
            try:
                if int(actual or 0) < int(expected):
                    return False
            except (TypeError, ValueError):
                return False
            continue
        if key in {"killMax", "cureMax", "resistDamageMax", "heroDamageMax"}:
            expected_bool = str(expected).lower() in {"1", "true", "yes", "on"}
            if bool(actual) != expected_bool:
                return False
            continue
        if isinstance(actual, (list, tuple, set)):
            if expected not in actual and str(expected) not in {str(item) for item in actual}:
                return False
            continue
        if str(actual) != str(expected):
            return False
    return True


class DashenMatchRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def list_recent_matches(self, query: DashenMatchQuery) -> List[Dict[str, Any]]:
        filters = resolve_match_filters(query.filters)
        if any(key in filters for key in ("_map_ids", "_hero_ids", "gameMode")):
            allowed = get_recent_dashen_seasons(include_previous=query.include_previous_season)
            seasons = [season for season in allowed if not query.seasons or season in query.seasons]
            return await self._search_matches(query, seasons, max(1, min(20, int(query.target_count))), filters)
        seasons = list(query.seasons or get_recent_dashen_seasons(include_previous=query.include_previous_season))
        matches: List[Dict[str, Any]] = []
        for logical_season in seasons:
            season_matches: List[Dict[str, Any]] = []
            for request_season in iter_dashen_season_request_values(logical_season):
                payloads = await self._fetch_recent_payloads(
                    query.customer_token,
                    request_season,
                    include_fight=query.include_fight,
                )
                for payload in payloads:
                    for match in extract_match_entries(payload, "matchList", "recentMatchList"):
                        item = dict(match)
                        item["_dashenSeason"] = logical_season
                        season_matches.append(item)
                if season_matches:
                    break
            matches = merge_unique_match_entries(matches, season_matches)
            if count_unique_match_entries(matches) >= query.target_count:
                break

        if filters:
            matches = [match for match in matches if _matches_filters(match, filters)]
        return matches

    async def _search_matches(self, query, seasons, limit, filters):
        async def scan_mode(mode, fight, season):
            found = []
            for request_season in iter_dashen_season_request_values(season):
                seen = set()
                page = 1
                while True:
                    fetch = self.api_client.fight_query_match_list if fight else self.api_client.query_match_list
                    payload = await fetch(query.customer_token, mode, page=page, season=request_season)
                    if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and (payload.get("success") is False or payload.get("ok") is False or payload.get("code") not in (None, 0, 200, "0", "200"))):
                        raise ModuleError(error="match_search_failed", message="对局检索失败，请稍后重试。", status_code=502)
                    batch = extract_match_entries(payload)
                    fresh = []
                    for match in batch:
                        key = str(match.get("matchId") or (match.get("beginTs"), match.get("mapGuid"), mode))
                        if key in seen:
                            continue
                        seen.add(key)
                        item = dict(match, _dashenSeason=season)
                        item["gameMode"] = mode
                        fresh.append(item)
                    if not fresh:
                        break
                    found = merge_unique_match_entries(found, [m for m in fresh if _matches_filters(m, filters)])
                    if len(found) >= limit:
                        break
                    page += 1
                if seen:
                    break
            return found[:limit]

        matches = []
        modes = [("leisure", False), ("sport", False)]
        if filters.get("gameMode"):
            modes = [(filters["gameMode"], False)]
        elif query.include_fight:
            modes += [(mode, True) for mode in DEFAULT_FIGHT_MODES]
        for season in seasons:
            batches = await asyncio.gather(*(scan_mode(mode, fight, season) for mode, fight in modes))
            for batch in batches:
                matches = merge_unique_match_entries(matches, batch)
            if len(matches) >= limit:
                break
        return matches[:limit]

    async def list_history_matches(
        self,
        customer_token: str,
        *,
        game_modes: Sequence[str] = ("sport", "leisure"),
        fight_modes: Sequence[str] = DEFAULT_FIGHT_MODES,
        seasons: Optional[Sequence[int]] = None,
        include_previous_season: bool = True,
        pages_per_batch: int = 5,
        min_begin_ts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        season_values = list(seasons or get_recent_dashen_seasons(include_previous=include_previous_season))
        matches: List[Dict[str, Any]] = []
        for logical_season in season_values:
            season_matches: List[Dict[str, Any]] = []
            for request_season in iter_dashen_season_request_values(logical_season):
                normal = await self._fetch_history_for_modes(
                    customer_token,
                    game_modes=game_modes,
                    season=request_season,
                    pages_per_batch=pages_per_batch,
                    min_begin_ts=min_begin_ts,
                )
                fight = await self._fetch_history_for_fight_modes(
                    customer_token,
                    fight_modes=fight_modes,
                    season=request_season,
                    pages_per_batch=pages_per_batch,
                    min_begin_ts=min_begin_ts,
                )
                for match in normal + fight:
                    item = dict(match)
                    item["_dashenSeason"] = logical_season
                    season_matches.append(item)
                if season_matches:
                    break
            matches = merge_unique_match_entries(matches, season_matches)
        return matches

    async def fetch_history_matches_page(
        self,
        customer_token: str,
        *,
        page: int = 1,
        season: Optional[int] = None,
        game_modes: Sequence[str] = ("sport", "leisure"),
        fight_modes: Sequence[str] = DEFAULT_FIGHT_MODES,
        min_begin_ts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        tasks = []
        task_meta: List[tuple[str, str]] = []
        page_num = max(1, int(page))

        for game_mode in game_modes:
            tasks.append(
                self.api_client.query_match_list(
                    customer_token,
                    game_mode,
                    page=page_num,
                    season=season,
                )
            )
            task_meta.append(("normal", str(game_mode)))

        for fight_mode in fight_modes:
            tasks.append(
                self.api_client.fight_query_match_list(
                    customer_token,
                    game_mode=fight_mode,
                    page=page_num,
                    season=season,
                )
            )
            task_meta.append(("fight", str(fight_mode)))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        matches: List[Dict[str, Any]] = []
        for (kind, game_mode), result in zip(task_meta, results):
            if isinstance(result, Exception) or not isinstance(result, dict):
                continue
            batch_matches = self._extract_history_batch([result], min_begin_ts=min_begin_ts)
            if not batch_matches:
                continue
            for match in batch_matches:
                item = dict(match)
                if kind == "fight":
                    item["gameMode"] = game_mode
                else:
                    item.setdefault("gameMode", game_mode)
                matches.append(item)
        return merge_unique_match_entries([], matches)

    async def get_match_detail(self, customer_token: str, match: Dict[str, Any] | str) -> DashenMatchDetail:
        if isinstance(match, dict):
            source_match = dict(match)
            match_id = str(source_match.get("matchId") or "")
            fight = is_fight_match(source_match)
        else:
            source_match = {}
            match_id = str(match)
            fight = False

        payload = (
            await self.api_client.fight_query_match_info(customer_token, match_id)
            if fight
            else await self.api_client.query_match_info(customer_token, match_id)
        )
        return DashenMatchDetail(
            match_id=match_id,
            match_kind="fight" if fight else "normal",
            payload=payload,
            source_match=source_match,
        )

    async def _fetch_recent_payloads(
        self,
        customer_token: str,
        season: Optional[int],
        *,
        include_fight: bool,
    ) -> List[Dict[str, Any]]:
        tasks = [
            self.api_client.query_count_info(customer_token, "leisure", season=season),
            self.api_client.query_count_info(customer_token, "sport", season=season),
            self.api_client.query_match_list(customer_token, "leisure", page=2, season=season),
            self.api_client.query_match_list(customer_token, "sport", page=2, season=season),
        ]
        fight_task_meta = []
        if include_fight:
            for page in (1, 2):
                for game_mode in DEFAULT_FIGHT_MODES:
                    tasks.append(
                        self.api_client.fight_query_match_list(
                            customer_token,
                            game_mode=game_mode,
                            page=page,
                            season=season,
                        )
                    )
                    fight_task_meta.append((len(tasks) - 1, game_mode))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        payloads: List[Dict[str, Any]] = []
        fight_mode_by_index = dict(fight_task_meta)
        for idx, result in enumerate(results):
            if isinstance(result, Exception) or not isinstance(result, dict):
                continue
            game_mode = fight_mode_by_index.get(idx)
            if game_mode:
                for match in extract_match_entries(result, "matchList", "recentMatchList"):
                    match["gameMode"] = game_mode
            payloads.append(result)
        return payloads

    async def _fetch_history_for_modes(
        self,
        customer_token: str,
        *,
        game_modes: Sequence[str],
        season: Optional[int],
        pages_per_batch: int,
        min_begin_ts: Optional[int],
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for game_mode in game_modes:
            page = 1
            while True:
                tasks = [
                    self.api_client.query_match_list(customer_token, game_mode, page=page + offset, season=season)
                    for offset in range(pages_per_batch)
                ]
                batch = await asyncio.gather(*tasks, return_exceptions=True)
                batch_matches = self._extract_history_batch(batch, min_begin_ts=min_begin_ts)
                if not batch_matches:
                    break
                for match in batch_matches:
                    match.setdefault("gameMode", game_mode)
                matches = merge_unique_match_entries(matches, batch_matches)
                if self._batch_is_older_than(batch_matches, min_begin_ts):
                    break
                page += pages_per_batch
        return matches

    async def _fetch_history_for_fight_modes(
        self,
        customer_token: str,
        *,
        fight_modes: Sequence[str],
        season: Optional[int],
        pages_per_batch: int,
        min_begin_ts: Optional[int],
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for game_mode in fight_modes:
            page = 1
            while True:
                tasks = [
                    self.api_client.fight_query_match_list(customer_token, game_mode, page=page + offset, season=season)
                    for offset in range(pages_per_batch)
                ]
                batch = await asyncio.gather(*tasks, return_exceptions=True)
                batch_matches = self._extract_history_batch(batch, min_begin_ts=min_begin_ts)
                if not batch_matches:
                    break
                for match in batch_matches:
                    match["gameMode"] = game_mode
                matches = merge_unique_match_entries(matches, batch_matches)
                if self._batch_is_older_than(batch_matches, min_begin_ts):
                    break
                page += pages_per_batch
        return matches

    def _extract_history_batch(self, payloads: Sequence[Any], *, min_begin_ts: Optional[int]) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for payload in payloads:
            if isinstance(payload, Exception):
                continue
            for match in extract_match_entries(payload, "matchList", "recentMatchList"):
                if min_begin_ts is not None and _match_begin_ts(match) < int(min_begin_ts):
                    continue
                matches.append(dict(match))
        return matches

    def _batch_is_older_than(self, matches: Sequence[Dict[str, Any]], min_begin_ts: Optional[int]) -> bool:
        if min_begin_ts is None or not matches:
            return False
        max_begin_ts = max(_match_begin_ts(match) for match in matches)
        return bool(max_begin_ts and max_begin_ts < int(min_begin_ts))
