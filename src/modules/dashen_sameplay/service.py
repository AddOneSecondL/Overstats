from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.src.modules.dashen_match import DashenMatchQuery, DashenMatchRequests, dashen_match_module
    from overstats.src.modules.dashen_match.enhanced_render import (
        build_target_hero_icons,
        decorate_rendered_image_header,
        map_icon_image_for_match,
        map_name_for_match,
        render_all_players_waterfall,
        render_analysis_report,
        render_player_hero_detail,
    )
    from overstats.src.modules.dashen_match.render import (
        RenderedImage,
        _extract_match_detail_data,
        render_match_detail,
        render_match_list,
    )
    from overstats.src.modules.dashen_match.requests import get_recent_dashen_seasons, iter_dashen_season_request_values
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.modules.dashen_match import DashenMatchQuery, DashenMatchRequests, dashen_match_module
    from src.modules.dashen_match.enhanced_render import (
        build_target_hero_icons,
        decorate_rendered_image_header,
        map_icon_image_for_match,
        map_name_for_match,
        render_all_players_waterfall,
        render_analysis_report,
        render_player_hero_detail,
    )
    from src.modules.dashen_match.render import (
        RenderedImage,
        _extract_match_detail_data,
        render_match_detail,
        render_match_list,
    )
    from src.modules.dashen_match.requests import get_recent_dashen_seasons, iter_dashen_season_request_values
    from src.modules.errors import ModuleError


SAMEPLAY_CACHE_TTL = 1800
SAMEPLAY_CACHE_MAX = 256
_CACHE_LOCK = threading.RLock()
_SAMEPLAY_LIST_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


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


