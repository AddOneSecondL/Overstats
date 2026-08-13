from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.src.constants.ranks import (
        RANK_LABELS_CN,
        RANK_NAME_TO_ICON_LEVEL,
        rank_info_score_to_strength,
        strength_score_to_icon_level,
        strength_score_to_rank,
    )
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.constants.ranks import (
        RANK_LABELS_CN,
        RANK_NAME_TO_ICON_LEVEL,
        rank_info_score_to_strength,
        strength_score_to_icon_level,
        strength_score_to_rank,
    )
    from src.modules.errors import ModuleError

from .render import RenderedImage, render_rank_leaderboard
from .requests import DashenRankLeaderboardQuery, DashenRankLeaderboardRequests, ROLE_LABELS, normalize_role


UNRANKED_LABEL = "未定级"
RANK_LABEL_ICON_LEVELS = {
    RANK_LABELS_CN[rank_name]: icon_level
    for rank_name, icon_level in RANK_NAME_TO_ICON_LEVEL.items()
}
RANK_LABEL_ICON_LEVELS["铂金"] = RANK_NAME_TO_ICON_LEVEL["Platinum"]


@dataclass(frozen=True)
class DashenRankLeaderboardEntry:
    rank_num: int
    user_name: str
    match_sum: int
    win_rate: float
    wins: int
    rank_score: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank_num": int(self.rank_num),
            "user_name": str(self.user_name),
            "match_sum": int(self.match_sum),
            "win_rate": float(self.win_rate),
            "wins": int(self.wins),
            "rank_score": int(self.rank_score),
        }


@dataclass(frozen=True)
class DashenRankLeaderboardGroup:
    rank_label: str
    rank_icon_level: int
    count: int
    entries: Sequence[DashenRankLeaderboardEntry]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank_label": str(self.rank_label),
            "rank_icon_level": int(self.rank_icon_level),
            "count": int(self.count),
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True)
class DashenRankLeaderboardOutput:
    province: str
    role: str
    role_label: str
    entry_count: int
    groups: Sequence[DashenRankLeaderboardGroup]
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "province": self.province,
            "role": self.role,
            "role_label": self.role_label,
            "entry_count": int(self.entry_count),
            "groups": [item.to_dict() for item in self.groups],
        }


