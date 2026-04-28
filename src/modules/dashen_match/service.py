from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from dataclasses import dataclass, field
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

try:
    from overstats.config import config as app_config
    from overstats.src.client.apiclient import DashenAPIClient
    from overstats.src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from config import config as app_config
    from src.client.apiclient import DashenAPIClient
    from src.modules.bnet_search import BnetSearchModule, BnetSearchResult, bnet_search_module
    from src.modules.errors import ModuleError

from .enhanced_render import (
    build_carry_index_data,
    build_target_hero_icons,
    calculate_match_scores,
    decorate_rendered_image_header,
    generate_detailed_stats_text,
    generate_match_summary_text,
    map_icon_image_for_match,
    map_name_for_match,
    render_all_players_waterfall,
    render_analysis_report,
    render_player_hero_detail,
)
from .render import (
    RenderedImage,
    _extract_match_detail_data,
    _load_ow_config,
    _sort_players,
    render_match_detail,
    render_match_list,
)
from .requests import DashenMatchDetail, DashenMatchQuery, DashenMatchRequests


PLAYER_TOKEN_CACHE_TTL = 600
PLAYER_TOKEN_CACHE_MAX = 512
PLAYER_DETAIL_CACHE_TTL = 1800
PLAYER_DETAIL_CACHE_MAX = 512
PLAYER_CARD_CACHE_TTL = 1800
PLAYER_CARD_CACHE_MAX = 512
REPLY_CONTEXT_CACHE_TTL = 1800
REPLY_CONTEXT_CACHE_MAX = 256

_CACHE_LOCK = threading.RLock()
_PLAYER_TOKEN_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_PLAYER_DETAIL_CACHE: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
_PLAYER_CARD_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_REPLY_CONTEXT_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def _cache_get(cache: OrderedDict, key: Any) -> Any:
    with _CACHE_LOCK:
        item = cache.get(key)
        if not isinstance(item, dict):
            return None
        if time.time() >= float(item.get("expiry", 0) or 0):
            cache.pop(key, None)
            return None
        try:
            cache.move_to_end(key)
        except Exception:
            pass
        return item.get("value")


def _cache_put(cache: OrderedDict, key: Any, value: Any, *, ttl: int, max_size: int) -> None:
    with _CACHE_LOCK:
        now = time.time()
        cache[key] = {"value": value, "created_at": now, "expiry": now + max(1, int(ttl))}
        try:
            cache.move_to_end(key)
        except Exception:
            pass
        while len(cache) > max_size:
            cache.popitem(last=False)


def _sanitize_api_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "replace-with-your" in text.lower():
        return ""
    return text


