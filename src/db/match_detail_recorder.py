from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlsplit

try:
    from overstats.config import is_database_write_enabled
    from overstats.src.constants.ranks import get_rank_score
    from overstats.src.db.match_stats import IDPoolDB
    from overstats.src.modules.dashen_summary.runtime.stat_reference import (
        normalize_dashen_hero_stat_value,
        normalize_hero_rank_score,
    )
    from overstats.src.modules.query_tool import read_query_tool
except ModuleNotFoundError:
    from config import is_database_write_enabled
    from src.constants.ranks import get_rank_score
    from src.db.match_stats import IDPoolDB
    from src.modules.dashen_summary.runtime.stat_reference import (
        normalize_dashen_hero_stat_value,
        normalize_hero_rank_score,
    )
    from src.modules.query_tool import read_query_tool


@dataclass(frozen=True)
class _MatchDetailEvent:
    url: str
    payload: Dict[str, Any]


@dataclass
class ParsedNormalMatchDetailBatch:
    hero_detail_rows: List[Dict[str, Any]] = field(default_factory=list)
    comp_data_rows: List[Dict[str, Any]] = field(default_factory=list)
    perk_pick_rows: List[Dict[str, Any]] = field(default_factory=list)
    comp_summary_keys: set[tuple[str, str, Optional[int]]] = field(default_factory=set)
    perk_summary_keys: set[tuple[str, int, Optional[int]]] = field(default_factory=set)

    def extend(self, other: "ParsedNormalMatchDetailBatch") -> None:
        self.hero_detail_rows.extend(other.hero_detail_rows)
        self.comp_data_rows.extend(other.comp_data_rows)
        self.perk_pick_rows.extend(other.perk_pick_rows)
        self.comp_summary_keys.update(other.comp_summary_keys)
        self.perk_summary_keys.update(other.perk_summary_keys)


_STAT_VALUE_TEXT_BY_GUID: Optional[Dict[str, str]] = None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_use_time_rate(value: Any, use_time_sec: Any, game_time_sec: Any) -> float:
    numeric = _safe_float(value, -1.0)
    if numeric < 0:
        use_time_numeric = max(0.0, _safe_float(use_time_sec, 0.0))
        game_time_numeric = max(0.0, _safe_float(game_time_sec, 0.0))
        if game_time_numeric <= 0:
            return 0.0
        numeric = use_time_numeric / game_time_numeric
    elif numeric > 1.0:
        numeric = numeric / 100.0
    return max(0.0, min(1.0, numeric))


def _load_stat_value_text_by_guid() -> Dict[str, str]:
    global _STAT_VALUE_TEXT_BY_GUID
    cached = _STAT_VALUE_TEXT_BY_GUID
    if cached is not None:
        return cached
    mapping: Dict[str, str] = {}
    try:
        config = read_query_tool(default={})
    except Exception:
        config = {}
    for item in config.get("heroAttrList", []) or []:
        if not isinstance(item, dict):
            continue
        value_guid = str(item.get("valueGuid") or "").strip()
        if not value_guid or value_guid in mapping:
            continue
        mapping[value_guid] = str(item.get("valueText") or "")
    _STAT_VALUE_TEXT_BY_GUID = mapping
    return mapping


def _extract_match_id_from_url(request_url: str) -> str:
    try:
        parsed = urlsplit(str(request_url or ""))
    except Exception:
        return ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    values = query.get("matchId") or query.get("matchid") or []
    return str(values[0] if values else "").strip()


def _player_name(player: Dict[str, Any]) -> str:
    for key in ("name", "userName", "playerName"):
        value = str(player.get(key) or "").strip()
        if value:
            return value
    return ""


def _find_player_by_bnet(players: Sequence[Dict[str, Any]], bnet_id: str) -> Dict[str, Any]:
    normalized = str(bnet_id or "").strip()
    if not normalized:
        return {}
    for player in players or []:
        if str(player.get("bnetId") or "").strip() == normalized:
            return dict(player)
    return {}


def _find_player_by_token(players: Sequence[Dict[str, Any]], customer_token: str) -> Dict[str, Any]:
    normalized = str(customer_token or "").strip()
    if not normalized:
        return {}
    for player in players or []:
        if str(player.get("customerToken") or "").strip() == normalized:
            return dict(player)
    return {}


