from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import locale
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Dict, Iterable, List, Optional, TypeVar

try:
    from overstats.config import APIConfig
    from overstats.src.client.apiclient import dashen_api_client
    from overstats.src.db.request_metrics import RequestMetricsRecorder, normalize_request_metric_url
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.dashen_profile import DashenProfileQuery, dashen_profile_module
    from overstats.src.modules.query_tool import ensure_query_tool_assets, load_query_tool
    from overstats.src.modules.dashen_match import DashenMatchQuery, dashen_match_module
    from overstats.src.modules.dashen_rank_history import DashenRankHistoryQuery, dashen_rank_history_module
    from overstats.src.modules.dashen_quick_strength import DashenQuickStrengthQuery, dashen_quick_strength_module
    from overstats.src.modules.dashen_competitive_strength import (
        DashenCompetitiveStrengthQuery,
        dashen_competitive_strength_module,
    )
    from overstats.src.modules.dashen_summary import DashenSummaryQuery, dashen_summary_module
    from overstats.src.modules.ow_hero_pick_rate import OWHeroPickRateQuery, ow_hero_pick_rate_module
    from overstats.src.modules.ow_shop import ow_shop_module
    from overstats.src.modules.ow_hero_leaderboard import OWHeroLeaderboardSyncService
    from overstats.src.modules.patch_notes import patch_notes_module
    from overstats.src.modules.player_identity_search import (
        PlayerIdentitySearchQuery,
        player_identity_search_module,
    )
    from overstats.src.http_server import resolve_http_ui_asset
except ModuleNotFoundError:
    from config import APIConfig
    from src.client.apiclient import dashen_api_client
    from src.db.request_metrics import RequestMetricsRecorder, normalize_request_metric_url
    from src.modules.errors import ModuleError
    from src.modules.dashen_profile import DashenProfileQuery, dashen_profile_module
    from src.modules.query_tool import ensure_query_tool_assets, load_query_tool
    from src.modules.dashen_match import DashenMatchQuery, dashen_match_module
    from src.modules.dashen_rank_history import DashenRankHistoryQuery, dashen_rank_history_module
    from src.modules.dashen_quick_strength import DashenQuickStrengthQuery, dashen_quick_strength_module
    from src.modules.dashen_competitive_strength import (
        DashenCompetitiveStrengthQuery,
        dashen_competitive_strength_module,
    )
    from src.modules.dashen_summary import DashenSummaryQuery, dashen_summary_module
    from src.modules.ow_hero_pick_rate import OWHeroPickRateQuery, ow_hero_pick_rate_module
    from src.modules.ow_shop import ow_shop_module
    from src.modules.ow_hero_leaderboard import OWHeroLeaderboardSyncService
    from src.modules.patch_notes import patch_notes_module
    from src.modules.player_identity_search import (
        PlayerIdentitySearchQuery,
        player_identity_search_module,
    )
    from src.http_server import resolve_http_ui_asset


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_profile_render_mode(payload: Dict[str, object]) -> str:
    if _coerce_bool(payload.get("competitive"), False):
        return "competitive"
    raw_mode = str(payload.get("mode") or payload.get("render_mode") or "").strip().lower()
    if raw_mode in {"competitive", "comp", "ranked"}:
        return "competitive"
    return "quick"


