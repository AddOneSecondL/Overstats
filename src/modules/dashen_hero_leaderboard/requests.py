from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client


MODE_LABELS = {
    "preset": "预设",
    "open": "开放",
}
MODE_SOURCE_MAP = {
    "preset": "SportPreset",
    "open": "SportOpen",
}
MODE_ALIASES = {
    "preset": "preset",
    "预设": "preset",
    "sportpreset": "preset",
    "open": "open",
    "开放": "open",
    "sportopen": "open",
}
SUPPORTED_MODES = tuple(MODE_LABELS.keys())


@dataclass(frozen=True)
class DashenHeroLeaderboardQuery:
    province: str = ""
    hero: str = ""
    mode: str = "preset"


def normalize_mode(value: Any) -> str:
    normalized = str(value or "preset").strip().lower()
    if not normalized:
        return "preset"
    resolved = MODE_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported mode: {value!r}")
    return resolved


class DashenHeroLeaderboardRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def query_hero_leaderboard(self, province: str, mode: str, hero_guid: str) -> Dict[str, Any]:
        payload = await self.api_client.get_hero_billboard(str(province), MODE_SOURCE_MAP[str(mode)], str(hero_guid))
        if not isinstance(payload, dict):
            raise TypeError("Dashen hero leaderboard payload must be a mapping.")
        code = int(payload.get("code") or 0)
        if code != 0:
            raise RuntimeError(
                "Dashen hero leaderboard request failed: "
                f"province={province} mode={mode} hero_guid={hero_guid} "
                f"code={code} msg={payload.get('msg') or payload.get('message')}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TypeError("Dashen hero leaderboard data must be an object.")
        return data


__all__ = [
    "DashenHeroLeaderboardQuery",
    "DashenHeroLeaderboardRequests",
    "MODE_LABELS",
    "MODE_SOURCE_MAP",
    "SUPPORTED_MODES",
    "normalize_mode",
]
