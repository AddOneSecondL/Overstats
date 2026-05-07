from __future__ import annotations

import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


MATCH_STATS_DB_PATH = Path(__file__).resolve().parent / "match_stats.sqlite3"
PLAYER_IDENTITY_TABLE = "player_identity_map"


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
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = None
            return connection
        except Exception as exc:
            self._warn_once(f"match stats sqlite connection failed: {type(exc).__name__}: {exc}")
            return None

    def _get_write_connection(self) -> Optional[sqlite3.Connection]:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.db_path), timeout=30)
            connection.row_factory = None
            return connection
        except Exception as exc:
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

    @staticmethod
    def _escape_like_pattern(text: str) -> str:
        return str(text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

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
                                WHEN bnetid LIKE ? ESCAPE '\' THEN 'prefix'
                                ELSE 'contains'
                            END AS match_type
                        FROM {PLAYER_IDENTITY_TABLE}
                        WHERE
                            bnetid = ?
                            OR bnetid LIKE ? ESCAPE '\'
                            OR bnetid LIKE ? ESCAPE '\'
                        ORDER BY
                            CASE
                                WHEN bnetid = ? THEN 0
                                WHEN bnetid LIKE ? ESCAPE '\' THEN 1
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

__all__ = ["IDPoolDB", "MATCH_STATS_DB_PATH", "PLAYER_IDENTITY_TABLE"]
