"""Preserve the mini-program's labels, units and missing-value semantics."""
from __future__ import annotations

import math

AXES = ("消灭", "助攻", "存活", "伤害", "治疗", "协防")


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip().removesuffix("%"))
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def collect_metrics(hero):
    result, seen = [], set()
    for group, field in (("概况", "simple_summary"), ("通用数据", "summary"),
                         ("英雄特色", "hero_specific_summary")):
        for item in rows(hero.get(field)):
            label = str(item.get("item_name") or "").strip()
            if not label:
                continue
            raw = item.get("item_value")
            text = str(raw).strip() if raw is not None else "—"
            unit = str(item.get("item_unit") or "").strip()
            if text.endswith("%") and not unit:
                unit = "%"
            if label == "胜率" and not unit:
                unit = "%"
            if label == "游戏时间" and not unit:
                unit = "小时"
            key = (label, unit)
            if key in seen:
                continue
            seen.add(key)
            numeric = number(raw)
            direction = 0
            if label in {"胜率", "KDA", "命中率", "暴击命中率"}:
                direction = 1
            elif any(prefix in label for prefix in ("每10分钟", "每十分钟", "场均", "平均")):
                if "死亡" in label:
                    direction = -1
                elif any(word in label for word in ("消灭", "助攻", "伤害", "治疗", "协防")):
                    direction = 1
            result.append({"key": label + "|" + unit, "label": label, "unit": unit,
                           "text": text, "value": numeric, "group": group,
                           "comment": str(item.get("item_comment") or ""), "direction": direction})
    return result


def display(metric):
    if not metric:
        return "—"
    text, unit = metric["text"], metric["unit"]
    if text in {"", "—", "--"}:
        return "—"
    return text if not unit or text.endswith(unit) else f"{text} {unit}"


def paired_metrics(left, right):
    sides = [{m["key"]: m for m in (hero or {}).get("metrics", [])} for hero in (left, right)]
    keys = dict.fromkeys([*sides[0], *sides[1]])
    return [(sides[0].get(key), sides[1].get(key)) for key in keys]


def winner(left, right):
    if not left or not right or left["key"] != right["key"]:
        return None
    a, b = left.get("value"), right.get("value")
    direction = left.get("direction", 0)
    if a is None or b is None or not direction or direction != right.get("direction") or a == b:
        return None
    return 0 if (a - b) * direction > 0 else 1


def radar_dimensions(hero):
    chart = hero.get("hexagon_chart")
    if not isinstance(chart, dict):
        return {}
    return {str(d.get("title")): {k: number(d.get(k)) for k in ("value", "min", "max")}
            for d in rows(chart.get("dimensions")) if d.get("title") in AXES}


def compare_radar(left, right):
    sources = [(hero or {}).get("radar", {}) for hero in (left, right)]
    result = []
    for label in AXES:
        pair = [source.get(label, {}) for source in sources]
        valid = [d for d in pair if d.get("min") is not None and d.get("max") is not None
                 and d["max"] > d["min"]]
        # Both players use the same per-axis domain; never normalize them independently.
        low = min((d["min"] for d in valid), default=None)
        high = max((d["max"] for d in valid), default=None)
        values = [d.get("value") for d in pair]
        normalized = [None if v is None or low is None else max(0., min(1., (v-low)/(high-low)))
                      for v in values]
        result.append({"label": label, "values": values, "min": low, "max": high,
                       "normalized": normalized})
    return result


def hero_hours(hero):
    for stat in rows(hero.get("simple_summary")):
        if stat.get("item_name") == "游戏时间":
            return max(0, number(stat.get("item_value")) or 0)
    return 0
