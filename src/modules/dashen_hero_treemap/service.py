from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

try:
    from overstats.src.client.apiclient import DashenAPIClient
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient
    from src.modules.errors import ModuleError
    from src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module

from .engine import DashenHeroTreemapEngine, DashenHeroTreemapHero, DashenHeroTreemapPlayer, DashenHeroTreemapSeason
from .engine import cloud_summary
from .render import RenderedImage, render_hero_treemap
from .requests import (
    DashenHeroTreemapQuery,
    DashenHeroTreemapRequests,
    normalize_treemap_mode,
)


@dataclass(frozen=True)
class DashenHeroTreemapOutput:
    player: DashenHeroTreemapPlayer
    season: DashenHeroTreemapSeason
    mode: str
    hero_count: int
    total_game_time_sec: float
    heroes: Sequence[DashenHeroTreemapHero]
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "player": self.player.to_dict(),
            "season": self.season.to_dict(),
            "mode": self.mode,
            "summary": cloud_summary(self.heroes),
            "hero_count": int(self.hero_count),
            "total_game_time_sec": float(self.total_game_time_sec),
            "heroes": [item.to_dict() for item in self.heroes],
        }


class DashenHeroTreemapModule:
    def __init__(
        self,
        api_client: Optional[DashenAPIClient] = None,
        search_module: Optional[BnetSearchModule] = None,
        requests: Optional[DashenHeroTreemapRequests] = None,
        engine: Optional[DashenHeroTreemapEngine] = None,
    ) -> None:
        self.requests = requests or DashenHeroTreemapRequests()
        if api_client is not None and requests is None:
            self.requests = DashenHeroTreemapRequests()
            self.requests.profile_requests.api_client = api_client
            self.requests.api_client = api_client
        self.engine = engine or DashenHeroTreemapEngine()
        self.search_module = search_module or bnet_search_module

    async def query_treemap(
        self,
        query: DashenHeroTreemapQuery,
        *,
        render: bool = False,
    ) -> DashenHeroTreemapOutput:
        resolved_query, resolved_bnet = await self._resolve_query(query)
        bundle = await self.requests.get_treemap_bundle(resolved_query)
        player, season, heroes = self.engine.build_output(
            bundle,
            mode=resolved_query.mode,
            resolved_name=(resolved_bnet.full_id if resolved_bnet else resolved_query.bnet_id),
        )
        from .details import enrich_recent_perks
        heroes = await enrich_recent_perks(heroes, bundle, resolved_query.mode, getattr(self.requests, "api_client", None), self.engine._load_ow_config())
        output = DashenHeroTreemapOutput(
            player=player,
            season=season,
            mode=resolved_query.mode,
            hero_count=len(heroes),
            total_game_time_sec=sum(item.game_time_sec for item in heroes),
            heroes=heroes,
        )
        if not render:
            return output

        await _prefetch_hero_icons(output.heroes)
        image = render_hero_treemap(
            player=output.player.to_dict(),
            season=output.season.to_dict(),
            mode=output.mode,
            hero_count=output.hero_count,
            total_game_time_sec=output.total_game_time_sec,
            heroes=[item.to_dict() for item in output.heroes],
        )
        return DashenHeroTreemapOutput(
            player=output.player,
            season=output.season,
            mode=output.mode,
            hero_count=output.hero_count,
            total_game_time_sec=output.total_game_time_sec,
            heroes=output.heroes,
            image=image,
        )

    async def _resolve_query(
        self,
        query: DashenHeroTreemapQuery,
    ) -> tuple[DashenHeroTreemapQuery, Optional[BnetSearchResult]]:
        try:
            normalized_mode = normalize_treemap_mode(query.mode)
        except ValueError as exc:
            raise ModuleError(
                error="invalid_treemap_query",
                message=str(exc),
                status_code=400,
                details={"mode": query.mode},
            ) from exc
        normalized_query = DashenHeroTreemapQuery(
            customer_token=str(query.customer_token or "").strip(),
            bnet_id=str(query.bnet_id or "").strip(),
            season=query.season,
            include_previous_season=bool(query.include_previous_season),
            mode=normalized_mode,
        )
        if normalized_query.customer_token:
            return normalized_query, None
        if not normalized_query.bnet_id:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        search_output = await self.search_module.search(normalized_query.bnet_id, render=False)
        customer_token = search_output.result.customer_token
        if not customer_token:
            payload: Dict[str, Any] = search_output.result.payload
            data = payload.get("data") if isinstance(payload, dict) else None
            raise ModuleError(
                error="bnet_not_found",
                message=f"Could not resolve customerToken from bnet_id: {normalized_query.bnet_id}",
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

        resolved_query = DashenHeroTreemapQuery(
            customer_token=customer_token,
            bnet_id=search_output.result.full_id,
            season=normalized_query.season,
            include_previous_season=normalized_query.include_previous_season,
            mode=normalized_query.mode,
        )
        return resolved_query, search_output.result


async def _prefetch_hero_icons(heroes: Sequence[DashenHeroTreemapHero]) -> None:
    """Warm only the requested portraits; unavailable assets keep the text fallback."""
    import httpx
    from PIL import Image
    from io import BytesIO
    from ..query_tool import get_cached_asset_path, cache_query_tool_asset_bytes

    urls = list(dict.fromkeys(url for h in heroes for url in [h.icon_url, *(p.get("icon_url") for p in h.recent_perks)] if url and not get_cached_asset_path(url, "heroes")))
    if not urls:
        return
    semaphore = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        async def fetch(url: str) -> None:
            async with semaphore:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    with Image.open(BytesIO(response.content)) as image:
                        image.verify()
                    cache_query_tool_asset_bytes(url, response.content, "heroes")
                except (httpx.HTTPError, OSError, ValueError):
                    pass
        await asyncio.gather(*(fetch(url) for url in urls))


dashen_hero_treemap_module = DashenHeroTreemapModule()


__all__ = [
    "DashenHeroTreemapHero",
    "DashenHeroTreemapModule",
    "DashenHeroTreemapOutput",
    "DashenHeroTreemapPlayer",
    "DashenHeroTreemapSeason",
    "RenderedImage",
    "dashen_hero_treemap_module",
]
