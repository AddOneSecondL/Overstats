"""LLM-friendly normalized match-detail builders.

The raw ``queryMatchInfo`` payload is camelCase, un-normalized and mixes the
querying player's hero detail with per-player summary stats.  These helpers turn
that payload into a stable, snake_case, machine-readable structure with resolved
Chinese hero/map/rank names so an LLM (or any other consumer) can read a match
without re-implementing the Overstats mapping tables.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from overstats.src.constants.ranks import (
        get_rank_name,
        get_rank_score,
        get_rank_sub_tier,
        rank_name_cn,
    )
except ModuleNotFoundError:
    from src.constants.ranks import (
        get_rank_name,
        get_rank_score,
        get_rank_sub_tier,
        rank_name_cn,
    )

try:
    from overstats.src.modules.dashen_match.render import (
        _extract_match_detail_data,
        _find_hero,
        _find_map,
        _format_begin_ts,
        _format_duration,
        _load_ow_config,
        _mode_label,
        _resolve_player_hero,
        _role_type,
        _sort_players,
    )
except ModuleNotFoundError:
    from src.modules.dashen_match.render import (
        _extract_match_detail_data,
        _find_hero,
        _find_map,
        _format_begin_ts,
        _format_duration,
        _load_ow_config,
        _mode_label,
        _resolve_player_hero,
        _role_type,
        _sort_players,
    )

try:
    from overstats.src.modules.dashen_match.enhanced_render import (
        _hero_stat_rows,
        calculate_match_scores,
    )
except ModuleNotFoundError:
    from src.modules.dashen_match.enhanced_render import (
        _hero_stat_rows,
        calculate_match_scores,
    )


ROLE_LABELS_CN = {
    "tank": "重装",
    "dps": "输出",
    "healer": "支援",
    "support": "支援",
    "open": "开放",
}

# Snake_case core stats kept on every player in the scoreboard payload.
_CORE_STAT_FIELDS = (
    ("kill", "kill"),
    ("assist", "assist"),
    ("death", "death"),
    ("finalHit", "final_hit"),
    ("targetCompetingTime", "target_competing_time"),
    ("heroDamage", "hero_damage"),
    ("damageTaken", "damage_taken"),
    ("cure", "cure"),
    ("healingTaken", "healing_taken"),
    ("resistDamage", "resist_damage"),
)


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def identify_focus_player(
    detail_root: Dict[str, Any],
    *,
    query_full_id: str = "",
    query_bnet_id: str = "",
    query_customer_token: str = "",
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return ``(player, team_type)`` for the queried player, if present."""
    normalized_full = str(query_full_id or "").strip().lower()
    normalized_tag = normalized_full.split("#", 1)[0]
    normalized_bnet_id = str(query_bnet_id or "").strip()
    normalized_customer_token = str(query_customer_token or "").strip()
    for team_key, team_type in (("teammateList", "teammate"), ("enemyList", "enemy")):
        for player in detail_root.get(team_key, []) or []:
            if not isinstance(player, dict):
                continue
            player_name = str(player.get("name") or "").strip().lower()
            player_tag = player_name.split("#", 1)[0]
            player_bnet_id = str(player.get("bnetId") or "").strip()
            player_customer_token = str(
                player.get("customerToken") or player.get("customer_token") or ""
            ).strip()
            if normalized_customer_token and player_customer_token == normalized_customer_token:
                return dict(player), team_type
            if normalized_bnet_id and player_bnet_id and normalized_bnet_id == player_bnet_id:
                return dict(player), team_type
            if normalized_full and player_name == normalized_full:
                return dict(player), team_type
            if normalized_tag and player_tag == normalized_tag:
                return dict(player), team_type
    return None, ""


def _normalize_rank(rank_info: Any, *, mode: str = "normal") -> Dict[str, Any]:
    rank_info = rank_info if isinstance(rank_info, dict) else {}
    score = _int_or_none(get_rank_score(rank_info))
    tier = str(get_rank_sub_tier(rank_info) or "").strip()
    name = str(get_rank_name(rank_info) or "").strip()
    name_cn = rank_name_cn(name) if name else ""
    if mode != "fight":
        name_cn = name_cn or rank_name_cn(name)
    if name and tier:
        label = f"{name_cn or name}{tier}"
    elif name:
        label = name_cn or name
    elif tier:
        label = tier
    else:
        label = ""
    return {
        "rank_name": name,
        "rank_name_cn": name_cn,
        "division": tier,
        "rank_score": score,
        "label": label,
        "raw": rank_info if rank_info else None,
    }


