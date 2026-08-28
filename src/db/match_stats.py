from __future__ import annotations

from collections import Counter
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MATCH_STATS_DB_PATH = Path(__file__).resolve().parent / "match_stats.sqlite3"
PLAYER_IDENTITY_TABLE = "player_identity_map"
HERO_MATCH_DETAIL_TABLE = "hero_match_detail"
COMP_DATA_TABLE = "comp_data"
COMP_DATA_SUMMARY_TABLE = "comp_data_summary"
HERO_PERK_PICK_TABLE = "hero_perk_pick"
HERO_PERK_SUMMARY_TABLE = "hero_perk_summary"
OVERALL_RANK_BUCKET_KEY = -1
SQLITE_BUSY_TIMEOUT_MS = 15_000


class IDPoolDB:
    """Small SQLite adapter used by summary rendering and dashen match highlights.

    The adapter is intentionally lazy and permissive:
    - if the sqlite database file is absent, every query degrades to an empty result
    - if the database schema is missing required tables, callers still get empty results
    """

    _warn_lock = threading.Lock()
    _write_lock = threading.Lock()
    _warned_messages: set[str] = set()

    def __init__(self, db_path: Optional[Path] = None, *args: Any, **kwargs: Any) -> None:
        self.db_path = Path(db_path or MATCH_STATS_DB_PATH)

    @classmethod
    def _warn_once(cls, message: str) -> None:
        with cls._warn_lock:
            if message in cls._warned_messages:
                return
            cls._warned_messages.add(message)
        print(f"[overstats] {message}")

    def _get_connection(self) -> Optional[sqlite3.Connection]:
        if not self.db_path.exists():
            self._warn_once(f"match stats sqlite db not found: {self.db_path}")
            return None
        try:
            connection = sqlite3.connect(
                str(self.db_path),
                timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            )
            connection.row_factory = None
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            return connection
        except Exception as exc:
            self._warn_once(f"match stats sqlite connection failed: {type(exc).__name__}: {exc}")
            return None

    def _get_write_connection(self) -> Optional[sqlite3.Connection]:
        connection: Optional[sqlite3.Connection] = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(self.db_path),
                timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            )
            connection.row_factory = None
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            # WAL keeps readers on a stable snapshot while the recorder appends a
            # batch, avoiding the read/write lock collision in strength renders.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA wal_autocheckpoint=1000")
            return connection
        except Exception as exc:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            self._warn_once(f"match stats sqlite write connection failed: {type(exc).__name__}: {exc}")
            return None

    def _initialize_player_identity_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PLAYER_IDENTITY_TABLE} (
                bnetid TEXT PRIMARY KEY,
                battletag TEXT NOT NULL,
                battlename TEXT NOT NULL,
                battlenum TEXT NOT NULL DEFAULT '',
                update_time INTEGER NOT NULL
            )
            """
        )

    def _table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        try:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (str(table_name or "").strip(),),
            ).fetchone()
        except Exception:
            return False
        return bool(row)

    def _get_existing_columns(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        try:
            rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall() or []
        except Exception:
            return set()
        return {str(row[1]) for row in rows if len(row) > 1 and str(row[1])}

    def _ensure_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_definitions: Sequence[tuple[str, str]],
    ) -> None:
        if not self._table_exists(connection, table_name):
            return
        existing = self._get_existing_columns(connection, table_name)
        for column_name, column_sql in column_definitions:
            if column_name in existing:
                continue
            try:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
            except Exception as exc:
                self._warn_once(
                    f"match stats sqlite add column failed table={table_name} column={column_name}: "
                    f"{type(exc).__name__}: {exc}"
                )

    def _initialize_match_detail_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERO_MATCH_DETAIL_TABLE} (
                match_id TEXT NOT NULL,
                player_bnet_id TEXT NOT NULL,
                player_name TEXT NOT NULL DEFAULT '',
                hero_guid TEXT NOT NULL,
                rank_score INTEGER,
                rank_bucket INTEGER,
                use_time_sec REAL NOT NULL DEFAULT 0,
                use_time_rate REAL NOT NULL DEFAULT 0,
                map_guid TEXT NOT NULL DEFAULT '',
                start_time INTEGER NOT NULL DEFAULT 0,
                game_time_sec INTEGER NOT NULL DEFAULT 0,
                stat_map_json TEXT NOT NULL DEFAULT '{{}}',
                last_update INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (match_id, player_bnet_id, hero_guid)
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {COMP_DATA_TABLE} (
                match_id TEXT NOT NULL DEFAULT '',
                player_bnet_id TEXT NOT NULL DEFAULT '',
                hero_guid TEXT NOT NULL,
                statmap_name TEXT NOT NULL,
                statmap_value REAL NOT NULL,
                statmap_raw_value REAL,
                rank_score INTEGER,
                rank_bucket INTEGER,
                use_time_sec REAL NOT NULL DEFAULT 0,
                use_time_rate REAL NOT NULL DEFAULT 0,
                last_update INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_columns(
            connection,
            COMP_DATA_TABLE,
            (
                ("match_id", "match_id TEXT NOT NULL DEFAULT ''"),
                ("player_bnet_id", "player_bnet_id TEXT NOT NULL DEFAULT ''"),
                ("statmap_raw_value", "statmap_raw_value REAL"),
                ("rank_bucket", "rank_bucket INTEGER"),
                ("use_time_sec", "use_time_sec REAL NOT NULL DEFAULT 0"),
                ("use_time_rate", "use_time_rate REAL NOT NULL DEFAULT 0"),
            ),
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERO_PERK_PICK_TABLE} (
                match_id TEXT NOT NULL,
                player_bnet_id TEXT NOT NULL,
                player_name TEXT NOT NULL DEFAULT '',
                hero_guid TEXT NOT NULL,
                perk_guid TEXT NOT NULL,
                perk_level INTEGER NOT NULL DEFAULT 0,
                slot_index INTEGER NOT NULL DEFAULT 0,
                rank_score INTEGER,
                rank_bucket INTEGER,
                start_time INTEGER NOT NULL DEFAULT 0,
                last_update INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (match_id, player_bnet_id, hero_guid, perk_level, slot_index, perk_guid)
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {COMP_DATA_SUMMARY_TABLE} (
                hero_guid TEXT NOT NULL,
                statmap_name TEXT NOT NULL,
                rank_bucket_key INTEGER NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                avg_value REAL,
                median_value REAL,
                top20_value REAL,
                top10_value REAL,
                top5_value REAL,
                top2_value REAL,
                bottom20_value REAL,
                bottom10_value REAL,
                bottom5_value REAL,
                bottom2_value REAL,
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (hero_guid, statmap_name, rank_bucket_key)
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERO_PERK_SUMMARY_TABLE} (
                hero_guid TEXT NOT NULL,
                perk_level INTEGER NOT NULL,
                perk_guid TEXT NOT NULL,
                rank_bucket_key INTEGER NOT NULL,
                pick_count INTEGER NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                pick_rate REAL NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (hero_guid, perk_level, perk_guid, rank_bucket_key)
            )
            """
        )
        index_statements = (
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{COMP_DATA_TABLE}_uniq "
            f"ON {COMP_DATA_TABLE} (match_id, player_bnet_id, hero_guid, statmap_name)",
            f"CREATE INDEX IF NOT EXISTS idx_{COMP_DATA_TABLE}_hero_stat_rank_value "
            f"ON {COMP_DATA_TABLE} (hero_guid, statmap_name, rank_bucket, statmap_value)",
            f"CREATE INDEX IF NOT EXISTS idx_{COMP_DATA_TABLE}_match_player "
            f"ON {COMP_DATA_TABLE} (match_id, player_bnet_id)",
            f"CREATE INDEX IF NOT EXISTS idx_{HERO_MATCH_DETAIL_TABLE}_hero_rank_start "
            f"ON {HERO_MATCH_DETAIL_TABLE} (hero_guid, rank_bucket, start_time)",
            f"CREATE INDEX IF NOT EXISTS idx_{HERO_PERK_PICK_TABLE}_hero_level_rank_perk "
            f"ON {HERO_PERK_PICK_TABLE} (hero_guid, perk_level, rank_bucket, perk_guid)",
            f"CREATE INDEX IF NOT EXISTS idx_{HERO_PERK_PICK_TABLE}_match_player "
            f"ON {HERO_PERK_PICK_TABLE} (match_id, player_bnet_id)",
            f"CREATE INDEX IF NOT EXISTS idx_{COMP_DATA_SUMMARY_TABLE}_hero_rank "
            f"ON {COMP_DATA_SUMMARY_TABLE} (hero_guid, rank_bucket_key, statmap_name)",
            f"CREATE INDEX IF NOT EXISTS idx_{HERO_PERK_SUMMARY_TABLE}_hero_level_rank "
            f"ON {HERO_PERK_SUMMARY_TABLE} (hero_guid, perk_level, rank_bucket_key, perk_guid)",
        )
        for statement in index_statements:
            try:
                connection.execute(statement)
            except Exception as exc:
                self._warn_once(f"match stats sqlite create index failed: {type(exc).__name__}: {exc}")

    def initialize_match_detail_schema(self) -> bool:
        with self._write_lock:
            conn = self._get_write_connection()
            if conn is None:
                return False
            try:
                self._initialize_player_identity_table(conn)
                self._initialize_match_detail_tables(conn)
                conn.commit()
                return True
            except Exception as exc:
                self._warn_once(f"match stats sqlite initialize schema failed: {type(exc).__name__}: {exc}")
                return False
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def initialize_player_identity_schema(self) -> bool:
        with self._write_lock:
            conn = self._get_write_connection()
            if conn is None:
                return False
            try:
                self._initialize_player_identity_table(conn)
                conn.commit()
                return True
            except Exception as exc:
                self._warn_once(f"match stats sqlite initialize player identity schema failed: {type(exc).__name__}: {exc}")
                return False
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _escape_like_pattern(text: str) -> str:
        return str(text or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")

    @staticmethod
    def _summary_rows_to_dict(rows: List[Any]) -> Dict[Any, Dict[str, Any]]:
        result: Dict[Any, Dict[str, Any]] = {}
        for row in rows or []:
            (
                statmap_name,
                rank_score,
                sample_count,
                avg_value,
                median_value,
                top20_value,
                top10_value,
                top5_value,
                top2_value,
                bottom20_value,
                bottom10_value,
                bottom5_value,
                bottom2_value,
            ) = row
            rank_key = int(rank_score) if rank_score is not None else None
            result[(str(statmap_name), rank_key)] = {
                "count": int(sample_count or 0),
                "avg": float(avg_value) if avg_value is not None else None,
                "median": float(median_value) if median_value is not None else None,
                "top20": float(top20_value) if top20_value is not None else None,
                "top10": float(top10_value) if top10_value is not None else None,
                "top5": float(top5_value) if top5_value is not None else None,
                "top2": float(top2_value) if top2_value is not None else None,
                "bottom20": float(bottom20_value) if bottom20_value is not None else None,
                "bottom10": float(bottom10_value) if bottom10_value is not None else None,
                "bottom5": float(bottom5_value) if bottom5_value is not None else None,
                "bottom2": float(bottom2_value) if bottom2_value is not None else None,
            }
        return result

    @staticmethod
    def _perk_summary_rows_to_dict(rows: List[Any]) -> Dict[Any, Dict[str, Any]]:
        grouped: Dict[Any, Dict[str, Any]] = {}
        for row in rows or []:
            hero_guid, perk_level, perk_guid, rank_bucket_key, pick_count, sample_count, pick_rate = row
            result_key = None if int(rank_bucket_key) == OVERALL_RANK_BUCKET_KEY else int(rank_bucket_key)
            bucket = grouped.setdefault(
                result_key,
                {"hero_guid": str(hero_guid), "perk_level": int(perk_level or 0), "sample_count": 0, "perks": {}},
            )
            bucket["sample_count"] = max(int(sample_count or 0), int(bucket.get("sample_count") or 0))
            bucket["perks"][str(perk_guid)] = {
                "pick_count": int(pick_count or 0),
                "sample_count": int(sample_count or 0),
                "pick_rate": float(pick_rate or 0.0),
            }
        return grouped

    def get_all_rank(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        if conn is None:
            return []
        try:
            cutoff = int(time.time()) - 15 * 24 * 3600
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT bnet_id, tank, dps, healer, "open", level, playtime, last_update
                    FROM "rank"
                    WHERE last_update > ?
                    """,
                    (cutoff,),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
            return [
                {
                    "bnet_id": row[0],
                    "tank": row[1],
                    "dps": row[2],
                    "healer": row[3],
                    "open": row[4],
                    "level": row[5],
                    "playtime": row[6],
                    "last_update": row[7],
                }
                for row in rows
            ]
        except Exception as exc:
            self._warn_once(f"match stats sqlite get_all_rank failed: {type(exc).__name__}: {exc}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_group_titles(self, bnet_id: str) -> List[Dict[str, Any]]:
        bnet_id = str(bnet_id or "").strip()
        if not bnet_id:
            return []
        conn = self._get_connection()
        if conn is None:
            return []
        created_at_sql = """
            CASE
                WHEN created_at IS NULL THEN 0
                WHEN typeof(created_at) IN ('integer', 'real') THEN CAST(created_at AS INTEGER)
                ELSE COALESCE(CAST(strftime('%s', created_at) AS INTEGER), 0)
            END
        """
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT bnet_id, battletag, battlenum, title, color, {created_at_sql} AS created_at_ts
                    FROM group_title
                    WHERE bnet_id = ?
                    ORDER BY created_at_ts ASC, title ASC
                    """,
                    (bnet_id,),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
            return [
                {
                    "bnet_id": row[0],
                    "battletag": row[1],
                    "battlenum": row[2],
                    "title": row[3],
                    "color": row[4],
                    "create_at": int(row[5] or 0),
                }
                for row in rows
            ]
        except Exception as exc:
            self._warn_once(f"match stats sqlite get_group_titles failed: {type(exc).__name__}: {exc}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_statmap_summary(
        self,
        hero_guid: str,
        statmap_names: Optional[List[str]] = None,
        rank_scores: Optional[List[int]] = None,
        ratio_statmap_names: Optional[List[str]] = None,
        group_by_rank: bool = True,
    ) -> Dict[str, Any]:
        hero_guid = str(hero_guid or "").strip()
        if not hero_guid:
            return {}

        statmap_names = [str(item) for item in (statmap_names or []) if str(item)]
        rank_scores = [int(item) for item in (rank_scores or [])]
        ratio_statmap_names = [str(item) for item in (ratio_statmap_names or []) if str(item)]

        conn = self._get_connection()
        if conn is None:
            return {}

        summary_rows = self._get_statmap_summary_preaggregated(
            conn,
            hero_guid=hero_guid,
            statmap_names=statmap_names,
            rank_scores=rank_scores,
            group_by_rank=group_by_rank,
        )
        if summary_rows:
            try:
                conn.close()
            except Exception:
                pass
            return summary_rows

        where_parts = ["hero_guid = ?"]
        params: List[Any] = [hero_guid]
        if statmap_names:
            placeholders = ",".join(["?"] * len(statmap_names))
            where_parts.append(f"statmap_name IN ({placeholders})")
            params.extend(statmap_names)
        if rank_scores:
            placeholders = ",".join(["?"] * len(rank_scores))
            where_parts.append(f"rank_score IN ({placeholders})")
            params.extend(rank_scores)

        where_sql = " AND ".join(where_parts)
        value_expr = "statmap_value"
        query_params = list(params)
        if ratio_statmap_names:
            ratio_placeholders = ",".join(["?"] * len(ratio_statmap_names))
            value_expr = (
                "CASE WHEN statmap_name IN "
                f"({ratio_placeholders}) "
                "THEN MIN(1.0, MAX(0.0, statmap_value)) "
                "ELSE statmap_value END"
            )
            query_params = list(ratio_statmap_names) + query_params

        rank_select = "rank_score" if group_by_rank else "NULL AS rank_score"
        partition_by = "statmap_name, rank_score" if group_by_rank else "statmap_name"

        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    WITH filtered AS (
                        SELECT statmap_name, {rank_select}, {value_expr} AS statmap_value
                        FROM comp_data
                        WHERE {where_sql}
                    ),
                    ranked AS (
                        SELECT
                            statmap_name,
                            rank_score,
                            statmap_value,
                            ROW_NUMBER() OVER (
                                PARTITION BY {partition_by}
                                ORDER BY statmap_value
                            ) AS rn,
                            COUNT(*) OVER (
                                PARTITION BY {partition_by}
                            ) AS cnt
                        FROM filtered
                    )
                    SELECT
                        statmap_name,
                        rank_score,
                        MAX(cnt) AS sample_count,
                        AVG(statmap_value) AS avg_value,
                        AVG(
                            CASE
                                WHEN rn IN (
                                    CAST((cnt + 1) / 2 AS INTEGER),
                                    CAST((cnt + 2) / 2 AS INTEGER)
                                )
                                THEN statmap_value
                            END
                        ) AS median_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 80) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top20_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 90) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top10_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 95) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top5_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 98) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top2_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 20) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom20_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 10) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom10_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 5) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom5_value,
                        MIN(CASE WHEN rn >= CAST(((cnt * 2) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom2_value
                    FROM ranked
                    GROUP BY statmap_name, rank_score
                    """,
                    tuple(query_params),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
            return self._summary_rows_to_dict(list(rows))
        except Exception as exc:
            self._warn_once(f"match stats sqlite get_statmap_summary window query failed: {type(exc).__name__}: {exc}")
            return self._get_statmap_summary_python(
                conn,
                where_sql=where_sql,
                params=params,
                ratio_statmap_names=set(ratio_statmap_names),
                group_by_rank=group_by_rank,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_personal_stat_percentiles(
        self,
        feature_values: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Compare personal hero-stat averages with per-player database averages.

        Each database player contributes exactly one value to a feature, regardless
        of how many matching records that player has. ``exceeded_percent`` counts
        lower player averages for normal metrics and higher averages for metrics
        marked with ``reverse`` (currently deaths).
        """
        normalized_features: List[tuple[str, str, float, int]] = []
        seen_keys: set[tuple[str, str]] = set()
        for item in feature_values or []:
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("hero_guid") or "").strip()
            statmap_name = str(item.get("statmap_name") or "").strip()
            if not hero_guid or not statmap_name:
                continue
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            reverse = 1 if bool(item.get("reverse")) else 0
            key = (hero_guid, statmap_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            normalized_features.append((hero_guid, statmap_name, value, reverse))

        if not normalized_features:
            return []

        conn = self._get_connection()
        if conn is None:
            return []

        results: List[Dict[str, Any]] = []
        try:
            cursor = conn.cursor()
            try:
                target_rows_sql = ",".join(["(?, ?, ?, ?)"] * len(normalized_features))
                params = tuple(value for feature in normalized_features for value in feature)
                cursor.execute(
                    f"""
                    WITH targets(hero_guid, statmap_name, target_value, reverse) AS (
                        VALUES {target_rows_sql}
                    ),
                    player_values AS (
                        SELECT
                            targets.hero_guid,
                            targets.statmap_name,
                            targets.target_value,
                            targets.reverse,
                            comp.player_bnet_id,
                            AVG(comp.statmap_value) AS player_value
                        FROM targets
                        JOIN {COMP_DATA_TABLE} AS comp
                            ON comp.hero_guid = targets.hero_guid
                            AND comp.statmap_name = targets.statmap_name
                        WHERE comp.player_bnet_id != ''
                        GROUP BY
                            targets.hero_guid,
                            targets.statmap_name,
                            targets.target_value,
                            targets.reverse,
                            comp.player_bnet_id
                    )
                    SELECT
                        hero_guid,
                        statmap_name,
                        target_value,
                        reverse,
                        COUNT(*) AS player_count,
                        COALESCE(
                            SUM(
                                CASE
                                    WHEN reverse = 1 AND player_value > target_value THEN 1
                                    WHEN reverse = 0 AND player_value < target_value THEN 1
                                    ELSE 0
                                END
                            ),
                            0
                        ) AS exceeded_count
                    FROM player_values
                    GROUP BY hero_guid, statmap_name, target_value, reverse
                    """,
                    params,
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
            by_key = {
                (hero_guid, statmap_name): index
                for index, (hero_guid, statmap_name, _, _) in enumerate(normalized_features)
            }
            for hero_guid, statmap_name, value, reverse, player_count, exceeded_count in rows:
                player_count = int(player_count or 0)
                exceeded_count = int(exceeded_count or 0)
                if player_count <= 0:
                    continue
                results.append(
                    {
                        "hero_guid": str(hero_guid),
                        "statmap_name": str(statmap_name),
                        "value": float(value),
                        "reverse": bool(reverse),
                        "player_count": player_count,
                        "exceeded_count": exceeded_count,
                        "exceeded_percent": exceeded_count * 100.0 / player_count,
                    }
                )
            results.sort(key=lambda item: by_key[(item["hero_guid"], item["statmap_name"])])
            return results
        except Exception as exc:
            self._warn_once(
                "match stats sqlite get_personal_stat_percentiles failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_personal_kda_percentiles(
        self,
        feature_values: Sequence[Dict[str, Any]],
        *,
        kill_guid: str = "603482350067646495",
        assist_guid: str = "603482350067648392",
        death_guid: str = "603482350067646506",
    ) -> List[Dict[str, Any]]:
        """Compare derived KDA values after aggregating each database player."""
        normalized_features: List[tuple[str, float]] = []
        seen_heroes: set[str] = set()
        for item in feature_values or []:
            if not isinstance(item, dict):
                continue
            hero_guid = str(item.get("hero_guid") or "").strip()
            if not hero_guid or hero_guid in seen_heroes:
                continue
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            seen_heroes.add(hero_guid)
            normalized_features.append((hero_guid, value))

        if not normalized_features:
            return []

        conn = self._get_connection()
        if conn is None:
            return []

        try:
            cursor = conn.cursor()
            try:
                target_rows_sql = ",".join(["(?, ?)"] * len(normalized_features))
                target_params = tuple(value for feature in normalized_features for value in feature)
                cursor.execute(
                    f"""
                    WITH targets(hero_guid, target_value) AS (
                        VALUES {target_rows_sql}
                    ),
                    stat_averages AS (
                        SELECT
                            targets.hero_guid,
                            targets.target_value,
                            comp.player_bnet_id,
                            comp.statmap_name,
                            AVG(comp.statmap_value) AS stat_value
                        FROM targets
                        JOIN {COMP_DATA_TABLE} AS comp
                            ON comp.hero_guid = targets.hero_guid
                            AND comp.statmap_name IN (?, ?, ?)
                        WHERE comp.player_bnet_id != ''
                        GROUP BY
                            targets.hero_guid,
                            targets.target_value,
                            comp.player_bnet_id,
                            comp.statmap_name
                    ),
                    player_components AS (
                        SELECT
                            hero_guid,
                            target_value,
                            player_bnet_id,
                            MAX(CASE WHEN statmap_name = ? THEN stat_value END) AS kills,
                            COALESCE(
                                MAX(CASE WHEN statmap_name = ? THEN stat_value END),
                                0.0
                            ) AS assists,
                            MAX(CASE WHEN statmap_name = ? THEN stat_value END) AS deaths
                        FROM stat_averages
                        GROUP BY hero_guid, target_value, player_bnet_id
                    ),
                    player_values AS (
                        SELECT
                            hero_guid,
                            target_value,
                            player_bnet_id,
                            (kills + assists) / MAX(deaths, 1.0) AS player_value
                        FROM player_components
                        WHERE kills IS NOT NULL AND deaths IS NOT NULL
                    )
                    SELECT
                        hero_guid,
                        target_value,
                        COUNT(*) AS player_count,
                        COALESCE(
                            SUM(CASE WHEN player_value < target_value THEN 1 ELSE 0 END),
                            0
                        ) AS exceeded_count
                    FROM player_values
                    GROUP BY hero_guid, target_value
                    """,
                    (
                        *target_params,
                        kill_guid,
                        assist_guid,
                        death_guid,
                        kill_guid,
                        assist_guid,
                        death_guid,
                    ),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()

            by_hero = {hero_guid: index for index, (hero_guid, _) in enumerate(normalized_features)}
            results = []
            for hero_guid, value, player_count, exceeded_count in rows:
                player_count = int(player_count or 0)
                exceeded_count = int(exceeded_count or 0)
                if player_count <= 0:
                    continue
                results.append(
                    {
                        "hero_guid": str(hero_guid),
                        "statmap_name": "KDA",
                        "value": float(value),
                        "reverse": False,
                        "player_count": player_count,
                        "exceeded_count": exceeded_count,
                        "exceeded_percent": exceeded_count * 100.0 / player_count,
                    }
                )
            results.sort(key=lambda item: by_hero[item["hero_guid"]])
            return results
        except Exception as exc:
            self._warn_once(
                "match stats sqlite get_personal_kda_percentiles failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _get_statmap_summary_preaggregated(
        self,
        conn: sqlite3.Connection,
        *,
        hero_guid: str,
        statmap_names: List[str],
        rank_scores: List[int],
        group_by_rank: bool,
    ) -> Dict[str, Any]:
        if not self._table_exists(conn, COMP_DATA_SUMMARY_TABLE):
            return {}
        where_parts = ["hero_guid = ?"]
        params: List[Any] = [hero_guid]
        if statmap_names:
            placeholders = ",".join(["?"] * len(statmap_names))
            where_parts.append(f"statmap_name IN ({placeholders})")
            params.extend(statmap_names)

        if group_by_rank:
            if rank_scores:
                placeholders = ",".join(["?"] * len(rank_scores))
                where_parts.append(f"rank_bucket_key IN ({placeholders})")
                params.extend(rank_scores)
            else:
                where_parts.append("rank_bucket_key != ?")
                params.append(OVERALL_RANK_BUCKET_KEY)
        else:
            where_parts.append("rank_bucket_key = ?")
            params.append(OVERALL_RANK_BUCKET_KEY)

        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT
                        statmap_name,
                        CASE
                            WHEN rank_bucket_key = ? THEN NULL
                            ELSE rank_bucket_key
                        END AS rank_score,
                        sample_count,
                        avg_value,
                        median_value,
                        top20_value,
                        top10_value,
                        top5_value,
                        top2_value,
                        bottom20_value,
                        bottom10_value,
                        bottom5_value,
                        bottom2_value
                    FROM {COMP_DATA_SUMMARY_TABLE}
                    WHERE {" AND ".join(where_parts)}
                    """,
                    (OVERALL_RANK_BUCKET_KEY, *params),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
        except Exception as exc:
            self._warn_once(f"match stats sqlite preaggregated statmap summary failed: {type(exc).__name__}: {exc}")
            return {}
        return self._summary_rows_to_dict(list(rows))

    def _get_statmap_summary_python(
        self,
        conn: Any,
        *,
        where_sql: str,
        params: List[Any],
        ratio_statmap_names: set[str],
        group_by_rank: bool,
    ) -> Dict[str, Any]:
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT statmap_name, rank_score, statmap_value
                    FROM comp_data
                    WHERE {where_sql}
                    ORDER BY statmap_name, rank_score, statmap_value
                    """,
                    tuple(params),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
        except Exception as exc:
            self._warn_once(f"match stats sqlite get_statmap_summary fallback failed: {type(exc).__name__}: {exc}")
            return {}

        grouped: Dict[Any, List[float]] = {}
        for statmap_name, rank_score, value in rows:
            try:
                normalized_value = float(value)
            except (TypeError, ValueError):
                continue
            if str(statmap_name) in ratio_statmap_names:
                normalized_value = max(0.0, min(1.0, normalized_value))
            rank_key = int(rank_score) if group_by_rank and rank_score is not None else None
            grouped.setdefault((str(statmap_name), rank_key), []).append(normalized_value)

        result: Dict[Any, Dict[str, Any]] = {}
        for key, values in grouped.items():
            count = len(values)
            if count <= 0:
                continue
            values.sort()
            mid_left = (count - 1) // 2
            mid_right = count // 2

            def percentile_index(ratio: float) -> int:
                return max(0, min(count - 1, math.ceil(count * ratio) - 1))

            result[key] = {
                "count": count,
                "avg": sum(values) / count,
                "median": (values[mid_left] + values[mid_right]) / 2,
                "top20": values[percentile_index(0.80)],
                "top10": values[percentile_index(0.90)],
                "top5": values[percentile_index(0.95)],
                "top2": values[percentile_index(0.98)],
                "bottom20": values[percentile_index(0.20)],
                "bottom10": values[percentile_index(0.10)],
                "bottom5": values[percentile_index(0.05)],
                "bottom2": values[percentile_index(0.02)],
            }
        return result

    def get_perk_pick_summary(
        self,
        hero_guid: str,
        perk_level: int,
        rank_scores: Optional[List[int]] = None,
        include_overall: bool = True,
    ) -> Dict[Any, Dict[str, Any]]:
        hero_guid = str(hero_guid or "").strip()
        if not hero_guid:
            return {}
        normalized_perk_level = max(0, int(perk_level or 0))
        normalized_ranks = [int(item) for item in (rank_scores or [])]

        conn = self._get_connection()
        if conn is None:
            return {}
        try:
            if self._table_exists(conn, HERO_PERK_SUMMARY_TABLE):
                where_parts = ["hero_guid = ?", "perk_level = ?"]
                params: List[Any] = [hero_guid, normalized_perk_level]
                rank_filters: List[int] = []
                if include_overall:
                    rank_filters.append(OVERALL_RANK_BUCKET_KEY)
                rank_filters.extend(normalized_ranks)
                if rank_filters:
                    placeholders = ",".join(["?"] * len(rank_filters))
                    where_parts.append(f"rank_bucket_key IN ({placeholders})")
                    params.extend(rank_filters)
                elif not include_overall:
                    where_parts.append("rank_bucket_key != ?")
                    params.append(OVERALL_RANK_BUCKET_KEY)

                cursor = conn.cursor()
                try:
                    cursor.execute(
                        f"""
                        SELECT
                            hero_guid,
                            perk_level,
                            perk_guid,
                            rank_bucket_key,
                            pick_count,
                            sample_count,
                            pick_rate
                        FROM {HERO_PERK_SUMMARY_TABLE}
                        WHERE {" AND ".join(where_parts)}
                        ORDER BY rank_bucket_key ASC, pick_count DESC, perk_guid ASC
                        """,
                        tuple(params),
                    )
                    rows = cursor.fetchall() or []
                finally:
                    cursor.close()
                if rows:
                    return self._perk_summary_rows_to_dict(list(rows))
        except Exception as exc:
            self._warn_once(f"match stats sqlite get_perk_pick_summary failed: {type(exc).__name__}: {exc}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return {}

    def get_perk_pick_summary_from_raw(
        self,
        hero_guid: str,
        perk_level: int,
        rank_scores: Optional[List[int]] = None,
        include_overall: bool = True,
    ) -> Dict[Any, Dict[str, Any]]:
        hero_guid = str(hero_guid or "").strip()
        if not hero_guid:
            return {}
        normalized_perk_level = max(0, int(perk_level or 0))
        normalized_ranks = [int(item) for item in (rank_scores or [])]

        conn = self._get_connection()
        if conn is None:
            return {}
        try:
            if not self._table_exists(conn, HERO_PERK_PICK_TABLE):
                return {}
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT
                        perk_guid,
                        rank_bucket,
                        match_id,
                        player_bnet_id
                    FROM {HERO_PERK_PICK_TABLE}
                    WHERE hero_guid = ? AND perk_level = ?
                    ORDER BY rank_bucket ASC, perk_guid ASC
                    """,
                    (hero_guid, normalized_perk_level),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
        except Exception as exc:
            self._warn_once(
                f"match stats sqlite get_perk_pick_summary_from_raw failed: {type(exc).__name__}: {exc}"
            )
            return {}
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not rows:
            return {}

        overall_samples: set[tuple[str, str]] = set()
        overall_counts: Counter[str] = Counter()
        rank_samples: Dict[int, set[tuple[str, str]]] = {}
        rank_counts: Dict[int, Counter[str]] = {}
        for perk_guid, rank_bucket, match_id, player_bnet_id in rows:
            normalized_perk_guid = str(perk_guid or "").strip()
            normalized_match_id = str(match_id or "").strip()
            normalized_player_id = str(player_bnet_id or "").strip()
            if not normalized_perk_guid or not normalized_match_id or not normalized_player_id:
                continue
            sample_key = (normalized_match_id, normalized_player_id)
            overall_samples.add(sample_key)
            overall_counts[normalized_perk_guid] += 1
            if rank_bucket is None:
                continue
            normalized_rank_bucket = int(rank_bucket)
            rank_samples.setdefault(normalized_rank_bucket, set()).add(sample_key)
            rank_counts.setdefault(normalized_rank_bucket, Counter())[normalized_perk_guid] += 1

        result: Dict[Any, Dict[str, Any]] = {}
        overall_sample_count = len(overall_samples)
        if include_overall and overall_sample_count > 0:
            result[None] = {
                "hero_guid": hero_guid,
                "perk_level": normalized_perk_level,
                "sample_count": overall_sample_count,
                "perks": {
                    perk_guid: {
                        "pick_count": int(pick_count),
                        "sample_count": overall_sample_count,
                        "pick_rate": float(pick_count / overall_sample_count),
                    }
                    for perk_guid, pick_count in overall_counts.items()
                },
            }

        if normalized_ranks:
            selected_ranks = list(dict.fromkeys(normalized_ranks))
        else:
            selected_ranks = sorted(rank_counts)

        for rank_bucket in selected_ranks:
            sample_count = len(rank_samples.get(rank_bucket) or ())
            if sample_count <= 0:
                continue
            counter = rank_counts.get(rank_bucket) or Counter()
            result[int(rank_bucket)] = {
                "hero_guid": hero_guid,
                "perk_level": normalized_perk_level,
                "sample_count": sample_count,
                "perks": {
                    perk_guid: {
                        "pick_count": int(pick_count),
                        "sample_count": sample_count,
                        "pick_rate": float(pick_count / sample_count),
                    }
                    for perk_guid, pick_count in counter.items()
                },
            }
        return result

    def _expand_comp_summary_keys(
        self,
        keys: Iterable[tuple[str, str, Optional[int]]],
    ) -> List[tuple[str, str, int]]:
        expanded: set[tuple[str, str, int]] = set()
        for hero_guid, statmap_name, rank_bucket in keys or []:
            normalized_hero_guid = str(hero_guid or "").strip()
            normalized_statmap_name = str(statmap_name or "").strip()
            if not normalized_hero_guid or not normalized_statmap_name:
                continue
            expanded.add((normalized_hero_guid, normalized_statmap_name, OVERALL_RANK_BUCKET_KEY))
            if rank_bucket is not None:
                expanded.add((normalized_hero_guid, normalized_statmap_name, int(rank_bucket)))
        return sorted(expanded)

    def _expand_perk_summary_keys(
        self,
        keys: Iterable[tuple[str, int, Optional[int]]],
    ) -> List[tuple[str, int, int]]:
        expanded: set[tuple[str, int, int]] = set()
        for hero_guid, perk_level, rank_bucket in keys or []:
            normalized_hero_guid = str(hero_guid or "").strip()
            normalized_perk_level = int(perk_level or 0)
            if not normalized_hero_guid or normalized_perk_level <= 0:
                continue
            expanded.add((normalized_hero_guid, normalized_perk_level, OVERALL_RANK_BUCKET_KEY))
            if rank_bucket is not None:
                expanded.add((normalized_hero_guid, normalized_perk_level, int(rank_bucket)))
        return sorted(expanded)

    def _refresh_comp_data_summaries(
        self,
        conn: sqlite3.Connection,
        summary_keys: Iterable[tuple[str, str, Optional[int]]],
        *,
        updated_at: int,
    ) -> None:
        expanded_keys = self._expand_comp_summary_keys(summary_keys)
        if not expanded_keys:
            return
        conn.execute("DROP TABLE IF EXISTS temp_comp_summary_key")
        conn.execute(
            """
            CREATE TEMP TABLE temp_comp_summary_key (
                hero_guid TEXT NOT NULL,
                statmap_name TEXT NOT NULL,
                rank_bucket_key INTEGER NOT NULL,
                PRIMARY KEY (hero_guid, statmap_name, rank_bucket_key)
            )
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO temp_comp_summary_key (
                hero_guid,
                statmap_name,
                rank_bucket_key
            ) VALUES (?, ?, ?)
            """,
            expanded_keys,
        )
        rows = conn.execute(
            f"""
            WITH filtered AS (
                SELECT
                    temp.hero_guid,
                    temp.statmap_name,
                    temp.rank_bucket_key,
                    comp.statmap_value
                FROM temp_comp_summary_key AS temp
                JOIN {COMP_DATA_TABLE} AS comp
                    ON comp.hero_guid = temp.hero_guid
                    AND comp.statmap_name = temp.statmap_name
                    AND (
                        temp.rank_bucket_key = {OVERALL_RANK_BUCKET_KEY}
                        OR comp.rank_bucket = temp.rank_bucket_key
                    )
            ),
            ranked AS (
                SELECT
                    hero_guid,
                    statmap_name,
                    rank_bucket_key,
                    statmap_value,
                    ROW_NUMBER() OVER (
                        PARTITION BY hero_guid, statmap_name, rank_bucket_key
                        ORDER BY statmap_value
                    ) AS rn,
                    COUNT(*) OVER (
                        PARTITION BY hero_guid, statmap_name, rank_bucket_key
                    ) AS cnt
                FROM filtered
            )
            SELECT
                hero_guid,
                statmap_name,
                rank_bucket_key,
                MAX(cnt) AS sample_count,
                AVG(statmap_value) AS avg_value,
                AVG(
                    CASE
                        WHEN rn IN (
                            CAST((cnt + 1) / 2 AS INTEGER),
                            CAST((cnt + 2) / 2 AS INTEGER)
                        )
                        THEN statmap_value
                    END
                ) AS median_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 80) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top20_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 90) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top10_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 95) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top5_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 98) + 99) / 100 AS INTEGER) THEN statmap_value END) AS top2_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 20) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom20_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 10) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom10_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 5) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom5_value,
                MIN(CASE WHEN rn >= CAST(((cnt * 2) + 99) / 100 AS INTEGER) THEN statmap_value END) AS bottom2_value
            FROM ranked
            GROUP BY hero_guid, statmap_name, rank_bucket_key
            """
        ).fetchall()
        conn.executemany(
            f"""
            INSERT INTO {COMP_DATA_SUMMARY_TABLE} (
                hero_guid,
                statmap_name,
                rank_bucket_key,
                sample_count,
                avg_value,
                median_value,
                top20_value,
                top10_value,
                top5_value,
                top2_value,
                bottom20_value,
                bottom10_value,
                bottom5_value,
                bottom2_value,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hero_guid, statmap_name, rank_bucket_key) DO UPDATE SET
                sample_count = excluded.sample_count,
                avg_value = excluded.avg_value,
                median_value = excluded.median_value,
                top20_value = excluded.top20_value,
                top10_value = excluded.top10_value,
                top5_value = excluded.top5_value,
                top2_value = excluded.top2_value,
                bottom20_value = excluded.bottom20_value,
                bottom10_value = excluded.bottom10_value,
                bottom5_value = excluded.bottom5_value,
                bottom2_value = excluded.bottom2_value,
                updated_at = excluded.updated_at
            """,
            [
                (
                    row[0],
                    row[1],
                    int(row[2]),
                    int(row[3] or 0),
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                    row[10],
                    row[11],
                    row[12],
                    row[13],
                    int(updated_at),
                )
                for row in rows
            ],
        )
        conn.execute("DROP TABLE IF EXISTS temp_comp_summary_key")

    def _refresh_hero_perk_summaries(
        self,
        conn: sqlite3.Connection,
        summary_keys: Iterable[tuple[str, int, Optional[int]]],
        *,
        updated_at: int,
    ) -> None:
        expanded_keys = self._expand_perk_summary_keys(summary_keys)
        if not expanded_keys:
            return
        conn.execute("DROP TABLE IF EXISTS temp_perk_summary_key")
        conn.execute(
            """
            CREATE TEMP TABLE temp_perk_summary_key (
                hero_guid TEXT NOT NULL,
                perk_level INTEGER NOT NULL,
                rank_bucket_key INTEGER NOT NULL,
                PRIMARY KEY (hero_guid, perk_level, rank_bucket_key)
            )
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO temp_perk_summary_key (
                hero_guid,
                perk_level,
                rank_bucket_key
            ) VALUES (?, ?, ?)
            """,
            expanded_keys,
        )
        rows = conn.execute(
            f"""
            WITH sample_source AS (
                SELECT
                    temp.hero_guid,
                    temp.perk_level,
                    temp.rank_bucket_key,
                    pick.match_id,
                    pick.player_bnet_id,
                    pick.hero_guid AS sample_hero_guid
                FROM temp_perk_summary_key AS temp
                JOIN {HERO_PERK_PICK_TABLE} AS pick
                    ON pick.hero_guid = temp.hero_guid
                    AND pick.perk_level = temp.perk_level
                    AND (
                        temp.rank_bucket_key = {OVERALL_RANK_BUCKET_KEY}
                        OR pick.rank_bucket = temp.rank_bucket_key
                    )
                GROUP BY
                    temp.hero_guid,
                    temp.perk_level,
                    temp.rank_bucket_key,
                    pick.match_id,
                    pick.player_bnet_id,
                    pick.hero_guid
            ),
            sample_counts AS (
                SELECT
                    hero_guid,
                    perk_level,
                    rank_bucket_key,
                    COUNT(*) AS sample_count
                FROM sample_source
                GROUP BY hero_guid, perk_level, rank_bucket_key
            ),
            pick_counts AS (
                SELECT
                    temp.hero_guid,
                    temp.perk_level,
                    pick.perk_guid,
                    temp.rank_bucket_key,
                    COUNT(*) AS pick_count
                FROM temp_perk_summary_key AS temp
                JOIN {HERO_PERK_PICK_TABLE} AS pick
                    ON pick.hero_guid = temp.hero_guid
                    AND pick.perk_level = temp.perk_level
                    AND (
                        temp.rank_bucket_key = {OVERALL_RANK_BUCKET_KEY}
                        OR pick.rank_bucket = temp.rank_bucket_key
                    )
                GROUP BY
                    temp.hero_guid,
                    temp.perk_level,
                    pick.perk_guid,
                    temp.rank_bucket_key
            )
            SELECT
                pick_counts.hero_guid,
                pick_counts.perk_level,
                pick_counts.perk_guid,
                pick_counts.rank_bucket_key,
                pick_counts.pick_count,
                sample_counts.sample_count,
                CASE
                    WHEN sample_counts.sample_count > 0
                    THEN CAST(pick_counts.pick_count AS REAL) / CAST(sample_counts.sample_count AS REAL)
                    ELSE 0
                END AS pick_rate
            FROM pick_counts
            JOIN sample_counts
                ON sample_counts.hero_guid = pick_counts.hero_guid
                AND sample_counts.perk_level = pick_counts.perk_level
                AND sample_counts.rank_bucket_key = pick_counts.rank_bucket_key
            """
        ).fetchall()
        conn.executemany(
            f"""
            INSERT INTO {HERO_PERK_SUMMARY_TABLE} (
                hero_guid,
                perk_level,
                perk_guid,
                rank_bucket_key,
                pick_count,
                sample_count,
                pick_rate,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hero_guid, perk_level, perk_guid, rank_bucket_key) DO UPDATE SET
                pick_count = excluded.pick_count,
                sample_count = excluded.sample_count,
                pick_rate = excluded.pick_rate,
                updated_at = excluded.updated_at
            """,
            [
                (
                    row[0],
                    int(row[1] or 0),
                    row[2],
                    int(row[3]),
                    int(row[4] or 0),
                    int(row[5] or 0),
                    float(row[6] or 0.0),
                    int(updated_at),
                )
                for row in rows
            ],
        )
        conn.execute("DROP TABLE IF EXISTS temp_perk_summary_key")

    def write_match_detail_batch(
        self,
        *,
        hero_detail_rows: Sequence[Dict[str, Any]],
        comp_data_rows: Sequence[Dict[str, Any]],
        perk_pick_rows: Sequence[Dict[str, Any]],
        comp_summary_keys: Iterable[tuple[str, str, Optional[int]]],
        perk_summary_keys: Iterable[tuple[str, int, Optional[int]]],
    ) -> Dict[str, int]:
        if not hero_detail_rows and not comp_data_rows and not perk_pick_rows:
            return {"hero_details": 0, "comp_data": 0, "perk_picks": 0}

        with self._write_lock:
            conn = self._get_write_connection()
            if conn is None:
                return {"hero_details": 0, "comp_data": 0, "perk_picks": 0}
            try:
                self._initialize_player_identity_table(conn)
                self._initialize_match_detail_tables(conn)

                if hero_detail_rows:
                    conn.executemany(
                        f"""
                        INSERT OR IGNORE INTO {HERO_MATCH_DETAIL_TABLE} (
                            match_id,
                            player_bnet_id,
                            player_name,
                            hero_guid,
                            rank_score,
                            rank_bucket,
                            use_time_sec,
                            use_time_rate,
                            map_guid,
                            start_time,
                            game_time_sec,
                            stat_map_json,
                            last_update
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                str(row.get("match_id") or ""),
                                str(row.get("player_bnet_id") or ""),
                                str(row.get("player_name") or ""),
                                str(row.get("hero_guid") or ""),
                                row.get("rank_score"),
                                row.get("rank_bucket"),
                                float(row.get("use_time_sec") or 0.0),
                                float(row.get("use_time_rate") or 0.0),
                                str(row.get("map_guid") or ""),
                                int(row.get("start_time") or 0),
                                int(row.get("game_time_sec") or 0),
                                str(row.get("stat_map_json") or "{}"),
                                int(row.get("last_update") or 0),
                            )
                            for row in hero_detail_rows
                        ],
                    )

                if comp_data_rows:
                    conn.executemany(
                        f"""
                        INSERT OR IGNORE INTO {COMP_DATA_TABLE} (
                            match_id,
                            player_bnet_id,
                            hero_guid,
                            statmap_name,
                            statmap_value,
                            statmap_raw_value,
                            rank_score,
                            rank_bucket,
                            use_time_sec,
                            use_time_rate,
                            last_update
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                str(row.get("match_id") or ""),
                                str(row.get("player_bnet_id") or ""),
                                str(row.get("hero_guid") or ""),
                                str(row.get("statmap_name") or ""),
                                float(row.get("statmap_value") or 0.0),
                                float(row.get("statmap_raw_value") or 0.0),
                                row.get("rank_score"),
                                row.get("rank_bucket"),
                                float(row.get("use_time_sec") or 0.0),
                                float(row.get("use_time_rate") or 0.0),
                                int(row.get("last_update") or 0),
                            )
                            for row in comp_data_rows
                        ],
                    )

                if perk_pick_rows:
                    conn.executemany(
                        f"""
                        INSERT OR IGNORE INTO {HERO_PERK_PICK_TABLE} (
                            match_id,
                            player_bnet_id,
                            player_name,
                            hero_guid,
                            perk_guid,
                            perk_level,
                            slot_index,
                            rank_score,
                            rank_bucket,
                            start_time,
                            last_update
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                str(row.get("match_id") or ""),
                                str(row.get("player_bnet_id") or ""),
                                str(row.get("player_name") or ""),
                                str(row.get("hero_guid") or ""),
                                str(row.get("perk_guid") or ""),
                                int(row.get("perk_level") or 0),
                                int(row.get("slot_index") or 0),
                                row.get("rank_score"),
                                row.get("rank_bucket"),
                                int(row.get("start_time") or 0),
                                int(row.get("last_update") or 0),
                            )
                            for row in perk_pick_rows
                        ],
                    )

                refresh_ts = int(time.time())
                self._refresh_comp_data_summaries(conn, comp_summary_keys, updated_at=refresh_ts)
                self._refresh_hero_perk_summaries(conn, perk_summary_keys, updated_at=refresh_ts)
                conn.commit()
                return {
                    "hero_details": len(hero_detail_rows),
                    "comp_data": len(comp_data_rows),
                    "perk_picks": len(perk_pick_rows),
                }
            except Exception as exc:
                self._warn_once(f"match stats sqlite write_match_detail_batch failed: {type(exc).__name__}: {exc}")
                return {"hero_details": 0, "comp_data": 0, "perk_picks": 0}
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def upsert_player_identity_records(self, rows: Iterable[Dict[str, Any]]) -> int:
        normalized_rows: Dict[str, tuple[str, str, str, str, int]] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            bnetid = str(row.get("bnetid") or row.get("bnetId") or row.get("bnet_id") or "").strip()
            battletag = str(row.get("battletag") or row.get("battleTag") or "").replace("＃", "#").strip()
            battlename = str(row.get("battlename") or row.get("battleName") or "").strip()
            battlenum = str(row.get("battlenum") or row.get("battleNum") or "").strip()
            if not battletag and battlename:
                battletag = battlename if not battlenum else f"{battlename}#{battlenum}"
            if not battlename and battletag:
                if "#" in battletag:
                    battlename, battlenum = battletag.rsplit("#", 1)
                    battlename = battlename.strip() or battletag
                    battlenum = battlenum.strip()
                else:
                    battlename = battletag
            if not bnetid or not battletag or not battlename:
                continue
            try:
                update_time = int(row.get("update_time") or time.time())
            except (TypeError, ValueError):
                update_time = int(time.time())
            normalized_rows[bnetid] = (bnetid, battletag, battlename, battlenum, update_time)

        if not normalized_rows:
            return 0

        with self._write_lock:
            conn = self._get_write_connection()
            if conn is None:
                return 0
            try:
                self._initialize_player_identity_table(conn)
                conn.executemany(
                    f"""
                    INSERT INTO {PLAYER_IDENTITY_TABLE} (
                        bnetid,
                        battletag,
                        battlename,
                        battlenum,
                        update_time
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(bnetid) DO UPDATE SET
                        battletag = excluded.battletag,
                        battlename = excluded.battlename,
                        battlenum = excluded.battlenum,
                        update_time = excluded.update_time
                    """,
                    list(normalized_rows.values()),
                )
                conn.commit()
                return len(normalized_rows)
            except Exception as exc:
                self._warn_once(f"match stats sqlite upsert_player_identity_records failed: {type(exc).__name__}: {exc}")
                return 0
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def search_player_identity_by_bnet_id(
        self,
        bnet_id: str,
        *,
        limit: int = 10,
        exact_only: bool = False,
    ) -> List[Dict[str, Any]]:
        normalized_bnet_id = str(bnet_id or "").strip()
        if not normalized_bnet_id:
            return []

        try:
            normalized_limit = max(1, int(limit or 10))
        except (TypeError, ValueError):
            normalized_limit = 10

        conn = self._get_connection()
        if conn is None:
            return []

        escaped_bnet_id = self._escape_like_pattern(normalized_bnet_id)
        prefix_pattern = f"{escaped_bnet_id}%"
        contains_pattern = f"%{escaped_bnet_id}%"

        try:
            cursor = conn.cursor()
            try:
                if exact_only:
                    cursor.execute(
                        f"""
                        SELECT
                            bnetid,
                            battletag,
                            battlename,
                            battlenum,
                            update_time,
                            'exact' AS match_type
                        FROM {PLAYER_IDENTITY_TABLE}
                        WHERE bnetid = ?
                        ORDER BY update_time DESC, bnetid ASC
                        LIMIT ?
                        """,
                        (normalized_bnet_id, normalized_limit),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT
                            bnetid,
                            battletag,
                            battlename,
                            battlenum,
                            update_time,
                            CASE
                                WHEN bnetid = ? THEN 'exact'
                                WHEN bnetid LIKE ? ESCAPE '!' THEN 'prefix'
                                ELSE 'contains'
                            END AS match_type
                        FROM {PLAYER_IDENTITY_TABLE}
                        WHERE
                            bnetid = ?
                            OR bnetid LIKE ? ESCAPE '!'
                            OR bnetid LIKE ? ESCAPE '!'
                        ORDER BY
                            CASE
                                WHEN bnetid = ? THEN 0
                                WHEN bnetid LIKE ? ESCAPE '!' THEN 1
                                ELSE 2
                            END ASC,
                            update_time DESC,
                            bnetid ASC
                        LIMIT ?
                        """,
                        (
                            normalized_bnet_id,
                            prefix_pattern,
                            normalized_bnet_id,
                            prefix_pattern,
                            contains_pattern,
                            normalized_bnet_id,
                            prefix_pattern,
                            normalized_limit,
                        ),
                    )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()

            return [
                {
                    "bnetid": row[0],
                    "battletag": row[1],
                    "battlename": row[2],
                    "battlenum": row[3],
                    "update_time": int(row[4] or 0),
                    "match_type": row[5],
                }
                for row in rows
            ]
        except Exception as exc:
            self._warn_once(f"match stats sqlite search_player_identity_by_bnet_id failed: {type(exc).__name__}: {exc}")
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_entry_ds_exact_ci_one(self, battletag: str, battlenum: Optional[int] = None) -> Optional[Dict[str, Any]]:
        return None

    def get_entry_ds(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def get_all_entries_ds2(self) -> List[Dict[str, Any]]:
        return []

    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> Any:
            if name == "get_entry_ds_exact_ci_one":
                return None
            if name.startswith("get_"):
                return []
            return None

        return _noop

__all__ = [
    "COMP_DATA_SUMMARY_TABLE",
    "COMP_DATA_TABLE",
    "HERO_MATCH_DETAIL_TABLE",
    "HERO_PERK_PICK_TABLE",
    "HERO_PERK_SUMMARY_TABLE",
    "IDPoolDB",
    "MATCH_STATS_DB_PATH",
    "OVERALL_RANK_BUCKET_KEY",
    "PLAYER_IDENTITY_TABLE",
]
