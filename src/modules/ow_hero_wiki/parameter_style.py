"""Editable display bands, not balance ratings or cross-hero rankings.

Each rule has three cut points in the displayed unit and an optional inverse
direction. Only simple scalars/ranges are rated; conditional formulas are not.
"""
from bisect import bisect_right
import re

from .stat_icons import LABEL_KEYS

TIERS = ((144, 174, 207), (101, 197, 237), (126, 220, 172), (249, 201, 106))
NEUTRAL = (239, 244, 252)
RULES = {
    "damage": ((25, 75, 150), False), "heal": ((25, 75, 150), False),
    "dps": ((75, 150, 250), False), "hps": ((30, 60, 100), False),
    "cooldown": ((3, 6, 12), True), "reload_time": ((1, 1.5, 2.5), True),
    "cast_time": ((.25, .5, 1), True), "duration": ((1, 4, 8), False),
    "ult_req": ((1200, 1800, 2400), True), "charges": ((2, 3, 4), False),
    "range": ((5, 15, 30), False), "radius": ((2, 5, 10), False),
    "width": ((1, 3, 6), False), "height": ((1, 3, 6), False),
    "fire_rate": ((2, 5, 10), False), "ammo": ((10, 30, 60), False),
    "ammo_drain": ((2, 3, 5), True), "pellets": ((3, 8, 15), False),
    "pspeed": ((20, 50, 100), False), "pradius": ((.1, .25, .5), False),
    "spread": ((1, 3, 6), True), "mspeed": ((5.5, 8, 12), False),
    "view_angle": ((45, 90, 180), False), "healing_mod": ((25, 50, 100), False),
    "health": ((100, 250, 500), False), "armor": ((50, 150, 250), False),
    "overhealth": ((25, 75, 150), False), "barrier_health": ((300, 700, 1200), False),
    "headshot_mod": ((1.5, 2, 3), False), "kbspeed": ((5, 10, 20), False),
    "damage_amp": ((20, 40, 75), False), "damage_red": ((20, 40, 75), False),
    "mspeed_buff": ((20, 40, 75), False), "mspeed_pen": ((20, 40, 75), True),
    "mspeed_slow": ((20, 40, 75), False), "kbmod": ((20, 40, 75), False),
}
PERCENT_KEYS = {"damage_amp", "damage_red", "mspeed_buff", "mspeed_pen", "mspeed_slow", "kbmod", "healing_mod"}
VALUE = re.compile(r"^\s*(\d+(?:\.\d+)?)(?:\s*[-–—~至]\s*(\d+(?:\.\d+)?))?\s*"
                   r"(秒|米|点|度|发|次|倍|%|s|m|seconds?|meters?|points?|degrees?|"
                   r"m\s*/\s*s|米\s*/\s*秒|shots\s*/\s*s|发\s*/\s*秒)?\s*$", re.I)


def numeric_colors(key, value, label=""):
    key = key or LABEL_KEYS.get(label, "")
    rule, match = RULES.get(key), VALUE.fullmatch(value)
    if not rule or not match or (key in PERCENT_KEYS and match.group(3) != "%"):
        return []
    unit = (match.group(3) or "").lower().replace(" ", "")
    allowed = {"", "点", "point", "points"}
    if key in PERCENT_KEYS:
        allowed = {"%"}
    elif key in {"cooldown", "reload_time", "cast_time", "duration"}:
        allowed = {"", "秒", "s", "second", "seconds"}
    elif key in {"range", "radius", "width", "height", "pradius"}:
        allowed = {"", "米", "m", "meter", "meters"}
    elif key in {"pspeed", "mspeed", "kbspeed"}:
        allowed = {"", "m/s", "米/秒"}
    elif key == "fire_rate":
        allowed = {"", "shots/s", "发/秒"}
    elif key in {"ammo", "ammo_drain", "pellets", "charges"}:
        allowed = {"", "次", "发"}
    elif key == "headshot_mod":
        allowed = {"", "倍"}
    elif key in {"spread", "view_angle"}:
        allowed = {"", "度", "degree", "degrees"}
    if unit not in allowed:
        return []
    cuts, inverse = rule
    result = []
    for raw in match.group(1, 2):
        if raw is None:
            continue
        tier = bisect_right(cuts, float(raw))
        result.append(TIERS[3-tier if inverse else tier])
    return result