def _find_player_by_hero(players: Sequence[Dict[str, Any]], hero_guid: str) -> Dict[str, Any]:
    normalized = str(hero_guid or "").strip()
    if not normalized:
        return {}
    for player in players or []:
        if str(player.get("heroGuid") or "").strip() == normalized:
            return dict(player)
    return {}


def find_normal_match_focus_player(data: Dict[str, Any]) -> Dict[str, Any]:
    players = [
        dict(item)
        for item in list(data.get("teammateList") or []) + list(data.get("enemyList") or [])
        if isinstance(item, dict)
    ]
    if not players:
        return {}

    focus = _find_player_by_bnet(players, str(data.get("bnetId") or ""))
    if focus:
        return focus

    focus = _find_player_by_token(players, str(data.get("customerToken") or ""))
    if focus:
        return focus

    hero_list = [item for item in (data.get("heroList") or []) if isinstance(item, dict)]
    if hero_list:
        focus = _find_player_by_hero(players, str(hero_list[0].get("heroId") or hero_list[0].get("heroGuid") or ""))
        if focus:
            return focus

    return {}


def normalize_match_detail_stat_value(
    value_guid: Any,
    value: Any,
    user_time_sec: Any,
    *,
    value_text: Any = None,
) -> Optional[float]:
    resolved_value_text = value_text
    if resolved_value_text in (None, ""):
        resolved_value_text = _load_stat_value_text_by_guid().get(str(value_guid or ""), "")
    return normalize_dashen_hero_stat_value(value, user_time_sec, resolved_value_text, value_guid)


