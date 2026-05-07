from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from overstats.src.client.apiclient import DashenAPIClient, dashen_api_client
except ModuleNotFoundError:
    from src.client.apiclient import DashenAPIClient, dashen_api_client


STATUS_LIVE = "正在进行"
STATUS_UPCOMING = "未开始"
STATUS_FINISHED = "已结束"
UNKNOWN_TEXT = "未知"
UNKNOWN_LEAGUE = "未分类赛事"

OW_ESPORTS_STATUS_ORDER = (STATUS_LIVE, STATUS_UPCOMING, STATUS_FINISHED)
OW_ESPORTS_ENDED_LIMIT = 10


def parse_ow_esports_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone()
    return parsed


def format_ow_esports_time(value: Any) -> str:
    parsed = parse_ow_esports_time(value)
    if not parsed:
        return UNKNOWN_TEXT
    return parsed.strftime("%Y-%m-%d %H:%M")


def map_ow_esports_status(raw_status: Any) -> str:
    normalized = str(raw_status or "").strip().lower()
    if normalized in {"running", "live"}:
        return STATUS_LIVE
    if normalized in {"not_started", "upcoming"}:
        return STATUS_UPCOMING
    return STATUS_FINISHED


def normalize_ow_esports_region(region: Any) -> str:
    normalized = str(region or "").strip().upper()
    if not normalized:
        return ""
    if normalized == "TW":
        return "CN(TW)"
    if normalized == "HK":
        return "CN(HK)"
    return normalized


def extract_ow_esports_team(wrapper: Any, fallback_region: str = UNKNOWN_TEXT) -> Dict[str, Any]:
    opponent = wrapper.get("opponent") if isinstance(wrapper, Mapping) else {}
    if not isinstance(opponent, Mapping):
        opponent = wrapper if isinstance(wrapper, Mapping) else {}
    if not isinstance(opponent, Mapping):
        opponent = {}

    region = normalize_ow_esports_region(
        opponent.get("location")
        or (wrapper.get("location") if isinstance(wrapper, Mapping) else "")
        or fallback_region
    )
    return {
        "id": opponent.get("id"),
        "name": str(opponent.get("name") or opponent.get("acronym") or "TBD").strip() or "TBD",
        "short_name": str(opponent.get("acronym") or opponent.get("name") or "TBD").strip() or "TBD",
        "logo": str(opponent.get("image_url") or opponent.get("dark_mode_image_url") or "").strip(),
        "region": region,
    }


def extract_ow_esports_score_pair(
    match_item: Mapping[str, Any],
    team1: Mapping[str, Any],
    team2: Mapping[str, Any],
) -> tuple[Optional[int], Optional[int]]:
    results = match_item.get("results")
    if not isinstance(results, list):
        return None, None

    score_map: Dict[Any, Any] = {}
    for item in results:
        if not isinstance(item, Mapping):
            continue
        team_id = item.get("team_id")
        if team_id is None:
            continue
        score_map[team_id] = item.get("score")

    score1 = score_map.get(team1.get("id"))
    score2 = score_map.get(team2.get("id"))
    if score1 is None and score2 is None:
        return None, None
    return _safe_int(score1), _safe_int(score2)


