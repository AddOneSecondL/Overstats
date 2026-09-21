"""Hourly play time from real match intervals, with no inferred durations."""
from collections import defaultdict
from datetime import datetime, timedelta
from math import isfinite


def hourly_activity(matches, durations, *, weekly=False, end_day=None):
    end_day = end_day or datetime.now().date()
    days = [end_day - timedelta(days=6-i) for i in range(7)] if weekly else []
    allowed = set(days)
    intervals = defaultdict(list)
    valid = 0
    seen = set()
    for match in matches:
        key = str(match.get("matchId") or match.get("beginTs") or "")
        if key in seen:
            continue
        seen.add(key)
        try:
            seconds = float(durations.get(key, match.get("gameTimeSec")) or 0)
            timestamp = float(match.get("beginTs") or 0)
            if not isfinite(seconds) or not isfinite(timestamp) or timestamp <= 0 or not 0 < seconds <= 21600:
                continue
            start = datetime.fromtimestamp(timestamp / 1000)
            end = start + timedelta(seconds=seconds)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        valid += 1
        while start < end:
            boundary = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            stop = min(end, boundary)
            if not weekly or start.date() in allowed:
                # Union overlapping/duplicated match intervals before summing minutes.
                intervals[(start.date(), start.hour)].append((start, stop))
            start = stop
    daily = defaultdict(lambda: [0.0] * 24)
    for (day, hour), segments in intervals.items():
        merged = []
        for start, stop in sorted(segments):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
            else:
                merged.append((start, stop))
        daily[day][hour] = sum((stop-start).total_seconds()/60 for start, stop in merged)
    if weekly:
        series = [(day, daily[day]) for day in days]
    else:
        series = [(None, [sum(values[hour] for values in daily.values()) for hour in range(24)])]
    return {"series":series, "valid":valid, "total":len(seen), "weekly":weekly}


def stacked_activity(series):
    """Return per-day lower/upper envelopes and the hourly total."""
    total = [0.0] * 24
    layers = []
    for day, values in series:
        lower = total[:]
        total = [base + value for base, value in zip(lower, values)]
        layers.append((day, lower, total[:]))
    return layers, total