class DashenRankLeaderboardModule:
    def __init__(self, requests: Optional[DashenRankLeaderboardRequests] = None) -> None:
        self.requests = requests or DashenRankLeaderboardRequests()

    async def query_rank_leaderboard(
        self,
        query: DashenRankLeaderboardQuery,
        *,
        render: bool = False,
    ) -> DashenRankLeaderboardOutput:
        resolved_query = self._normalize_query(query)
        try:
            data = await self.requests.query_province_rank(resolved_query.province, resolved_query.role)
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(
                error="rank_leaderboard_upstream_error",
                message="Failed to fetch Dashen province rank data.",
                status_code=502,
                details={
                    "province": resolved_query.province,
                    "role": resolved_query.role,
                    "exception": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc

        rows = [item for item in list(data.get("rankList") or []) if isinstance(item, dict)]
        if not rows:
            raise ModuleError(
                error="dashen_rank_leaderboard_empty",
                message="No Dashen province rank data found for the requested filters.",
                status_code=404,
                details={
                    "province": resolved_query.province,
                    "role": resolved_query.role,
                },
            )

        entries = sorted(
            (self._to_entry(item) for item in rows),
            key=lambda item: (
                -item.rank_score,
                item.rank_num if item.rank_num > 0 else 999999,
                item.user_name.lower(),
            ),
        )
        groups = self._group_entries(entries)
        output = DashenRankLeaderboardOutput(
            province=resolved_query.province,
            role=resolved_query.role,
            role_label=ROLE_LABELS[resolved_query.role],
            entry_count=len(entries),
            groups=groups,
        )
        if not render:
            return output

        image = render_rank_leaderboard(
            province=output.province,
            role_label=output.role_label,
            entry_count=output.entry_count,
            groups=[item.to_dict() for item in output.groups],
        )
        return DashenRankLeaderboardOutput(
            province=output.province,
            role=output.role,
            role_label=output.role_label,
            entry_count=output.entry_count,
            groups=output.groups,
            image=image,
        )

    def _normalize_query(self, query: DashenRankLeaderboardQuery) -> DashenRankLeaderboardQuery:
        province = str(query.province or "").strip()
        raw_role = str(query.role or "").strip()
        if not province:
            raise ModuleError(
                error="missing_province",
                message="province is required.",
                status_code=400,
                hint='Example: {"province":"北京","role":"tank"}',
            )
        if not raw_role:
            raise ModuleError(
                error="missing_role",
                message="role is required.",
                status_code=400,
                hint='Example: {"province":"北京","role":"tank"}',
            )
        try:
            role = normalize_role(raw_role)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_role",
                message=str(exc),
                status_code=400,
                details={"role": query.role},
            ) from exc
        return DashenRankLeaderboardQuery(province=province, role=role)

    def _to_entry(self, payload: Dict[str, Any]) -> DashenRankLeaderboardEntry:
        rank_info = payload.get("rankInfo") or payload.get("rank_info")
        normalized_rank_score = rank_info_score_to_strength(rank_info) if isinstance(rank_info, dict) else None
        rank_score = normalized_rank_score if normalized_rank_score is not None else 0
        match_sum = self._safe_int(payload.get("matchSum"))
        win_rate = self._safe_float(payload.get("winRate"))
        wins = round(win_rate / 100.0 * match_sum) if match_sum > 0 else 0
        return DashenRankLeaderboardEntry(
            rank_num=self._safe_int(payload.get("rankNum")),
            user_name=str(payload.get("name") or payload.get("userName") or "-"),
            match_sum=match_sum,
            win_rate=win_rate,
            wins=wins,
            rank_score=rank_score,
        )

    def _group_entries(self, entries: Sequence[DashenRankLeaderboardEntry]) -> tuple[DashenRankLeaderboardGroup, ...]:
        groups: List[DashenRankLeaderboardGroup] = []
        current_label: Optional[str] = None
        current_icon_level = 0
        current_entries: List[DashenRankLeaderboardEntry] = []
        for entry in entries:
            rank_label = score_to_rank(entry.rank_score)
            rank_icon_level = rank_icon_level_for_score(entry.rank_score)
            if current_label != rank_label:
                if current_entries:
                    groups.append(
                        DashenRankLeaderboardGroup(
                            rank_label=str(current_label or UNRANKED_LABEL),
                            rank_icon_level=current_icon_level,
                            count=len(current_entries),
                            entries=tuple(current_entries),
                        )
                    )
                current_label = rank_label
                current_icon_level = rank_icon_level
                current_entries = []
            current_entries.append(entry)
        if current_entries:
            groups.append(
                DashenRankLeaderboardGroup(
                    rank_label=str(current_label or UNRANKED_LABEL),
                    rank_icon_level=current_icon_level,
                    count=len(current_entries),
                    entries=tuple(current_entries),
                )
            )
        return tuple(groups)

    def _safe_int(self, value: Any) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


def rank_icon_level_for_score(score: int) -> int:
    return strength_score_to_icon_level(score)


def score_to_rank(score: int) -> str:
    return strength_score_to_rank(score, chinese=True)


dashen_rank_leaderboard_module = DashenRankLeaderboardModule()


__all__ = [
    "DashenRankLeaderboardEntry",
    "DashenRankLeaderboardGroup",
    "DashenRankLeaderboardModule",
    "DashenRankLeaderboardOutput",
    "RANK_LABEL_ICON_LEVELS",
    "UNRANKED_LABEL",
    "dashen_rank_leaderboard_module",
    "rank_icon_level_for_score",
    "score_to_rank",
]