def normalize_ow_esports_rows(payload: Any) -> List[Dict[str, Any]]:
    match_items = extract_ow_esports_match_items(payload)
    rows: List[Dict[str, Any]] = []
    for item in match_items:
        if not isinstance(item, Mapping):
            continue

        league = item.get("league") if isinstance(item.get("league"), Mapping) else {}
        tournament = item.get("tournament") if isinstance(item.get("tournament"), Mapping) else {}
        series = item.get("serie") if isinstance(item.get("serie"), Mapping) else {}
        league_name = (
            str(league.get("name") or tournament.get("name") or series.get("name") or UNKNOWN_LEAGUE).strip()
            or UNKNOWN_LEAGUE
        )
        fallback_region = (
            str(tournament.get("region") or series.get("region") or league.get("region") or "").strip()
            or UNKNOWN_TEXT
        )
        status_text = map_ow_esports_status(item.get("status"))
        opponents = item.get("opponents")
        if not isinstance(opponents, list):
            opponents = []

        team1 = extract_ow_esports_team(opponents[0] if len(opponents) > 0 else {}, fallback_region)
        team2 = extract_ow_esports_team(opponents[1] if len(opponents) > 1 else {}, fallback_region)
        begin_at = (
            item.get("begin_at")
            or item.get("scheduled_at")
            or item.get("original_scheduled_at")
            or item.get("start_at")
        )
        begin_dt = parse_ow_esports_time(begin_at)
        start_timestamp = int(begin_dt.timestamp()) if begin_dt else None
        score1, score2 = extract_ow_esports_score_pair(item, team1, team2)

        rows.append(
            {
                "league_name": league_name,
                "status": status_text,
                "raw_status": str(item.get("status") or "").strip() or "unknown",
                "match_name": str(item.get("name") or "").strip() or f"{team1['short_name']} vs {team2['short_name']}",
                "start_time": format_ow_esports_time(begin_at),
                "start_timestamp": start_timestamp,
                "score": build_ow_esports_score_text(score1, score2, status_text),
                "score1": score1,
                "score2": score2,
                "team1": team1,
                "team2": team2,
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("league_name") or ""),
            row.get("start_timestamp") is None,
            row.get("start_timestamp") if row.get("start_timestamp") is not None else 2**31 - 1,
            str(row.get("match_name") or ""),
        )
    )
    return rows


def build_ow_esports_score_text(score1: Optional[int], score2: Optional[int], status_text: str) -> str:
    if status_text == STATUS_UPCOMING:
        return STATUS_UPCOMING
    if score1 is None and score2 is None:
        return status_text
    return f"{0 if score1 is None else score1}:{0 if score2 is None else score2}"


