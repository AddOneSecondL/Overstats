from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, Optional

try:
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.modules.errors import ModuleError

from .requests import AutoRouteRequests


TOKEN_PREFIXES = (
    "token:",
    "ctoken:",
    "customer_token:",
    "customer-token:",
    "customer:",
)
PROFILE_COMPETITIVE_FLAGS = {"竞技", "comp", "competitive", "ranked"}
PROFILE_QUICK_FLAGS = {"快速", "quick", "overview"}
AUTO_ROUTE_SUPPORTED_COMMANDS = (
    "玩家资料 Player#12345",
    "竞技资料 Player#12345",
    "近期对局 Player#12345",
    "近期对局 Player#12345 第3场 详细 AI锐评",
    "同玩查询 PlayerA#12345 PlayerB#67890",
    "今日总结 Player#12345",
    "昨日总结 Player#12345",
    "本周总结 Player#12345",
    "历史段位 Player#12345 15 22",
    "快速强度 Player#12345",
    "竞技强度 Player#12345",
    "英雄选取率 榜单 竞技 宗师",
    "英雄选取率 历史 安娜 竞技 宗师 30",
    "OW商店",
    "补丁说明 大更",
    "OW赛事",
    "守望赛事",
)
AUTO_ROUTE_GAME_MODE_ALIASES = {
    "快速": "quick",
    "quick": "quick",
    "竞技": "competitive",
    "comp": "competitive",
    "competitive": "competitive",
    "ranked": "competitive",
}
AUTO_ROUTE_MMR_ALIASES = {
    "全段位": "all",
    "all": "all",
    "青铜": "Bronze",
    "bronze": "Bronze",
    "白银": "Silver",
    "silver": "Silver",
    "黄金": "Gold",
    "gold": "Gold",
    "白金": "Platinum",
    "platinum": "Platinum",
    "钻石": "Diamond",
    "diamond": "Diamond",
    "大师": "Master",
    "master": "Master",
    "宗师": "Grandmaster",
    "grandmaster": "Grandmaster",
    "冠军": "Champion",
    "champion": "Champion",
}
AUTO_ROUTE_VIEW_ALIASES = {
    "ranking": "ranking",
    "榜单": "ranking",
    "排行": "ranking",
    "history": "history",
    "历史": "history",
    "曲线": "history",
    "趋势": "history",
}
AUTO_ROUTE_PATCH_KIND_ALIASES = {
    "latest": "latest",
    "最新": "latest",
    "自动": "latest",
    "auto": "latest",
    "small": "small",
    "小更": "small",
    "小更新": "small",
    "小补丁": "small",
    "big": "big",
    "major": "big",
    "大更": "big",
    "大更新": "big",
    "大补丁": "big",
}
AUTO_ROUTE_SYSTEM_PROMPT = """
You are the overstats core auto-router.
Select exactly one function tool and never answer in natural language.

Rules:
1. This API is stateless. Never assume previous targets, previous messages, or reply context.
2. Keep the user's original target text for BattleTag, numeric id, token:xxxx, or ctoken:xxxx.
3. For match and sameplay detail, index is 1-based.
4. If analyze=true, also set show_all_heroes=true.
5. For hero_pick_rate, default to ranking + quick + all unless the user clearly asks for history or another mode/rank.
6. For patch_notes, default to latest.
7. If the user asks for one player tool but the target is missing, still choose the best tool instead of chatting.
""".strip()


@dataclass(frozen=True)
class AutoRouteSelection:
    tool_name: str
    module_name: str
    endpoint: str
    endpoint_mode: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "module_name": self.module_name,
            "endpoint": self.endpoint,
            "endpoint_mode": self.endpoint_mode,
            "payload": dict(self.payload),
        }


def _normalize_target_text(raw_text: Any) -> str:
    return str(raw_text or "").strip().replace("＃", "#")


def _normalize_tool_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_tool_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "是"}:
        return True
    if text in {"0", "false", "no", "n", "off", "否"}:
        return False
    return default


