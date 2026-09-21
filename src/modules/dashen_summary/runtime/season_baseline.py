"""Parse queryCountInfo hero baselines without depending on local match storage."""
from math import isfinite

# Shared raw stat GUIDs used by Dashen hero statMap.
CORE_GUIDS = {
    "603482350067646507": "finalHit", "603482350067647671": "heroDamage",
    "603482350067646506": "death", "603482350067646913": "cure",
    "603482350067647479": "cure", "603482350067648392": "assist",
}
ALIASES = {"aveFinalHit":"finalHit", "aveFinalBlows":"finalHit", "finalBlows":"finalHit",
           "aveHeroDamage":"heroDamage", "damage":"heroDamage", "aveDeath":"death",
           "aveCure":"cure", "healing":"cure", "aveResistDamage":"resistDamage", "aveAssist":"assist"}


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) and result >= 0 else None


def stat_values(raw):
    if isinstance(raw, dict):
        raw = raw.get("statMap", raw)
        if not isinstance(raw, dict):
            return {}
        items = raw.items()
    elif isinstance(raw, list):
        items = ((item.get("valueGuid") or item.get("statGuid"), item.get("value"))
                 for item in raw if isinstance(item, dict))
    else:
        return {}
    result = {}
    for key, value in items:
        if isinstance(value, dict):
            value = value.get("value")
        n = number(value)
        if key is not None and n is not None:
            result[str(key)] = n
    return result


def parse_count_info(payload):
    if not isinstance(payload, dict) or payload.get("code", 0) != 0:
        return {}
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return {}
    result = {}
    for queue, key in (("presets", "presetsHeroUseSummaryList"), ("open", "openHeroUseSummaryList"), ("v6", "v6HeroUseSummaryList")):
        heroes = {}
        for item in data.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            hero = str(item.get("heroGuid") or "")
            samples = int(number(item.get("matchSum")) or 0)
            if not hero or samples < 5:
                continue
            per10, average = stat_values(item.get("statPerTenMinCount")), stat_values(item.get("statAveCount"))
            # Preserve BOTH units: per-game averages are never divided by a guessed duration.
            units = {}
            for unit, raw in (("per10", per10), ("per_game", average)):
                core = {}
                for name, value in raw.items():
                    normalized = CORE_GUIDS.get(name, ALIASES.get(name, name))
                    if normalized in set(CORE_GUIDS.values()):
                        core[normalized] = value
                units[unit] = {"core": core, "stats": raw}
            if per10 or average:
                heroes[hero] = {"sample_count":samples, "units":units}
        if heroes:
            result[queue] = heroes
    return result


def queue_for_match(match):
    raw = str(match.get("gameMode") or match.get("_seasonSummaryMode") or "").lower()
    if "open" in raw:
        return "open"
    if "v6" in raw or "6v6" in raw:
        return "v6"
    if "preset" in raw or raw in {"quickplay", "competitive"}:
        return "presets"
    return None


def hero_baseline(parsed, match, hero):
    queue = queue_for_match(match)
    if queue:
        return (parsed.get(queue) or {}).get(str(hero))
    # Broad sport/leisure tags don't identify the queue. Only use an unambiguous response.
    if len(parsed) == 1:
        return next(iter(parsed.values())).get(str(hero))
    return None