def build_ow_esports_sections(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        league_name = str(row.get("league_name") or UNKNOWN_LEAGUE).strip() or UNKNOWN_LEAGUE
        status = str(row.get("status") or STATUS_FINISHED).strip() or STATUS_FINISHED
        grouped.setdefault(league_name, {}).setdefault(status, []).append(dict(row))

    sections: List[Dict[str, Any]] = []
    for league_name in sorted(grouped.keys()):
        status_sections: List[Dict[str, Any]] = []
        for status_name in OW_ESPORTS_STATUS_ORDER:
            rows_in_status = list(grouped[league_name].get(status_name) or [])
            if not rows_in_status:
                continue
            if status_name == STATUS_FINISHED:
                rows_to_show = sorted(rows_in_status, key=lambda row: _row_timestamp(row), reverse=True)[:OW_ESPORTS_ENDED_LIMIT]
            else:
                rows_to_show = sorted(rows_in_status, key=lambda row: _row_timestamp(row))
            status_sections.append(
                {
                    "status": status_name,
                    "rows": rows_to_show,
                    "hidden_count": max(0, len(rows_in_status) - len(rows_to_show)),
                }
            )
        sections.append({"league_name": league_name, "status_sections": status_sections})
    return sections


def extract_ow_esports_match_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        if not payload:
            return []
        if all(isinstance(item, Mapping) for item in payload):
            return [dict(item) for item in payload]

    direct_candidates = []
    if isinstance(payload, Mapping):
        for key in ("data", "results", "matches", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                direct_candidates.append(value)
            elif isinstance(value, Mapping):
                for nested_key in ("data", "results", "matches", "items"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, list):
                        direct_candidates.append(nested_value)

    scored: List[tuple[int, int, List[Dict[str, Any]]]] = []
    for index, candidate in enumerate(direct_candidates):
        normalized_candidate = _normalize_candidate_list(candidate)
        if normalized_candidate is None:
            continue
        scored.append((_match_candidate_score(normalized_candidate), index, normalized_candidate))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_candidate = scored[0]
        if best_score > 0 or not best_candidate:
            return best_candidate

    recursive_candidates: List[List[Dict[str, Any]]] = []
    seen = set()
    for candidate in _iter_recursive_list_candidates(payload):
        normalized_candidate = _normalize_candidate_list(candidate)
        if normalized_candidate is None:
            continue
        key = id(candidate)
        if key in seen:
            continue
        seen.add(key)
        recursive_candidates.append(normalized_candidate)

    if not recursive_candidates:
        raise ValueError("OW esports payload does not contain a match list.")

    best_candidate = max(recursive_candidates, key=_match_candidate_score)
    if _match_candidate_score(best_candidate) <= 0 and best_candidate:
        raise ValueError("OW esports payload match list is not recognizable.")
    return best_candidate


def _iter_recursive_list_candidates(node: Any, *, depth: int = 0, max_depth: int = 6) -> Iterable[Any]:
    if depth > max_depth:
        return
    if isinstance(node, list):
        yield node
        for item in node[:24]:
            if isinstance(item, (list, Mapping)):
                yield from _iter_recursive_list_candidates(item, depth=depth + 1, max_depth=max_depth)
        return
    if isinstance(node, Mapping):
        for value in node.values():
            if isinstance(value, (list, Mapping)):
                yield from _iter_recursive_list_candidates(value, depth=depth + 1, max_depth=max_depth)


def _normalize_candidate_list(value: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(value, list):
        return None
    if not value:
        return []
    if not all(isinstance(item, Mapping) for item in value):
        return None
    return [dict(item) for item in value]


def _match_candidate_score(items: Sequence[Mapping[str, Any]]) -> int:
    if not items:
        return 1
    score = 0
    for item in items[:24]:
        if _looks_like_match_item(item):
            score += 6
        if isinstance(item.get("league"), Mapping):
            score += 2
        if isinstance(item.get("tournament"), Mapping):
            score += 1
        if isinstance(item.get("opponents"), list):
            score += 2
        if item.get("status") is not None:
            score += 1
    return score


def _looks_like_match_item(item: Mapping[str, Any]) -> bool:
    return any(
        (
            isinstance(item.get("opponents"), list),
            isinstance(item.get("results"), list),
            isinstance(item.get("league"), Mapping),
            isinstance(item.get("tournament"), Mapping),
            item.get("status") is not None,
            item.get("begin_at") is not None,
            item.get("scheduled_at") is not None,
        )
    )


def _row_timestamp(row: Mapping[str, Any]) -> int:
    value = row.get("start_timestamp")
    if value is None:
        return 2**31 - 1
    return _safe_int(value, default=2**31 - 1)


def _safe_int(value: Any, *, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class OWEsportsRequests:
    def __init__(self, api_client: Optional[DashenAPIClient] = None) -> None:
        self.api_client = api_client or dashen_api_client

    async def fetch_payload(self) -> Any:
        return await self.api_client.fetch_ow_esports_payload()

    async def fetch_rows(self) -> List[Dict[str, Any]]:
        payload = await self.fetch_payload()
        return normalize_ow_esports_rows(payload)

    async def fetch_logo_assets(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        max_concurrency: int = 8,
    ) -> Dict[str, bytes]:
        urls: List[str] = []
        seen = set()
        for row in rows or []:
            for team_key in ("team1", "team2"):
                team = row.get(team_key)
                if not isinstance(team, Mapping):
                    continue
                logo = str(team.get("logo") or "").strip()
                if not logo or not logo.startswith(("http://", "https://")) or logo in seen:
                    continue
                seen.add(logo)
                urls.append(logo)

        if not urls:
            return {}

        semaphore = asyncio.Semaphore(max(1, int(max_concurrency or 1)))
        assets: Dict[str, bytes] = {}

        async def run(url: str) -> None:
            async with semaphore:
                try:
                    content = await self.api_client.get_icon(url)
                except Exception as exc:
                    print(f"[overstats] ow_esports logo fetch failed: url={url} error={type(exc).__name__}: {exc}")
                    return
                if content:
                    assets[url] = content

        await asyncio.gather(*(run(url) for url in urls))
        return assets