def _analysis_model_for_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().lower()
    if "generativelanguage.googleapis.com" in normalized or "googleapis.com" in normalized:
        return str(getattr(app_config, "ANALYSIS_GOOGLE_MODEL", "gemini-3.1-flash-lite-preview") or "gemini-3.1-flash-lite-preview")
    if "deepseek" in normalized:
        return str(getattr(app_config, "ANALYSIS_DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat")
    return str(getattr(app_config, "ANALYSIS_OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini")


def _resolved_payload(resolved: Optional[BnetSearchResult]) -> Optional[Dict[str, Any]]:
    if not resolved:
        return None
    return {
        "query": resolved.query,
        "full_id": resolved.full_id,
        "bnet_id": resolved.bnet_id,
        "customer_token": resolved.customer_token,
        "has_customer_token": bool(resolved.customer_token),
    }


def _image_reply(rendered: RenderedImage) -> Dict[str, Any]:
    return {
        "type": "image",
        "media_type": rendered.media_type,
        "base64": base64.b64encode(rendered.content).decode("ascii"),
    }


def _text_reply(text: str) -> Dict[str, Any]:
    return {"type": "text", "data": str(text or "")}


def _meta_reply(meta_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "meta", "meta_type": meta_type, "data": data}


def _extract_llm_message_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return str(message.get("content") or "")
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_llm_message_content(data)
    return ""


def _clean_llm_text(text: Any) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _parse_analysis_json(text: Any) -> Optional[Dict[str, Any]]:
    cleaned = _clean_llm_text(text)
    if not cleaned:
        return None
    candidates = [cleaned]
    candidates.extend(re.findall(r"\{.*\}", cleaned, flags=re.DOTALL))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


@dataclass(frozen=True)
class DashenMatchListOutput:
    matches: List[Dict[str, Any]]
    customer_token: str
    resolved_bnet: Optional[BnetSearchResult] = None
    image: Optional[RenderedImage] = None


@dataclass(frozen=True)
class DashenMatchDetailOutput:
    detail: DashenMatchDetail
    customer_token: str
    resolved_bnet: Optional[BnetSearchResult] = None
    image: Optional[RenderedImage] = None


@dataclass(frozen=True)
class DashenMatchRepliesOutput:
    customer_token: str
    resolved_bnet: Optional[BnetSearchResult] = None
    replies: List[Dict[str, Any]] = field(default_factory=list)
    match_id: str = ""
    match_kind: str = ""


class DashenMatchModule:
    def __init__(
        self,
        api_client: Optional[DashenAPIClient] = None,
        search_module: Optional[BnetSearchModule] = None,
    ) -> None:
        self.requests = DashenMatchRequests(api_client)
        self.search_module = search_module or bnet_search_module

    async def query_match_list(self, query: DashenMatchQuery, *, render: bool = True) -> DashenMatchListOutput:
        query, resolved_bnet = await self._resolve_query(query)
        matches = await self.requests.list_recent_matches(query)
        full_id = resolved_bnet.full_id if resolved_bnet else (query.bnet_id or f"token:{query.customer_token}")
        image = render_match_list(matches, full_id=full_id) if render else None
        self._store_reply_context(query, resolved_bnet, matches)
        return DashenMatchListOutput(
            matches=matches,
            customer_token=query.customer_token,
            resolved_bnet=resolved_bnet,
            image=image,
        )

    async def query_match_list_replies(self, query: DashenMatchQuery) -> DashenMatchRepliesOutput:
        result = await self.query_match_list(query, render=True)
        full_id = result.resolved_bnet.full_id if result.resolved_bnet else (query.bnet_id or f"token:{result.customer_token}")
        replies = [
            _meta_reply(
                "ds_match_list",
                {
                    "context_type": "ds_match_list",
                    "full_id": full_id,
                    "resolved": _resolved_payload(result.resolved_bnet),
                    "match_entries": result.matches,
                },
            ),
        ]
        if result.image:
            replies.append(_image_reply(result.image))
        return DashenMatchRepliesOutput(
            customer_token=result.customer_token,
            resolved_bnet=result.resolved_bnet,
            replies=replies,
        )

    async def query_match_detail(
        self,
        customer_token: str,
        match: Dict[str, Any] | str,
        *,
        query_full_id: str = "",
        query_bnet_id: str = "",
        render: bool = True,
    ) -> DashenMatchDetailOutput:
        detail = await self.requests.get_match_detail(customer_token, match)
        image = (
            render_match_detail(
                detail.payload,
                source_match=detail.source_match,
                query_full_id=query_full_id,
                query_bnet_id=query_bnet_id,
            )
            if render
            else None
        )
        return DashenMatchDetailOutput(detail=detail, customer_token=customer_token, image=image)

    async def query_match_detail_by_index(
        self,
        query: DashenMatchQuery,
        index: int,
        *,
        render: bool = True,
    ) -> DashenMatchDetailOutput:
        query, resolved_bnet = await self._resolve_query(query)
        matches = await self._list_matches_for_query(query, resolved_bnet)
        if index < 0 or index >= len(matches):
            raise ModuleError(
                error="match_index_out_of_range",
                message=f"Match index out of range: {index}",
                status_code=400,
                hint=f"Use an index from 0 to {max(len(matches) - 1, 0)}.",
                details={"index": index, "match_count": len(matches)},
            )
        detail = await self.requests.get_match_detail(query.customer_token, matches[index])
        image = (
            render_match_detail(
                detail.payload,
                source_match=detail.source_match,
                query_full_id=resolved_bnet.full_id if resolved_bnet else query.bnet_id,
                query_bnet_id=resolved_bnet.bnet_id if resolved_bnet else "",
            )
            if render
            else None
        )
        return DashenMatchDetailOutput(
            detail=detail,
            customer_token=query.customer_token,
            resolved_bnet=resolved_bnet,
            image=image,
        )

    async def query_match_detail_replies(
        self,
        *,
        query: Optional[DashenMatchQuery] = None,
        customer_token: str = "",
        match_id: str = "",
        index: Optional[int] = None,
        show_all_heroes: bool = False,
        analyze: bool = False,
    ) -> DashenMatchRepliesOutput:
        resolved_query: Optional[DashenMatchQuery] = None
        resolved_bnet: Optional[BnetSearchResult] = None
        source_match: Dict[str, Any] = {}

        if match_id:
            direct_customer_token = str(customer_token or (query.customer_token if query else "")).strip()
            if not direct_customer_token:
                raise ModuleError(
                    error="missing_customer_token",
                    message="customer_token is required when querying detail by match_id directly.",
                    status_code=400,
                    hint='Use {"bnet_id":"Player#12345","index":0} or provide customer_token with match_id.',
                )
            customer_token = direct_customer_token
            if query and query.bnet_id:
                try:
                    _, resolved_bnet = await self._resolve_query(query)
                except Exception:
                    resolved_bnet = None
            detail = await self._get_match_detail_direct(customer_token, match_id)
        else:
            if query is None or index is None:
                raise ModuleError(
                    error="missing_match_selector",
                    message="index or match_id is required for match detail.",
                    status_code=400,
                    hint='Example: {"bnet_id":"Player#12345","index":0}',
                )
            resolved_query, resolved_bnet = await self._resolve_query(query)
            customer_token = resolved_query.customer_token
            matches = await self._list_matches_for_query(resolved_query, resolved_bnet)
            if index < 0 or index >= len(matches):
                raise ModuleError(
                    error="match_index_out_of_range",
                    message=f"Match index out of range: {index}",
                    status_code=400,
                    hint=f"Use an index from 0 to {max(len(matches) - 1, 0)}.",
                    details={"index": index, "match_count": len(matches)},
                )
            source_match = dict(matches[index])
            detail = await self.requests.get_match_detail(customer_token, source_match)

        query_full_id = (
            (resolved_bnet.full_id if resolved_bnet else "")
            or (resolved_query.bnet_id if resolved_query else "")
            or (query.bnet_id if query else "")
            or f"token:{customer_token[:8]}"
        )
        query_bnet_id = (resolved_bnet.bnet_id if resolved_bnet else "") or (str(query.bnet_id or "") if query else "")

        main_image = render_match_detail(
            detail.payload,
            source_match=detail.source_match or source_match,
            query_full_id=query_full_id,
            query_bnet_id=query_bnet_id,
        )
        main_image = decorate_rendered_image_header(
            main_image,
            query_full_id,
            bnet_id=query_bnet_id,
            subtitle="角斗对局主战绩" if detail.match_kind == "fight" else "大神对局主战绩",
        )

        detail_root = _extract_match_detail_data(detail.payload)
        ordered_player_ids = self._ordered_player_ids(detail_root)
        is_competitive_match = self._is_competitive_match(detail_root, detail.match_kind, detail.source_match or source_match)
        replies = [
            _meta_reply(
                "ds_match_detail_players",
                {
                    "context_type": "ds_match_detail_players",
                    "player_ids": ordered_player_ids if detail.match_kind != "fight" else [],
                    "competitive": bool(is_competitive_match),
                },
            ),
            _image_reply(main_image),
        ]

        if detail.match_kind == "fight":
            if show_all_heroes or analyze:
                replies.append(_text_reply("角斗对局暂不支持全员详细或 AI锐评。"))
            return DashenMatchRepliesOutput(
                customer_token=customer_token,
                resolved_bnet=resolved_bnet,
                replies=replies,
                match_id=detail.match_id,
                match_kind=detail.match_kind,
            )

        focus_player = self._find_focus_player(detail_root, query_full_id=query_full_id, query_bnet_id=query_bnet_id)
        focus_detail = {
            "heroList": detail_root.get("heroList") or (focus_player.get("heroList") if focus_player else []) or [],
            "rankInfo": (focus_player.get("rankInfo") if focus_player else {}) or {},
        }

        if show_all_heroes:
            player_details, target_id = await self._build_all_player_details(
                detail_root,
                detail.match_id,
                query_full_id=query_full_id,
                query_bnet_id=query_bnet_id,
            )
            waterfall = render_all_players_waterfall(player_details, match_game_time_sec=detail_root.get("gameTimeSec"))
            waterfall = decorate_rendered_image_header(waterfall, query_full_id, bnet_id=query_bnet_id, subtitle="全员详细数据")
            replies.append(_image_reply(waterfall))
            if analyze:
                analysis_result = await self._build_ai_analysis(
                    match_data=detail_root,
                    all_player_details=player_details,
                    target_id=target_id,
                )
                if analysis_result.get("json") is not None:
                    json_data = dict(analysis_result["json"])
                    json_data["generated_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                    analysis_image = render_analysis_report(
                        json_data,
                        target_hero_images=build_target_hero_icons(focus_detail["heroList"], size=40),
                        map_name=map_name_for_match(detail_root),
                        map_icon_img=map_icon_image_for_match(detail_root),
                        match_result=self._match_result_text(detail_root),
                        footer_source=analysis_result.get("footer_source"),
                    )
                    replies.append(_image_reply(analysis_image))
                else:
                    replies.append(_text_reply(analysis_result.get("fallback_text") or "AI锐评暂不可用。"))
        else:
            detail_image = render_player_hero_detail(
                query_full_id,
                focus_detail,
                match_game_time_sec=detail_root.get("gameTimeSec"),
            )
            detail_image = decorate_rendered_image_header(detail_image, query_full_id, bnet_id=query_bnet_id, subtitle="英雄详细数据")
            replies.append(_image_reply(detail_image))

        return DashenMatchRepliesOutput(
            customer_token=customer_token,
            resolved_bnet=resolved_bnet,
            replies=replies,
            match_id=detail.match_id,
            match_kind=detail.match_kind,
        )

    async def query_match_list_by_bnet_id(
        self,
        bnet_id: str,
        *,
        render: bool = True,
        **query_options: Any,
    ) -> DashenMatchListOutput:
        return await self.query_match_list(DashenMatchQuery(bnet_id=bnet_id, **query_options), render=render)

    async def query_match_detail_by_bnet_id(
        self,
        bnet_id: str,
        index: int,
        *,
        render: bool = True,
        **query_options: Any,
    ) -> DashenMatchDetailOutput:
        return await self.query_match_detail_by_index(
            DashenMatchQuery(bnet_id=bnet_id, **query_options),
            index,
            render=render,
        )

    async def _resolve_query(self, query: DashenMatchQuery) -> tuple[DashenMatchQuery, Optional[BnetSearchResult]]:
        if query.customer_token:
            return query, None
        if not query.bnet_id:
            raise ModuleError(
                error="missing_target",
                message="Missing query target: bnet_id or customer_token is required.",
                status_code=400,
                hint='Example: {"bnet_id":"Player#12345","limit":20}',
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
        resolved_query = DashenMatchQuery(
            customer_token=customer_token,
            bnet_id=search_output.result.full_id,
            seasons=query.seasons,
            include_previous_season=query.include_previous_season,
            include_fight=query.include_fight,
            target_count=query.target_count,
            filters=query.filters,
        )
        return resolved_query, search_output.result

    def _reply_context_cache_key(self, query: DashenMatchQuery, resolved_bnet: Optional[BnetSearchResult]) -> str:
        return json.dumps(
            {
                "customer_token": query.customer_token,
                "full_id": resolved_bnet.full_id if resolved_bnet else query.bnet_id,
                "target_count": int(query.target_count),
                "include_fight": bool(query.include_fight),
                "include_previous_season": bool(query.include_previous_season),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _store_reply_context(
        self,
        query: DashenMatchQuery,
        resolved_bnet: Optional[BnetSearchResult],
        matches: List[Dict[str, Any]],
    ) -> None:
        _cache_put(
            _REPLY_CONTEXT_CACHE,
            self._reply_context_cache_key(query, resolved_bnet),
            {"matches": matches, "resolved_bnet": resolved_bnet},
            ttl=REPLY_CONTEXT_CACHE_TTL,
            max_size=REPLY_CONTEXT_CACHE_MAX,
        )

    async def _list_matches_for_query(self, query: DashenMatchQuery, resolved_bnet: Optional[BnetSearchResult]) -> List[Dict[str, Any]]:
        cached = _cache_get(_REPLY_CONTEXT_CACHE, self._reply_context_cache_key(query, resolved_bnet))
        if isinstance(cached, dict) and isinstance(cached.get("matches"), list):
            return list(cached["matches"])
        matches = await self.requests.list_recent_matches(query)
        self._store_reply_context(query, resolved_bnet, matches)
        return matches

    async def _get_match_detail_direct(self, customer_token: str, match_id: str) -> DashenMatchDetail:
        last_error: Optional[Exception] = None
        try:
            payload = await self.requests.api_client.query_match_info(customer_token, match_id)
            root = _extract_match_detail_data(payload)
            if root.get("teammateList") or root.get("enemyList") or root.get("heroList"):
                return DashenMatchDetail(match_id=match_id, match_kind="normal", payload=payload, source_match={})
        except Exception as exc:
            last_error = exc
        try:
            payload = await self.requests.api_client.fight_query_match_info(customer_token, match_id)
            root = _extract_match_detail_data(payload)
            if root.get("roundCountList") or root.get("totalCount") or root.get("teammateList") or root.get("enemyList"):
                return DashenMatchDetail(match_id=match_id, match_kind="fight", payload=payload, source_match={})
        except Exception as exc:
            last_error = exc
        if last_error is not None:
            raise last_error
        return DashenMatchDetail(match_id=match_id, match_kind="normal", payload={}, source_match={})

    def _ordered_player_ids(self, detail_root: Dict[str, Any]) -> List[str]:
        config = _load_ow_config()
        ordered: List[str] = []
        for team_key in ("teammateList", "enemyList"):
            for player in _sort_players(detail_root.get(team_key, []), config):
                name = str(player.get("name") or "").strip()
                if name:
                    ordered.append(name)
        return ordered

    def _is_competitive_match(self, detail_root: Dict[str, Any], match_kind: str, source_match: Optional[Dict[str, Any]]) -> bool:
        if match_kind == "fight":
            return "sportfight" in str((source_match or {}).get("gameMode") or "").lower()
        for player in list(detail_root.get("teammateList") or []) + list(detail_root.get("enemyList") or []):
            rank_info = player.get("rankInfo") or {}
            try:
                if int(rank_info.get("rankScore") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return "sport" in str((source_match or {}).get("gameMode") or detail_root.get("gameMode") or "").lower()

    def _find_focus_player(self, detail_root: Dict[str, Any], *, query_full_id: str, query_bnet_id: str) -> Dict[str, Any]:
        normalized_full = str(query_full_id or "").strip().lower()
        normalized_tag = normalized_full.split("#", 1)[0]
        normalized_bnet_id = str(query_bnet_id or "").strip()
        for player in list(detail_root.get("teammateList") or []) + list(detail_root.get("enemyList") or []):
            player_name = str(player.get("name") or "").strip().lower()
            player_tag = player_name.split("#", 1)[0]
            player_bnet_id = str(player.get("bnetId") or "").strip()
            if normalized_bnet_id and player_bnet_id and normalized_bnet_id == player_bnet_id:
                return dict(player)
            if normalized_full and player_name == normalized_full:
                return dict(player)
            if normalized_tag and player_tag == normalized_tag:
                return dict(player)
        return {}

    async def _build_all_player_details(
        self,
        detail_root: Dict[str, Any],
        match_id: str,
        *,
        query_full_id: str,
        query_bnet_id: str,
    ) -> tuple[List[Dict[str, Any]], str]:
        focus_player = self._find_focus_player(detail_root, query_full_id=query_full_id, query_bnet_id=query_bnet_id)
        target_id = str(focus_player.get("name") or query_full_id or "").strip() or query_full_id
        all_targets: List[Dict[str, Any]] = []
        for team_key, team_type in (("teammateList", "teammate"), ("enemyList", "enemy")):
            for player in detail_root.get(team_key, []) or []:
                name = str(player.get("name") or "").strip()
                if not name or "#" not in name:
                    continue
                all_targets.append(
                    {
                        "name": name,
                        "team_type": team_type,
                        "rankInfo": player.get("rankInfo") or {},
                        "bnet_id": str(player.get("bnetId") or ""),
                    }
                )

        async def fetch_target(target: Dict[str, Any]) -> Dict[str, Any]:
            full_name = str(target.get("name") or "")
            if full_name.lower() == target_id.lower():
                token = await self._resolve_player_customer_token(full_name)
                try:
                    card_payload = await self._fetch_cached_player_card(token) if token else {}
                except Exception:
                    card_payload = {}
                card_data = card_payload.get("data") if isinstance(card_payload, dict) and isinstance(card_payload.get("data"), dict) else {}
                return {
                    "name": full_name,
                    "heroList": detail_root.get("heroList") or [],
                    "bnet_id": target.get("bnet_id") or query_bnet_id,
                    "rankInfo": target.get("rankInfo") or {},
                    "team_type": target.get("team_type"),
                    "icon": str(card_data.get("icon") or "").strip(),
                    "success": True,
                }
            token = await self._resolve_player_customer_token(full_name)
            if not token:
                return {"name": full_name, "team_type": target.get("team_type"), "success": False}
            detail_payload, card_payload = await asyncio.gather(
                self._fetch_cached_player_match_detail(token, match_id),
                self._fetch_cached_player_card(token),
                return_exceptions=True,
            )
            payload = detail_payload if isinstance(detail_payload, dict) else {}
            root = _extract_match_detail_data(payload)
            card_data = card_payload.get("data") if isinstance(card_payload, dict) and isinstance(card_payload.get("data"), dict) else {}
            return {
                "name": full_name,
                "heroList": root.get("heroList") or [],
                "bnet_id": target.get("bnet_id"),
                "rankInfo": target.get("rankInfo") or {},
                "team_type": target.get("team_type"),
                "icon": str(card_data.get("icon") or "").strip(),
                "success": bool(root.get("heroList")),
            }

        results = await asyncio.gather(*(fetch_target(item) for item in all_targets), return_exceptions=True)
        valid: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception) or not isinstance(result, dict):
                continue
            if result.get("success") and result.get("heroList"):
                valid.append(result)

        if not any(str(item.get("name") or "").lower() == target_id.lower() for item in valid) and detail_root.get("heroList"):
            team_type = "teammate"
            focus_name = str(focus_player.get("name") or "").strip()
            for enemy in detail_root.get("enemyList", []) or []:
                if str(enemy.get("name") or "").strip() == focus_name:
                    team_type = "enemy"
                    break
            valid.insert(
                0,
                {
                    "name": target_id,
                    "heroList": detail_root.get("heroList") or [],
                    "bnet_id": query_bnet_id,
                    "rankInfo": focus_player.get("rankInfo") or {},
                    "team_type": team_type,
                    "icon": "",
                    "success": True,
                },
            )
        ordered_names = {name.lower(): idx for idx, name in enumerate(self._ordered_player_ids(detail_root))}
        valid.sort(
            key=lambda item: (
                ordered_names.get(str(item.get("name") or "").lower(), 10_000),
                0 if item.get("team_type") == "teammate" else 1,
                str(item.get("name") or "").lower(),
            )
        )
        return valid, target_id

    async def _resolve_player_customer_token(self, full_name: str) -> str:
        cache_key = str(full_name or "").strip().lower()
        cached = _cache_get(_PLAYER_TOKEN_CACHE, cache_key)
        if isinstance(cached, str):
            return cached
        try:
            search_output = await self.search_module.search(full_name, render=False)
        except Exception:
            return ""
        customer_token = search_output.result.customer_token
        if customer_token:
            _cache_put(_PLAYER_TOKEN_CACHE, cache_key, customer_token, ttl=PLAYER_TOKEN_CACHE_TTL, max_size=PLAYER_TOKEN_CACHE_MAX)
        return customer_token

    async def _fetch_cached_player_match_detail(self, customer_token: str, match_id: str) -> Dict[str, Any]:
        cache_key = (str(customer_token or ""), str(match_id or ""))
        cached = _cache_get(_PLAYER_DETAIL_CACHE, cache_key)
        if isinstance(cached, dict):
            return cached
        payload = await self.requests.api_client.query_match_info(customer_token, match_id)
        _cache_put(_PLAYER_DETAIL_CACHE, cache_key, payload, ttl=PLAYER_DETAIL_CACHE_TTL, max_size=PLAYER_DETAIL_CACHE_MAX)
        return payload

    async def _fetch_cached_player_card(self, customer_token: str) -> Dict[str, Any]:
        cache_key = str(customer_token or "").strip()
        if not cache_key:
            return {}
        cached = _cache_get(_PLAYER_CARD_CACHE, cache_key)
        if isinstance(cached, dict):
            return cached
        payload = await self.requests.api_client.query_card(cache_key)
        card_data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
        icon_url = str(card_data.get("icon") or "").strip()
        if icon_url:
            try:
                await self.requests.api_client.get_icon(icon_url)
            except Exception:
                pass
        _cache_put(_PLAYER_CARD_CACHE, cache_key, payload, ttl=PLAYER_CARD_CACHE_TTL, max_size=PLAYER_CARD_CACHE_MAX)
        return payload

    async def _build_ai_analysis(
        self,
        *,
        match_data: Dict[str, Any],
        all_player_details: List[Dict[str, Any]],
        target_id: str,
    ) -> Dict[str, Any]:
        summary_text = generate_match_summary_text(match_data, target_id)
        detailed_text = generate_detailed_stats_text(all_player_details, target_id)
        score_bundle = calculate_match_scores(match_data)
        persona_prompt = str(getattr(app_config, "ANALYSIS_PERSONA_PROMPT", "") or "").strip()
        if persona_prompt:
            persona_prompt = persona_prompt.format(
                target_id=target_id,
                anti_pressure=score_bundle["anti_pressure"],
                teamwork=score_bundle["teamwork"],
                aggressiveness=score_bundle["aggressiveness"],
                match_quality=score_bundle["match_quality"],
            )

        prompt = f"""
{persona_prompt}
【助攻判读补充规则】
不要把“助攻低”或“没有助攻”机械地当成负面结论。对于坦克位和输出位，助攻不是通用核心指标。很多英雄的技能机制、收割定位、爆发击杀方式或单点作战方式，本来就不容易稳定获得助攻。除非该英雄本身明显依赖团队增益、控制、挂状态或持续参与混战，且同场其他数据也能证明其协同性偏低，否则禁止写出无意义的“零助攻/助攻少所以表现差”评价。

【身份】
请扮演一位资深的电竞数据分析师，根据提供的比赛数据，输出一份犀利、简明扼要的分析报告。

【输出要求】
1. 必须严格使用中文，只输出纯 JSON，不要 markdown，不要解释，不要前后缀。
2. 分析必须专业、简明、直接，结论要清晰，不能硬夸，不能胡编。
3. 所有判断都必须以给定数据为准，不得虚构不存在的对局细节。
4. 如果 JSON 字符串内部需要双引号，请转义为 \\\"，避免输出非法 JSON。

【任务】
1. 客观给焦点玩家评分，只能填 S/A/B/C/D。
2. 用一句话指出焦点玩家最大优点或最大问题。
3. 只写一个最关键的胜负手。
4. 必须明确点出真正的 MVP 或背锅位，不能强行偏袒焦点玩家。
5. 必须严格比较三路：坦克位、输出位、辅助位。
6. 要写出最突出的个人表现、关键数据差距，或者同英雄对位 Diff。
7. `attribute_scores` 的数值必须原样保留，不允许改动。

【输出 JSON 模板】
{{
  "player_id": "{target_id}",
  "score": "S/A/B/C/D",
  "general_summary": "一句话核心总结",
  "key_to_win_loss": "决定胜负的唯一核心点",
  "red_black_list": {{
    "mvp_or_potg": "真正的 MVP 或背锅位及依据",
    "role_comparison": [
      "坦克位：[双方对比结论]",
      "输出位：[双方对比结论]",
      "辅助位：[双方对比结论]"
    ],
    "outstanding_performance": "最突出的个人表现、关键数据差距或同英雄对位 Diff"
  }},
  "summary": "一句话总结本场整体观感",
  "attribute_scores": {{
    "anti_pressure": {score_bundle["anti_pressure"]},
    "teamwork": {score_bundle["teamwork"]},
    "aggressiveness": {score_bundle["aggressiveness"]},
    "match_quality": {score_bundle["match_quality"]}
  }},
  "evaluation": "基于四项属性分的针对性评价",
  "extra": "100字以内的人格化鼓励/安慰/小结",
  "carry_index_data": []
}}

【原始比赛数据如下】
{summary_text}
--------------------------------------------------
{detailed_text}
--------------------------------------------------
""".strip()

        base_url = str(getattr(app_config, "ANALYSIS_BASE_URL", "") or "").strip()
        api_key = _sanitize_api_key(getattr(app_config, "ANALYSIS_API_KEY", ""))

        if not base_url or not api_key:
            return {"fallback_text": "AI锐评未配置 ANALYSIS_BASE_URL / ANALYSIS_API_KEY。"}

        model = _analysis_model_for_base_url(base_url)
        try:
            raw = await self._call_openai_compatible(
                self._chat_completion_url(base_url),
                api_key,
                {
                    "model": model,
                    "temperature": 0.2,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            parsed = _parse_analysis_json(_extract_llm_message_content(raw))
            if parsed:
                parsed["carry_index_data"] = build_carry_index_data(match_data)
                return {
                    "json": parsed,
                    "footer_source": "AI锐评",
                }
            return {"fallback_text": f"AI锐评生成失败。错误：invalid json ({model})"}
        except Exception as exc:
            return {"fallback_text": f"AI锐评生成失败。错误：{type(exc).__name__}: {exc}"}

    def _chat_completion_url(self, base_url: str) -> str:
        base = str(base_url or "").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/chat/completions"

    async def _call_openai_compatible(self, url: str, api_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    def _match_result_text(self, match_data: Dict[str, Any]) -> str:
        if match_data.get("matchRet") == 1:
            return "胜利"
        if match_data.get("matchRet") == 0:
            return "平局"
        return "失败"


dashen_match_module = DashenMatchModule()