def extract_normal_match_detail_records(
    payload: Dict[str, Any],
    *,
    request_url: str = "",
    extracted_at: Optional[int] = None,
) -> ParsedNormalMatchDetailBatch:
    result = ParsedNormalMatchDetailBatch()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return result

    data = payload.get("data")
    if not isinstance(data, dict):
        return result

    match_id = _extract_match_id_from_url(request_url)
    if not match_id:
        return result

    focus_player = find_normal_match_focus_player(data)
    focus_bnet_id = str((focus_player or {}).get("bnetId") or data.get("bnetId") or "").strip()
    if not focus_bnet_id:
        return result

    now_ts = _safe_int(extracted_at if extracted_at is not None else time.time())
    focus_player_name = _player_name(focus_player) or str(data.get("name") or "").strip()
    focus_rank_score = _safe_int(get_rank_score(focus_player.get("rankInfo") or focus_player.get("rank_info") or {}), 0)
    focus_rank_bucket = normalize_hero_rank_score(focus_rank_score)
    map_guid = str(data.get("mapGuid") or "").strip()
    start_time = _safe_int(data.get("startTime"), 0)
    game_time_sec = _safe_int(data.get("gameTimeSec"), 0)

    for hero in data.get("heroList") or []:
        if not isinstance(hero, dict):
            continue
        hero_guid = str(hero.get("heroId") or hero.get("heroGuid") or "").strip()
        if not hero_guid:
            continue
        stat_map = hero.get("statMap")
        if not isinstance(stat_map, dict) or not stat_map:
            continue

        use_time_sec = _safe_float(hero.get("userTimeSec"), 0.0)
        use_time_rate = _normalize_use_time_rate(hero.get("useTimeRate"), use_time_sec, game_time_sec)
        result.hero_detail_rows.append(
            {
                "match_id": match_id,
                "player_bnet_id": focus_bnet_id,
                "player_name": focus_player_name,
                "hero_guid": hero_guid,
                "rank_score": focus_rank_bucket,
                "rank_bucket": focus_rank_bucket,
                "use_time_sec": use_time_sec,
                "use_time_rate": use_time_rate,
                "map_guid": map_guid,
                "start_time": start_time,
                "game_time_sec": game_time_sec,
                "stat_map_json": json.dumps(stat_map, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "last_update": now_ts,
            }
        )

        for statmap_name, raw_value in stat_map.items():
            statmap_key = str(statmap_name or "").strip()
            if not statmap_key:
                continue
            normalized_value = normalize_match_detail_stat_value(statmap_key, raw_value, use_time_sec)
            if normalized_value is None:
                continue
            raw_numeric = _safe_float(raw_value, 0.0)
            result.comp_data_rows.append(
                {
                    "match_id": match_id,
                    "player_bnet_id": focus_bnet_id,
                    "hero_guid": hero_guid,
                    "statmap_name": statmap_key,
                    "statmap_value": normalized_value,
                    "statmap_raw_value": raw_numeric,
                    "rank_score": focus_rank_bucket,
                    "rank_bucket": focus_rank_bucket,
                    "use_time_sec": use_time_sec,
                    "use_time_rate": use_time_rate,
                    "last_update": now_ts,
                }
            )
            result.comp_summary_keys.add((hero_guid, statmap_key, focus_rank_bucket))

    for player in list(data.get("teammateList") or []) + list(data.get("enemyList") or []):
        if not isinstance(player, dict):
            continue
        hero_guid = str(player.get("heroGuid") or "").strip()
        player_bnet_id = str(player.get("bnetId") or "").strip()
        if not hero_guid or not player_bnet_id:
            continue
        perks = player.get("perks") or []
        if not isinstance(perks, list) or not perks:
            continue
        player_name = _player_name(player)
        rank_score = _safe_int(get_rank_score(player.get("rankInfo") or player.get("rank_info") or {}), 0)
        rank_bucket = normalize_hero_rank_score(rank_score)
        for slot_index, perk in enumerate(perks):
            if not isinstance(perk, dict):
                continue
            perk_guid = str(perk.get("guid") or perk.get("perkGuid") or perk.get("id") or "").strip()
            if not perk_guid:
                continue
            perk_level = _safe_int(perk.get("perkLevel"), 0) or (slot_index + 1)
            result.perk_pick_rows.append(
                {
                    "match_id": match_id,
                    "player_bnet_id": player_bnet_id,
                    "player_name": player_name,
                    "hero_guid": hero_guid,
                    "perk_guid": perk_guid,
                    "perk_level": perk_level,
                    "slot_index": slot_index,
                    "rank_score": rank_bucket,
                    "rank_bucket": rank_bucket,
                    "start_time": start_time,
                    "last_update": now_ts,
                }
            )
            result.perk_summary_keys.add((hero_guid, perk_level, rank_bucket))

    return result


class MatchDetailRecorder:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db = IDPoolDB(db_path)
        self._queue: asyncio.Queue[Optional[_MatchDetailEvent]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started or not is_database_write_enabled():
            return
        await asyncio.to_thread(self.db.initialize_match_detail_schema)
        self._worker_task = asyncio.create_task(self._worker(), name="match-detail-recorder-worker")
        self._started = True

    async def enqueue(self, url: str, payload: Dict[str, Any]) -> None:
        if self._closed or not is_database_write_enabled():
            return
        if not self._started:
            await self.start()
        await self._queue.put(_MatchDetailEvent(str(url or ""), dict(payload or {})))

    async def close(self) -> None:
        if not self._started or self._closed:
            return
        self._closed = True
        await self._queue.join()
        await self._queue.put(None)
        if self._worker_task is not None:
            await self._worker_task
        self._worker_task = None

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:
                self._queue.task_done()
                return
            batch = [event]
            while True:
                try:
                    extra = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if extra is None:
                    await self._queue.put(None)
                    break
                batch.append(extra)
            try:
                await asyncio.to_thread(self._write_batch, batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _write_batch(self, batch: Sequence[_MatchDetailEvent]) -> None:
        merged = ParsedNormalMatchDetailBatch()
        extracted_at = int(time.time())
        for event in batch or []:
            merged.extend(
                extract_normal_match_detail_records(
                    event.payload,
                    request_url=event.url,
                    extracted_at=extracted_at,
                )
            )
        self.db.write_match_detail_batch(
            hero_detail_rows=merged.hero_detail_rows,
            comp_data_rows=merged.comp_data_rows,
            perk_pick_rows=merged.perk_pick_rows,
            comp_summary_keys=merged.comp_summary_keys,
            perk_summary_keys=merged.perk_summary_keys,
        )


__all__ = [
    "MatchDetailRecorder",
    "ParsedNormalMatchDetailBatch",
    "extract_normal_match_detail_records",
    "find_normal_match_focus_player",
    "normalize_match_detail_stat_value",
]
