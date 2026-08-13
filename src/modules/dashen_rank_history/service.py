from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.src.constants.ranks import get_rank_score, get_rank_sub_tier, raw_rank_score_to_icon_level
    from overstats.src.client.apiclient import DashenAPIClient
    from overstats.src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from overstats.src.modules.dashen_profile import get_live_dashen_season
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.risk_status import RiskStatus, parse_risk_status
    from overstats.src.modules.season_config import get_dashen_history_start_season
except ModuleNotFoundError:
    from src.constants.ranks import get_rank_score, get_rank_sub_tier, raw_rank_score_to_icon_level
    from src.client.apiclient import DashenAPIClient
    from src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from src.modules.dashen_profile import get_live_dashen_season
    from src.modules.errors import ModuleError
    from src.modules.risk_status import RiskStatus, parse_risk_status
    from src.modules.season_config import get_dashen_history_start_season

from .render import HISTORY_SUBTITLE, RenderedImage, collect_missing_assets, render_rank_history
from .requests import (
    DashenRankHistoryQuery,
    DashenRankHistoryRequests,
    DashenRankHistorySeasonPayload,
    fight_payload_has_content,
    payload_data,
    sport_payload_has_content,
)


ROLE_ORDER = ("tank", "dps", "healer", "open")


@dataclass(frozen=True)
class DashenRankHistoryOutput:
    customer_token: str
    full_id: str
    bnet_id: str
    start_season: int
    end_season: int
    seasons: Sequence[Dict[str, Any]]
    raw_seasons: Sequence[DashenRankHistorySeasonPayload]
    missing_assets: Sequence[str]
    resolved_bnet: Optional[BnetSearchResult] = None
    image: Optional[RenderedImage] = None
    risk_status: Optional[RiskStatus] = None


