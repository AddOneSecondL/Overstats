"""Deterministic, sample-aware awards. Scores describe visible statistics only."""
from math import isfinite
from statistics import median

METRICS = {
    "finalHit": ("最后一击", 1), "heroDamage": ("伤害", 1),
    "death": ("死亡", -1), "cure": ("治疗", 1),
    "resistDamage": ("阻挡", 1), "assist": ("助攻", 1),
}
WEIGHTS = {
    "Damage": {"finalHit": .35, "heroDamage": .30, "death": .25, "assist": .10},
    "Tank": {"finalHit": .20, "heroDamage": .20, "death": .30, "resistDamage": .20, "assist": .10},
    "Support": {"finalHit": .10, "heroDamage": .10, "death": .25, "cure": .40, "assist": .15},
}

def rates(player, seconds):
    if seconds < 180:
        return {}
    result = {}
    for key in METRICS:
        raw = player.get(key)
        if raw is None and key == "finalHit":
            raw = player.get("finalBlows")
        try:
            value = float(raw)
        except (ValueError, TypeError):
            continue
        if isfinite(value) and value >= 0:
            result[key] = value * 600 / seconds
    return result


def compare(record, references, minimum):
    """Smoothed empirical percentile; ties are neutral, missing values excluded."""
    weighted, mass, evidence = 0., 0., []
    weights = WEIGHTS.get(record["role"], {})
    for key, weight in weights.items():
        if key not in record["rates"]:
            continue
        values = [r["rates"][key] for r in references if key in r["rates"]]
        if len(values) < minimum:
            continue
        current = record["rates"][key]
        direction = METRICS[key][1]
        wins = sum(direction * (current - v) > 0 for v in values)
        ties = sum(current == v for v in values)
        percentile = 100 * (wins + .5 * ties + 2) / (len(values) + 4)
        weighted += percentile * weight
        mass += weight
        evidence.append({"key": key, "value": current, "baseline": median(values), "score": percentile})
    if len(evidence) < 3 or "death" not in {e["key"] for e in evidence} or mass < .6:
        return None
    return weighted / mass, sorted(evidence, key=lambda e: e["score"], reverse=True)


def grade(score):
    if score is None:
        return "—"
    return "S" if score >= 65 else "A" if score >= 57 else "B" if score >= 45 else "C" if score >= 35 else "D"


def compare_season(record):
    baseline = record.get("season_baseline")
    if not baseline or not record.get("single_hero"):
        return None
    weights = WEIGHTS.get(record["role"], {})
    for unit in ("per10", "per_game"):
        values = baseline["units"][unit]["core"]
        evidence, weighted, mass = [], 0., 0.
        for key, weight in weights.items():
            if key not in record["rates"] or key not in values:
                continue
            reference = values[key]
            current = record["rates"][key] * (record["seconds"] / 600 if unit == "per_game" else 1)
            if reference <= 0:
                continue
            change = METRICS[key][1] * (current - reference) / reference
            score = max(10, min(90, 50 + 40 * change))
            weighted += score * weight
            mass += weight
            evidence.append({"key":key, "value":current, "baseline":reference, "score":score, "unit":unit})
        if len(evidence) >= 3 and any(e["key"] == "death" for e in evidence) and mass >= .6:
            score = weighted / mass
            # Hero-specific improvements contribute, capped so one skill cannot dominate.
            features = record.get("feature_evidence", [])[:3]
            if features:
                feature_score = sum(e["score"] for e in features)/len(features)
                score = .8 * score + .2 * feature_score
            return score, sorted(evidence, key=lambda e:e["score"], reverse=True)
    return None


def record_key(record):
    return str(record["match"].get("matchId") or record["match"].get("beginTs") or "")


def select_awards(records, history):
    best, breakthrough, session_progress = None, None, None
    evaluated = []
    for record in records:
        references, source = record["peers"], "lobby"
        result = compare(record, references, 1)
        if result is None:
            references, source, result = [], "season", compare_season(record)
        if result is None:
            references = [r for r in records if r is not record and r["hero_guid"] == record["hero_guid"]
                          and r["mode"] == record["mode"] and r.get("single_hero") and record.get("single_hero")]
            source, result = "session", compare(record, references, 2)
        if result:
            performance, evidence = result
            score = .95 * performance + .05 * {1: 100, 0: 50}.get(record["result"], 0)
            candidate = dict(record, score=score, evidence=evidence, sample_count=(record.get("season_baseline") or {}).get("sample_count",0) if source=="season" else len(references), source=source)
            evaluated.append(candidate)
            priority = {"lobby": 2, "season": 1, "session": 0}
            if best is None or (priority[source], score) > (priority[best["source"]], best["score"]):
                best = candidate
        if not record.get("single_hero"):
            continue
        refs = [r for r in history if r.get("single_hero") and r["hero_guid"] == record["hero_guid"]
                and r["mode"] == record["mode"] and r["timestamp"] < record["period_start"]]
        result = compare(record, refs, 5)
        if result and result[0] > 55:
            score, evidence = result
            candidate = dict(record, score=score, evidence=evidence, sample_count=len(refs), source="history")
            if breakthrough is None or score > breakthrough["score"]:
                breakthrough = candidate
        if result is None:
            season_result = compare_season(record)
            if season_result and season_result[0] > 55:
                score, evidence = season_result
                candidate = dict(record, score=score, evidence=evidence, sample_count=record["season_baseline"]["sample_count"], source="season")
                if breakthrough is None or score > breakthrough["score"]:
                    breakthrough = candidate
            refs = [r for r in records if r.get("single_hero") and r["hero_guid"] == record["hero_guid"]
                    and r["mode"] == record["mode"] and r["timestamp"] < record["timestamp"]]
            local_result = compare(record, refs, 3)
            if local_result and local_result[0] > 55:
                score, evidence = local_result
                candidate = dict(record, score=score, evidence=evidence, sample_count=len(refs), source="session_progress")
                if session_progress is None or score > session_progress["score"]:
                    session_progress = candidate
    # Never pretend a session standout is a historical breakthrough.
    fallback = dict(best, source="spotlight", evaluation_source=best["source"]) if best else None
    return {"best": best, "breakthrough": breakthrough or session_progress or fallback,
            "evaluated": evaluated, "records": records}
