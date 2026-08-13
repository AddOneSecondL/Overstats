from __future__ import annotations

from typing import Any, Mapping, Optional


# Dashen keeps the original rank ids for the eight existing ranks and uses 8
# for Emerald.  The id therefore is not the display/sort order.
RANK_ORDER = (
    "Bronze",
    "Silver",
    "Gold",
    "Platinum",
    "Emerald",
    "Diamond",
    "Master",
    "Grandmaster",
    "Champion",
)

RANK_LABELS_CN = {
    "Bronze": "青铜",
    "Silver": "白银",
    "Gold": "黄金",
    "Platinum": "白金",
    "Emerald": "翡翠",
    "Diamond": "钻石",
    "Master": "大师",
    "Grandmaster": "宗师",
    "Champion": "英杰",
    "Unranked": "未定级",
}

RAW_RANK_ID_TO_NAME = {
    0: "Bronze",
    1: "Silver",
    2: "Gold",
    3: "Platinum",
    8: "Emerald",
    4: "Diamond",
    5: "Master",
    6: "Grandmaster",
    7: "Champion",
}

# Continuous scores are used by strength charts and leaderboards.  Five
# divisions occupy 100 points each; Emerald is inserted at 2500 without
# changing the existing Diamond-and-above boundaries.
RAW_RANK_ID_TO_STRENGTH_BASE = {
    0: 500,
    1: 1000,
    2: 1500,
    3: 2000,
    8: 2500,
    4: 3000,
    5: 3500,
    6: 4000,
    7: 4500,
}

RANK_STRENGTH_SPANS = (
    (500, 1000, "Bronze"),
    (1000, 1500, "Silver"),
    (1500, 2000, "Gold"),
    (2000, 2500, "Platinum"),
    (2500, 3000, "Emerald"),
    (3000, 3500, "Diamond"),
    (3500, 4000, "Master"),
    (4000, 4500, "Grandmaster"),
    (4500, 5000, "Champion"),
)

_RANK_NAME_TO_STRENGTH_BASE = {
    RAW_RANK_ID_TO_NAME[raw_rank_id]: base
    for raw_rank_id, base in RAW_RANK_ID_TO_STRENGTH_BASE.items()
}

# Local assets retain their original ids.  Emerald temporarily uses asset 9,
# which is a copy of the Platinum artwork.
RANK_NAME_TO_ICON_LEVEL = {
    "Bronze": 1,
    "Silver": 2,
    "Gold": 3,
    "Platinum": 4,
    "Emerald": 9,
    "Diamond": 5,
    "Master": 6,
    "Grandmaster": 7,
    "Champion": 8,
}

_RANK_NAME_ALIASES = {
    "bronze": "Bronze",
    "青铜": "Bronze",
    "silver": "Silver",
    "白银": "Silver",
    "gold": "Gold",
    "黄金": "Gold",
    "platinum": "Platinum",
    "platium": "Platinum",
    "白金": "Platinum",
    "铂金": "Platinum",
    "emerald": "Emerald",
    "翡翠": "Emerald",
    "diamond": "Diamond",
    "钻石": "Diamond",
    "master": "Master",
    "大师": "Master",
    "grandmaster": "Grandmaster",
    "宗师": "Grandmaster",
    "gm": "Grandmaster",
    "champion": "Champion",
    "英杰": "Champion",
    "冠军": "Champion",
}


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def canonical_rank_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _RANK_NAME_ALIASES.get(text.casefold(), text)


def rank_name_cn(value: Any) -> str:
    canonical = canonical_rank_name(value)
    return RANK_LABELS_CN.get(canonical, str(value or "").strip())


def get_rank_score(rank_info: Mapping[str, Any] | None, default: Any = 0) -> Any:
    if not isinstance(rank_info, Mapping):
        return default
    for key in ("rankScore", "rank_score", "score"):
        if key in rank_info and rank_info.get(key) not in (None, ""):
            return rank_info.get(key)
    return default


def get_rank_sub_tier(rank_info: Mapping[str, Any] | None, default: Any = "") -> Any:
    if not isinstance(rank_info, Mapping):
        return default
    for key in ("rankSubTier", "rank_sub_tier"):
        if key in rank_info and rank_info.get(key) not in (None, ""):
            return rank_info.get(key)
    return default


