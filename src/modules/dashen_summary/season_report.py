"""Season report prototype. Intentionally absent from the public UI registry."""
from __future__ import annotations

import math
import re
from pathlib import Path

import httpx

from .engine import SUMMARY_SEMAPHORE
from ..season_config import get_dashen_current_season
from ..errors import ModuleError
from .season_report_ranks import classify_ranks, enrich_rank_queues

RESOURCE_DIR = Path(__file__).resolve().parents[3] / "res"

ENDPOINT = "https://datamsapi.ds.163.com/v1/dsbdld5/ld5_season_report/season_summary_by_season"
REPORT_YEAR = 2026
CARD_ENDPOINT = "https://datamsapi.ds.163.com/v1/a19ld5tool/customer/queryCard"
MODE_NAMES = {"1": "休闲比赛", "2": "竞技比赛"}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


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
    return MODE_NAMES.get(str(value), f"模式 {value}" if value is not None else "—")


def match_data(item):
    detail = mapping(item.get("match_detail"))
    mine = mapping(detail.get("myMatchDetail"))
    return {
        "hero": mine.get("heroGuid"), "map": detail.get("mapGuid"),
        "kill": mine.get("kill"), "assist": mine.get("assist"), "death": mine.get("death"),
        "damage": mine.get("heroDamage"), "cure": mine.get("cure"), "resist_damage": mine.get("resistDamage"),
        "rank": pick(mine.get("rankInfo"), "rank_name rankName rank_sub_tier rankSubTier rankScore"),
        "perks": [pick(p, "guid id perkGuid perkLevel") for p in rows(mine.get("perks"))],
        "result": detail.get("matchRet"), "team_score": detail.get("teamScore"),
        "opponent_score": detail.get("opponentScore"), "begin_ts": mine.get("beginTs"),
    }


def own_match_token(data, role_id):
    return next((
        mine.get("customerToken")
        for entry in rows(data.get("match_summary")) + rows(data.get("true_match_summary"))
        for mine in [mapping(mapping(entry.get("match_detail")).get("myMatchDetail"))]
        if str(mine.get("bnetId") or "") == role_id and mine.get("customerToken")
    ), None)


def parse_report(payload):
    if isinstance(payload, dict) and payload.get("errorMsg") == "NOT_REPORT_DATA":
        raise ModuleError(error="season_report_empty", message="该玩家在此赛季暂无报告。", status_code=404)
    if not isinstance(payload, dict) or payload.get("code") != 0 or payload.get("success") is False:
        raise ModuleError(error="season_report_upstream_error", message="赛季报告接口返回失败，请检查 token 是否有效。", status_code=502)
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("season_summary"), dict) or not data["season_summary"]:
        raise ModuleError(error="season_report_empty", message="暂无该玩家的赛季报告。", status_code=404)
    # Whitelist fields: upstream match details contain customerToken and other credentials.
    report = {
        "icon": str(data.get("icon") or ""),
        "season": pick(data.get("season_summary"), "bnet_account_id season match_cnt online_time ahead_rate oneday_max_online_dt oneday_max_online_time get_honors_cnt send_honors_cnt mode_most_play mode_most_play_match_cnt stadium_match_cnt stadium_worth"),
        "overview": pick(data.get("season_overview_summary"), "bnet_account_id first_landing_day match_cnt active_day_cnt active_day_rate online_time online_time_rate win_rate win_rate_rate kill_sum kill_rnk_rate assist_sum assist_rnk_rate damage_sum damage_rnk_rate cure_sum cure_rnk_rate resist_damage_sum resist_damage_rate role_most_play mode_most_play max_rank_level"),
        "ranks": [pick(r, "mode_type most_play_hero_guid final_rank_level max_rank_level win_rate match_cnt ruleset_queue_guid ip_province player_rank") for r in rows(data.get("rank_summary"))],
        "heroes": [pick(r, "role_type role_most_play_hero_guid role_match_cnt role_win_rate damage resist_damage cure kill assist stat_map") for r in rows(data.get("role_summary")) if str(r.get("role_type")) != "-1"],
        "focus": next((pick(r, "role_most_play_hero_guid role_match_cnt role_win_rate stat_map") for r in rows(data.get("role_summary")) if str(r.get("role_type")) == "-1"), {}),
        "lootbox": pick(data.get("lootbox_summary"), "open_lootbox_cnt epic_cnt legendary_cnt"),
        "friends": [pick(r, "friend_name friend_icon with_friend_match_cnt with_friend_win_rate") for r in rows(data.get("friend_summary"))],
        "highlights": [],
        "low_win_heroes": [pick(r, "hero_guid match_cnt win_rate") for r in rows(data.get("low_win_hero_summary"))],
        "true_matches": [{**pick(r, "match_type match_cnt"), **match_data(r)} for r in rows(data.get("true_match_summary"))],
        "player_name": str(data.get("name") or data.get("battletag") or ""),
    }
    for item in rows(data.get("match_summary")):
        # Only these three record types can be checked against the actual match stats.
        key = {"1": "heroDamage", "2": "resistDamage", "3": "cure"}.get(str(item.get("matchType")))
        mine = mapping(mapping(item.get("match_detail")).get("myMatchDetail"))
        if key and mine:
            report["highlights"].append({**match_data(item), "metric": key, "value": mine.get(key)})
    for hero in report["heroes"] + [report["focus"]]:
        if "stat_map" in hero:
            unique = []
            for raw in rows(hero["stat_map"]):
                stat = pick(raw, "index_name index_value index_rate")
                if stat not in unique:
                    unique.append(stat)
            hero["stat_map"] = unique
    classify_ranks(report["ranks"])
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
            report = parse_report(payload)
            report["season"].setdefault("season", selected_season)
            # The report omits the BattleTag; use its own customer token in memory only.
            data = mapping(payload.get("data"))
            own_token = own_match_token(data, role_id)
            # Old reports can retain totals after all match details have expired.
            # A single recent-report lookup is used only to recover the identity.
            recent_season = resolve_season()
            if not report["player_name"] and not own_token and selected_season != recent_season:
                try:
                    recent_response = await client.get(ENDPOINT, params={
                        "token": token, "roleId": role_id, "season": recent_season,
                        "dts": REPORT_YEAR, "appKey": "ld5", "server": 1,
                    }, timeout=10)
                    recent_response.raise_for_status()
                    recent_payload = recent_response.json()
                    own_token = own_match_token(mapping(recent_payload.get("data")), role_id)
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
            if own_token and report["ranks"]:
                await enrich_rank_queues(client, report["ranks"], customer_token=own_token,
                                         token=token, role_id=role_id, season=selected_season, dts=REPORT_YEAR)
            if not report["player_name"] and own_token:
                try:
                    card_response = await client.get(CARD_ENDPOINT, params={"token": own_token}, headers={
                        "GL-Bigdata-Auth-Token": token, "GL-Bigdata-Role-Id": role_id,
                        "GL-Bigdata-Dts": str(REPORT_YEAR), "GL-Bigdata-Server": "1",
                    }, timeout=10)
                    card_response.raise_for_status()
                    card_payload = card_response.json()
                    card = mapping(card_payload.get("data"))
                    if card_payload.get("code") == 0 and str(card.get("bnetId") or "") == role_id:
                        report["player_name"] = str(card.get("name") or "")
                        report["icon"] = str(card.get("icon") or report["icon"])
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
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