def _normalize_core_stats(player: Dict[str, Any]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for raw_key, out_key in _CORE_STAT_FIELDS:
        value = player.get(raw_key)
        stats[out_key] = _int_or_none(value) if value not in (None, "") else None
    return stats


def _normalize_hero(hero: Dict[str, Any], config: Dict[str, Any], rank_info: Any) -> Dict[str, Any]:
    hero_guid = str(_first(hero.get("heroGuid"), hero.get("heroId")) or "")
    hero_info = _find_hero(config, hero_guid)
    hero_name = str(hero_info.get("name") or "未知英雄")
    role_type = str(hero_info.get("roleType") or hero_info.get("role") or "")
    stat_rows: List[Dict[str, Any]] = []
    try:
        for row in _hero_stat_rows(config, hero, rank_info=rank_info):
            stat_rows.append(
                {
                    "guid": row.get("guid"),
                    "label": row.get("label"),
                    "value_text": row.get("value_text"),
                    "value_type": row.get("value_type"),
                    "band": row.get("band"),
                    "avg_text": row.get("avg_text"),
                }
            )
    except Exception:
        # Fall back to raw statMap -> labeled rows without DB averages.
        stat_map = hero.get("statMap") or {}
        attr_lookup = {}
        for item in config.get("heroAttrList", []) or []:
            if str(item.get("heroGuid") or "") == hero_guid:
                attr_lookup[str(item.get("valueGuid") or "")] = item
        for raw_guid, raw_value in (stat_map or {}).items():
            attr = attr_lookup.get(str(raw_guid), {})
            stat_rows.append(
                {
                    "guid": str(raw_guid),
                    "label": str(attr.get("valueText") or raw_guid),
                    "value_text": str(raw_value),
                    "value_type": str(attr.get("valueType") or ""),
                    "band": "unknown",
                    "avg_text": None,
                }
            )
    return {
        "hero_guid": hero_guid,
        "hero_name": hero_name,
        "role_type": role_type,
        "stats": stat_rows,
    }


def _normalize_player(
    player: Dict[str, Any],
    team_type: str,
    config: Dict[str, Any],
    *,
    mode: str,
    is_focus: bool,
    hero_list: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    hero_info = _resolve_player_hero(config, player)
    hero_name = str(hero_info.get("name") or "")
    hero_guid = str(
        _first(
            hero_info.get("heroGuid"),
            hero_info.get("heroId"),
            player.get("heroGuid"),
            player.get("heroId"),
        )
        or ""
    )
    role_type = _role_type(player, hero_info) or str(hero_info.get("roleType") or "")
    rank_info = player.get("rankInfo") or player.get("rank_info") or {}
    heroes: List[Dict[str, Any]] = []
    for hero in hero_list or []:
        if isinstance(hero, dict):
            heroes.append(_normalize_hero(hero, config, rank_info))
    return {
        "name": str(player.get("name") or ""),
        "bnet_id": str(player.get("bnetId") or ""),
        "customer_token": str(player.get("customerToken") or player.get("customer_token") or "").strip(),
        "team_type": team_type,
        "is_focus": is_focus,
        "hero": hero_name,
        "hero_guid": hero_guid,
        "role_type": role_type,
        "role_label": ROLE_LABELS_CN.get(role_type, ""),
        "rank": _normalize_rank(rank_info, mode=mode),
        "stats": _normalize_core_stats(player),
        "heroes": heroes,
    }


def build_match_overview(
    detail_root: Dict[str, Any],
    source_match: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    source_match = source_match or {}
    map_guid = _first(detail_root.get("mapGuid"), source_match.get("mapGuid"))
    map_info = _find_map(config, map_guid)
    match_ret = _first(detail_root.get("matchRet"), source_match.get("matchRet"))
    result_code = _int_or_none(match_ret)
    if result_code == 1:
        result = "胜利"
    elif result_code == 0:
        result = "平局"
    else:
        result = "失败"
    game_time_sec = _int_or_none(detail_root.get("gameTimeSec"))
    mode_label, _ = _mode_label({**source_match, **detail_root})

    start_time = detail_root.get("startTime")
    if start_time:
        try:
            start_time_text = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(int(start_time) + int(game_time_sec or 0)),
            )
        except Exception:
            start_time_text = _format_begin_ts(
                _first(detail_root.get("beginTs"), source_match.get("beginTs"))
            )
    else:
        start_time_text = _format_begin_ts(
            _first(detail_root.get("beginTs"), source_match.get("beginTs"))
        )

    return {
        "result": result,
        "result_code": result_code,
        "map_guid": str(map_guid or ""),
        "map_name": str(map_info.get("name") or str(map_guid or "未知地图")),
        "map_mode": str(map_info.get("mode") or ""),
        "team_score": _int_or_none(_first(detail_root.get("teamScore"), source_match.get("teamScore"))),
        "opponent_score": _int_or_none(
            _first(detail_root.get("opponentScore"), source_match.get("opponentScore"))
        ),
        "game_time_sec": game_time_sec,
        "duration": _format_duration(game_time_sec),
        "mode_label": mode_label,
        "start_time": start_time_text,
        "begin_ts": _first(source_match.get("beginTs"), detail_root.get("beginTs")),
    }


def build_carry_index(match_data: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Icon-free carry index, sorted by score descending."""
    game_time = float(match_data.get("gameTimeSec") or 600 or 600)
    time_coef = max(1.0, game_time) / 600.0
    carry: List[Dict[str, Any]] = []

    for team_label, player_list in (
        ("teammate", match_data.get("teammateList", [])),
        ("enemy", match_data.get("enemyList", [])),
    ):
        for player in player_list or []:
            if not isinstance(player, dict):
                continue
            total_damage = float(player.get("heroDamage", 0) or 0)
            total_healing = float(player.get("cure", 0) or 0)
            total_blocked = float(player.get("resistDamage", 0) or 0)
            total_kill = float(player.get("kill", 0) or 0)
            total_final_blows = float(player.get("finalBlows", player.get("finalHit", 0)) or 0)
            total_solo_kills = float(player.get("soloKills", 0) or 0)
            total_assist = float(player.get("assist", 0) or 0)
            total_healing_taken = float(player.get("healingTaken", 0) or 0)
            total_damage_taken = float(player.get("damageTaken", 0) or 0)
            total_death = float(player.get("death", 0) or 0)

            score = (
                (total_damage + total_healing + (total_blocked / 10.0))
                + (total_kill * 200.0)
                + (total_final_blows * 200.0)
                + (total_solo_kills * 300.0)
                + (total_assist * 50.0)
                + (total_healing_taken * -0.3)
                + (total_damage_taken * 0.3)
                - (total_death * 200.0)
            ) / time_coef

            hero_info = _resolve_player_hero(config, player)
            carry.append(
                {
                    "name": str(player.get("name") or "未知").split("#", 1)[0],
                    "team": team_label,
                    "score": int(round(score)),
                    "hero": str(hero_info.get("name") or ""),
                }
            )

    carry.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return carry


def build_llm_match_detail(
    detail_payload: Dict[str, Any],
    *,
    source_match: Optional[Dict[str, Any]] = None,
    match_id: str = "",
    match_kind: str = "normal",
    query_full_id: str = "",
    query_bnet_id: str = "",
    query_customer_token: str = "",
    all_player_details: Optional[Sequence[Dict[str, Any]]] = None,
    analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = _load_ow_config()
    detail_root = _extract_match_detail_data(detail_payload)
    source_match = source_match or {}

    focus_player, focus_team_type = identify_focus_player(
        detail_root,
        query_full_id=query_full_id,
        query_bnet_id=query_bnet_id,
        query_customer_token=query_customer_token,
    )
    focus_name = str((focus_player or {}).get("name") or "")

    # Map player name -> heroList gathered from the "show all heroes" fetch.
    hero_details_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for item in all_player_details or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        heroes = item.get("heroList")
        if name and isinstance(heroes, list):
            hero_details_by_name[name] = [h for h in heroes if isinstance(h, dict)]

    def normalize_team(players: Sequence[Dict[str, Any]], team_type: str) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for player in _sort_players(players, config):
            name = str(player.get("name") or "")
            is_focus = bool(focus_name) and name.strip().lower() == focus_name.strip().lower()
            hero_list = hero_details_by_name.get(name.strip().lower())
            if is_focus and not hero_list:
                hero_list = detail_root.get("heroList") or []
            normalized.append(
                _normalize_player(
                    player,
                    team_type,
                    config,
                    mode=match_kind,
                    is_focus=is_focus,
                    hero_list=hero_list,
                )
            )
        return normalized

    data: Dict[str, Any] = {
        "match_id": match_id,
        "match_kind": match_kind,
        "match": build_match_overview(detail_root, source_match, config),
        "teammates": normalize_team(detail_root.get("teammateList") or [], "teammate"),
        "enemies": normalize_team(detail_root.get("enemyList") or [], "enemy"),
        "focus_player": {
            "name": focus_name,
            "team_type": focus_team_type,
        }
        if focus_name
        else None,
        "scores": calculate_match_scores(detail_root),
        "carry_index": build_carry_index(detail_root, config),
    }

    # Fight matches keep round/total aggregates instead of a scoreboard.
    if match_kind == "fight":
        data["total_count"] = detail_root.get("totalCount")
        data["rounds"] = detail_root.get("roundCountList") or []
        data["teammates"] = []
        data["enemies"] = []

    if analysis is not None:
        data["analysis"] = analysis

    return data


def sanitize_analysis_json(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Strip non-JSON-serializable fields (PIL icons) from an AI analysis payload."""
    cleaned = dict(analysis)
    carry = cleaned.get("carry_index_data")
    if isinstance(carry, list):
        clean_carry = []
        for item in carry:
            if isinstance(item, dict):
                item = dict(item)
                item.pop("icon", None)
                clean_carry.append(item)
        cleaned["carry_index_data"] = clean_carry
    return cleaned
