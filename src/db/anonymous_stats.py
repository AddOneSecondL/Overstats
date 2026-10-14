"""Anonymous distributions and counters; no player or match records are stored."""
import hashlib
import hmac
import json
import math
import secrets
import time
from collections import defaultdict

QUANTILES = (80, 90, 95, 98, 20, 10, 5, 2)


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS anonymous_meta (name TEXT PRIMARY KEY, value BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS anonymous_seen (digest BLOB PRIMARY KEY) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS anonymous_stat_distribution (
      hero_guid TEXT NOT NULL, statmap_name TEXT NOT NULL, rank_bucket_key INTEGER NOT NULL,
      value REAL NOT NULL, count INTEGER NOT NULL,
      PRIMARY KEY(hero_guid,statmap_name,rank_bucket_key,value));
    CREATE TABLE IF NOT EXISTS comp_data_summary (
      hero_guid TEXT NOT NULL, statmap_name TEXT NOT NULL, rank_bucket_key INTEGER NOT NULL,
      sample_count INTEGER NOT NULL, avg_value REAL, median_value REAL,
      top20_value REAL, top10_value REAL, top5_value REAL, top2_value REAL,
      bottom20_value REAL, bottom10_value REAL, bottom5_value REAL, bottom2_value REAL,
      updated_at INTEGER, PRIMARY KEY(hero_guid,statmap_name,rank_bucket_key));
    CREATE TABLE IF NOT EXISTS hero_perk_summary (
      hero_guid TEXT NOT NULL, perk_level INTEGER NOT NULL, perk_guid TEXT NOT NULL,
      rank_bucket_key INTEGER NOT NULL, pick_count INTEGER NOT NULL,
      sample_count INTEGER NOT NULL, pick_rate REAL, updated_at INTEGER,
      PRIMARY KEY(hero_guid,perk_level,perk_guid,rank_bucket_key));
    CREATE TABLE IF NOT EXISTS anonymous_perk_samples (
      hero_guid TEXT NOT NULL, perk_level INTEGER NOT NULL, rank_bucket_key INTEGER NOT NULL,
      sample_count INTEGER NOT NULL, PRIMARY KEY(hero_guid,perk_level,rank_bucket_key));
    """)
    conn.execute("INSERT OR IGNORE INTO anonymous_meta VALUES ('event_key', ?)", (secrets.token_bytes(32),))
    # Existing anonymous perk totals remain usable after upgrading.
    conn.execute("""INSERT OR IGNORE INTO anonymous_perk_samples
      SELECT hero_guid,perk_level,rank_bucket_key,MAX(sample_count)
      FROM hero_perk_summary GROUP BY hero_guid,perk_level,rank_bucket_key""")
    conn.commit()


def anonymize(batch, key):
    def digest(kind, parts):
        return hmac.digest(key, json.dumps([kind, *parts], separators=(',', ':')).encode(), hashlib.sha256)
    stats, perks = [], []
    for r in batch.comp_data_rows:
        try:
            value = float(r['statmap_value'])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        event = digest('stat', [r['match_id'], r['player_bnet_id'], r['hero_guid'], r['statmap_name']])
        stats.append((event, r['hero_guid'], r['statmap_name'], r.get('rank_bucket'), value))
    grouped = defaultdict(set)
    for r in batch.perk_pick_rows:
        grouped[(r['match_id'], r['player_bnet_id'], r['hero_guid'], int(r['perk_level']), r.get('rank_bucket'))].add(str(r['perk_guid']))
    for (match, player, hero, level, rank), choices in grouped.items():
        if level not in (1, 2):
            continue
        perks.append((digest('perk', [match, player, hero, level]), hero, level, rank, tuple(sorted(choices))))
    return stats, perks


def write(conn, batches):
    changed = set()
    now = int(time.time())
    counts = {'comp_data': 0, 'perk_picks': 0, 'hero_details': 0}
    with conn:
        for stats, perks in batches:
            for event, hero, stat, rank, value in stats:
                if not conn.execute('INSERT OR IGNORE INTO anonymous_seen VALUES (?)', (event,)).rowcount:
                    continue
                for bucket in {-1, int(rank) if rank is not None else -1}:
                    conn.execute("""INSERT INTO anonymous_stat_distribution VALUES (?,?,?,?,1)
                      ON CONFLICT(hero_guid,statmap_name,rank_bucket_key,value)
                      DO UPDATE SET count=count+1""", (hero, stat, bucket, value))
                    changed.add((hero, stat, bucket))
                counts['comp_data'] += 1
            for event, hero, level, rank, choices in perks:
                if not conn.execute('INSERT OR IGNORE INTO anonymous_seen VALUES (?)', (event,)).rowcount:
                    continue
                for bucket in {-1, int(rank) if rank is not None else -1}:
                    group = (hero, level, bucket)
                    conn.execute("""INSERT INTO anonymous_perk_samples VALUES (?,?,?,1)
                      ON CONFLICT(hero_guid,perk_level,rank_bucket_key)
                      DO UPDATE SET sample_count=sample_count+1""", group)
                    total = conn.execute('SELECT sample_count FROM anonymous_perk_samples WHERE hero_guid=? AND perk_level=? AND rank_bucket_key=?', group).fetchone()[0]
                    for perk in choices:
                        conn.execute("""INSERT INTO hero_perk_summary VALUES (?,?,?,?,1,?,0,?)
                          ON CONFLICT(hero_guid,perk_level,perk_guid,rank_bucket_key)
                          DO UPDATE SET pick_count=pick_count+1""", (hero, level, perk, bucket, total, now))
                    conn.execute("""UPDATE hero_perk_summary SET sample_count=?,pick_rate=1.0*pick_count/?,updated_at=?
                      WHERE hero_guid=? AND perk_level=? AND rank_bucket_key=?""", (total,total,now,*group))
                counts['perk_picks'] += len(choices)
        for group in changed:
            rows = conn.execute('SELECT value,count FROM anonymous_stat_distribution WHERE hero_guid=? AND statmap_name=? AND rank_bucket_key=? ORDER BY value', group).fetchall()
            count = sum(n for _, n in rows)
            def at(position):
                running = 0
                for value, n in rows:
                    running += n
                    if running >= position:
                        return value
            avg = sum(v*n for v,n in rows)/count
            median = (at((count+1)//2)+at((count+2)//2))/2
            values = [at(max(1,math.ceil(count*q/100))) for q in QUANTILES]
            conn.execute("""INSERT INTO comp_data_summary
              (hero_guid,statmap_name,rank_bucket_key,sample_count,avg_value,median_value,
               top20_value,top10_value,top5_value,top2_value,bottom20_value,bottom10_value,bottom5_value,bottom2_value,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(hero_guid,statmap_name,rank_bucket_key) DO UPDATE SET
               sample_count=excluded.sample_count,avg_value=excluded.avg_value,median_value=excluded.median_value,
               top20_value=excluded.top20_value,top10_value=excluded.top10_value,top5_value=excluded.top5_value,
               top2_value=excluded.top2_value,bottom20_value=excluded.bottom20_value,bottom10_value=excluded.bottom10_value,
               bottom5_value=excluded.bottom5_value,bottom2_value=excluded.bottom2_value,updated_at=excluded.updated_at""",
               (*group,count,avg,median,*values,now))
    return counts
