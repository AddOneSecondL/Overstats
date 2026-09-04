from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RankDistributionQuery:
    """Aggregated current-season rank rows and unique-player mode totals."""

    season: Any = 0
    total_count: Any = 0
    rows: Sequence[Mapping[str, Any]] = ()
    mode_summary: Mapping[str, Any] = field(default_factory=dict)
