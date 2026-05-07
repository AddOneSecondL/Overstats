from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client


@dataclass(frozen=True)
class BnetSearchResult:
    query: str
    payload: Dict[str, Any]

    @property
    def data(self) -> Dict[str, Any]:
        data = self.payload.get("data")
        return data if isinstance(data, dict) else {}

    @property
    def customer_token(self) -> str:
        return str(self.data.get("customerToken") or "").strip()

    @property
    def bnet_id(self) -> str:
        return str(self.data.get("bnetId") or "").strip()

    @property
    def full_id(self) -> str:
        return str(self.data.get("name") or self.query).strip()

    @property
    def icon_url(self) -> str:
        return str(self.data.get("icon") or "").strip()


def normalize_bnet_id(bnet_id: str) -> str:
    return str(bnet_id or "").replace("＃", "#").strip()


class BnetSearchRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def search(self, bnet_id: str) -> BnetSearchResult:
        query = normalize_bnet_id(bnet_id)
        payload = await self.api_client.search_bnet_account(query)
        return BnetSearchResult(query=query, payload=payload)