def _token_preview(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return "unknown"
    return token[:8]


def _is_competitive_mode(match: Dict[str, Any]) -> bool:
    return "sport" in str((match or {}).get("gameMode") or "").lower()


def _safe_begin_ts(match: Dict[str, Any]) -> int:
    try:
        return int(match.get("beginTs") or 0)
    except (TypeError, ValueError):
        return 0


def _merge_unique_sorted_matches(
    existing_matches: Sequence[Dict[str, Any]],
    new_matches: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_ids = set()
    for source in (existing_matches or [], new_matches or []):
        for match in source:
            if not isinstance(match, dict):
                continue
            item = dict(match)
            match_id = str(item.get("matchId") or "").strip()
            if not match_id or match_id in seen_ids:
                continue
            seen_ids.add(match_id)
            merged.append(item)
    merged.sort(key=_safe_begin_ts, reverse=True)
    return merged


@dataclass(frozen=True)
class ResolvedSameplayPlayer:
    query: str
    full_id: str
    bnet_id: str
    customer_token: str

    @property
    def display_name(self) -> str:
        return str(self.full_id or self.query or f"token:{_token_preview(self.customer_token)}").strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "full_id": self.full_id,
            "bnet_id": self.bnet_id,
            "customer_token": self.customer_token,
            "has_customer_token": bool(self.customer_token),
        }


@dataclass(frozen=True)
class DashenSameplayQuery:
    player1_bnet_id: str = ""
    player1_customer_token: str = ""
    player2_bnet_id: str = ""
    player2_customer_token: str = ""
    include_previous_season: bool = True
    limit: int = 20


@dataclass(frozen=True)
class DashenSameplayListOutput:
    player1: ResolvedSameplayPlayer
    player2: ResolvedSameplayPlayer
    summary: Dict[str, Any]
    matches: List[Dict[str, Any]]
    all_matches: List[Dict[str, Any]]
    image: Optional[RenderedImage] = None


@dataclass(frozen=True)
class DashenSameplayDetailPlayerOutput:
    player: ResolvedSameplayPlayer
    available: bool
    detail_payload: Dict[str, Any] = field(default_factory=dict)
    image: Optional[RenderedImage] = None
    note: str = ""


@dataclass(frozen=True)
class DashenSameplayDetailOutput:
    player1: ResolvedSameplayPlayer
    player2: ResolvedSameplayPlayer
    summary: Dict[str, Any]
    matches: List[Dict[str, Any]]
    source_match: Dict[str, Any]
    match_id: str
    detail: Dict[str, Any]
    match_kind: str
    main_image: Optional[RenderedImage]
    main_detail_source_player: int
    player_details: List[DashenSameplayDetailPlayerOutput] = field(default_factory=list)
    waterfall_image: Optional[RenderedImage] = None
    analysis_image: Optional[RenderedImage] = None
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DashenSameplayRepliesOutput:
    player1: ResolvedSameplayPlayer
    player2: ResolvedSameplayPlayer
    summary: Dict[str, Any]
    replies: List[Dict[str, Any]] = field(default_factory=list)
    matches: List[Dict[str, Any]] = field(default_factory=list)
    match_id: str = ""
    match_kind: str = ""


_AUTO_REQUEST_SEASON = object()


@dataclass
class _SameplayModeCursor:
    mode: str
    seasons: List[int]
    season_index: int = 0
    request_season: Any = _AUTO_REQUEST_SEASON
    next_page: int = 1
    completed: bool = False
    oldest_seen_ts: Optional[int] = None


@dataclass
class _SameplayPlayerCursor:
    player: ResolvedSameplayPlayer
    modes: Dict[str, _SameplayModeCursor]
    history: List[Dict[str, Any]] = field(default_factory=list)
    match_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class DashenSameplayModule:
    def __init__(self, requests: Optional[DashenMatchRequests] = None) -> None:
        self.requests = requests or DashenMatchRequests()
        self.match_module = dashen_match_module

    async def query_sameplay_list(self, query: DashenSameplayQuery, *, render: bool = True) -> DashenSameplayListOutput:
        player1, player2 = await self._resolve_players(query)
        visible_limit = self._clamp_limit(query.limit)
        common_output = await self._list_common_matches(
            player1,
            player2,
            include_previous_season=query.include_previous_season,
            required_count=visible_limit,
        )
        visible_matches = list(common_output["matches"])[:visible_limit]
        summary = dict(common_output["summary"])
        summary["returned_count"] = len(visible_matches)
        image = None
        if render:
            image = render_match_list(
                visible_matches,
                title=f"{player1.display_name} & {player2.display_name} 同玩对局",
                footer_lines=[self._build_list_footer(summary, scan_complete=bool(common_output.get("scan_complete")))],
                hint_text="回复此图片并 @机器人 发送 1 / 1* / 1**，可按序号查看同玩对局详情",
            )
        return DashenSameplayListOutput(
            player1=player1,
            player2=player2,
            summary=summary,
            matches=visible_matches,
            all_matches=list(common_output["matches"]),
            image=image,
        )

    async def query_sameplay_list_replies(self, query: DashenSameplayQuery) -> DashenSameplayRepliesOutput:
        result = await self.query_sameplay_list(query, render=True)
        replies = [
            _meta_reply(
                "ds_sameplay_list",
                {
                    "context_type": "ds_sameplay_list",
                    "players": {
                        "player1": result.player1.to_dict(),
                        "player2": result.player2.to_dict(),
                    },
                    "customer_tokens": {
                        "player1": result.player1.customer_token,
                        "player2": result.player2.customer_token,
                    },
                    "summary": dict(result.summary),
                    "match_entries": list(result.matches),
                },
            )
        ]
        if result.image:
            replies.append(_image_reply(result.image))
        return DashenSameplayRepliesOutput(
            player1=result.player1,
            player2=result.player2,
            summary=dict(result.summary),
            replies=replies,
            matches=list(result.matches),
        )

    async def query_sameplay_detail(
        self,
        query: DashenSameplayQuery,
        *,
        index: Optional[int] = None,
        match_id: str = "",
        show_all_heroes: bool = False,
        analyze: bool = False,
        render: bool = True,
    ) -> DashenSameplayDetailOutput:
        player1, player2 = await self._resolve_players(query)
        force_full_scan = bool(match_id)
        required_count = None if force_full_scan else max(1, int(index or 0) + 1)
        common_output = await self._list_common_matches(
            player1,
            player2,
            include_previous_season=query.include_previous_season,
            required_count=required_count,
            force_full_scan=force_full_scan,
        )
        source_match = self._select_source_match(common_output["matches"], index=index, match_id=match_id)
        detail, source_player_index = await self._fetch_main_match_detail(player1, player2, source_match)
        detail_root = _extract_match_detail_data(detail.payload)

        main_image = None
        if render:
            main_image = render_match_detail(
                detail.payload,
                source_match=source_match,
                query_full_id=player1.full_id,
                query_bnet_id=player1.bnet_id,
            )
            main_image = decorate_rendered_image_header(
                main_image,
                player1.display_name,
                bnet_id=player1.bnet_id,
                subtitle="同玩对局主战绩",
            )

        player_details = await asyncio.gather(
            self._build_focus_player_output(player1, source_match, render=render),
            self._build_focus_player_output(player2, source_match, render=render),
        )
        notes = [item.note for item in player_details if item.note]

        waterfall_image = None
        analysis_image = None
        if render and show_all_heroes:
            focus_player = player1 if source_player_index == 1 else player2
            all_player_details, target_id = await self.match_module._build_all_player_details(
                detail_root,
                detail.match_id,
                query_full_id=focus_player.full_id,
                query_bnet_id=focus_player.bnet_id,
            )
            if all_player_details:
                waterfall_image = render_all_players_waterfall(
                    all_player_details,
                    match_game_time_sec=detail_root.get("gameTimeSec"),
                )
                waterfall_image = decorate_rendered_image_header(
                    waterfall_image,
                    focus_player.display_name,
                    bnet_id=focus_player.bnet_id,
                    subtitle="全员详细数据",
                )
                if analyze:
                    analysis = await self.match_module._build_ai_analysis(
                        match_data=detail_root,
                        all_player_details=all_player_details,
                        target_id=target_id,
                    )
                    if analysis.get("json") is not None:
                        json_data = dict(analysis["json"])
                        json_data["generated_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                        focus_detail = next(
                            (
                                item
                                for item in all_player_details
                                if str(item.get("name") or "").strip().lower() == str(target_id).strip().lower()
                            ),
                            {},
                        )
                        analysis_image = render_analysis_report(
                            json_data,
                            target_hero_images=build_target_hero_icons(focus_detail.get("heroList") or [], size=40),
                            map_name=map_name_for_match(detail_root),
                            map_icon_img=map_icon_image_for_match(detail_root),
                            match_result=self.match_module._match_result_text(detail_root),
                            footer_source=analysis.get("footer_source"),
                        )
                    elif analysis.get("fallback_text"):
                        notes.append(str(analysis.get("fallback_text")))

        summary = dict(common_output["summary"])
        summary["returned_count"] = min(self._clamp_limit(query.limit), len(common_output["matches"]))
        return DashenSameplayDetailOutput(
            player1=player1,
            player2=player2,
            summary=summary,
            matches=list(common_output["matches"]),
            source_match=dict(source_match),
            match_id=detail.match_id,
            detail=detail.payload,
            match_kind=detail.match_kind,
            main_image=main_image,
            main_detail_source_player=source_player_index,
            player_details=list(player_details),
            waterfall_image=waterfall_image,
            analysis_image=analysis_image,
            notes=notes,
        )

    async def query_sameplay_detail_replies(
        self,
        query: DashenSameplayQuery,
        *,
        index: Optional[int] = None,
        match_id: str = "",
        show_all_heroes: bool = False,
        analyze: bool = False,
    ) -> DashenSameplayRepliesOutput:
        detail_output = await self.query_sameplay_detail(
            query,
            index=index,
            match_id=match_id,
            show_all_heroes=show_all_heroes,
            analyze=analyze,
            render=True,
        )
        detail_root = _extract_match_detail_data(detail_output.detail)
        replies: List[Dict[str, Any]] = [
            _meta_reply(
                "ds_match_detail_players",
                {
                    "context_type": "ds_match_detail_players",
                    "player_ids": self.match_module._ordered_player_ids(detail_root),
                    "competitive": bool(
                        self.match_module._is_competitive_match(
                            detail_root,
                            detail_output.match_kind,
                            detail_output.source_match,
                        )
                    ),
                },
            )
        ]
        if detail_output.main_image:
            replies.append(_image_reply(detail_output.main_image))
        for player_output in detail_output.player_details:
            if player_output.image:
                replies.append(_image_reply(player_output.image))
        for note in detail_output.notes:
            replies.append(_text_reply(note))
        if detail_output.waterfall_image:
            replies.append(_image_reply(detail_output.waterfall_image))
        if detail_output.analysis_image:
            replies.append(_image_reply(detail_output.analysis_image))
        return DashenSameplayRepliesOutput(
            player1=detail_output.player1,
            player2=detail_output.player2,
            summary=dict(detail_output.summary),
            replies=replies,
            matches=list(detail_output.matches),
            match_id=detail_output.match_id,
            match_kind=detail_output.match_kind,
        )

    async def _resolve_players(self, query: DashenSameplayQuery) -> tuple[ResolvedSameplayPlayer, ResolvedSameplayPlayer]:
        player1 = await self._resolve_player(query.player1_bnet_id, query.player1_customer_token)
        player2 = await self._resolve_player(query.player2_bnet_id, query.player2_customer_token)
        if player1.customer_token == player2.customer_token:
            raise ModuleError(
                error="sameplay_same_player",
                message="Both sameplay targets resolved to the same player.",
                status_code=400,
                details={
                    "player1": player1.to_dict(),
                    "player2": player2.to_dict(),
                },
            )
        return player1, player2

    async def _resolve_player(self, bnet_id: str, customer_token: str) -> ResolvedSameplayPlayer:
        query = DashenMatchQuery(
            customer_token=str(customer_token or "").strip(),
            bnet_id=str(bnet_id or "").strip(),
            include_fight=False,
            target_count=20,
        )
        resolved_query, resolved_bnet = await self.match_module._resolve_query(query)
        if resolved_bnet is not None:
            return ResolvedSameplayPlayer(
                query=resolved_bnet.query,
                full_id=resolved_bnet.full_id,
                bnet_id=resolved_bnet.bnet_id,
                customer_token=resolved_query.customer_token,
            )
        token_label = f"token:{_token_preview(resolved_query.customer_token)}"
        explicit_bnet_id = str(bnet_id or "").strip()
        return ResolvedSameplayPlayer(
            query=explicit_bnet_id or token_label,
            full_id=explicit_bnet_id or token_label,
            bnet_id=explicit_bnet_id,
            customer_token=resolved_query.customer_token,
        )

    async def _list_common_matches(
        self,
        player1: ResolvedSameplayPlayer,
        player2: ResolvedSameplayPlayer,
        *,
        include_previous_season: bool,
        required_count: Optional[int] = None,
        force_full_scan: bool = False,
    ) -> Dict[str, Any]:
        normalized_required = None if force_full_scan else max(1, int(required_count or 1))
        cache_key = json.dumps(
            {
                "player1_customer_token": player1.customer_token,
                "player2_customer_token": player2.customer_token,
                "include_previous_season": bool(include_previous_season),
                "required_count": normalized_required,
                "force_full_scan": bool(force_full_scan),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        cached = _cache_get(_SAMEPLAY_LIST_CACHE, cache_key)
        if isinstance(cached, dict):
            return {
                "matches": list(cached.get("matches") or []),
                "summary": dict(cached.get("summary") or {}),
                "scan_complete": bool(cached.get("scan_complete")),
            }

        player1_cursor = self._build_player_cursor(player1, include_previous_season=include_previous_season)
        player2_cursor = self._build_player_cursor(player2, include_previous_season=include_previous_season)
        common_by_id: Dict[str, Dict[str, Any]] = {}

        while True:
            player1_new, player2_new = await asyncio.gather(
                self._advance_player_cursor(player1_cursor),
                self._advance_player_cursor(player2_cursor),
            )
            if player1_new:
                self._update_common_matches(common_by_id, player1_cursor, player2_cursor, player1_new)
            if player2_new:
                self._update_common_matches(common_by_id, player1_cursor, player2_cursor, player2_new)

            common_matches = sorted(common_by_id.values(), key=_safe_begin_ts, reverse=True)
            if normalized_required is not None and self._can_stop_progressive_scan(
                player1_cursor,
                player2_cursor,
                common_matches,
                required_count=normalized_required,
            ):
                break
            if self._all_players_complete(player1_cursor, player2_cursor):
                break

        matches = sorted(common_by_id.values(), key=_safe_begin_ts, reverse=True)
        quick_count = 0
        competitive_count = 0
        for match in matches:
            if _is_competitive_mode(match):
                competitive_count += 1
            else:
                quick_count += 1
        scan_complete = self._all_players_complete(player1_cursor, player2_cursor)
        summary: Dict[str, Any] = {
            "total_common_count": len(matches),
            "returned_count": len(matches),
            "quick_count": quick_count,
            "competitive_count": competitive_count,
            "scanned_count": len(player1_cursor.history) + len(player2_cursor.history),
            "scan_complete": scan_complete,
        }
        _cache_put(
            _SAMEPLAY_LIST_CACHE,
            cache_key,
            {
                "matches": list(matches),
                "summary": dict(summary),
                "scan_complete": scan_complete,
            },
            ttl=SAMEPLAY_CACHE_TTL,
            max_size=SAMEPLAY_CACHE_MAX,
        )
        return {"matches": matches, "summary": summary, "scan_complete": scan_complete}

    def _build_player_cursor(
        self,
        player: ResolvedSameplayPlayer,
        *,
        include_previous_season: bool,
    ) -> _SameplayPlayerCursor:
        seasons = list(get_recent_dashen_seasons(include_previous=include_previous_season))
        return _SameplayPlayerCursor(
            player=player,
            modes={
                "sport": _SameplayModeCursor(mode="sport", seasons=list(seasons)),
                "leisure": _SameplayModeCursor(mode="leisure", seasons=list(seasons)),
            },
        )

    async def _advance_player_cursor(self, cursor: _SameplayPlayerCursor) -> List[Dict[str, Any]]:
        pending_modes = [mode_cursor for mode_cursor in cursor.modes.values() if not mode_cursor.completed]
        if not pending_modes:
            return []
        batches = await asyncio.gather(*(self._fetch_next_mode_batch(cursor.player, mode_cursor) for mode_cursor in pending_modes))
        new_items: List[Dict[str, Any]] = []
        for batch in batches:
            new_items.extend(batch)
        if not new_items:
            return []
        fresh_items: List[Dict[str, Any]] = []
        seen_new_ids = set()
        for match in new_items:
            match_id = str(match.get("matchId") or "").strip()
            if not match_id or match_id in cursor.match_by_id or match_id in seen_new_ids:
                continue
            seen_new_ids.add(match_id)
            item = dict(match)
            cursor.match_by_id[match_id] = item
            fresh_items.append(item)
        if fresh_items:
            cursor.history = _merge_unique_sorted_matches(cursor.history, fresh_items)
        return fresh_items

    async def _fetch_next_mode_batch(
        self,
        player: ResolvedSameplayPlayer,
        mode_cursor: _SameplayModeCursor,
    ) -> List[Dict[str, Any]]:
        while not mode_cursor.completed:
            if mode_cursor.season_index >= len(mode_cursor.seasons):
                mode_cursor.completed = True
                return []

            logical_season = mode_cursor.seasons[mode_cursor.season_index]
            if mode_cursor.request_season is _AUTO_REQUEST_SEASON:
                request_seasons = list(iter_dashen_season_request_values(logical_season))
            else:
                request_seasons = [mode_cursor.request_season]

            for request_season in request_seasons:
                batch = await self.requests.fetch_history_matches_page(
                    player.customer_token,
                    page=mode_cursor.next_page,
                    season=request_season,
                    game_modes=(mode_cursor.mode,),
                    fight_modes=(),
                )
                if not batch:
                    continue
                prepared: List[Dict[str, Any]] = []
                for match in batch:
                    item = dict(match)
                    item["_dashenSeason"] = logical_season
                    item.setdefault("gameMode", mode_cursor.mode)
                    prepared.append(item)
                batch_oldest = min((_safe_begin_ts(item) for item in prepared), default=0)
                if batch_oldest:
                    if mode_cursor.oldest_seen_ts is None:
                        mode_cursor.oldest_seen_ts = batch_oldest
                    else:
                        mode_cursor.oldest_seen_ts = min(mode_cursor.oldest_seen_ts, batch_oldest)
                mode_cursor.request_season = request_season
                mode_cursor.next_page += 1
                return prepared

            mode_cursor.season_index += 1
            mode_cursor.request_season = _AUTO_REQUEST_SEASON
            mode_cursor.next_page = 1

        return []

    def _update_common_matches(
        self,
        common_by_id: Dict[str, Dict[str, Any]],
        player1_cursor: _SameplayPlayerCursor,
        player2_cursor: _SameplayPlayerCursor,
        new_items: Sequence[Dict[str, Any]],
    ) -> None:
        for match in new_items:
            match_id = str(match.get("matchId") or "").strip()
            if not match_id or match_id in common_by_id or match_id not in player2_cursor.match_by_id:
                continue
            source_match = player1_cursor.match_by_id.get(match_id) or player2_cursor.match_by_id.get(match_id) or dict(match)
            common_by_id[match_id] = dict(source_match)

    def _can_stop_progressive_scan(
        self,
        player1_cursor: _SameplayPlayerCursor,
        player2_cursor: _SameplayPlayerCursor,
        common_matches: Sequence[Dict[str, Any]],
        *,
        required_count: int,
    ) -> bool:
        if len(common_matches) < int(required_count):
            return False
        threshold_ts = _safe_begin_ts(common_matches[int(required_count) - 1])
        return self._player_unseen_upper_bound(player1_cursor) <= threshold_ts and self._player_unseen_upper_bound(
            player2_cursor
        ) <= threshold_ts

    def _player_unseen_upper_bound(self, cursor: _SameplayPlayerCursor) -> int:
        upper_bounds: List[int] = []
        for mode_cursor in cursor.modes.values():
            if mode_cursor.completed:
                continue
            if mode_cursor.oldest_seen_ts is None:
                return 2**63 - 1
            upper_bounds.append(int(mode_cursor.oldest_seen_ts))
        if not upper_bounds:
            return 0
        return max(upper_bounds)

    def _all_players_complete(self, *cursors: _SameplayPlayerCursor) -> bool:
        return all(all(mode_cursor.completed for mode_cursor in cursor.modes.values()) for cursor in cursors)

    def _build_list_footer(self, summary: Dict[str, Any], *, scan_complete: bool) -> str:
        total = int(summary.get("total_common_count") or 0)
        quick = int(summary.get("quick_count") or 0)
        competitive = int(summary.get("competitive_count") or 0)
        scanned = int(summary.get("scanned_count") or 0)
        if scan_complete:
            return (
                f"共找到 {total} 场同玩对局"
                f" | 快速 {quick} 场"
                f" | 竞技 {competitive} 场"
                f" | 扫描总场次 {scanned}"
            )
        return (
            f"已找到至少 {total} 场同玩对局"
            f" | 快速 {quick} 场"
            f" | 竞技 {competitive} 场"
            f" | 已扫描对局 {scanned} 场"
        )

    def _select_source_match(self, matches: Sequence[Dict[str, Any]], *, index: Optional[int], match_id: str) -> Dict[str, Any]:
        if match_id:
            normalized = str(match_id or "").strip()
            for match in matches:
                if str(match.get("matchId") or "").strip() == normalized:
                    return dict(match)
            raise ModuleError(
                error="sameplay_match_not_found",
                message="The requested match is not present in the sameplay history window.",
                status_code=404,
                details={"match_id": normalized},
            )
        if index is None:
            raise ModuleError(
                error="missing_match_selector",
                message="index or match_id is required.",
                status_code=400,
            )
        if index < 0 or index >= len(matches):
            raise ModuleError(
                error="match_index_out_of_range",
                message=f"Match index out of range: {index}",
                status_code=400,
                hint=f"Use an index from 0 to {max(len(matches) - 1, 0)}.",
                details={"index": index, "match_count": len(matches)},
            )
        return dict(matches[index])

    async def _fetch_main_match_detail(
        self,
        player1: ResolvedSameplayPlayer,
        player2: ResolvedSameplayPlayer,
        source_match: Dict[str, Any],
    ) -> tuple[Any, int]:
        failures: List[str] = []
        for player_index, player in ((1, player1), (2, player2)):
            try:
                detail = await self.requests.get_match_detail(player.customer_token, source_match)
                return detail, player_index
            except Exception as exc:
                failures.append(f"player{player_index}:{type(exc).__name__}:{exc}")
        raise ModuleError(
            error="sameplay_detail_unavailable",
            message="Failed to fetch the sameplay match detail for both players.",
            status_code=502,
            details={"failures": failures},
        )

    async def _build_focus_player_output(
        self,
        player: ResolvedSameplayPlayer,
        source_match: Dict[str, Any],
        *,
        render: bool,
    ) -> DashenSameplayDetailPlayerOutput:
        match_id = str(source_match.get("matchId") or "").strip()
        if not match_id:
            return DashenSameplayDetailPlayerOutput(
                player=player,
                available=False,
                note=f"Missing hero detail for {player.display_name}: matchId is unavailable.",
            )
        try:
            payload = await self.requests.api_client.query_match_info(player.customer_token, match_id)
        except Exception as exc:
            return DashenSameplayDetailPlayerOutput(
                player=player,
                available=False,
                note=f"Failed to fetch hero detail for {player.display_name}: {type(exc).__name__}: {exc}",
            )

        detail_root = _extract_match_detail_data(payload)
        focus_player = self.match_module._find_focus_player(
            detail_root,
            query_full_id=player.full_id,
            query_bnet_id=player.bnet_id,
        )
        focus_detail = {
            "heroList": detail_root.get("heroList") or (focus_player.get("heroList") if focus_player else []) or [],
            "rankInfo": (focus_player.get("rankInfo") if focus_player else {}) or {},
        }
        if not focus_detail["heroList"]:
            return DashenSameplayDetailPlayerOutput(
                player=player,
                available=False,
                detail_payload=payload,
                note=f"Hero detail for {player.display_name} did not return a valid heroList.",
            )

        image = None
        if render:
            image = render_player_hero_detail(
                player.display_name,
                focus_detail,
                match_game_time_sec=detail_root.get("gameTimeSec"),
            )
            image = decorate_rendered_image_header(
                image,
                player.display_name,
                bnet_id=player.bnet_id,
                subtitle="英雄详细数据",
            )
        return DashenSameplayDetailPlayerOutput(
            player=player,
            available=True,
            detail_payload=payload,
            image=image,
        )

    def _clamp_limit(self, value: int) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 20
        return max(1, min(numeric, 40))


dashen_sameplay_module = DashenSameplayModule()
