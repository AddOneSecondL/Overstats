"""Remove retired player-level storage, retaining anonymous aggregate tables."""
import sqlite3
from pathlib import Path
from .match_stats import MATCH_STATS_DB_PATH

RETIRED_TABLES = ('player_identity_map', 'hero_match_detail', 'comp_data', 'hero_perk_pick')

def purge_player_storage(db_path: Path = MATCH_STATS_DB_PATH) -> None:
    path = Path(db_path)
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=15)
    try:
        connection.execute('PRAGMA secure_delete=ON')
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables.intersection(RETIRED_TABLES):
            return
        with connection:
            for table in RETIRED_TABLES:
                connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        connection.execute('VACUUM')
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        connection.close()

if __name__ == '__main__':
    purge_player_storage()
    print('Retired player storage removed; anonymous aggregates retained.')