def _coerce_optional_int(payload: Dict[str, object], *keys: str) -> Optional[int]:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value in (None, "", "auto", "AUTO", "Auto"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ModuleError(
                error="invalid_integer",
                message=f"{key} must be an integer when provided.",
                status_code=400,
                details={key: value},
            ) from exc
    return None


def _is_success_status(status: HTTPStatus) -> bool:
    return 200 <= int(status) < 300


def _build_ow_hero_pick_rate_query(payload: Dict[str, object]) -> OWHeroPickRateQuery:
    return OWHeroPickRateQuery(
        view=str(payload.get("view") or "").strip(),
        game_mode=str(payload.get("game_mode") or payload.get("gameMode") or "").strip(),
        mmr=str(payload.get("mmr") or "").strip(),
        hero=str(payload.get("hero") or "").strip(),
        history_limit=payload.get("history_limit", payload.get("historyLimit")),
    )


_T = TypeVar("_T")


class DashenRequestQueue:
    def __init__(self, max_concurrent_requests: int) -> None:
        self.max_concurrent_requests = max(1, int(max_concurrent_requests or 1))
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_requests = 0
        self._queued_requests = 0

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        return self._semaphore

    async def run(self, label: str, factory: Callable[[], Awaitable[_T]]) -> _T:
        semaphore = self._get_semaphore()
        self._queued_requests += 1
        try:
            await semaphore.acquire()
        finally:
            self._queued_requests -= 1

        self._active_requests += 1
        if self._queued_requests > 0:
            print(
                "[overstats] dashen request dequeued "
                f"label={label} active={self._active_requests} queued={self._queued_requests}"
            )
        try:
            return await factory()
        finally:
            self._active_requests -= 1
            semaphore.release()


class OverstatsCoreService:
    """Core request facade used by every downstream client."""

    def __init__(self, dashen_max_concurrent_requests: int = 2) -> None:
        self.dashen_request_queue = DashenRequestQueue(dashen_max_concurrent_requests)

    async def handle_dashen_profile(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "profile",
            lambda: self._handle_dashen_profile(payload),
        )

    async def handle_dashen_profile_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "profile_image",
            lambda: self._handle_dashen_profile_image(payload),
        )

    async def _handle_dashen_profile(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        season_value = payload.get("season")
        if season_value is None:
            season_value = payload.get("season_c")

        season = None
        if season_value not in (None, "", 0, "0", "auto", "AUTO", "Auto"):
            try:
                season = int(season_value)
            except (TypeError, ValueError) as exc:
                raise ModuleError(
                    error="invalid_season",
                    message="season must be an integer when provided.",
                    status_code=400,
                    hint='Example: {"bnet_id":"Player#12345","season":22}',
                    details={"season": season_value},
                ) from exc

        include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)

        result = await dashen_profile_module.query_profile(
            DashenProfileQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                season=season,
                include_previous_season=include_previous_season,
            )
        )
        resolved = result.resolved_bnet
        bundle = result.bundle
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": resolved.query,
                "full_id": resolved.full_id,
                "bnet_id": resolved.bnet_id,
                "has_customer_token": bool(resolved.customer_token),
            } if resolved else None,
            "season": {
                "logical": bundle.logical_season,
                "request": bundle.request_season,
                "include_previous_season": include_previous_season,
            },
            "profile_card": bundle.profile_card,
            "sport": bundle.sport,
            "leisure": bundle.leisure,
        }

    async def _handle_dashen_profile_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        season_value = payload.get("season")
        if season_value is None:
            season_value = payload.get("season_c")

        season = None
        if season_value not in (None, "", 0, "0", "auto", "AUTO", "Auto"):
            try:
                season = int(season_value)
            except (TypeError, ValueError) as exc:
                raise ModuleError(
                    error="invalid_season",
                    message="season must be an integer when provided.",
                    status_code=400,
                    hint='Example: {"bnet_id":"Player#12345","season":22}',
                    details={"season": season_value},
                ) from exc

        include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)
        render_mode = _coerce_profile_render_mode(payload)

        result = await dashen_profile_module.query_profile_image(
            DashenProfileQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                season=season,
                include_previous_season=include_previous_season,
            ),
            render_mode=render_mode,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen profile image was not generated.",
                status_code=500,
            )
        return result.image.content

    def handle_query(
        self,
        route: str,
        text: str,
        stream: bool,
        extra: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        replies: List[Dict[str, object]] = [
            {
                "type": "meta",
                "data": {
                    "route": route,
                    "stream": stream,
                },
            },
            {
                "type": "text",
                "data": f"overstats core received: {text or route}",
            },
        ]
        return {
            "ok": True,
            "route": route,
            "text": text,
            "stream": stream,
            "extra": extra or {},
            "replies": replies,
        }

    async def handle_player_identity_search(self, payload: Dict[str, object]) -> Dict[str, object]:
        lookup_bnet_id = str(
            payload.get("bnet_id")
            or payload.get("bnetId")
            or payload.get("query")
            or payload.get("target")
            or ""
        ).strip()
        limit = _coerce_optional_int(payload, "limit")
        if limit is None:
            limit = 10
        exact_only_value = payload.get("exact_only")
        if exact_only_value is None:
            exact_only_value = payload.get("exactOnly")
        exact_only = _coerce_bool(exact_only_value, False)
        result = await player_identity_search_module.search(
            PlayerIdentitySearchQuery(
                bnet_id=lookup_bnet_id,
                limit=limit,
                exact_only=exact_only,
            )
        )
        matches = [item.to_dict() for item in result.matches]
        return {
            "ok": True,
            "query": {
                "bnet_id": result.query.bnet_id,
                "limit": result.query.limit,
                "exact_only": result.query.exact_only,
            },
            "count": len(matches),
            "candidates": [str(item["battletag"]) for item in matches if item.get("battletag")],
            "matches": matches,
        }

    def iter_query_events(
        self,
        route: str,
        text: str,
        stream: bool,
        extra: Optional[Dict[str, object]] = None,
    ) -> Iterable[Dict[str, object]]:
        result = self.handle_query(route=route, text=text, stream=stream, extra=extra)
        yield {
            "type": "meta",
            "data": {
                "route": result["route"],
                "stream": result["stream"],
            },
        }
        for reply in result["replies"]:
            if reply.get("type") == "meta":
                continue
            yield reply
        yield {
            "type": "done",
            "data": {
                "ok": True,
            },
        }

    async def handle_ow_shop(self, payload: Dict[str, object]) -> Dict[str, object]:
        result = await ow_shop_module.query_shop(render=False)
        return result.to_dict()

    async def handle_ow_shop_image(self, payload: Dict[str, object]) -> bytes:
        result = await ow_shop_module.query_shop(render=True)
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="OW shop image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_patch_notes(self, payload: Dict[str, object]) -> Dict[str, object]:
        patch_kind = payload.get("patch_kind")
        if patch_kind is None:
            patch_kind = payload.get("kind")
        result = await patch_notes_module.query_patch_notes(patch_kind=patch_kind, render=False)
        return result.to_dict()

    async def handle_patch_notes_image(self, payload: Dict[str, object]) -> bytes:
        patch_kind = payload.get("patch_kind")
        if patch_kind is None:
            patch_kind = payload.get("kind")
        result = await patch_notes_module.query_patch_notes(patch_kind=patch_kind, render=True)
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Patch notes image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_ow_hero_pick_rate(self, payload: Dict[str, object]) -> Dict[str, object]:
        query = _build_ow_hero_pick_rate_query(payload)
        result = await ow_hero_pick_rate_module.query_pick_rate(query, render=False)
        return result.to_dict()

    async def handle_ow_hero_pick_rate_image(self, payload: Dict[str, object]) -> bytes:
        query = _build_ow_hero_pick_rate_query(payload)
        result = await ow_hero_pick_rate_module.query_pick_rate(query, render=True)
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Hero pick-rate image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_dashen_match(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "match_list",
            lambda: self._handle_dashen_match(payload),
        )

    async def handle_dashen_match_replies(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "match_replies",
            lambda: self._handle_dashen_match_replies(payload),
        )

    async def _handle_dashen_match(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        if not bnet_id and not customer_token:
            return {
                "ok": False,
                "error": "missing_target",
                "message": "bnet_id or customer_token is required",
            }

        target_count = int(payload.get("target_count") or payload.get("limit") or 20)
        include_fight = _coerce_bool(payload.get("include_fight"), True)
        include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)
        render = _coerce_bool(payload.get("render"), False)

        result = await dashen_match_module.query_match_list(
            DashenMatchQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                target_count=target_count,
                include_fight=include_fight,
                include_previous_season=include_previous_season,
            ),
            render=render,
        )
        resolved = result.resolved_bnet
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": resolved.query,
                "full_id": resolved.full_id,
                "bnet_id": resolved.bnet_id,
                "has_customer_token": bool(resolved.customer_token),
            } if resolved else None,
            "count": len(result.matches),
            "matches": result.matches,
        }

    async def _handle_dashen_match_replies(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","limit":20}',
            )

        result = await dashen_match_module.query_match_list_replies(
            DashenMatchQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                target_count=int(payload.get("target_count") or payload.get("limit") or 20),
                include_fight=_coerce_bool(payload.get("include_fight"), True),
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            )
        )
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": result.resolved_bnet.query,
                "full_id": result.resolved_bnet.full_id,
                "bnet_id": result.resolved_bnet.bnet_id,
                "has_customer_token": bool(result.resolved_bnet.customer_token),
            } if result.resolved_bnet else None,
            "replies": result.replies,
        }

    async def handle_dashen_match_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "match_image",
            lambda: self._handle_dashen_match_image(payload),
        )

    async def _handle_dashen_match_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","limit":20}',
            )

        target_count = int(payload.get("target_count") or payload.get("limit") or 20)
        include_fight = _coerce_bool(payload.get("include_fight"), True)
        include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)

        result = await dashen_match_module.query_match_list(
            DashenMatchQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                target_count=target_count,
                include_fight=include_fight,
                include_previous_season=include_previous_season,
            ),
            render=True,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen match image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_dashen_match_detail(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "match_detail",
            lambda: self._handle_dashen_match_detail(payload),
        )

    async def handle_dashen_match_detail_replies(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "match_detail_replies",
            lambda: self._handle_dashen_match_detail_replies(payload),
        )

    async def _handle_dashen_match_detail(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        match_id = str(payload.get("match_id") or payload.get("matchId") or "").strip()
        index_value = payload.get("index")
        if index_value is None:
            index_value = payload.get("idx")

        if match_id and not customer_token:
            raise ModuleError(
                error="missing_customer_token",
                message="customer_token is required when querying detail by match_id directly.",
                status_code=400,
                hint='Use {"bnet_id":"Player#12345","index":0} or provide customer_token with match_id.',
            )
        if not match_id and index_value is None:
            raise ModuleError(
                error="missing_match_selector",
                message="index or match_id is required for match detail.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","index":0}',
            )

        if match_id:
            result = await dashen_match_module.query_match_detail(
                customer_token,
                match_id,
                render=False,
            )
        else:
            if not bnet_id and not customer_token:
                raise ModuleError(
                    error="missing_target",
                    message="Missing query target: bnet_id or customer_token is required.",
                    status_code=400,
                    hint='Example: {"bnet_id":"Player#12345","index":0}',
                )
            target_count = int(payload.get("target_count") or payload.get("limit") or 20)
            include_fight = _coerce_bool(payload.get("include_fight"), True)
            include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)
            result = await dashen_match_module.query_match_detail_by_index(
                DashenMatchQuery(
                    customer_token=customer_token,
                    bnet_id=bnet_id,
                    target_count=target_count,
                    include_fight=include_fight,
                    include_previous_season=include_previous_season,
                ),
                int(index_value),
                render=False,
            )

        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": result.resolved_bnet.query,
                "full_id": result.resolved_bnet.full_id,
                "bnet_id": result.resolved_bnet.bnet_id,
                "has_customer_token": bool(result.resolved_bnet.customer_token),
            } if result.resolved_bnet else None,
            "match_id": result.detail.match_id,
            "match_kind": result.detail.match_kind,
            "source_match": result.detail.source_match,
            "detail": result.detail.payload,
        }

    async def _handle_dashen_match_detail_replies(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        match_id = str(payload.get("match_id") or payload.get("matchId") or "").strip()
        index_value = payload.get("index")
        if index_value is None:
            index_value = payload.get("idx")

        show_all_heroes = _coerce_bool(
            payload.get("show_all_heroes", payload.get("show_all", payload.get("all_heroes"))),
            False,
        )
        analyze = _coerce_bool(payload.get("analyze"), False)
        if analyze:
            show_all_heroes = True

        if match_id and not customer_token:
            raise ModuleError(
                error="missing_customer_token",
                message="customer_token is required when querying detail by match_id directly.",
                status_code=400,
                hint='Use {"bnet_id":"Player#12345","index":0} or provide customer_token with match_id.',
            )
        if not match_id and index_value is None:
            raise ModuleError(
                error="missing_match_selector",
                message="index or match_id is required for match detail.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","index":0}',
            )

        query = None
        if not match_id:
            if not bnet_id and not customer_token:
                raise ModuleError(
                    error="missing_target",
                    message="Missing query target: bnet_id or customer_token is required.",
                    status_code=400,
                    hint='Example: {"bnet_id":"Player#12345","index":0}',
                )
            query = DashenMatchQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                target_count=int(payload.get("target_count") or payload.get("limit") or 20),
                include_fight=_coerce_bool(payload.get("include_fight"), True),
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            )
        elif bnet_id:
            query = DashenMatchQuery(customer_token=customer_token, bnet_id=bnet_id)

        result = await dashen_match_module.query_match_detail_replies(
            query=query,
            customer_token=customer_token,
            match_id=match_id,
            index=int(index_value) if index_value is not None else None,
            show_all_heroes=show_all_heroes,
            analyze=analyze,
        )
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": result.resolved_bnet.query,
                "full_id": result.resolved_bnet.full_id,
                "bnet_id": result.resolved_bnet.bnet_id,
                "has_customer_token": bool(result.resolved_bnet.customer_token),
            } if result.resolved_bnet else None,
            "match_id": result.match_id,
            "match_kind": result.match_kind,
            "replies": result.replies,
        }

    async def handle_dashen_match_detail_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "match_detail_image",
            lambda: self._handle_dashen_match_detail_image(payload),
        )

    async def _handle_dashen_match_detail_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        index_value = payload.get("index")
        if index_value is None:
            index_value = payload.get("idx")
        if index_value is None:
            raise ModuleError(
                error="missing_match_selector",
                message="index is required for match detail image.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","index":0}',
            )
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","index":0}',
            )

        target_count = int(payload.get("target_count") or payload.get("limit") or 20)
        include_fight = _coerce_bool(payload.get("include_fight"), True)
        include_previous_season = _coerce_bool(payload.get("include_previous_season"), True)
        result = await dashen_match_module.query_match_detail_by_index(
            DashenMatchQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                target_count=target_count,
                include_fight=include_fight,
                include_previous_season=include_previous_season,
            ),
            int(index_value),
            render=True,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen match detail image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_dashen_summary(self, payload: Dict[str, object], *, scope: str = "today") -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            f"summary_{scope}",
            lambda: self._handle_dashen_summary(payload, scope=scope),
        )

    async def _handle_dashen_summary(self, payload: Dict[str, object], *, scope: str = "today") -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        full_id = str(payload.get("full_id") or payload.get("fullId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        result = await dashen_summary_module.query_summary(
            DashenSummaryQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                full_id=full_id,
                scope=scope,
            )
        )
        resolved = result.resolved_bnet
        return {
            "ok": True,
            "scope": result.scope,
            "title": result.title,
            "customer_token": result.customer_token,
            "resolved": {
                "query": resolved.query if resolved else (bnet_id or full_id),
                "full_id": result.full_id,
                "bnet_id": result.bnet_id,
                "has_customer_token": bool(result.customer_token),
            },
            "summary": {
                "worker_url": result.worker_url,
                "match_count": result.match_count,
                "all_match_count": result.all_match_count,
                "payload_kb": result.payload_kb,
                "timings": result.timings,
            },
        }

    async def handle_dashen_summary_image(self, payload: Dict[str, object], *, scope: str = "today") -> tuple[bytes, str]:
        return await self.dashen_request_queue.run(
            f"summary_{scope}_image",
            lambda: self._handle_dashen_summary_image(payload, scope=scope),
        )

    async def _handle_dashen_summary_image(self, payload: Dict[str, object], *, scope: str = "today") -> tuple[bytes, str]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        full_id = str(payload.get("full_id") or payload.get("fullId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        result = await dashen_summary_module.query_summary(
            DashenSummaryQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                full_id=full_id,
                scope=scope,
            )
        )
        return result.image_bytes, result.image_media_type

    async def handle_dashen_rank_history(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "rank_history",
            lambda: self._handle_dashen_rank_history(payload),
        )

    async def _handle_dashen_rank_history(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_rank_history_module.query_rank_history(
            DashenRankHistoryQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                start_season=_coerce_optional_int(payload, "start_season", "startSeason"),
                end_season=_coerce_optional_int(payload, "end_season", "endSeason"),
            ),
            render=False,
        )
        resolved = result.resolved_bnet
        seasons = []
        for item in result.seasons:
            seasons.append(
                {
                    "season": item.get("season"),
                    "has_competitive": item.get("has_competitive"),
                    "has_stadium": item.get("has_stadium"),
                    "competitive": item.get("competitive"),
                    "stadium": item.get("stadium"),
                }
            )
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "resolved": {
                "query": resolved.query,
                "full_id": result.full_id,
                "bnet_id": result.bnet_id,
                "has_customer_token": bool(resolved.customer_token),
            } if resolved else {
                "query": bnet_id or customer_token,
                "full_id": result.full_id,
                "bnet_id": result.bnet_id,
                "has_customer_token": bool(result.customer_token),
            },
            "season_range": {
                "start_season": result.start_season,
                "end_season": result.end_season,
            },
            "seasons": seasons,
            "missing_assets": list(result.missing_assets),
        }

    async def handle_dashen_rank_history_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "rank_history_image",
            lambda: self._handle_dashen_rank_history_image(payload),
        )

    async def _handle_dashen_rank_history_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_rank_history_module.query_rank_history(
            DashenRankHistoryQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                start_season=_coerce_optional_int(payload, "start_season", "startSeason"),
                end_season=_coerce_optional_int(payload, "end_season", "endSeason"),
            ),
            render=True,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen rank history image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_dashen_quick_strength(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "quick_strength",
            lambda: self._handle_dashen_quick_strength(payload),
        )

    async def _handle_dashen_quick_strength(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        limit = _coerce_optional_int(payload, "limit") or 12
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_quick_strength_module.query_quick_strength(
            DashenQuickStrengthQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                limit=limit,
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            ),
            render=False,
        )
        resolved = result.resolved_bnet
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "full_id": result.full_id,
            "bnet_id": result.bnet_id,
            "resolved": {
                "query": resolved.query,
                "full_id": resolved.full_id,
                "bnet_id": resolved.bnet_id,
                "has_customer_token": bool(resolved.customer_token),
            } if resolved else {
                "query": bnet_id or customer_token,
                "full_id": result.full_id,
                "bnet_id": result.bnet_id,
                "has_customer_token": bool(result.customer_token),
            },
            "summary": result.summary.to_dict(),
            "matches": [item.to_dict() for item in result.matches],
        }

    async def handle_dashen_quick_strength_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "quick_strength_image",
            lambda: self._handle_dashen_quick_strength_image(payload),
        )

    async def _handle_dashen_quick_strength_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        limit = _coerce_optional_int(payload, "limit") or 12
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_quick_strength_module.query_quick_strength(
            DashenQuickStrengthQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                limit=limit,
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            ),
            render=True,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen quick strength image was not generated.",
                status_code=500,
            )
        return result.image.content

    async def handle_dashen_competitive_strength(self, payload: Dict[str, object]) -> Dict[str, object]:
        return await self.dashen_request_queue.run(
            "competitive_strength",
            lambda: self._handle_dashen_competitive_strength(payload),
        )

    async def _handle_dashen_competitive_strength(self, payload: Dict[str, object]) -> Dict[str, object]:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        limit = _coerce_optional_int(payload, "limit") or 12
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_competitive_strength_module.query_competitive_strength(
            DashenCompetitiveStrengthQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                limit=limit,
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            ),
            render=False,
        )
        resolved = result.resolved_bnet
        return {
            "ok": True,
            "customer_token": result.customer_token,
            "full_id": result.full_id,
            "bnet_id": result.bnet_id,
            "resolved": {
                "query": resolved.query,
                "full_id": resolved.full_id,
                "bnet_id": resolved.bnet_id,
                "has_customer_token": bool(resolved.customer_token),
            } if resolved else {
                "query": bnet_id or customer_token,
                "full_id": result.full_id,
                "bnet_id": result.bnet_id,
                "has_customer_token": bool(result.customer_token),
            },
            "summary": result.summary.to_dict(),
            "matches": [item.to_dict() for item in result.matches],
        }

    async def handle_dashen_competitive_strength_image(self, payload: Dict[str, object]) -> bytes:
        return await self.dashen_request_queue.run(
            "competitive_strength_image",
            lambda: self._handle_dashen_competitive_strength_image(payload),
        )

    async def _handle_dashen_competitive_strength_image(self, payload: Dict[str, object]) -> bytes:
        bnet_id = str(payload.get("bnet_id") or payload.get("bnetId") or "").strip()
        customer_token = str(payload.get("customer_token") or payload.get("customerToken") or "").strip()
        limit = _coerce_optional_int(payload, "limit") or 12
        if not bnet_id and not customer_token:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345"}',
            )

        result = await dashen_competitive_strength_module.query_competitive_strength(
            DashenCompetitiveStrengthQuery(
                customer_token=customer_token,
                bnet_id=bnet_id,
                limit=limit,
                include_previous_season=_coerce_bool(payload.get("include_previous_season"), True),
            ),
            render=True,
        )
        if not result.image:
            raise ModuleError(
                error="render_failed",
                message="Dashen competitive strength image was not generated.",
                status_code=500,
            )
        return result.image.content


