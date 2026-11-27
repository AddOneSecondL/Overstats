"""Identify season-report queues using same-season, explicitly scoped API data."""
from __future__ import annotations

import asyncio
import re

import httpx

from ...constants.rank_queues import (
    QUEUE_LABELS, ROLE_LABELS, normalize_rank_role, queue_mode, rank_card_track, rank_queue_key,
)
from .runtime.summary_perks import guid
from .season_report_fields import number

STADIUM_RANKS = ("菜鸟", "新秀", "斗士", "精英", "专家", "全明星", "传奇")


def rank_role(row):
    return next((role for field in ("role_type", "roleType", "role_guid", "roleGuid", "mode_type", "modeType")
                 if (role := normalize_rank_role(row.get(field)))), None)


def queue_guids(value):
    found = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"rulesetQueueGuid", "ruleset_queue_guid"} and isinstance(nested, (str, int)) and guid(nested) not in {"", "0"}:
                found.add(guid(nested))
            elif isinstance(nested, (dict, list)):
                found.update(queue_guids(nested))
    elif isinstance(value, list):
        for item in value:
            found.update(queue_guids(item))
    return found


def classify_ranks(rank_rows, sport_data=None, stadium_data=None, *, matches=()):
    can_compare_totals = isinstance(sport_data, dict) and isinstance(stadium_data, dict)
    sport_data = sport_data if isinstance(sport_data, dict) else {}
    stadium_data = stadium_data if isinstance(stadium_data, dict) else {}
    candidates = {}
    cards = []
    for scope, values in (("preset", sport_data.get("guideCountData")), ("stadium", stadium_data.get("roleTypeCountData"))):
        for card in values or []:
            if isinstance(card, dict):
                queue, role = rank_card_track(card, scope)
                if rank_queue_key(queue, role) is not None:
                    cards.append((queue, role, card, queue_guids(card)))
    sources = [
        ("preset", sport_data.get("presetsHeroUseSummaryList")),
        ("preset", sport_data.get("presetsSummaryData")),
        ("open", sport_data.get("openHeroUseSummaryList")),
        ("open", sport_data.get("openSummaryData")),
        ("stadium", stadium_data),
    ]
    for queue, _, _, card_ids in cards:
        for queue_id in card_ids:
            candidates.setdefault(queue_id, set()).add(queue)
    for row in [*matches, *(sport_data.get("matchList") or [])]:
        if isinstance(row, dict) and (category := queue_mode(row.get("game_mode") or row.get("gameMode"))):
            sources.append((category, row))
    for category, source in sources:
        for queue_id in queue_guids(source):
            candidates.setdefault(queue_id, set()).add(category)

    def matching_tracks(row, role, queue_id):
        count, rate = number(row.get("match_cnt")), number(row.get("win_rate"))
        if count is None or count <= 0 or rate is None:
            return set()
        tracks = set()
        for queue, card_role, card, card_ids in cards:
            if (role and card_role != role) or (card_ids and queue_id not in {"", "0"} and queue_id not in card_ids):
                continue
            card_rate = number(card.get("winRate"))
            if number(card.get("matchSum")) == count and card_rate is not None and abs(card_rate - rate) <= 0.05:
                tracks.add((queue, card_role))
        return tracks

    for row in rank_rows:
        role = rank_role(row)
        queue_id = guid(row.get("ruleset_queue_guid"))
        categories = candidates.get(queue_id, set())
        mode = str(row.get("queue_mode") or "").strip()
        explicit = queue_mode(mode) or queue_mode(row.get("mode_type"))
        generic_mode = mode.casefold() in {"", "sport"}
        rank_names = [re.sub(r"\d+\s*$", "", str(row.get(key) or "").replace("\u200c", "")).strip()
                      for key in ("final_rank_level", "max_rank_level")]
        if explicit is None and any(name in STADIUM_RANKS for name in rank_names):
            explicit = "stadium"
        if explicit is None and generic_mode and role == "open" and not categories:
            explicit = "open"
        totals = matching_tracks(row, role, queue_id)
        if explicit:
            categories = {explicit}
        elif not categories and generic_mode and can_compare_totals:
            categories = {queue for queue, _ in totals}
        category = next(iter(categories)) if len(categories) == 1 else "unknown"
        if category in {"preset", "stadium"} and not role:
            roles_with_guid = {card_role for queue, card_role, _, card_ids in cards
                               if queue == category and queue_id in card_ids}
            roles_with_totals = {card_role for queue, card_role in totals if queue == category}
            roles = (roles_with_guid & roles_with_totals) if roles_with_guid and roles_with_totals else (roles_with_guid or roles_with_totals)
            if len(roles) == 1:
                role = next(iter(roles))
        row["queue_type"] = category
        row["queue_label"] = ROLE_LABELS.get(role, QUEUE_LABELS[category]) if category == "unknown" else QUEUE_LABELS[category]
        row["role_type"] = "open" if category == "open" else role if role in ROLE_LABELS else "unknown"
        row["queue_key"] = rank_queue_key(category, row["role_type"])
    return rank_rows


async def enrich_rank_queues(client, rank_rows, *, customer_token, token, role_id, season, dts,
                             matches=()):
    async def fetch(path, params):
        try:
            response = await client.get(
                "https://datamsapi.ds.163.com/v1/a19ld5tool/customer/" + path,
                params={"token": customer_token, "season": season, **params},
                headers={"GL-Bigdata-Auth-Token": token, "GL-Bigdata-Role-Id": role_id,
                         "GL-Bigdata-Dts": str(dts), "GL-Bigdata-Server": "1"}, timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if payload.get("code") == 0 and isinstance(data, dict):
                if data.get("bnetId") is not None and str(data["bnetId"]) != role_id:
                    return None
                if data.get("season") is not None and number(data["season"]) != season:
                    return None
                return data
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return None

    sport, stadium = await asyncio.gather(fetch("queryCountInfo", {"gameMode": "sport"}), fetch("fight/queryCount", {}))
    classify_ranks(rank_rows, sport, stadium, matches=matches)
