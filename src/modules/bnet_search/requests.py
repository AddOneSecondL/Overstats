from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle
from threading import Lock
from typing import Any, Dict, Optional

import httpx

try:
    from overstats.src.client.apiclient import CLIENT_CONFIG, DashenAPIClient, DashenCredential, dashen_api_client
except ModuleNotFoundError:
    from src.client.apiclient import CLIENT_CONFIG, DashenAPIClient, DashenCredential, dashen_api_client


# Search-only fallback credentials; deliberately independent of DASHEN_ACCOUNTS.
_FALLBACK_ACCOUNTS = (
    ("account-217943997", 217943997, "805ef05683a7bd5d4e86cf5370c37756"),
    ("account-207219421", 207219421, "0c0f007c41fa51a4cab819b06f62a3fc"),
)
_fallback_starts = cycle(range(len(_FALLBACK_ACCOUNTS)))
_fallback_lock = Lock()


def _search_unavailable(payload: Dict[str, Any]) -> bool:
    if payload.get("success") is False or payload.get("ok") is False:
        return True
    code = payload.get("code")
    if code is not None:
        return str(code) != "0"
    if payload.get("success") is True or payload.get("ok") is True:
        return False
    data = payload.get("data")
    return not isinstance(data, dict) or not data.get("customerToken")


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
        payload = None
        last_error = None
        try:
            payload = await self.api_client.search_bnet_account(query)
            if not _search_unavailable(payload):
                return BnetSearchResult(query=query, payload=payload)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_error = exc

        with _fallback_lock:
            start = next(_fallback_starts)
        defaults = CLIENT_CONFIG.accounts[0]
        for offset in range(len(_FALLBACK_ACCOUNTS)):
            name, role_id, token = _FALLBACK_ACCOUNTS[(start + offset) % len(_FALLBACK_ACCOUNTS)]
            credential = DashenCredential(
                name=name, role_id=role_id, token=token,
                dts=defaults.dts, server=defaults.server,
            )
            try:
                payload = await self.api_client.search_bnet_account(query, credential=credential)
                last_error = None
                if not _search_unavailable(payload):
                    return BnetSearchResult(query=query, payload=payload)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return BnetSearchResult(query=query, payload=payload)
