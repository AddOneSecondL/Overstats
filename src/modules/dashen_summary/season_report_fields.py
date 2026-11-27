"""Normalize optional upstream values without replacing measured zeros."""
import math


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def first_value(*values):
    return next((value for value in values if value is not None and value != ""), None)


def name_text(value):
    name = value.strip() if isinstance(value, str) else ""
    placeholders = {"unknown", "unknown player", "unknown hero", "unknown map", "未知", "未知好友",
                    "未知英雄", "未知地图", "未知威能", "null", "none", "—"}
    return "" if name.casefold() in placeholders else name
