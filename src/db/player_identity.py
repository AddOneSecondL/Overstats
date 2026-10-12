from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.config import is_database_write_enabled
    from overstats.src.db.match_stats import IDPoolDB, PLAYER_IDENTITY_TABLE
except ModuleNotFoundError:
    from config import is_database_write_enabled
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


@dataclass(frozen=True)
class _IdentityEvent:
    payload: Any


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
    return []


async def record_identity_records(records: List[Dict[str, Any]], *, db: Optional[IDPoolDB] = None) -> int:
    return 0


async def record_identity_payload(payload: Any, *, db: Optional[IDPoolDB] = None) -> int:
    return 0


class PlayerIdentityRecorder:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db = IDPoolDB(db_path)
        self._queue: asyncio.Queue[Optional[_IdentityEvent]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        return

    async def enqueue(self, payload: Any) -> None:
        return

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

    def _write_batch(self, batch: Sequence[_IdentityEvent]) -> int:
        return 0


async def search_identity_by_bnet_id(
    bnet_id: Any,
    *,
    db: Optional[IDPoolDB] = None,
    limit: int = 10,
    exact_only: bool = False,
) -> List[Dict[str, Any]]:
    return []


__all__ = [
    "PLAYER_IDENTITY_TABLE",
    "PlayerIdentityRecorder",
    "extract_identity_records",
    "normalize_battletag",
    "normalize_identity_record",
    "record_identity_payload",
    "record_identity_records",
    "search_identity_by_bnet_id",
    "split_battletag",
]
