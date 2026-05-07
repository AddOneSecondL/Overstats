from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client


ROLE_LABELS = {
    "tank": "重装",
    "dps": "输出",
    "healer": "支援",
    "open": "开放",
}
ROLE_ALIASES = {
    "tank": "tank",
    "重装": "tank",
    "坦克": "tank",
    "t": "tank",
    "dps": "dps",
    "damage": "dps",
    "输出": "dps",
    "c": "dps",
    "healer": "healer",
    "support": "healer",
    "支援": "healer",
    "辅助": "healer",
    "奶": "healer",
    "h": "healer",
    "open": "open",
    "开放": "open",
}
SUPPORTED_ROLES = tuple(ROLE_LABELS.keys())


@dataclass(frozen=True)
class DashenRankLeaderboardQuery:
    province: str = ""
    role: str = ""


def normalize_role(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("role is required.")
    resolved = ROLE_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported role: {value!r}")
    return resolved


class DashenRankLeaderboardRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def query_province_rank(self, province: str, role: str) -> Dict[str, Any]:
        payload = await self.api_client.query_province_rank(str(province), str(role))
        if not isinstance(payload, dict):
            raise TypeError("Dashen province rank payload must be a mapping.")
        code = int(payload.get("code") or 0)
        if code != 0:
            raise RuntimeError(
                "Dashen province rank request failed: "
                f"province={province} role={role} code={code} msg={payload.get('msg') or payload.get('message')}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TypeError("Dashen province rank data must be an object.")
        return data


__all__ = [
    "DashenRankLeaderboardQuery",
    "DashenRankLeaderboardRequests",
    "ROLE_LABELS",
    "SUPPORTED_ROLES",
    "normalize_role",
]
