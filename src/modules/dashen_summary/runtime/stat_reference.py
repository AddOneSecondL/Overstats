from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Optional, Sequence

from ....constants.ranks import normalize_raw_rank_bucket


HERO_AVG_PERCENT_KEYWORDS = ("率", "效率", "占比")
HERO_AVG_PERCENT_TEXTS = {"英雄获胜"}
HERO_AVG_RAW_VALUE_TEXTS = {"英雄获胜", "累计游戏时间", "累积游戏时间"}
HERO_AVG_RAW_VALUE_GUIDS = {"603482350067646497", "603482350067648623"}
HERO_AVG_SKIP_VALUE_GUIDS = {"603482350067646497"}

_STATMAP_SUMMARY_CACHE: "OrderedDict[tuple[Any, ...], dict[str, Any]]" = OrderedDict()


def is_hero_avg_percent_stat(value_text: Any) -> bool:
    value_text = str(value_text or "")
    return value_text in HERO_AVG_PERCENT_TEXTS or any(keyword in value_text for keyword in HERO_AVG_PERCENT_KEYWORDS)


def is_hero_avg_raw_stat(value_text: Any, value_guid: Any = None) -> bool:
    return str(value_guid or "") in HERO_AVG_RAW_VALUE_GUIDS or str(value_text or "") in HERO_AVG_RAW_VALUE_TEXTS


def clamp_percent_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_hero_rank_score(rank_score: Any) -> Optional[int]:
    return normalize_raw_rank_bucket(rank_score)


def get_hero_avg_percent_guids(config: dict[str, Any], stat_guids: Optional[Iterable[Any]] = None) -> list[str]:
    stat_guid_set = {str(guid) for guid in stat_guids} if stat_guids else None
    percent_guids = []
    for item in config.get("heroAttrList", []) or []:
        value_guid = str(item.get("valueGuid") or "")
        if not value_guid or (stat_guid_set is not None and value_guid not in stat_guid_set):
            continue
        if is_hero_avg_percent_stat(item.get("valueText")):
            percent_guids.append(value_guid)
    return sorted(set(percent_guids))


def normalize_dashen_hero_stat_value(
    value: Any,
    user_time_sec: Any,
    value_text: Any = None,
    value_guid: Any = None,
) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
        user_time_sec = float(user_time_sec or 0)
    except (TypeError, ValueError):
        return None
    if is_hero_avg_percent_stat(value_text):
        return clamp_percent_value(value)
    if is_hero_avg_raw_stat(value_text, value_guid):
        return value
    time_coef = user_time_sec / 600
    if time_coef <= 0:
        return None
    return value / time_coef


def classify_hero_average_band(current_value: Any, ref: Optional[dict[str, Any]]) -> str:
    if current_value is None or not ref:
        return "unknown"
    if ref.get("top2") is not None and current_value >= ref["top2"]:
        return "top2"
    if ref.get("top5") is not None and current_value >= ref["top5"]:
        return "top5"
    if ref.get("top10") is not None and current_value >= ref["top10"]:
        return "top10"
    if ref.get("top20") is not None and current_value >= ref["top20"]:
        return "top20"
    if ref.get("avg") is not None and current_value > ref["avg"]:
        return "above_median"
    return "below_median"


def get_cached_statmap_summary(
    db: Any,
    lookup_key: Any,
    stat_guids: Optional[Sequence[Any]],
    rank_buckets: Optional[Sequence[Any]],
    ratio_stat_guids: Optional[Sequence[Any]],
    prefer_rank: bool,
    *,
    cache_max: int = 2048,
) -> dict[str, Any]:
    cache_key = (
        str(lookup_key),
        tuple(sorted(str(item) for item in (stat_guids or []))),
        tuple(sorted(str(item) for item in (rank_buckets or []))) if rank_buckets is not None else None,
        tuple(sorted(str(item) for item in (ratio_stat_guids or []))),
        bool(prefer_rank),
    )
    cached = _STATMAP_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        try:
            _STATMAP_SUMMARY_CACHE.move_to_end(cache_key)
        except Exception:
            pass
        return cached

    result = db.get_statmap_summary(
        lookup_key,
        list(stat_guids or []),
        list(rank_buckets) if rank_buckets is not None else None,
        list(ratio_stat_guids or []),
        bool(prefer_rank),
    ) or {}
    _STATMAP_SUMMARY_CACHE[cache_key] = result
    while len(_STATMAP_SUMMARY_CACHE) > max(32, int(cache_max or 2048)):
        _STATMAP_SUMMARY_CACHE.popitem(last=False)
    return result
