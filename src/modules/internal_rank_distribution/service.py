from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence

try:
    from overstats.src.constants.ranks import RANK_ORDER, canonical_rank_name
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.constants.ranks import RANK_ORDER, canonical_rank_name
    from src.modules.errors import ModuleError

from .render import RenderedImage, render_rank_distribution
from .requests import RankDistributionQuery


RANK_DISTRIBUTION_ORDER = tuple(RANK_ORDER) + ("Unranked",)


@dataclass(frozen=True)
class RankDistributionRow:
    rank_bucket: str
    rank_division: int
    sample_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "rank_bucket": self.rank_bucket,
            "rank_division": self.rank_division,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class RankDistributionOutput:
    season: int
    total_count: int
    rows: tuple[RankDistributionRow, ...]
    mode_summary: Mapping[str, int]
    image: RenderedImage | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": True,
            "season": self.season,
            "total_count": self.total_count,
            "rows": [row.to_dict() for row in self.rows],
            "mode_summary": dict(self.mode_summary),
        }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_rows(rows: Sequence[Mapping[str, Any]] | None) -> tuple[RankDistributionRow, ...]:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for raw_row in rows or ():
        if not isinstance(raw_row, Mapping):
            continue
        rank_bucket = canonical_rank_name(raw_row.get("rank_bucket") or raw_row.get("rankBucket"))
        if not rank_bucket:
            rank_bucket = "Unranked"
        if rank_bucket not in RANK_DISTRIBUTION_ORDER:
            # Keep the chart's fixed rank order stable. Unexpected labels are
            # treated as unranked rather than disappearing from the total.
            rank_bucket = "Unranked"
        division = _safe_int(raw_row.get("rank_division", raw_row.get("rankDivision", 0)))
        if rank_bucket == "Unranked":
            division = 0
        elif division not in {1, 2, 3, 4, 5}:
            division = 0
        count = _safe_int(raw_row.get("sample_count", raw_row.get("sampleCount", 0)))
        if count <= 0:
            continue
        counts[(rank_bucket, division)] += count

    known_order = {name: index for index, name in enumerate(RANK_DISTRIBUTION_ORDER)}
    ordered_keys = sorted(
        counts,
        key=lambda key: (known_order.get(key[0], len(known_order)), key[1], key[0]),
    )
    return tuple(
        RankDistributionRow(
            rank_bucket=key[0],
            rank_division=key[1],
            sample_count=counts[key],
        )
        for key in ordered_keys
    )


def _normalize_mode_summary(raw: Mapping[str, Any] | None) -> dict[str, int]:
    raw = raw or {}

    def value(*keys: str) -> int:
        for key in keys:
            if key in raw:
                return max(0, _safe_int(raw.get(key)))
        return 0

    return {
        "pure_quick_player_count": value(
            "pure_quick_player_count", "pureQuickPlayerCount", "quick_count", "quickCount"
        ),
        "competitive_player_count": value(
            "competitive_player_count", "competitivePlayerCount", "competitive_count", "competitiveCount"
        ),
        "unknown_player_count": value(
            "unknown_player_count", "unknownPlayerCount", "unknown_count", "unknownCount"
        ),
        "total_player_count": value(
            "total_player_count", "totalPlayerCount", "total_count", "totalCount"
        ),
    }


class InternalRankDistributionModule:
    """Private renderer endpoint; it is intentionally not registered in web UI."""

    async def query_rank_distribution(
        self,
        query: RankDistributionQuery,
        *,
        render: bool = False,
    ) -> RankDistributionOutput:
        try:
            season = _safe_int(query.season)
            rows = _normalize_rows(query.rows)
            mode_summary = _normalize_mode_summary(query.mode_summary)
        except Exception as exc:
            raise ModuleError(
                error="invalid_rank_distribution",
                message="Invalid rank distribution payload.",
                status_code=400,
            ) from exc

        total_count = sum(row.sample_count for row in rows)
        if total_count <= 0:
            raise ModuleError(
                error="empty_rank_distribution",
                message="No rank distribution data was supplied.",
                status_code=404,
            )

        image = None
        if render:
            image = render_rank_distribution(
                season=season,
                total_count=total_count,
                rows=[row.to_dict() for row in rows],
                mode_summary=mode_summary,
            )
        return RankDistributionOutput(
            season=season,
            total_count=total_count,
            rows=rows,
            mode_summary=mode_summary,
            image=image,
        )


internal_rank_distribution_module = InternalRankDistributionModule()
