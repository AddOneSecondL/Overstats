from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

try:
    from overstats.src.client.apiclient import DashenAPIClient
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient

from .render import RenderedImage, render_bnet_search_result
from .requests import BnetSearchRequests, BnetSearchResult


@dataclass(frozen=True)
class BnetSearchOutput:
    result: BnetSearchResult
    image: Optional[RenderedImage] = None
    risk_status: Optional[dict[str, Any]] = None


class BnetSearchModule:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.requests = BnetSearchRequests(api_client)

    async def search(self, bnet_id: str, *, render: bool = False) -> BnetSearchOutput:
        result = await self.requests.search(bnet_id)
        risk_status = None
        if render and result.customer_token:
            try:
                card_payload = await self.requests.api_client.query_card(result.customer_token)
            except Exception:
                card_payload = {}
            card_data = card_payload.get("data") if isinstance(card_payload, dict) else None
            if isinstance(card_data, dict) and isinstance(card_data.get("riskStatus"), dict):
                risk_status = dict(card_data["riskStatus"])
        image = render_bnet_search_result(result, risk_status=risk_status) if render else None
        return BnetSearchOutput(result=result, risk_status=risk_status, image=image)

    async def resolve_customer_token(self, bnet_id: str) -> str:
        output = await self.search(bnet_id, render=False)
        return output.result.customer_token


bnet_search_module = BnetSearchModule()
