from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from overstats.src.client.apiclient import DashenAPIClient
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient
    from src.modules.errors import ModuleError
    from src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module

from .engine import DashenProfileEngine
from .render import RenderedImage, render_profile_summary
from .requests import DashenProfileBundle, DashenProfileQuery, DashenProfileRequests


@dataclass(frozen=True)
class DashenProfileOutput:
    bundle: DashenProfileBundle
    customer_token: str
    resolved_bnet: Optional[BnetSearchResult] = None
    image: Optional[RenderedImage] = None


class DashenProfileModule:
    def __init__(
        self,
        api_client: Optional[DashenAPIClient] = None,
        search_module: Optional[BnetSearchModule] = None,
    ) -> None:
        self.requests = DashenProfileRequests(api_client)
        self.engine = DashenProfileEngine(self.requests)
        self.search_module = search_module or bnet_search_module

    async def query_profile(
        self,
        query: DashenProfileQuery,
        *,
        render: bool = False,
        render_mode: str = "quick",
    ) -> DashenProfileOutput:
        query, resolved_bnet = await self._resolve_query(query)
        bundle = await self.requests.get_profile_bundle(query)

        profile_card = bundle.profile_card if isinstance(bundle.profile_card, dict) else {}
        if profile_card.get("code") not in (None, 0):
            raise ModuleError(
                error="profile_query_failed",
                message="Dashen profile queryCard request failed.",
                status_code=502,
                details={
                    "upstream_code": profile_card.get("code"),
                    "upstream_msg": profile_card.get("msg"),
                },
            )

        image = None
        if render:
            avatar_bytes = await self._try_fetch_avatar_bytes(profile_card)
            try:
                context = await self.engine.build_render_context(
                    bundle,
                    resolved_name=(resolved_bnet.full_id if resolved_bnet else query.bnet_id),
                    avatar_bytes=avatar_bytes,
                    render_mode=render_mode,
                )
                image = render_profile_summary(context)
            except RuntimeError as exc:
                raise ModuleError(
                    error="render_dependency_missing",
                    message=str(exc),
                    status_code=500,
                    hint="Install Pillow in the runtime environment to enable image rendering.",
                ) from exc

        return DashenProfileOutput(
            bundle=bundle,
            customer_token=query.customer_token,
            resolved_bnet=resolved_bnet,
            image=image,
        )

    async def query_profile_by_bnet_id(
        self,
        bnet_id: str,
        *,
        season: Optional[int] = None,
        include_previous_season: bool = True,
    ) -> DashenProfileOutput:
        return await self.query_profile(
            DashenProfileQuery(
                bnet_id=bnet_id,
                season=season,
                include_previous_season=include_previous_season,
            ),
            render=False,
        )

    async def query_profile_image(self, query: DashenProfileQuery, *, render_mode: str = "quick") -> DashenProfileOutput:
        return await self.query_profile(query, render=True, render_mode=render_mode)

    async def _resolve_query(self, query: DashenProfileQuery) -> tuple[DashenProfileQuery, Optional[BnetSearchResult]]:
        if query.customer_token:
            return query, None
        if not query.bnet_id:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        search_output = await self.search_module.search(query.bnet_id, render=False)
        customer_token = search_output.result.customer_token
        if not customer_token:
            payload: Dict[str, Any] = search_output.result.payload
            data = payload.get("data") if isinstance(payload, dict) else None
            raise ModuleError(
                error="bnet_not_found",
                message=f"Could not resolve customerToken from bnet_id: {query.bnet_id}",
                status_code=404,
                hint=(
                    "Check exact letter case and the number after '#'. "
                    "Dashen search is often case-sensitive. "
                    "If you already have customer_token, query with customer_token directly."
                ),
                details={
                    "query": search_output.result.query,
                    "upstream_code": payload.get("code") if isinstance(payload, dict) else None,
                    "upstream_msg": payload.get("msg") if isinstance(payload, dict) else None,
                    "has_data": isinstance(data, dict),
                    "has_customer_token": bool(customer_token),
                    "resolved_name": search_output.result.full_id,
                    "resolved_bnet_id": search_output.result.bnet_id,
                },
            )

        resolved_query = DashenProfileQuery(
            customer_token=customer_token,
            bnet_id=search_output.result.full_id,
            season=query.season,
            include_previous_season=query.include_previous_season,
        )
        return resolved_query, search_output.result

    async def _try_fetch_avatar_bytes(self, profile_card: Dict[str, Any]) -> Optional[bytes]:
        card_data = profile_card.get("data") if isinstance(profile_card.get("data"), dict) else {}
        avatar_url = str(card_data.get("icon") or "").strip()
        if not avatar_url:
            return None
        try:
            return await self.requests.api_client.get_icon(avatar_url)
        except Exception as exc:
            print(f"[overstats] failed to fetch dashen profile avatar: {exc}")
            return None


dashen_profile_module = DashenProfileModule()
