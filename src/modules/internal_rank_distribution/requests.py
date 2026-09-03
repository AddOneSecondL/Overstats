from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RankDistributionQuery:
    """Aggregated current-season rank rows supplied by nb2_overstats_core."""

    season: Any = 0
    total_count: Any = 0
    rows: Sequence[Mapping[str, Any]] = ()