class DashenRankHistoryModule:
    def __init__(
        self,
        api_client: Optional[DashenAPIClient] = None,
        search_module: Optional[BnetSearchModule] = None,
    ) -> None:
        self.requests = DashenRankHistoryRequests(api_client)
        self.search_module = search_module or bnet_search_module

    async def query_rank_history(
        self,
        query: DashenRankHistoryQuery,
        *,
        render: bool = False,
    ) -> DashenRankHistoryOutput:
        query, resolved_bnet = await self._resolve_query(query)
        start_season, end_season = self._resolve_season_range(query.start_season, query.end_season)
        raw_seasons = await self.requests.get_history_payloads(
            query.customer_token,
            start_season=start_season,
            end_season=end_season,
        )
        seasons = self._build_season_summaries(raw_seasons)
        missing_assets = collect_missing_assets(seasons)

        full_id = ""
        bnet_id = ""
        if resolved_bnet is not None:
            full_id = resolved_bnet.full_id
            bnet_id = resolved_bnet.bnet_id
        elif query.bnet_id:
            full_id = query.bnet_id
            bnet_id = query.bnet_id

        image = None
        risk_status = None
        if render:
            try:
                try:
                    card_payload = await self.requests.api_client.query_card(query.customer_token)
                except Exception:
                    card_payload = {}
                card_data = card_payload.get("data") if isinstance(card_payload, dict) else None
                if isinstance(card_data, dict):
                    risk_status = parse_risk_status(card_data)
                    full_id = str(card_data.get("name") or full_id).strip()
                    bnet_id = str(card_data.get("bnetId") or bnet_id).strip()
                image = render_rank_history(
                    player_name=full_id or bnet_id or query.bnet_id or "Unknown",
                    subtitle=HISTORY_SUBTITLE,
                    seasons=seasons,
                    risk_status=risk_status,
                )
            except RuntimeError as exc:
                raise ModuleError(
                    error="render_dependency_missing",
                    message=str(exc),
                    status_code=500,
                    hint="Install Pillow in the runtime environment to enable image rendering.",
                ) from exc

        return DashenRankHistoryOutput(
            customer_token=query.customer_token,
            full_id=full_id or bnet_id or "Unknown",
            bnet_id=bnet_id or full_id or "Unknown",
            start_season=start_season,
            end_season=end_season,
            seasons=tuple(seasons),
            raw_seasons=tuple(raw_seasons),
            missing_assets=tuple(missing_assets),
            risk_status=risk_status,
            resolved_bnet=resolved_bnet,
            image=image,
        )

    async def _resolve_query(self, query: DashenRankHistoryQuery) -> tuple[DashenRankHistoryQuery, Optional[BnetSearchResult]]:
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
            DashenRankHistoryQuery(
                customer_token=customer_token,
                bnet_id=search_output.result.full_id or search_output.result.bnet_id or query.bnet_id,
                start_season=query.start_season,
                end_season=query.end_season,
            ),
            search_output.result,
        )

    def _resolve_season_range(self, start_season: Optional[int], end_season: Optional[int]) -> tuple[int, int]:
        live_season = int(get_live_dashen_season())
        start = int(start_season or get_dashen_history_start_season())
        end = int(end_season or live_season)
        if start <= 0 or end <= 0:
            raise ModuleError(
                error="invalid_season_range",
                message="start_season and end_season must be positive integers.",
                status_code=400,
                details={"start_season": start, "end_season": end},
            )
        if start > end:
            raise ModuleError(
                error="invalid_season_range",
                message="start_season must be less than or equal to end_season.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","start_season":15,"end_season":22}',
                details={"start_season": start, "end_season": end},
            )
        return start, end

    def _build_season_summaries(self, raw_seasons: Sequence[DashenRankHistorySeasonPayload]) -> List[Dict[str, Any]]:
        seasons: List[Dict[str, Any]] = []
        for season_payload in raw_seasons:
            sport_payload = season_payload.sport
            fight_payload = season_payload.fight
            has_sport = bool(sport_payload and sport_payload_has_content(sport_payload))
            has_fight = bool(fight_payload and fight_payload_has_content(fight_payload))
            if not has_sport and not has_fight:
                continue

            sport_data = payload_data(sport_payload)
            fight_data = payload_data(fight_payload)
            seasons.append(
                {
                    "season": season_payload.season,
                    "has_competitive": has_sport,
                    "has_stadium": has_fight,
                    "competitive": self._serialize_competitive(sport_data) if has_sport else None,
                    "stadium": self._serialize_stadium(fight_data) if has_fight else None,
                    "sport_payload": sport_payload,
                    "fight_payload": fight_payload,
                }
            )
        return seasons

    def _serialize_competitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "frequent_hero_ids": [str(item) for item in list(data.get("frequentHeroIds") or []) if str(item or "").strip()],
            "roles": self._serialize_roles(list(data.get("guideCountData") or [])),
        }

    def _serialize_stadium(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "hero_use_summary_ids": [
                str(item.get("heroGuid") or "")
                for item in list(data.get("heroUseSummaryList") or [])
                if isinstance(item, dict) and str(item.get("heroGuid") or "").strip()
            ],
            "roles": self._serialize_roles(list(data.get("roleTypeCountData") or [])),
        }

    def _serialize_roles(self, rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lookup = {str(row.get("roleType") or ""): row for row in rows if isinstance(row, dict)}
        serialized: List[Dict[str, Any]] = []
        for role_type in ROLE_ORDER:
            row = lookup.get(role_type)
            if row is None:
                continue
            last_rank_info = row.get("lastRankInfo") if isinstance(row.get("lastRankInfo"), dict) else {}
            max_rank_info = row.get("maxRankInfo") if isinstance(row.get("maxRankInfo"), dict) else {}
            match_sum = self._safe_int(row.get("matchSum"))
            win_rate = self._safe_float(row.get("winRate"))
            serialized.append(
                {
                    "role_type": role_type,
                    "match_sum": match_sum,
                    "win_rate": win_rate,
                    "win_sum": int(match_sum * win_rate / 100) if match_sum > 0 else 0,
                    "current": {
                        "rank_score": self._safe_int(get_rank_score(last_rank_info)),
                        "rank_sub_tier": self._safe_int(get_rank_sub_tier(last_rank_info)),
                        "rank_level": raw_rank_score_to_icon_level(get_rank_score(last_rank_info)),
                    },
                    "peak": {
                        "rank_score": self._safe_int(get_rank_score(max_rank_info)),
                        "rank_sub_tier": self._safe_int(get_rank_sub_tier(max_rank_info)),
                        "rank_level": raw_rank_score_to_icon_level(get_rank_score(max_rank_info)),
                    },
                }
            )
        return serialized

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


dashen_rank_history_module = DashenRankHistoryModule()