def get_rank_name(rank_info: Mapping[str, Any] | None, default: Any = "") -> Any:
    if not isinstance(rank_info, Mapping):
        return default
    for key in ("rankName", "rank_name"):
        if key in rank_info and rank_info.get(key) not in (None, ""):
            return rank_info.get(key)
    return default


def raw_rank_score_parts(value: Any) -> Optional[tuple[int, int]]:
    """Return ``(raw rank id, division)`` for Dashen's compact rankScore."""
    score = _safe_int(value)
    if score is None or score <= 0:
        return None
    raw_rank_id, suffix = divmod(score, 100)
    if raw_rank_id not in RAW_RANK_ID_TO_NAME or not 95 <= suffix <= 99:
        return None
    return raw_rank_id, 100 - suffix


def raw_rank_score_to_strength(value: Any) -> Optional[int]:
    parts = raw_rank_score_parts(value)
    if parts is None:
        return None
    raw_rank_id, division = parts
    return RAW_RANK_ID_TO_STRENGTH_BASE[raw_rank_id] + (5 - division) * 100


def rank_info_score_to_strength(rank_info: Mapping[str, Any] | None) -> Optional[int]:
    """Normalize rankInfo score, accepting compact raw or continuous scores."""
    score = _safe_int(get_rank_score(rank_info, None))
    if score is None or score <= 0:
        return None
    compact_score = raw_rank_score_to_strength(score)
    if compact_score is not None:
        return compact_score
    return score


def normalize_raw_rank_bucket(value: Any) -> Optional[int]:
    """Normalize a compact rankScore (or an existing raw id) for DB buckets."""
    score = _safe_int(value)
    if score is None or score < 0:
        return None
    if score in RAW_RANK_ID_TO_NAME:
        return score
    parts = raw_rank_score_parts(score)
    if parts is not None:
        return parts[0]
    return None


def raw_rank_score_to_icon_level(value: Any) -> int:
    parts = raw_rank_score_parts(value)
    if parts is None:
        return 0
    return RANK_NAME_TO_ICON_LEVEL[RAW_RANK_ID_TO_NAME[parts[0]]]


def strength_score_rank_name(value: Any) -> str:
    score = _safe_int(value)
    if score is None or score < RANK_STRENGTH_SPANS[0][0]:
        return "Unranked"
    for lower, upper, name in RANK_STRENGTH_SPANS:
        if lower <= score < upper:
            return name
    return "Champion"


def strength_score_to_icon_level(value: Any) -> int:
    name = strength_score_rank_name(value)
    return RANK_NAME_TO_ICON_LEVEL.get(name, 0)


def strength_score_to_rank(value: Any, *, chinese: bool = False) -> str:
    score = _safe_int(value)
    name = strength_score_rank_name(score)
    if name == "Unranked" or score is None:
        return RANK_LABELS_CN["Unranked"] if chinese else "Unranked"

    lower = _RANK_NAME_TO_STRENGTH_BASE[name]
    bucket_index = max(0, min(4, (score - lower) // 100))
    division = 5 - int(bucket_index)
    label = RANK_LABELS_CN[name] if chinese else name
    separator = "" if chinese else " "
    return f"{label}{separator}{division}"


__all__ = [
    "RANK_LABELS_CN",
    "RANK_NAME_TO_ICON_LEVEL",
    "RANK_ORDER",
    "RANK_STRENGTH_SPANS",
    "RAW_RANK_ID_TO_NAME",
    "RAW_RANK_ID_TO_STRENGTH_BASE",
    "canonical_rank_name",
    "get_rank_name",
    "get_rank_score",
    "get_rank_sub_tier",
    "normalize_raw_rank_bucket",
    "rank_info_score_to_strength",
    "rank_name_cn",
    "raw_rank_score_parts",
    "raw_rank_score_to_icon_level",
    "raw_rank_score_to_strength",
    "strength_score_rank_name",
    "strength_score_to_icon_level",
    "strength_score_to_rank",
]
