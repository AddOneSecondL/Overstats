"""Season report prototype. Intentionally absent from the public UI registry."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from .engine import SUMMARY_SEMAPHORE
from ..season_config import get_dashen_current_season
from ..errors import ModuleError
from .season_report_fields import first_value, name_text, number
from .season_report_ranks import classify_ranks, enrich_rank_queues, rank_role
from .runtime.summary_perks import guid, hero_choices

RESOURCE_DIR = Path(__file__).resolve().parents[3] / "res"

ENDPOINT = "https://datamsapi.ds.163.com/v1/dsbdld5/ld5_season_report/season_summary_by_season"
REPORT_YEAR = 2026
CARD_ENDPOINT = "https://datamsapi.ds.163.com/v1/a19ld5tool/customer/queryCard"
HIGHLIGHT_METRICS = {"1": ("heroDamage", "damage"), "2": ("resistDamage", "resist_damage"), "3": ("cure", "cure")}
MODE_NAMES = {
    "1": "休闲比赛", "leisure": "休闲比赛", "leisurepreset": "休闲比赛", "quickplay": "休闲比赛",
    "leisureopen": "休闲开放职责", "leisurev6": "快速 6V6",
    "2": "竞技比赛", "sport": "竞技比赛", "sportpreset": "竞技预设职责", "sportopen": "竞技开放职责",
    "sportv6": "竞技 6V6",
    "quickfight": "角斗快速", "leisurefight": "角斗快速", "sportfight": "角斗竞技",
}


def fmt(value, decimals=0, suffix=""):
    value = number(value)
    return "—" if value is None else f"{value:,.{decimals}f}{suffix}"


def rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def pick(value, keys):
    value = value if isinstance(value, dict) else {}
    return {key: value[key] for key in keys.split() if key in value}


def mapping(value):
    return value if isinstance(value, dict) else {}


def resolve_season(value=None):
    if value is None or value == "":
        return max(1, get_dashen_current_season() - 1)
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value).strip()):
        raise ModuleError(error="invalid_season", message="season 必须为正整数。", status_code=400)
    return int(value)


def mode_name(value):
    value = str(value).strip()
    return value if value in MODE_NAMES.values() else MODE_NAMES.get(value.casefold(), "")


def match_detail(item):
    data = item.get("match_detail") or item.get("matchDetail")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    return mapping(data)


def match_player(detail, role_id):
    mine = mapping(detail.get("myMatchDetail"))
    if not role_id or (mine and str(mine.get("bnetId") or role_id) == role_id):
        return mine
    return next((row for row in rows(detail.get("teammateList")) if str(row.get("bnetId")) == role_id), {})


def match_data(item, role_id=None):
    detail = match_detail(item)
    mine = match_player(detail, role_id)
    match_heroes = rows(mine.get("heroList")) or rows(detail.get("heroList"))
    main_hero = max(match_heroes, key=lambda row: number(row.get("userTimeSec")) or 0, default={})
    hero = mine.get("heroGuid") or mine.get("heroId") or item.get("heroGuid") or main_hero.get("heroId") or main_hero.get("heroGuid")
    rank_fields = "rank_name rankName rank_sub_tier rankSubTier rankScore rank_score score"
    if hero:
        choices = hero_choices({**mine, "heroGuid": hero, "heroList": match_heroes}).get(guid(hero), [])
        perks = [{"guid": perk["guid"], "perkLevel": perk["level"] or None} for perk in choices]
    else:
        perks = [pick(perk, "guid id perkGuid value perkLevel level") for perk in rows(mine.get("perks"))]

    def stat(key):
        return first_value(mine.get(key), item.get(key))

    def field(key):
        return first_value(detail.get(key), item.get(key))

    return {
        "hero": hero, "map": field("mapGuid") or detail.get("mapId") or item.get("mapId"),
        "hero_name": name_text(stat("heroName")), "hero_icon": name_text(stat("heroIcon")),
        "map_name": name_text(field("mapName")),
        "kill": stat("kill"), "assist": stat("assist"), "death": stat("death"),
        "damage": stat("heroDamage"), "cure": stat("cure"), "resist_damage": stat("resistDamage"),
        "rank": pick(mine.get("rankInfo"), rank_fields) or pick(field("rankInfo"), rank_fields),
        "perks": perks,
        "result": field("matchRet"), "team_score": field("teamScore"), "opponent_score": field("opponentScore"),
        "begin_ts": first_value(mine.get("beginTs"), field("beginTs"), detail.get("startTime")),
        "game_mode": field("gameMode") or mine.get("gameMode"),
        "ruleset_queue_guid": field("rulesetQueueGuid") or field("ruleset_queue_guid") or mine.get("rulesetQueueGuid"),
    }


def own_match_players(data, role_id):
    for entry in rows(data.get("match_summary")) + rows(data.get("true_match_summary")):
        detail = match_detail(entry)
        for player in [mapping(detail.get("myMatchDetail")), *rows(detail.get("teammateList"))]:
            if str(player.get("bnetId") or "") == role_id:
                yield player


def own_match_token(data, role_id):
    return next((mine["customerToken"] for mine in own_match_players(data, role_id) if mine.get("customerToken")), None)


def parse_report(payload, role_id=None):
    if isinstance(payload, dict) and payload.get("errorMsg") == "NOT_REPORT_DATA":
        raise ModuleError(error="season_report_empty", message="该玩家在此赛季暂无报告。", status_code=404)
    if not isinstance(payload, dict) or payload.get("code") != 0 or payload.get("success") is False:
        raise ModuleError(error="season_report_upstream_error", message="赛季报告接口返回失败，请检查 token 是否有效。", status_code=502)
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("season_summary"), dict) or not data["season_summary"]:
        raise ModuleError(error="season_report_empty", message="暂无该玩家的赛季报告。", status_code=404)
    role_id = str(role_id or data["season_summary"].get("bnet_account_id") or "")
    raw_ranks = rows(data.get("rank_summary"))
    # Whitelist fields: upstream match details contain customerToken and other credentials.
    report = {
        "icon": str(data.get("icon") or ""),
        "season": pick(data.get("season_summary"), "bnet_account_id season match_cnt online_time ahead_rate oneday_max_online_dt oneday_max_online_time get_honors_cnt send_honors_cnt mode_most_play mode_most_play_match_cnt stadium_match_cnt stadium_worth"),
        "overview": pick(data.get("season_overview_summary"), "bnet_account_id first_landing_day match_cnt active_day_cnt active_day_rate online_time online_time_rate win_rate win_rate_rate kill_sum kill_rnk_rate assist_sum assist_rnk_rate damage_sum damage_rnk_rate cure_sum cure_rnk_rate resist_damage_sum resist_damage_rate role_most_play mode_most_play max_rank_level"),
        "ranks": [pick(r, "mode_type most_play_hero_guid final_rank_level max_rank_level win_rate match_cnt ruleset_queue_guid ip_province player_rank role_type") for r in raw_ranks],
        "heroes": [pick(r, "role_type role_most_play_hero_guid role_most_play_hero_name role_match_cnt role_win_rate damage resist_damage cure kill assist stat_map") for r in rows(data.get("role_summary")) if str(r.get("role_type")) != "-1"],
        "focus": next((pick(r, "role_most_play_hero_guid role_most_play_hero_name role_match_cnt role_win_rate stat_map") for r in rows(data.get("role_summary")) if str(r.get("role_type")) == "-1"), {}),
        "lootbox": pick(data.get("lootbox_summary"), "open_lootbox_cnt epic_cnt legendary_cnt"),
        "friends": [pick(r, "friend_name friend_icon with_friend_match_cnt with_friend_win_rate") for r in rows(data.get("friend_summary"))],
        "highlights": [],
        "low_win_heroes": [pick(r, "hero_guid hero_name match_cnt win_rate") for r in rows(data.get("low_win_hero_summary"))],
        "true_matches": [{**pick(r, "match_type match_cnt"), **match_data(r, role_id)} for r in rows(data.get("true_match_summary"))],
        "player_name": name_text(data.get("battletag")) or name_text(data.get("name")),
    }
    for rank, raw in zip(report["ranks"], raw_ranks):
        mode = first_value(raw.get("gameMode"), raw.get("game_mode"), raw.get("queueType"), raw.get("queue_type"))
        if mode is not None:
            rank["queue_mode"] = mode
        if "mode_type" not in rank and raw.get("modeType") is not None:
            rank["mode_type"] = raw["modeType"]
        if not rank.get("ruleset_queue_guid") and raw.get("rulesetQueueGuid"):
            rank["ruleset_queue_guid"] = raw["rulesetQueueGuid"]
        if role := rank_role(raw):
            rank["role_type"] = role
    for friend in report["friends"]:
        if "friend_name" in friend:
            friend["friend_name"] = name_text(friend["friend_name"])
    if not report["player_name"] and role_id:
        report["player_name"] = next((name for mine in own_match_players(data, role_id)
                                      if (name := name_text(mine.get("name")))), "")
    for item in rows(data.get("match_summary")):
        # Only these three record types can be checked against the actual match stats.
        keys = HIGHLIGHT_METRICS.get(str(first_value(item.get("matchType"), item.get("match_type"))))
        if keys:
            match = match_data(item, role_id)
            value = match[keys[1]]
            if number(value) is not None or match_player(match_detail(item), role_id):
                report["highlights"].append({**match, "metric": keys[0], "value": value})
    for hero in report["heroes"] + [report["focus"]]:
        if "stat_map" in hero:
            unique = []
            for raw in rows(hero["stat_map"]):
                stat = pick(raw, "index_name index_value index_rate")
                if stat not in unique:
                    unique.append(stat)
            hero["stat_map"] = unique
    classify_ranks(report["ranks"], matches=report["highlights"] + report["true_matches"])
    return report


async def fetch_report(token, role_id, season=None):
    token, role_id = str(token or "").strip(), str(role_id or "").strip()
    if not token or not role_id.isascii() or not role_id.isdigit():
        raise ModuleError(error="invalid_season_target", message="请提供完整 token 和数字 roleId。", status_code=400)
    selected_season = resolve_season(season)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(ENDPOINT, params={"token": token, "roleId": role_id, "season": selected_season, "dts": REPORT_YEAR, "appKey": "ld5", "server": 1})
            response.raise_for_status()
            payload = response.json()
            report = parse_report(payload, role_id)
            if report["season"].get("season") is None:
                report["season"]["season"] = selected_season
            data = mapping(payload.get("data"))
            own_token = own_match_token(data, role_id)
            unresolved_ranks = any(row["queue_key"] is None for row in report["ranks"])
            recent_season = resolve_season()
            if (not report["player_name"] or unresolved_ranks) and not own_token and selected_season != recent_season:
                try:
                    recent_response = await client.get(ENDPOINT, params={
                        "token": token, "roleId": role_id, "season": recent_season,
                        "dts": REPORT_YEAR, "appKey": "ld5", "server": 1,
                    }, timeout=10)
                    recent_response.raise_for_status()
                    recent_payload = recent_response.json()
                    if isinstance(recent_payload, dict) and recent_payload.get("code") == 0:
                        own_token = own_match_token(mapping(recent_payload.get("data")), role_id)
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass

            async def enrich_identity():
                try:
                    card_response = await client.get(CARD_ENDPOINT, params={"token": own_token}, headers={
                        "GL-Bigdata-Auth-Token": token, "GL-Bigdata-Role-Id": role_id,
                        "GL-Bigdata-Dts": str(REPORT_YEAR), "GL-Bigdata-Server": "1",
                    }, timeout=10)
                    card_response.raise_for_status()
                    card_payload = card_response.json()
                    card = mapping(card_payload.get("data"))
                    if card_payload.get("code") == 0 and str(card.get("bnetId") or "") == role_id:
                        report["player_name"] = name_text(card.get("name"))
                        report["icon"] = str(card.get("icon") or report["icon"])
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass

            if own_token:
                enrichment = []
                if unresolved_ranks:
                    enrichment.append(enrich_rank_queues(
                        client, report["ranks"], customer_token=own_token, token=token, role_id=role_id,
                        season=selected_season, dts=REPORT_YEAR,
                        matches=report["highlights"] + report["true_matches"],
                    ))
                if not report["player_name"]:
                    enrichment.append(enrich_identity())
                await asyncio.gather(*enrichment)
    except (httpx.HTTPError, ValueError):
        # Never include the authenticated request URL in errors.
        raise ModuleError(error="season_report_unavailable", message="赛季报告暂时无法获取，请稍后重试。", status_code=502) from None
    return report


async def render_report(report, role_id):
    from .season_report_render import render_report as render
    return await render(report, role_id)


async def query_season_report(payload, *, render=False):
    role_id = str(payload.get("roleId") or payload.get("role_id") or "").strip()
    report = await fetch_report(payload.get("token"), role_id, payload.get("season"))
    if render:
        async with SUMMARY_SEMAPHORE:
            return await render_report(report, role_id)
    return {"ok": True, "scope": "season", "title": "赛季总结", "roleId": role_id,
            "season": report["season"].get("season"), "summary": report}
