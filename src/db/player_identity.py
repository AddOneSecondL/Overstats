from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

try:
    from overstats.src.db.match_stats import IDPoolDB, PLAYER_IDENTITY_TABLE
except ModuleNotFoundError:
    from src.db.match_stats import IDPoolDB, PLAYER_IDENTITY_TABLE


_BNET_ID_KEYS = ("bnetId", "bnetid", "bnet_id")
_BATTLETAG_KEYS = (
    "battletag",
    "battleTag",
    "battle_tag",
    "name",
    "userName",
    "playerName",
    "full_id",
    "fullId",
)
_BATTLENAME_KEYS = ("battlename", "battleName", "battle_name")
_BATTLENUM_KEYS = ("battlenum", "battleNum", "battle_num")


def _first_non_empty(mapping: Dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def normalize_battletag(text: Any) -> str:
    return str(text or "").replace("＃", "#").strip()


def split_battletag(text: Any) -> tuple[str, str]:
    normalized = normalize_battletag(text)
    if "#" not in normalized:
        return normalized, ""
    battlename, battlenum = normalized.rsplit("#", 1)
    return battlename.strip() or normalized, battlenum.strip()


def normalize_identity_record(
    *,
    bnetid: Any,
    battletag: Any = "",
    battlename: Any = "",
    battlenum: Any = "",
    update_time: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    normalized_bnetid = str(bnetid or "").strip()
    normalized_battletag = normalize_battletag(battletag)
    normalized_battlename = str(battlename or "").strip()
    normalized_battlenum = str(battlenum or "").strip()

    if not normalized_battletag and normalized_battlename:
        normalized_battletag = (
            normalized_battlename
            if not normalized_battlenum
            else f"{normalized_battlename}#{normalized_battlenum}"
        )

    if normalized_battletag:
        split_name, split_num = split_battletag(normalized_battletag)
        if not normalized_battlename:
            normalized_battlename = split_name
        if not normalized_battlenum:
            normalized_battlenum = split_num

    if not normalized_battletag and normalized_battlename:
        normalized_battletag = (
            normalized_battlename
            if not normalized_battlenum
            else f"{normalized_battlename}#{normalized_battlenum}"
        )

    if not normalized_bnetid or not normalized_battletag or not normalized_battlename:
        return None

    try:
        normalized_update_time = int(update_time if update_time is not None else time.time())
    except (TypeError, ValueError):
        normalized_update_time = int(time.time())

    return {
        "bnetid": normalized_bnetid,
        "battletag": normalized_battletag,
        "battlename": normalized_battlename,
        "battlenum": normalized_battlenum,
        "update_time": normalized_update_time,
    }


def _extract_from_mapping(mapping: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return normalize_identity_record(
        bnetid=_first_non_empty(mapping, _BNET_ID_KEYS),
        battletag=_first_non_empty(mapping, _BATTLETAG_KEYS),
        battlename=_first_non_empty(mapping, _BATTLENAME_KEYS),
        battlenum=_first_non_empty(mapping, _BATTLENUM_KEYS),
    )


def extract_identity_records(payload: Any) -> List[Dict[str, Any]]:
    if payload is None:
        return []

    pending: List[Any] = [payload]
    seen_nodes: set[int] = set()
    rows_by_bnetid: Dict[str, Dict[str, Any]] = {}

    while pending:
        current = pending.pop()
        node_id = id(current)
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)

        if isinstance(current, dict):
            record = _extract_from_mapping(current)
            if record is not None:
                rows_by_bnetid[record["bnetid"]] = record
            pending.extend(current.values())
            continue

        if isinstance(current, (list, tuple, set)):
            pending.extend(current)

    return list(rows_by_bnetid.values())


async def record_identity_records(records: List[Dict[str, Any]], *, db: Optional[IDPoolDB] = None) -> int:
    if not records:
        return 0
    identity_db = db or IDPoolDB()
    return await asyncio.to_thread(identity_db.upsert_player_identity_records, records)


async def record_identity_payload(payload: Any, *, db: Optional[IDPoolDB] = None) -> int:
    records = extract_identity_records(payload)
    if not records:
        return 0
    return await record_identity_records(records, db=db)


async def search_identity_by_bnet_id(
    bnet_id: Any,
    *,
    db: Optional[IDPoolDB] = None,
    limit: int = 10,
    exact_only: bool = False,
) -> List[Dict[str, Any]]:
    normalized_bnet_id = str(bnet_id or "").strip()
    if not normalized_bnet_id:
        return []
    identity_db = db or IDPoolDB()
    return await asyncio.to_thread(
        identity_db.search_player_identity_by_bnet_id,
        normalized_bnet_id,
        limit=limit,
        exact_only=exact_only,
    )


__all__ = [
    "PLAYER_IDENTITY_TABLE",
    "extract_identity_records",
    "normalize_battletag",
    "normalize_identity_record",
    "record_identity_payload",
    "record_identity_records",
    "search_identity_by_bnet_id",
    "split_battletag",
]
