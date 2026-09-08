"""Identify season-report queues using same-season, explicitly scoped API data."""
from __future__ import annotations

import asyncio
import httpx

ROLE_GUIDS = {
    "972777519512029264": "tank",
    "972777519512029262": "dps",
    "972777519512029265": "healer",
}
QUEUE_LABELS = {"preset": "预设职责", "open": "开放职责", "stadium": "角斗领域", "unknown": "未识别队列"}
ROLE_LABELS = {"tank": "重装", "dps": "输出", "healer": "支援"}


def queue_guids(value):
    found = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"rulesetQueueGuid", "ruleset_queue_guid"} and nested is not None:
                found.add(str(nested))
            elif isinstance(nested, (dict, list)):
                found.update(queue_guids(nested))
    elif isinstance(value, list):
        for item in value:
            found.update(queue_guids(item))
    return found


def classify_ranks(rank_rows, sport_data=None, stadium_data=None):
    sport_data = sport_data if isinstance(sport_data, dict) else {}
    stadium_data = stadium_data if isinstance(stadium_data, dict) else {}
    candidates = {}
    sources = [
        ("preset", sport_data.get("presetsHeroUseSummaryList")),
        ("preset", sport_data.get("presetsSummaryData")),
        ("open", sport_data.get("openHeroUseSummaryList")),
        ("open", sport_data.get("openSummaryData")),
        ("stadium", stadium_data),
    ]
    # Competitive role cards can also carry explicit queue ids.
    for row in sport_data.get("guideCountData") or []:
        if isinstance(row, dict) and row.get("roleType") in {"tank", "dps", "healer", "open"}:
            sources.append(("open" if row["roleType"] == "open" else "preset", row))
    for category, source in sources:
        for guid in queue_guids(source):
            candidates.setdefault(guid, set()).add(category)
    for row in rank_rows:
        categories = candidates.get(str(row.get("ruleset_queue_guid") or ""), set())
        category = next(iter(categories)) if len(categories) == 1 else "unknown"
        row["queue_type"] = category
        row["queue_label"] = QUEUE_LABELS[category]
        row["role_type"] = "open" if category == "open" else ROLE_GUIDS.get(str(row.get("mode_type")), "unknown")
    return rank_rows


async def enrich_rank_queues(client, rank_rows, *, customer_token, token, role_id, season, dts):
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
                    return {}
                return data
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return {}

    sport, stadium = await asyncio.gather(fetch("queryCountInfo", {"gameMode": "sport"}), fetch("fight/queryCount", {}))
    classify_ranks(rank_rows, sport, stadium)
