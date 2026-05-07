from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

try:
    from overstats.src.client.apiclient import DashenAPIClient
    from overstats.src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.query_tool import load_query_tool
    from overstats.src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        RenderedImage,
        render_quick_strength,
    )
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient
    from src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from src.modules.errors import ModuleError
    from src.modules.query_tool import load_query_tool
    from src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        RenderedImage,
        render_quick_strength,
    )

from .engine import DashenCompetitiveStrengthEngine, normalize_limit
from .requests import DashenCompetitiveStrengthQuery, DashenCompetitiveStrengthRequests


@dataclass(frozen=True)
class DashenCompetitiveStrengthSummary:
    match_count: int
    overall_avg_score: float
    overall_avg_rank: str
    score_range: Dict[str, int]
    used_previous_season_fallback: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_count": int(self.match_count),
            "overall_avg_score": float(self.overall_avg_score),
            "overall_avg_rank": str(self.overall_avg_rank),
            "score_range": dict(self.score_range),
            "used_previous_season_fallback": bool(self.used_previous_season_fallback),
        }


@dataclass(frozen=True)
class DashenCompetitiveStrengthMatchPoint:
    match_id: str
    begin_ts: int
    result: int
    map_guid: str
    avg_score: float
    avg_rank: str
    role_range: Dict[str, int]
    all_role_range: Dict[str, int]
    current_role_range: Dict[str, int]
    current_all_role_range: Dict[str, int]
    team_scores: Sequence[int]
    enemy_scores: Sequence[int]
    team_streak_avg: float
    enemy_streak_avg: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "begin_ts": int(self.begin_ts),
            "result": int(self.result),
            "map_guid": self.map_guid,
            "avg_score": float(self.avg_score),
            "avg_rank": self.avg_rank,
            "role_range": dict(self.role_range),
            "all_role_range": dict(self.all_role_range),
            "current_role_range": dict(self.current_role_range),
            "current_all_role_range": dict(self.current_all_role_range),
            "team_scores": [int(score) for score in self.team_scores],
            "enemy_scores": [int(score) for score in self.enemy_scores],
            "team_streak_avg": float(self.team_streak_avg),
            "enemy_streak_avg": float(self.enemy_streak_avg),
        }


@dataclass(frozen=True)
class DashenCompetitiveStrengthOutput:
    customer_token: str
    full_id: str
    bnet_id: str
    summary: DashenCompetitiveStrengthSummary
    matches: Sequence[DashenCompetitiveStrengthMatchPoint]
    resolved_bnet: Optional[BnetSearchResult] = None
    image: Optional[RenderedImage] = None


