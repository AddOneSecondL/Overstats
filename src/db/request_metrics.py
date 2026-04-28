from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


REQUEST_METRICS_DB_PATH = Path(__file__).resolve().parent / "request_metrics.sqlite3"
REQUEST_METRICS_TABLE = "request_url_stats"
REQUEST_SOURCE_MODULE = "module"
REQUEST_SOURCE_UPSTREAM = "upstream"


@dataclass(frozen=True)
class _MetricEvent:
    url: str
    source_type: str
    success: bool


def normalize_request_metric_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urlsplit(normalized)
    except Exception:
        return normalized.split("?", 1)[0].strip()
    if not parsed.scheme and not parsed.netloc:
        path = parsed.path or normalized
        return path.split("?", 1)[0].strip()
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")).strip()


def _normalize_metric_row(
    url: str,
    source_type: str,
    total_requests: object,
    successful_requests: object,
    failed_requests: object,
    updated_at: str,
) -> Optional[tuple[str, str, int, int, int, float, str]]:
    normalized_url = normalize_request_metric_url(url)
    normalized_source = str(source_type or "").strip().lower()
    if not normalized_url or normalized_source not in {REQUEST_SOURCE_MODULE, REQUEST_SOURCE_UPSTREAM}:
        return None

    total = max(int(total_requests or 0), 0)
    successful = max(int(successful_requests or 0), 0)
    failed = max(int(failed_requests or 0), 0)
    computed_total = successful + failed
    if total < computed_total:
        total = computed_total
    if total <= 0:
        return None
    success_rate = float(successful) / float(total)
    return (
        normalized_url,
        normalized_source,
        total,
        successful,
        failed,
        success_rate,
        str(updated_at or "").strip() or datetime.now(timezone.utc).isoformat(),
    )


class RequestMetricsRecorder:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or REQUEST_METRICS_DB_PATH)
        self._queue: asyncio.Queue[Optional[_MetricEvent]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_database)
        self._worker_task = asyncio.create_task(self._worker(), name="request-metrics-worker")
        self._started = True

    async def enqueue(self, url: str, source_type: str, success: bool) -> None:
        normalized_url = normalize_request_metric_url(url)
        normalized_source = str(source_type or "").strip().lower()
        if not normalized_url or normalized_source not in {REQUEST_SOURCE_MODULE, REQUEST_SOURCE_UPSTREAM}:
            return
        if self._closed:
            return
        if not self._started:
            await self.start()
        await self._queue.put(_MetricEvent(normalized_url, normalized_source, bool(success)))

    async def close(self) -> None:
        if not self._started or self._closed:
            return
        self._closed = True
        await self._queue.join()
        await self._queue.put(None)
        if self._worker_task is not None:
            await self._worker_task
        self._worker_task = None

    def _initialize_database(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {REQUEST_METRICS_TABLE} (
                    url TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    successful_requests INTEGER NOT NULL DEFAULT 0,
                    failed_requests INTEGER NOT NULL DEFAULT 0,
                    success_rate REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._normalize_existing_rows(connection)
            connection.commit()
        finally:
            connection.close()

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:
                self._queue.task_done()
                return
            try:
                await asyncio.to_thread(self._write_event, event)
            finally:
                self._queue.task_done()

    def _write_event(self, event: _MetricEvent) -> None:
        normalized_row = _normalize_metric_row(
            event.url,
            event.source_type,
            1,
            1 if event.success else 0,
            0 if event.success else 1,
            datetime.now(timezone.utc).isoformat(),
        )
        if normalized_row is None:
            return
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"""
                INSERT INTO {REQUEST_METRICS_TABLE} (
                    url,
                    source_type,
                    total_requests,
                    successful_requests,
                    failed_requests,
                    success_rate,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source_type = excluded.source_type,
                    total_requests = {REQUEST_METRICS_TABLE}.total_requests + excluded.total_requests,
                    successful_requests = {REQUEST_METRICS_TABLE}.successful_requests + excluded.successful_requests,
                    failed_requests = {REQUEST_METRICS_TABLE}.failed_requests + excluded.failed_requests,
                    success_rate = CAST(
                        {REQUEST_METRICS_TABLE}.successful_requests + excluded.successful_requests AS REAL
                    ) / CAST({REQUEST_METRICS_TABLE}.total_requests + excluded.total_requests AS REAL),
                    updated_at = excluded.updated_at
                """,
                normalized_row,
            )
            connection.commit()
        finally:
            connection.close()

    def _normalize_existing_rows(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            f"""
            SELECT
                url,
                source_type,
                total_requests,
                successful_requests,
                failed_requests,
                updated_at
            FROM {REQUEST_METRICS_TABLE}
            """
        ).fetchall()
        if not rows:
            return

        merged_rows: dict[str, list[object]] = {}
        for row in rows:
            normalized_row = _normalize_metric_row(*row)
            if normalized_row is None:
                continue
            url, source_type, total, successful, failed, _success_rate, updated_at = normalized_row
            bucket = merged_rows.get(url)
            if bucket is None:
                merged_rows[url] = [source_type, total, successful, failed, updated_at]
                continue
            bucket[1] = int(bucket[1]) + total
            bucket[2] = int(bucket[2]) + successful
            bucket[3] = int(bucket[3]) + failed
            if str(updated_at) >= str(bucket[4]):
                bucket[0] = source_type
                bucket[4] = updated_at

        normalized_rows = []
        for url, (source_type, total, successful, failed, updated_at) in merged_rows.items():
            total_int = int(total)
            success_int = int(successful)
            normalized_rows.append(
                (
                    url,
                    str(source_type),
                    total_int,
                    success_int,
                    int(failed),
                    float(success_int) / float(total_int),
                    str(updated_at),
                )
            )

        if len(normalized_rows) == len(rows):
            unchanged = True
            original_rows = {
                (
                    str(url),
                    str(source_type),
                    int(total_requests or 0),
                    int(successful_requests or 0),
                    int(failed_requests or 0),
                    str(updated_at or "").strip(),
                )
                for url, source_type, total_requests, successful_requests, failed_requests, updated_at in rows
            }
            normalized_snapshot = {
                (
                    str(url),
                    str(source_type),
                    int(total_requests),
                    int(successful_requests),
                    int(failed_requests),
                    str(updated_at).strip(),
                )
                for url, source_type, total_requests, successful_requests, failed_requests, _success_rate, updated_at in normalized_rows
            }
            unchanged = original_rows == normalized_snapshot
            if unchanged:
                return

        connection.execute(f"DELETE FROM {REQUEST_METRICS_TABLE}")
        connection.executemany(
            f"""
            INSERT INTO {REQUEST_METRICS_TABLE} (
                url,
                source_type,
                total_requests,
                successful_requests,
                failed_requests,
                success_rate,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            normalized_rows,
        )
