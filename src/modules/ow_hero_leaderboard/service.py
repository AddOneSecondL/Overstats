from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
import datetime as dt
from typing import Callable, Dict, Optional

try:
    from overstats.config import is_database_write_enabled
    from overstats.src.db import (
        HERO_LEADERBOARD_CN_TABLE,
        HERO_LEADERBOARD_GLOBAL_TABLE,
        OWHeroLeaderboardDB,
    )
except ModuleNotFoundError:
    from config import is_database_write_enabled
    from src.db import (
        HERO_LEADERBOARD_CN_TABLE,
        HERO_LEADERBOARD_GLOBAL_TABLE,
        OWHeroLeaderboardDB,
    )

from .requests import OWHeroLeaderboardRequests


def _load_beijing_timezone() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")
    except (ImportError, KeyError):
        # Current leaderboard schedules use UTC+8, even without zoneinfo or tzdata.
        return dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


BEIJING_TIMEZONE = _load_beijing_timezone()


@dataclass(frozen=True)
class OWHeroLeaderboardSyncResult:
    region: str
    status: str
    attempted_targets: int
    successful_targets: int
    failed_targets: int
    rows_written: int
    failures: tuple[str, ...] = field(default_factory=tuple)


class OWHeroLeaderboardSyncService:
    def __init__(
        self,
        requests: Optional[OWHeroLeaderboardRequests] = None,
        db: Optional[OWHeroLeaderboardDB] = None,
        *,
        now_provider: Optional[Callable[[], dt.datetime]] = None,
        sleep_func: Optional[Callable[[float], Awaitable[object]]] = None,
    ) -> None:
        self.requests = requests or OWHeroLeaderboardRequests()
        self.db = db or OWHeroLeaderboardDB()
        self.now_provider = now_provider or (lambda: dt.datetime.now(BEIJING_TIMEZONE))
        self.sleep_func = sleep_func or asyncio.sleep
        self._task: Optional[asyncio.Task[None]] = None
        self.last_results: Dict[str, OWHeroLeaderboardSyncResult] = {}

    async def start(self) -> None:
        if not is_database_write_enabled():
            return
        if self._task is not None and not self._task.done():
            return
        await asyncio.to_thread(self.db.initialize_database)
        self._task = asyncio.create_task(self._run_forever(), name="ow-hero-leaderboard-sync")

    async def close(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def sync_once(self) -> Dict[str, OWHeroLeaderboardSyncResult]:
        results = {
            "cn": await self.sync_cn_once(),
            "global": await self.sync_global_once(),
        }
        self.last_results = results
        return results

    async def sync_cn_once(self) -> OWHeroLeaderboardSyncResult:
        if not is_database_write_enabled():
            return OWHeroLeaderboardSyncResult(
                region="cn",
                status="skipped_db_write_disabled",
                attempted_targets=0,
                successful_targets=0,
                failed_targets=0,
                rows_written=0,
                failures=(),
            )
        targets = self.requests.build_cn_targets()
        rows = []
        failures = []
        successful_targets = 0

        for target in targets:
            try:
                target_rows = await self.requests.fetch_cn_target(target)
            except Exception as exc:
                failures.append(
                    f"{target.game_mode}:{target.mmr}:{type(exc).__name__}: {exc}"
                )
                continue

            successful_targets += 1
            rows.extend(target_rows)

        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        rows_written = await asyncio.to_thread(
            self.db.upsert_rows,
            HERO_LEADERBOARD_CN_TABLE,
            rows,
            updated_at=timestamp,
        )

        status = "ok"
        if failures and successful_targets > 0:
            status = "partial_failure"
        elif failures and successful_targets == 0:
            status = "failed"

        return OWHeroLeaderboardSyncResult(
            region="cn",
            status=status,
            attempted_targets=len(targets),
            successful_targets=successful_targets,
            failed_targets=len(failures),
            rows_written=rows_written,
            failures=tuple(failures),
        )

    async def sync_global_once(self) -> OWHeroLeaderboardSyncResult:
        return OWHeroLeaderboardSyncResult(
            region="global",
            status="skipped_not_implemented",
            attempted_targets=0,
            successful_targets=0,
            failed_targets=0,
            rows_written=0,
            failures=(),
        )

    @classmethod
    def next_scheduled_run_at(cls, now: Optional[dt.datetime] = None) -> dt.datetime:
        current = cls._normalize_now(now or dt.datetime.now(BEIJING_TIMEZONE))
        candidate = current.replace(hour=12, minute=0, second=0, microsecond=0)
        if current >= candidate:
            candidate += dt.timedelta(days=1)
        return candidate

    @classmethod
    def seconds_until_next_run(cls, now: Optional[dt.datetime] = None) -> float:
        current = cls._normalize_now(now or dt.datetime.now(BEIJING_TIMEZONE))
        next_run = cls.next_scheduled_run_at(current)
        return max(0.0, float((next_run - current).total_seconds()))

    async def _run_forever(self) -> None:
        while True:
            try:
                results = await self.sync_once()
                print(
                    "[overstats] ow hero leaderboard sync "
                    f"cn_status={results['cn'].status} "
                    f"cn_rows={results['cn'].rows_written} "
                    f"global_status={results['global'].status}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[overstats] ow hero leaderboard sync failed: {type(exc).__name__}: {exc}")

            delay_seconds = self.seconds_until_next_run(self.now_provider())
            await self.sleep_func(delay_seconds)

    @staticmethod
    def _normalize_now(now: dt.datetime) -> dt.datetime:
        if now.tzinfo is None:
            return now.replace(tzinfo=BEIJING_TIMEZONE)
        return now.astimezone(BEIJING_TIMEZONE)