def _normalize_optional_int(value: Any, *, field_name: str) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ModuleError(
            error="auto_route_invalid_arguments",
            message=f"{field_name} must be an integer when provided.",
            status_code=400,
            details={field_name: value},
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ModuleError(
            error="auto_route_invalid_arguments",
            message=f"{field_name} must be an integer when provided.",
            status_code=400,
            details={field_name: value},
        ) from exc


def _normalize_positive_int(value: Any, *, field_name: str) -> Optional[int]:
    normalized = _normalize_optional_int(value, field_name=field_name)
    if normalized is None:
        return None
    if normalized <= 0:
        raise ModuleError(
            error="auto_route_invalid_arguments",
            message=f"{field_name} must be greater than 0.",
            status_code=400,
            details={field_name: normalized},
        )
    return normalized


def _normalize_tool_mode(value: Any, *, default: str = "quick") -> str:
    normalized = _normalize_tool_text(value).lower()
    if normalized in PROFILE_COMPETITIVE_FLAGS:
        return "competitive"
    if normalized in PROFILE_QUICK_FLAGS:
        return "quick"
    return AUTO_ROUTE_GAME_MODE_ALIASES.get(normalized, default)


def _normalize_tool_view(value: Any, *, default: str = "ranking") -> str:
    normalized = _normalize_tool_text(value).lower()
    return AUTO_ROUTE_VIEW_ALIASES.get(normalized, default)


def _normalize_tool_mmr(value: Any, *, default: str = "all") -> str:
    normalized = _normalize_tool_text(value).lower()
    return AUTO_ROUTE_MMR_ALIASES.get(normalized, default)


def _normalize_tool_patch_kind(value: Any, *, default: str = "latest") -> str:
    normalized = _normalize_tool_text(value).lower()
    return AUTO_ROUTE_PATCH_KIND_ALIASES.get(normalized, default)


def _build_target_payload(
    raw_target: Any,
    *,
    bnet_key: str = "bnet_id",
    customer_token_key: str = "customer_token",
    include_full_id: bool = True,
) -> Dict[str, Any]:
    normalized = _normalize_target_text(raw_target)
    if not normalized:
        return {}

    lowered = normalized.lower()
    for prefix in TOKEN_PREFIXES:
        if lowered.startswith(prefix):
            token = normalized[len(prefix):].strip()
            if not token:
                raise ModuleError(
                    error="auto_route_invalid_arguments",
                    message=f"{customer_token_key} must not be empty.",
                    status_code=400,
                    details={"target": raw_target},
                )
            return {customer_token_key: token}

    payload: Dict[str, Any] = {bnet_key: normalized}
    if include_full_id:
        payload["full_id"] = normalized
    return payload


def _require_target_payload(raw_target: Any, *, field_name: str = "target", include_full_id: bool = True) -> Dict[str, Any]:
    payload = _build_target_payload(raw_target, include_full_id=include_full_id)
    if payload:
        return payload
    raise ModuleError(
        error="auto_route_invalid_arguments",
        message=f"{field_name} is required.",
        status_code=400,
    )


def _require_two_player_payload(arguments: Dict[str, Any]) -> Dict[str, Any]:
    player1_payload = _build_target_payload(
        arguments.get("player1"),
        bnet_key="player1_bnet_id",
        customer_token_key="player1_customer_token",
        include_full_id=False,
    )
    player2_payload = _build_target_payload(
        arguments.get("player2"),
        bnet_key="player2_bnet_id",
        customer_token_key="player2_customer_token",
        include_full_id=False,
    )
    if not player1_payload:
        raise ModuleError(
            error="auto_route_invalid_arguments",
            message="player1 is required.",
            status_code=400,
        )
    if not player2_payload:
        raise ModuleError(
            error="auto_route_invalid_arguments",
            message="player2 is required.",
            status_code=400,
        )
    payload = dict(player1_payload)
    payload.update(player2_payload)
    return payload


class AutoRouteModule:
    def __init__(self, requests: Optional[AutoRouteRequests] = None) -> None:
        self.requests = requests or AutoRouteRequests()
        self._selection_builders: Dict[str, Callable[[Dict[str, Any]], AutoRouteSelection]] = {
            "dashen_profile": self._build_dashen_profile_selection,
            "dashen_match": self._build_dashen_match_selection,
            "dashen_sameplay": self._build_dashen_sameplay_selection,
            "summary_today": lambda arguments: self._build_summary_selection(arguments, scope="today"),
            "summary_yesterday": lambda arguments: self._build_summary_selection(arguments, scope="yesterday"),
            "summary_week": lambda arguments: self._build_summary_selection(arguments, scope="week"),
            "rank_history": self._build_rank_history_selection,
            "quick_strength": self._build_quick_strength_selection,
            "competitive_strength": self._build_competitive_strength_selection,
            "hero_pick_rate": self._build_hero_pick_rate_selection,
            "ow_esports": self._build_ow_esports_selection,
            "ow_shop": self._build_ow_shop_selection,
            "patch_notes": self._build_patch_notes_selection,
        }

    def build_tools(self) -> list[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "dashen_profile",
                    "description": "Query player profile.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "mode": {"type": "string", "enum": ["quick", "competitive"]},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "dashen_match",
                    "description": "Query recent matches or one match detail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "index": {"type": "integer"},
                            "show_all_heroes": {"type": "boolean"},
                            "analyze": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "dashen_sameplay",
                    "description": "Query shared matches between two players.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "player1": {"type": "string"},
                            "player2": {"type": "string"},
                            "index": {"type": "integer"},
                            "show_all_heroes": {"type": "boolean"},
                            "analyze": {"type": "boolean"},
                        },
                        "required": ["player1", "player2"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summary_today",
                    "description": "Generate today's summary.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summary_yesterday",
                    "description": "Generate yesterday's summary.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summary_week",
                    "description": "Generate weekly summary.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rank_history",
                    "description": "Query rank history.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "start_season": {"type": "integer"},
                            "end_season": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "quick_strength",
                    "description": "Query quick-play strength.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "competitive_strength",
                    "description": "Query competitive strength.",
                    "parameters": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "hero_pick_rate",
                    "description": "Query hero pick-rate ranking or history.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "view": {"type": "string", "enum": ["ranking", "history"]},
                            "game_mode": {"type": "string", "enum": ["quick", "competitive"]},
                            "mmr": {
                                "type": "string",
                                "enum": [
                                    "all",
                                    "Bronze",
                                    "Silver",
                                    "Gold",
                                    "Platinum",
                                    "Diamond",
                                    "Master",
                                    "Grandmaster",
                                    "Champion",
                                ],
                            },
                            "hero": {"type": "string"},
                            "history_limit": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ow_esports",
                    "description": "Query current OW esports matches.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ow_shop",
                    "description": "Query the current OW shop.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "patch_notes",
                    "description": "Query patch notes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "patch_kind": {"type": "string", "enum": ["latest", "small", "big"]},
                        },
                        "additionalProperties": False,
                    },
                },
            },
        ]

    async def select(self, text: str) -> AutoRouteSelection:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ModuleError(
                error="missing_text",
                message="text is required.",
                status_code=400,
            )

        tool_call = await self.requests.select_tool_call(
            user_text=normalized_text,
            system_prompt=AUTO_ROUTE_SYSTEM_PROMPT,
            tools=self.build_tools(),
            supported_commands=AUTO_ROUTE_SUPPORTED_COMMANDS,
        )
        builder = self._selection_builders.get(tool_call.name)
        if builder is None:
            raise ModuleError(
                error="auto_route_invalid_tool",
                message=f"Unsupported LLM tool: {tool_call.name}",
                status_code=502,
                details={"tool_name": tool_call.name},
            )
        return builder(tool_call.arguments)

    def _build_dashen_profile_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"))
        payload["mode"] = _normalize_tool_mode(arguments.get("mode"))
        return AutoRouteSelection(
            tool_name="dashen_profile",
            module_name="dashen_profile",
            endpoint="/api/v2/dashen-profile/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_dashen_match_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"))
        index = _normalize_positive_int(arguments.get("index"), field_name="index")
        show_all_heroes = _normalize_tool_bool(arguments.get("show_all_heroes"), default=False)
        analyze = _normalize_tool_bool(arguments.get("analyze"), default=False)
        if analyze:
            show_all_heroes = True
        if index is None:
            return AutoRouteSelection(
                tool_name="dashen_match",
                module_name="dashen_match",
                endpoint="/api/v2/dashen-match/replies",
                endpoint_mode="replies",
                payload=payload,
            )
        payload.update(
            {
                "index": index - 1,
                "show_all_heroes": show_all_heroes,
                "analyze": analyze,
            }
        )
        return AutoRouteSelection(
            tool_name="dashen_match",
            module_name="dashen_match",
            endpoint="/api/v2/dashen-match/detail/replies",
            endpoint_mode="replies",
            payload=payload,
        )

    def _build_dashen_sameplay_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_two_player_payload(arguments)
        index = _normalize_positive_int(arguments.get("index"), field_name="index")
        show_all_heroes = _normalize_tool_bool(arguments.get("show_all_heroes"), default=False)
        analyze = _normalize_tool_bool(arguments.get("analyze"), default=False)
        if analyze:
            show_all_heroes = True
        if index is None:
            return AutoRouteSelection(
                tool_name="dashen_sameplay",
                module_name="dashen_sameplay",
                endpoint="/api/v2/dashen-sameplay/replies",
                endpoint_mode="replies",
                payload=payload,
            )
        payload.update(
            {
                "index": index - 1,
                "show_all_heroes": show_all_heroes,
                "analyze": analyze,
            }
        )
        return AutoRouteSelection(
            tool_name="dashen_sameplay",
            module_name="dashen_sameplay",
            endpoint="/api/v2/dashen-sameplay/detail/replies",
            endpoint_mode="replies",
            payload=payload,
        )

    def _build_summary_selection(self, arguments: Dict[str, Any], *, scope: str) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"))
        return AutoRouteSelection(
            tool_name=f"summary_{scope}",
            module_name="dashen_summary",
            endpoint=f"/api/v2/dashen-summary/{scope}/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_rank_history_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"), include_full_id=False)
        start_season = _normalize_positive_int(arguments.get("start_season"), field_name="start_season")
        end_season = _normalize_positive_int(arguments.get("end_season"), field_name="end_season")
        if start_season is not None:
            payload["start_season"] = start_season
        if end_season is not None:
            payload["end_season"] = end_season
        if start_season is not None and end_season is not None and start_season > end_season:
            raise ModuleError(
                error="auto_route_invalid_arguments",
                message="start_season cannot be greater than end_season.",
                status_code=400,
                details={"start_season": start_season, "end_season": end_season},
            )
        return AutoRouteSelection(
            tool_name="rank_history",
            module_name="dashen_rank_history",
            endpoint="/api/v2/dashen-rank-history/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_quick_strength_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"), include_full_id=False)
        return AutoRouteSelection(
            tool_name="quick_strength",
            module_name="dashen_quick_strength",
            endpoint="/api/v2/dashen-quick-strength/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_competitive_strength_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = _require_target_payload(arguments.get("target"), include_full_id=False)
        return AutoRouteSelection(
            tool_name="competitive_strength",
            module_name="dashen_competitive_strength",
            endpoint="/api/v2/dashen-competitive-strength/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_hero_pick_rate_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        view = _normalize_tool_view(arguments.get("view"))
        payload: Dict[str, Any] = {
            "view": view,
            "game_mode": _normalize_tool_mode(arguments.get("game_mode")),
            "mmr": _normalize_tool_mmr(arguments.get("mmr")),
        }
        hero = _normalize_tool_text(arguments.get("hero"))
        history_limit = _normalize_positive_int(arguments.get("history_limit"), field_name="history_limit")
        if view == "history":
            if not hero:
                raise ModuleError(
                    error="auto_route_invalid_arguments",
                    message="hero is required when view=history.",
                    status_code=400,
                )
            payload["hero"] = hero
            if history_limit is not None:
                payload["history_limit"] = history_limit
        return AutoRouteSelection(
            tool_name="hero_pick_rate",
            module_name="ow_hero_pick_rate",
            endpoint="/api/v2/ow-hero-pick-rate/image",
            endpoint_mode="image",
            payload=payload,
        )

    def _build_ow_esports_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        return AutoRouteSelection(
            tool_name="ow_esports",
            module_name="ow_esports",
            endpoint="/api/v2/ow-esports/image",
            endpoint_mode="image",
            payload={},
        )

    def _build_ow_shop_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        return AutoRouteSelection(
            tool_name="ow_shop",
            module_name="ow_shop",
            endpoint="/api/v2/ow-shop/image",
            endpoint_mode="image",
            payload={},
        )

    def _build_patch_notes_selection(self, arguments: Dict[str, Any]) -> AutoRouteSelection:
        payload = {"patch_kind": _normalize_tool_patch_kind(arguments.get("patch_kind"))}
        return AutoRouteSelection(
            tool_name="patch_notes",
            module_name="patch_notes",
            endpoint="/api/v2/patch-notes/image",
            endpoint_mode="image",
            payload=payload,
        )


auto_route_module = AutoRouteModule()
