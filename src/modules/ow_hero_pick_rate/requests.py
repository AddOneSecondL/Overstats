from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VIEW_RANKING = "ranking"
VIEW_HISTORY = "history"
SUPPORTED_VIEWS = (VIEW_RANKING, VIEW_HISTORY)

GAME_MODE_QUICK = "quick"
GAME_MODE_COMPETITIVE = "competitive"
SUPPORTED_GAME_MODES = (GAME_MODE_QUICK, GAME_MODE_COMPETITIVE)
GAME_MODE_SOURCE_MAP = {
    GAME_MODE_QUICK: "kuaisu",
    GAME_MODE_COMPETITIVE: "jingji",
}

MMR_ALL = "all"
SUPPORTED_MMRS = (
    MMR_ALL,
    "Bronze",
    "Silver",
    "Gold",
    "Platinum",
    "Diamond",
    "Master",
    "Grandmaster",
    "Champion",
)
MMR_SOURCE_MAP = {
    MMR_ALL: "-127",
    "Bronze": "Bronze",
    "Silver": "Silver",
    "Gold": "Gold",
    "Platinum": "Platinum",
    "Diamond": "Diamond",
    "Master": "Master",
    "Grandmaster": "Grandmaster",
    "Champion": "Champion",
}

HISTORY_LIMIT_DEFAULT = 20


@dataclass(frozen=True)
class OWHeroPickRateQuery:
    view: str = VIEW_RANKING
    game_mode: str = GAME_MODE_QUICK
    mmr: str = MMR_ALL
    hero: str = ""
    history_limit: int = HISTORY_LIMIT_DEFAULT


def normalize_view(value: Any) -> str:
    normalized = str(value or VIEW_RANKING).strip().lower()
    if normalized in SUPPORTED_VIEWS:
        return normalized
    raise ValueError(f"Unsupported view: {value!r}")


def normalize_game_mode(value: Any) -> str:
    normalized = str(value or GAME_MODE_QUICK).strip().lower()
    if normalized in SUPPORTED_GAME_MODES:
        return normalized
    raise ValueError(f"Unsupported game_mode: {value!r}")


def normalize_mmr(value: Any) -> str:
    normalized = str(value or MMR_ALL).strip()
    if not normalized:
        return MMR_ALL
    for candidate in SUPPORTED_MMRS:
        if normalized == candidate:
            return candidate
        if normalized.lower() == str(candidate).lower():
            return candidate
    raise ValueError(f"Unsupported mmr: {value!r}")


def normalize_history_limit(value: Any) -> int:
    if value in (None, ""):
        return HISTORY_LIMIT_DEFAULT
    limit = int(value)
    return max(1, limit)
