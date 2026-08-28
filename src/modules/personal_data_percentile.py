from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping, Optional, Sequence

try:
    from overstats.config import is_database_write_enabled
    from overstats.src.db.match_stats import IDPoolDB
    from overstats.src.modules.dashen_summary.runtime.stat_reference import (
        normalize_dashen_hero_stat_value,
    )
except ModuleNotFoundError:
    from config import is_database_write_enabled
    from src.db.match_stats import IDPoolDB
    from src.modules.dashen_summary.runtime.stat_reference import (
        normalize_dashen_hero_stat_value,
    )


COMPARABLE_VALUE_TYPES = {"特色数据", "通用数据"}
GAME_TIME_GUID = "603482350067646497"
KILL_GUID = "603482350067646495"
ASSIST_GUID = "603482350067648392"
DEATH_GUID = "603482350067646506"


@dataclass(frozen=True)
class PersonalDataRanking:
    exceeded_percent: float
    top_percent: float
    metric_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exceeded_percent": float(self.exceeded_percent),
            "top_percent": float(self.top_percent),
            "metric_count": int(self.metric_count),
        }


def _feature_attr_lookup(config: Mapping[str, Any]) -> Dict[tuple[str, str], str]:
    lookup: Dict[tuple[str, str], str] = {}
    for item in config.get("heroAttrList", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("valueType") or "").strip() not in COMPARABLE_VALUE_TYPES:
            continue
        hero_guid = str(item.get("heroGuid") or "").strip()
        value_guid = str(item.get("valueGuid") or "").strip()
        if hero_guid and value_guid and value_guid != GAME_TIME_GUID:
            lookup[(hero_guid, value_guid)] = str(item.get("valueText") or "")
    return lookup


def collect_personal_feature_values(
    config: Mapping[str, Any],
    match_detail_payloads: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    """Average each available personal feature across the queried matches."""
    attr_lookup = _feature_attr_lookup(config)
    if not attr_lookup:
        return []

    values_by_feature: Dict[tuple[str, str], list[float]] = defaultdict(list)
    for payload in match_detail_payloads or []:
        if not isinstance(payload, Mapping) or payload.get("code") != 0:
            continue
        data = payload.get("data")
        if not isinstance(data, Mapping):
            continue
        for hero in data.get("heroList", []) or []:
            if not isinstance(hero, Mapping):
                continue
            hero_guid = str(hero.get("heroId") or hero.get("heroGuid") or "").strip()
            stat_map = hero.get("statMap")
            if not hero_guid or not isinstance(stat_map, Mapping):
                continue
            user_time_sec = hero.get("userTimeSec")
            if not user_time_sec:
                user_time_sec = stat_map.get(GAME_TIME_GUID, 0)
            for raw_guid, raw_value in stat_map.items():
                value_guid = str(raw_guid or "").strip()
                value_text = attr_lookup.get((hero_guid, value_guid))
                if value_text is None:
                    continue
                normalized = normalize_dashen_hero_stat_value(
                    raw_value,
                    user_time_sec,
                    value_text,
                    value_guid,
                )
                if normalized is None or not math.isfinite(normalized):
                    continue
                values_by_feature[(hero_guid, value_guid)].append(float(normalized))

    return [
        {
            "hero_guid": hero_guid,
            "statmap_name": statmap_name,
            "value": sum(values) / len(values),
            "reverse": statmap_name == DEATH_GUID,
        }
        for (hero_guid, statmap_name), values in sorted(values_by_feature.items())
        if values
    ]


def calculate_personal_data_ranking(
    config: Mapping[str, Any],
    match_detail_payloads: Sequence[Mapping[str, Any]],
    *,
    db: Optional[IDPoolDB] = None,
    database_enabled: Optional[bool] = None,
) -> Optional[PersonalDataRanking]:
    enabled = is_database_write_enabled() if database_enabled is None else bool(database_enabled)
    if not enabled:
        return None

    feature_values = collect_personal_feature_values(config, match_detail_payloads)
    if not feature_values:
        return None

    active_db = db or IDPoolDB()
    comparisons = active_db.get_personal_stat_percentiles(feature_values)
    values_by_key = {
        (str(item.get("hero_guid") or ""), str(item.get("statmap_name") or "")): float(item["value"])
        for item in feature_values
    }
    kda_values = []
    hero_guids = sorted({hero_guid for hero_guid, _ in values_by_key})
    for hero_guid in hero_guids:
        kills = values_by_key.get((hero_guid, KILL_GUID))
        deaths = values_by_key.get((hero_guid, DEATH_GUID))
        if kills is None or deaths is None:
            continue
        assists = values_by_key.get((hero_guid, ASSIST_GUID), 0.0)
        kda_values.append(
            {
                "hero_guid": hero_guid,
                "value": (kills + assists) / max(deaths, 1.0),
            }
        )
    if kda_values:
        comparisons.extend(active_db.get_personal_kda_percentiles(kda_values))
    exceeded_percentages = [
        float(item.get("exceeded_percent"))
        for item in comparisons or []
        if isinstance(item, dict) and item.get("exceeded_percent") is not None
    ]
    if not exceeded_percentages:
        return None

    exceeded_percent = max(
        0.0,
        min(100.0, sum(exceeded_percentages) / len(exceeded_percentages)),
    )
    return PersonalDataRanking(
        exceeded_percent=round(exceeded_percent, 1),
        top_percent=round(100.0 - exceeded_percent, 1),
        metric_count=len(exceeded_percentages),
    )


__all__ = [
    "ASSIST_GUID",
    "COMPARABLE_VALUE_TYPES",
    "DEATH_GUID",
    "KILL_GUID",
    "PersonalDataRanking",
    "calculate_personal_data_ranking",
    "collect_personal_feature_values",
]