class AsyncRunner:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="overstats-async-loop", daemon=True)
        self.thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def submit(self, coro) -> None:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def _on_done(done_future) -> None:
            try:
                done_future.result()
            except Exception as exc:
                print(f"[overstats] async background task failed: {exc}")

        future.add_done_callback(_on_done)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        if not self.loop.is_closed():
            self.loop.close()


def create_server(config: APIConfig) -> ThreadingHTTPServer:
    query_tool_config = load_query_tool()
    asset_status = ensure_query_tool_assets(query_tool_config)
    print(
        "[overstats] query_tool assets "
        f"checked={asset_status['checked']} "
        f"cached={asset_status.get('cached', 0)} "
        f"downloaded={asset_status['downloaded']} "
        f"failed={asset_status['failed']} "
        f"dir={asset_status['asset_dir']}"
    )
    service = OverstatsCoreService(
        dashen_max_concurrent_requests=config.dashen_max_concurrent_requests,
    )
    print(
        "[overstats] dashen request queue enabled "
        f"max_concurrent={config.dashen_max_concurrent_requests}"
    )
    async_runner = AsyncRunner()
    request_metrics_recorder = RequestMetricsRecorder()
    async_runner.run(request_metrics_recorder.start())
    ow_hero_leaderboard_sync_service = OWHeroLeaderboardSyncService()
    async_runner.run(ow_hero_leaderboard_sync_service.start())
    previous_request_metrics_recorder = dashen_api_client.request_metrics_recorder
    dashen_api_client.request_metrics_recorder = request_metrics_recorder

    class OverstatsRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "OverstatsCore/0.1"

        def _request_path(self) -> str:
            normalized = normalize_request_metric_url(self.path)
            return normalized.rstrip("/") or "/"

        def do_GET(self) -> None:
            path = self._request_path()
            self._set_metrics_context(path if path.startswith("/api/v2/") else None)
            if path == "/healthz":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "service": "overstats-core",
                        "default_stream": config.use_stream_response,
                        "dashen_max_concurrent_requests": config.dashen_max_concurrent_requests,
                    },
                )
                return

            ui_asset = resolve_http_ui_asset(path)
            if ui_asset is not None:
                self._send_binary(ui_asset.status, ui_asset.body, ui_asset.content_type)
                return

            self._send_json(
                HTTPStatus.NOT_FOUND,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )

        def do_POST(self) -> None:
            path = self._request_path()
            self._set_metrics_context(path if path.startswith("/api/v2/") else None)
            if path == "/api/v2/internal/player-identity/search":
                self._handle_player_identity_search_post()
                return

            if path == "/api/v2/patch-notes/image":
                self._handle_patch_notes_image_post()
                return

            if path == "/api/v2/patch-notes":
                self._handle_patch_notes_post()
                return

            if path == "/api/v2/ow-hero-pick-rate/image":
                self._handle_ow_hero_pick_rate_image_post()
                return

            if path == "/api/v2/ow-hero-pick-rate":
                self._handle_ow_hero_pick_rate_post()
                return

            if path == "/api/v2/ow-shop/image":
                self._handle_ow_shop_image_post()
                return

            if path == "/api/v2/ow-shop":
                self._handle_ow_shop_post()
                return

            if path == "/api/v2/dashen-summary/week/image":
                self._handle_dashen_summary_image_post("week")
                return

            if path == "/api/v2/dashen-summary/week":
                self._handle_dashen_summary_post("week")
                return

            if path == "/api/v2/dashen-summary/yesterday/image":
                self._handle_dashen_summary_image_post("yesterday")
                return

            if path == "/api/v2/dashen-summary/yesterday":
                self._handle_dashen_summary_post("yesterday")
                return

            if path == "/api/v2/dashen-summary/today/image":
                self._handle_dashen_summary_image_post("today")
                return

            if path == "/api/v2/dashen-summary/today":
                self._handle_dashen_summary_post("today")
                return

            if path == "/api/v2/dashen-profile/image":
                self._handle_dashen_profile_image_post()
                return

            if path == "/api/v2/dashen-profile":
                self._handle_dashen_profile_post()
                return

            if path == "/api/v2/dashen-rank-history/image":
                self._handle_dashen_rank_history_image_post()
                return

            if path == "/api/v2/dashen-rank-history":
                self._handle_dashen_rank_history_post()
                return

            if path == "/api/v2/dashen-quick-strength/image":
                self._handle_dashen_quick_strength_image_post()
                return

            if path == "/api/v2/dashen-quick-strength":
                self._handle_dashen_quick_strength_post()
                return

            if path == "/api/v2/dashen-competitive-strength/image":
                self._handle_dashen_competitive_strength_image_post()
                return

            if path == "/api/v2/dashen-competitive-strength":
                self._handle_dashen_competitive_strength_post()
                return

            if path == "/api/v2/dashen-match/detail/replies":
                self._handle_dashen_match_detail_replies_post()
                return

            if path == "/api/v2/dashen-match/detail/image":
                self._handle_dashen_match_detail_image_post()
                return

            if path == "/api/v2/dashen-match/detail":
                self._handle_dashen_match_detail_post()
                return

            if path == "/api/v2/dashen-match/replies":
                self._handle_dashen_match_replies_post()
                return

            if path == "/api/v2/dashen-match/image":
                self._handle_dashen_match_image_post()
                return

            if path == "/api/v2/dashen-match":
                self._handle_dashen_match_post()
                return

            if path != "/api/v2/query":
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {
                        "ok": False,
                        "error": "not_found",
                    },
                )
                return

            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            route = str(payload.get("route") or "default")
            text = str(payload.get("text") or "")
            stream = _coerce_bool(payload.get("stream"), config.use_stream_response)
            extra = payload.get("extra")
            if extra is not None and not isinstance(extra, dict):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_extra",
                        "message": "extra must be an object when provided",
                    },
                )
                return

            if stream:
                self._send_stream(
                    HTTPStatus.OK,
                    service.iter_query_events(
                        route=route,
                        text=text,
                        stream=True,
                        extra=extra,
                    ),
                )
                return

            self._send_json(
                HTTPStatus.OK,
                service.handle_query(
                    route=route,
                    text=text,
                    stream=False,
                    extra=extra,
                ),
            )

        def _handle_player_identity_search_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_player_identity_search(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_match_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_match(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(status, result)

        def _handle_dashen_match_replies_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_match_replies(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_ow_shop_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_ow_shop(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_ow_shop_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_ow_shop_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_patch_notes_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_patch_notes(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_patch_notes_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_patch_notes_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_ow_hero_pick_rate_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_ow_hero_pick_rate(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_ow_hero_pick_rate_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_ow_hero_pick_rate_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_profile_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_profile(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(status, result)

        def _handle_dashen_profile_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_profile_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_rank_history_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_rank_history(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_rank_history_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_rank_history_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_quick_strength_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_quick_strength(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_quick_strength_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_quick_strength_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_competitive_strength_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_competitive_strength(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_competitive_strength_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_competitive_strength_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_summary_post(self, scope: str) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_summary(payload, scope=scope))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_summary_image_post(self, scope: str) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body, content_type = async_runner.run(service.handle_dashen_summary_image(payload, scope=scope))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, content_type)

        def _handle_dashen_match_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_match_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def _handle_dashen_match_detail_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_match_detail(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_match_detail_replies_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                result = async_runner.run(service.handle_dashen_match_detail_replies(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_json(HTTPStatus.OK, result)

        def _handle_dashen_match_detail_image_post(self) -> None:
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "ok": False,
                        "error": "invalid_json",
                        "message": str(exc),
                    },
                )
                return

            try:
                image_body = async_runner.run(service.handle_dashen_match_detail_image(payload))
            except ModuleError as exc:
                self._send_json(
                    HTTPStatus(exc.status_code),
                    {
                        "ok": False,
                        "error": exc.error,
                        "message": exc.message,
                        "hint": exc.hint,
                        "details": exc.details,
                    },
                )
                return
            except Exception as exc:
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "ok": False,
                        "error": "internal_error",
                        "message": "Internal server error. See details.",
                        "details": {
                            "exception": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
                return

            self._send_binary(HTTPStatus.OK, image_body, "image/png")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _set_metrics_context(self, url: Optional[str]) -> None:
            normalized = normalize_request_metric_url(str(url or "").strip())
            self._request_metrics_url = normalized or None
            self._request_metrics_recorded = False

        def _record_module_metric(self, status: HTTPStatus, *, success: bool) -> None:
            metrics_url = getattr(self, "_request_metrics_url", None)
            if not metrics_url or getattr(self, "_request_metrics_recorded", False):
                return
            self._request_metrics_recorded = True
            async_runner.submit(request_metrics_recorder.enqueue(metrics_url, "module", success))

        def _record_json_metric(self, status: HTTPStatus, payload: Dict[str, object]) -> None:
            success = _is_success_status(status) and payload.get("ok") is True
            self._record_module_metric(status, success=success)

        def _record_binary_metric(self, status: HTTPStatus) -> None:
            self._record_module_metric(status, success=_is_success_status(status))

        def _record_stream_metric(self, status: HTTPStatus) -> None:
            self._record_module_metric(status, success=_is_success_status(status))

        def _read_json_body(self) -> Dict[str, object]:
            length_header = self.headers.get("Content-Length")
            length = int(length_header) if length_header else 0
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            if not raw_body.strip():
                return {}
            try:
                data = json.loads(self._decode_body(raw_body))
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "request body is not valid UTF-8/GBK JSON text; "
                    "Windows cmd users can avoid this by using ASCII bnet_id or --data-binary @body.json"
                ) from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed json body: {exc.msg}") from exc
            if not isinstance(data, dict):
                raise ValueError("json body must be an object")
            return data

        def _decode_body(self, raw_body: bytes) -> str:
            content_type = self.headers.get("Content-Type") or ""
            charset = ""
            for item in content_type.split(";"):
                item = item.strip()
                if item.lower().startswith("charset="):
                    charset = item.split("=", 1)[1].strip()
                    break

            encodings = []
            if charset:
                encodings.append(charset)
            encodings.extend(["utf-8", "utf-8-sig", "gbk", locale.getpreferredencoding(False)])

            last_error = None
            for encoding in dict.fromkeys(encodings):
                try:
                    return raw_body.decode(encoding)
                except UnicodeDecodeError as exc:
                    last_error = exc
            if last_error:
                raise last_error
            return raw_body.decode("utf-8")

        def _send_json(self, status: HTTPStatus, payload: Dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self._record_json_metric(status, payload)

        def _send_binary(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self._record_binary_metric(status)

        def _send_stream(
            self,
            status: HTTPStatus,
            events: Iterable[Dict[str, object]],
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            for item in events:
                self._write_chunk((json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))

            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            self._record_stream_metric(status)

        def _write_chunk(self, data: bytes) -> None:
            if not data:
                return
            size = f"{len(data):X}\r\n".encode("ascii")
            self.wfile.write(size)
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()

    server = ThreadingHTTPServer((config.host, config.port), OverstatsRequestHandler)
    original_server_close = server.server_close

    def server_close() -> None:
        dashen_api_client.request_metrics_recorder = previous_request_metrics_recorder
        async_runner.run(ow_hero_leaderboard_sync_service.close())
        async_runner.run(request_metrics_recorder.close())
        async_runner.close()
        original_server_close()

    server.server_close = server_close
    server.ow_hero_leaderboard_sync_service = ow_hero_leaderboard_sync_service
    return server
