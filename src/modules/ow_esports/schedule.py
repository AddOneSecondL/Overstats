from __future__ import annotations

import asyncio
import datetime as dt
import httpx
from .requests import normalize_ow_esports_rows
from ..errors import ModuleError

REGIONS = {"china": "中国", "korea": "韩国", "japan": "日本", "north_america": "北美", "emea": "EMEA", "world": "世界"}
ALIASES = {**{k: k for k in REGIONS}, **{v.lower(): k for k, v in REGIONS.items()}, "cn": "china", "kr": "korea", "jp": "japan", "na": "north_america", "north america": "north_america", "全球": "world", "全部": "world", "欧洲": "emea"}


def normalize_region(value):
    key = str(value or "china").strip().lower()
    if key not in ALIASES:
        raise ModuleError(error="invalid_esports_region", message="赛区支持：中国、韩国、日本、北美、EMEA、世界。", status_code=400)
    return ALIASES[key]


def region_of(match):
    name = str((match.get("serie") or {}).get("full_name") or (match.get("serie") or {}).get("name") or "").lower()
    for prefix, region in (("china", "china"), ("korea", "korea"), ("japan", "japan"), ("north america", "north_america"), ("emea", "emea")):
        if prefix in name:
            return region
    return "world"


async def fetch_schedule(key, region, *, transport=None):
    requested = normalize_region(region)
    async with httpx.AsyncClient(timeout=30, trust_env=False, transport=transport,
                                 headers={"Authorization": "Bearer " + key}) as client:
        async def get(path, params=None):
            try:
                response = await client.get("https://api.pandascore.co" + path, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                raise ModuleError(error="ow_esports_unavailable", message="赛事数据暂不可用，请稍后重试。", status_code=502) from None
        async def pages(state, *, path=None):
            result = []
            cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
            for page in range(1, 101):
                batch = await get(path or ("/ow/matches/" + state), {"per_page": 100, "page": page, **({"sort": "-scheduled_at"} if state == "past" else {})})
                if not isinstance(batch, list):
                    raise ModuleError(error="ow_esports_invalid_payload", message="赛事数据格式异常。", status_code=502)
                if state == "past":
                    recent = [m for m in batch if str(m.get("scheduled_at") or m.get("begin_at") or "") >= cutoff]
                    result.extend(recent)
                    if len(recent) < len(batch):
                        return result
                else:
                    result.extend(batch)
                if len(batch) < 100:
                    return result
            raise ModuleError(error="ow_esports_too_many_matches", message="赛事数据过多，请稍后重试。", status_code=502)
        batches = await asyncio.gather(pages("running"), pages("upcoming"), pages("past"))
        matches = list({m["id"]: m for batch in batches for m in batch}.values())
        selected = matches if requested == "world" else [m for m in matches if region_of(m) == requested]
        effective = requested
        if requested == "china" and not selected:
            selected, effective = matches, "world"
        groups = {}
        for match in selected:
            groups.setdefault(match["tournament_id"], []).append(match)
        semaphore = asyncio.Semaphore(4)
        async def tournament(tid, scheduled):
            async with semaphore:
                detail = await get(f"/tournaments/{tid}")
                # Fetch the entire selected tournament, including finished matches.
                # Global historical matches would pull unrelated seasons into the schedule.
                history = await pages("", path=f"/tournaments/{tid}/matches")
                raw = list({m["id"]: m for m in [*scheduled, *history]}.values())
                bracket = False
                if detail.get("has_bracket"):
                    try:
                        bracket_rows = await get(f"/tournaments/{tid}/brackets")
                        if isinstance(bracket_rows, list) and bracket_rows:
                            raw = list({m["id"]: m for m in [*raw, *bracket_rows]}.values())
                            bracket = any(m.get("previous_matches") for m in raw)
                    except ModuleError:
                        pass  # Keep the actual schedule if bracket access is unavailable.
                normalized = []
                for m in raw:
                    row = normalize_ow_esports_rows([m])[0]
                    row.update(id=m["id"], previous_matches=m.get("previous_matches") or [],
                               winner_id=m.get("winner_id"), number_of_games=m.get("number_of_games"),
                               match_type=m.get("match_type"))
                    normalized.append(row)
                normalized.sort(key=lambda r: (r.get("start_timestamp") or 0, r["id"]))
                return {"region": region_of(scheduled[0]), "name": detail.get("name") or "赛事",
                        "series": (detail.get("serie") or {}).get("full_name") or "",
                        "tournament_id": tid, "bracket": bracket, "rows": normalized}
        sections = await asyncio.gather(*(tournament(tid, rows) for tid, rows in groups.items()))
        sections.sort(key=lambda s: (list(REGIONS).index(s["region"]), min((r.get("start_timestamp") or 0 for r in s["rows"]), default=0)))
        return requested, effective, sections