class DashenCompetitiveStrengthModule:
    def __init__(
        self,
        api_client: Optional[DashenAPIClient] = None,
        search_module: Optional[BnetSearchModule] = None,
    ) -> None:
        self.requests = DashenCompetitiveStrengthRequests(api_client)
        self.engine = DashenCompetitiveStrengthEngine(self.requests)
        self.search_module = search_module or bnet_search_module

    async def query_competitive_strength(
        self,
        query: DashenCompetitiveStrengthQuery,
        *,
        render: bool = False,
    ) -> DashenCompetitiveStrengthOutput:
        query, resolved_bnet = await self._resolve_query(query)
        config = self._load_ow_config()
        computed = await self.engine.build(
            customer_token=query.customer_token,
            limit=normalize_limit(query.limit),
            include_previous_season=bool(query.include_previous_season),
            config=config,
        )
        summary_dict = computed.get("summary") if isinstance(computed.get("summary"), dict) else {}
        match_dicts = [item for item in list(computed.get("matches") or []) if isinstance(item, dict)]
        if not match_dicts:
            raise ModuleError(
                error="competitive_strength_empty",
                message="No competitive matches found for the requested player.",
                status_code=404,
                details={
                    "customer_token": query.customer_token,
                    "bnet_id": query.bnet_id,
                },
            )

        summary = DashenCompetitiveStrengthSummary(
            match_count=int(summary_dict.get("match_count") or len(match_dicts)),
            overall_avg_score=float(summary_dict.get("overall_avg_score") or 0),
            overall_avg_rank=str(summary_dict.get("overall_avg_rank") or "Unranked"),
            score_range=dict(summary_dict.get("score_range") or {"min": 0, "max": 0}),
            used_previous_season_fallback=bool(summary_dict.get("used_previous_season_fallback")),
        )
        matches = tuple(
            DashenCompetitiveStrengthMatchPoint(
                match_id=str(item.get("match_id") or ""),
                begin_ts=int(item.get("begin_ts") or 0),
                result=int(item.get("result") or 0),
                map_guid=str(item.get("map_guid") or ""),
                avg_score=float(item.get("avg_score") or 0),
                avg_rank=str(item.get("avg_rank") or "Unranked"),
                role_range=dict(item.get("role_range") or {"min": 0, "max": 0}),
                all_role_range=dict(item.get("all_role_range") or {"min": 0, "max": 0}),
                current_role_range=dict(item.get("current_role_range") or {"min": 0, "max": 0}),
                current_all_role_range=dict(item.get("current_all_role_range") or {"min": 0, "max": 0}),
                team_scores=tuple(int(score) for score in list(item.get("team_scores") or [])),
                enemy_scores=tuple(int(score) for score in list(item.get("enemy_scores") or [])),
                team_streak_avg=float(item.get("team_streak_avg") or 0),
                enemy_streak_avg=float(item.get("enemy_streak_avg") or 0),
            )
            for item in match_dicts
        )

        full_id = resolved_bnet.full_id if resolved_bnet else (query.bnet_id or "Unknown")
        bnet_id = resolved_bnet.bnet_id if resolved_bnet else (query.bnet_id or "Unknown")
        image = None
        if render:
            avatar_bytes = await self._try_fetch_avatar_bytes(resolved_bnet, query.customer_token)
            try:
                image = render_quick_strength(
                    player_name=full_id,
                    bnet_id=bnet_id,
                    summary=summary.to_dict(),
                    matches=[item.to_dict() for item in matches],
                    avatar_bytes=avatar_bytes,
                    config=config,
                    theme=COMPETITIVE_STRENGTH_THEME,
                    title_text="竞技强度指数",
                    chart_title_text="竞技强度趋势",
                    match_scope_text="竞技",
                )
            except RuntimeError as exc:
                raise ModuleError(
                    error="render_dependency_missing",
                    message=str(exc),
                    status_code=500,
                    hint="Install Pillow in the runtime environment to enable image rendering.",
                ) from exc

        return DashenCompetitiveStrengthOutput(
            customer_token=query.customer_token,
            full_id=full_id,
            bnet_id=bnet_id,
            summary=summary,
            matches=matches,
            resolved_bnet=resolved_bnet,
            image=image,
        )

    async def _resolve_query(
        self,
        query: DashenCompetitiveStrengthQuery,
    ) -> tuple[DashenCompetitiveStrengthQuery, Optional[BnetSearchResult]]:
        if query.customer_token:
            return (
                DashenCompetitiveStrengthQuery(
                    customer_token=query.customer_token,
                    bnet_id=query.bnet_id,
                    limit=normalize_limit(query.limit),
                    include_previous_season=bool(query.include_previous_season),
                ),
                None,
            )

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
            payload = search_output.result.payload
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

        return (
            DashenCompetitiveStrengthQuery(
                customer_token=customer_token,
                bnet_id=search_output.result.full_id or query.bnet_id,
                limit=normalize_limit(query.limit),
                include_previous_season=bool(query.include_previous_season),
            ),
            search_output.result,
        )

    async def _try_fetch_avatar_bytes(
        self,
        resolved_bnet: Optional[BnetSearchResult],
        customer_token: str,
    ) -> Optional[bytes]:
        icon_url = str(resolved_bnet.icon_url or "").strip() if resolved_bnet else ""
        if not icon_url:
            try:
                payload = await self.requests.api_client.query_card(customer_token)
            except Exception as exc:
                print(f"[overstats] failed to fetch competitive-strength profile card: {exc}")
                payload = {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                icon_url = str(data.get("icon") or "").strip()
        if not icon_url:
            return None
        try:
            return await self.requests.api_client.get_icon(icon_url)
        except Exception as exc:
            print(f"[overstats] failed to fetch competitive-strength avatar: {exc}")
            return None

    def _load_ow_config(self) -> Dict[str, Any]:
        try:
            return load_query_tool()
        except Exception as exc:
            print(f"[overstats] failed to load query_tool config for competitive strength: {exc}")
            return {}


dashen_competitive_strength_module = DashenCompetitiveStrengthModule()
