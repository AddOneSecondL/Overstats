from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from typing import Any, Dict, Iterable, Optional

try:
    from overstats.src.modules.dashen_profile.engine import HeroUsageRow, ProfileRenderContext
except ModuleNotFoundError:
    from src.modules.dashen_profile.engine import HeroUsageRow, ProfileRenderContext


BLIZZARD_PROFILE_FETCH_LOCALE = "en-us"
BLIZZARD_HERO_TITLE_QUICK = "QUICK PLAY HERO TIME"
BLIZZARD_HERO_TITLE_COMPETITIVE = "COMPETITIVE HERO TIME"

_PROFILE_NAME_RE = re.compile(r'<h1 class="Profile-player--name">(.*?)</h1>', re.DOTALL)
_PROFILE_TITLE_RE = re.compile(r'<h2 class="Profile-player--title">(.*?)</h2>', re.DOTALL)
_PROFILE_PORTRAIT_RE = re.compile(r'<img class="Profile-player--portrait" src="([^"]+)"', re.DOTALL)
_PROFILE_ENDORSEMENT_RE = re.compile(
    r'Profile-playerSummary--endorsement" src="[^"]*/(\d+)-[^"]*',
    re.DOTALL,
)
_PROFILE_LAST_UPDATED_RE = re.compile(
    r'<blz-section class="Profile-masthead"[^>]*data-lastUpdate="(\d+)"',
    re.DOTALL,
)
_PLATFORM_BLOCK_RE = re.compile(
    r'<div class="(?P<platform>mouseKeyboard-view|controller-view) Profile-view(?: is-active)?">',
    re.DOTALL,
)
_HERO_VIEW_RE = re.compile(
    r'<div class="Profile-heroSummary--view (?P<mode>quickPlay|competitive)-view(?: is-active)?">',
    re.DOTALL,
)
_STATS_SECTION_RE = re.compile(
    r'<blz-section class="stats (?P<mode>quickPlay|competitive)-view(?: is-active)?">',
    re.DOTALL,
)
_OPTION_RE = re.compile(r'<option value="([^"]+)"[^>]*option-id="([^"]+)"[^>]*>', re.DOTALL)
_PROGRESS_BLOCK_RE = re.compile(
    r'<div class="Profile-progressBars(?: is-active)?"[^>]*data-category-id="([^"]+)"[^>]*>',
    re.DOTALL,
)
_PROGRESS_ENTRY_RE = re.compile(
    r'<div class="Profile-progressBar(?: hide)?">.*?'
    r'<img class="Profile-progressBar--icon" src="([^"]+)".*?'
    r'data-hero-id="([^"]*)".*?'
    r'Profile-progressBar--progress" style="--hero-color:([^;"\s]+)[^"]*".*?'
    r'<div class="Profile-progressBar-title">(.*?)</div>'
    r'<div class="Profile-progressBar-description">(.*?)</div>',
    re.DOTALL,
)
_STATS_CONTAINER_RE = re.compile(r'<span class="stats-container option-(\d+)">', re.DOTALL)
_CATEGORY_BLOCK_RE = re.compile(r'<div class="category">', re.DOTALL)
_CATEGORY_HEADER_RE = re.compile(r'<div class="header"><p>(.*?)</p></div>', re.DOTALL)
_STAT_ITEM_RE = re.compile(
    r'<div class="stat-item"><p class="name">(.*?)</p><p class="value">(.*?)</p></div>',
    re.DOTALL,
)
_STRIP_TAG_RE = re.compile(r"<[^>]+>")
_DIGIT_SUFFIX_RE = re.compile(r"^(.*?)[#-](\d+)$")


@dataclass(frozen=True)
class BlizzardProfileSummary:
    display_name: str
    title: str
    avatar_url: str
    endorsement_level: int
    last_updated_at: int
    platform: str
    mode: str
    time_played_raw: str
    game_time_hours: float
    ave_kill: float
    ave_hero_damage: float
    ave_healing: float
    ave_resist_damage: float
    ave_death: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "title": self.title,
            "avatar_url": self.avatar_url,
            "endorsement_level": self.endorsement_level,
            "last_updated_at": self.last_updated_at,
            "platform": self.platform,
            "mode": self.mode,
            "time_played": self.time_played_raw,
            "game_time_hours": round(self.game_time_hours, 2),
            "ave_kill": self.ave_kill,
            "ave_hero_damage": self.ave_hero_damage,
            "ave_healing": self.ave_healing,
            "ave_resist_damage": self.ave_resist_damage,
            "ave_death": self.ave_death,
        }


@dataclass(frozen=True)
class BlizzardParsedProfile:
    summary: BlizzardProfileSummary
    selected_payload: Dict[str, Any]
    hero_title: str
    hero_rows: tuple[HeroUsageRow, ...]
    top_heroes: tuple[HeroUsageRow, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "hero_title": self.hero_title,
            "top_heroes": [_hero_row_to_dict(item) for item in self.top_heroes],
            "hero_rows": [_hero_row_to_dict(item) for item in self.hero_rows],
            "selected_payload": self.selected_payload,
        }


def parse_blizzard_profile_html(
    html: str,
    *,
    mode: str = "quick",
    preferred_title: str = "",
    preferred_last_updated_at: int = 0,
) -> BlizzardParsedProfile:
    normalized_mode = _normalize_mode(mode)
    display_name = _extract_text(_PROFILE_NAME_RE, html)
    if not display_name:
        raise ValueError("Player profile summary is unavailable.")

    title = preferred_title or _extract_text(_PROFILE_TITLE_RE, html)
    avatar_url = _extract_text(_PROFILE_PORTRAIT_RE, html)
    endorsement_level = _extract_int(_PROFILE_ENDORSEMENT_RE, html)
    last_updated_at = preferred_last_updated_at or _extract_int(_PROFILE_LAST_UPDATED_RE, html)

    hero_view_html, stats_html, platform = _select_profile_sections(html, normalized_mode)
    comparisons = _parse_hero_comparisons(hero_view_html)
    stats_by_hero = _parse_career_stats(stats_html)
    summary_stats = _build_summary_stats(stats_by_hero, comparisons)
    hero_rows = _build_hero_rows(comparisons, stats_by_hero)

    summary = BlizzardProfileSummary(
        display_name=display_name,
        title=title,
        avatar_url=avatar_url,
        endorsement_level=endorsement_level,
        last_updated_at=last_updated_at,
        platform=platform,
        mode=normalized_mode,
        time_played_raw=summary_stats["time_played_raw"],
        game_time_hours=summary_stats["game_time_hours"],
        ave_kill=summary_stats["ave_kill"],
        ave_hero_damage=summary_stats["ave_hero_damage"],
        ave_healing=summary_stats["ave_healing"],
        ave_resist_damage=summary_stats["ave_resist_damage"],
        ave_death=summary_stats["ave_death"],
    )
    return BlizzardParsedProfile(
        summary=summary,
        selected_payload=_build_selected_payload(summary_stats),
        hero_title=BLIZZARD_HERO_TITLE_COMPETITIVE if normalized_mode == "competitive" else BLIZZARD_HERO_TITLE_QUICK,
        hero_rows=hero_rows,
        top_heroes=hero_rows[:3],
    )


def build_blizzard_render_context(
    parsed: BlizzardParsedProfile,
    *,
    resolved_player_label: str = "",
) -> ProfileRenderContext:
    battletag, battlenum = _resolve_battletag_display(resolved_player_label, parsed.summary.display_name)
    return ProfileRenderContext(
        profile_card={
            "data": {
                "name": parsed.summary.display_name,
                "title": parsed.summary.title,
                "icon": parsed.summary.avatar_url,
                "level": parsed.summary.endorsement_level,
                "gameTime": parsed.summary.game_time_hours,
            }
        },
        sport_payload={},
        leisure_payload={},
        resolved_name=resolved_player_label,
        battletag=battletag,
        battlenum=battlenum,
        title=parsed.summary.title,
        level=parsed.summary.endorsement_level,
        game_time=parsed.summary.game_time_hours,
        risk_status=None,
        logical_season=None,
        quick_mode=parsed.summary.mode != "competitive",
        avatar_bytes=None,
        selected_payload=parsed.selected_payload,
        role_entries=(),
        hero_title=parsed.hero_title,
        hero_rows=parsed.hero_rows,
        top_heroes=parsed.top_heroes,
        recent_matches=(),
        leftover_open_billboards=(),
        leftover_preset_billboards=(),
        race_progress=None,
    )


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"competitive", "comp", "ranked"}:
        return "competitive"
    return "quick"


def _resolve_battletag_display(player_label: str, display_name: str) -> tuple[str, str]:
    normalized_label = str(player_label or "").strip()
    match = _DIGIT_SUFFIX_RE.fullmatch(normalized_label)
    if match is not None:
        base_name, battlenum = match.groups()
        return str(display_name or base_name or "").strip(), battlenum.strip()
    return str(display_name or normalized_label or "").strip(), ""


def _select_profile_sections(html: str, mode: str) -> tuple[str, str, str]:
    requested_mode = "competitive" if mode == "competitive" else "quickPlay"
    candidates = []
    for match, platform_html in _iter_match_blocks(html, _PLATFORM_BLOCK_RE):
        platform_key = "pc" if match.group("platform") == "mouseKeyboard-view" else "console"
        hero_section = _extract_hero_summary_section(platform_html)
        hero_view_html = _extract_mode_block(hero_section, _HERO_VIEW_RE, requested_mode)
        stats_html = _extract_mode_block(platform_html, _STATS_SECTION_RE, requested_mode)
        if _has_profile_data(hero_view_html) or _has_profile_data(stats_html):
            candidates.append((platform_key, hero_view_html, stats_html))

    if not candidates:
        raise ValueError(f"No Blizzard career data was found for mode={mode}.")

    for preferred in ("pc", "console"):
        for platform_key, hero_view_html, stats_html in candidates:
            if platform_key == preferred:
                return hero_view_html, stats_html, platform_key
    return candidates[0][1], candidates[0][2], candidates[0][0]


def _extract_hero_summary_section(platform_html: str) -> str:
    start = platform_html.find('<blz-section class="Profile-heroSummary"')
    if start < 0:
        return ""
    end_candidates = [
        idx
        for idx in (
            platform_html.find('<blz-section class="stats quickPlay-view', start),
            platform_html.find('<blz-section class="stats competitive-view', start),
        )
        if idx > start
    ]
    end = min(end_candidates) if end_candidates else len(platform_html)
    return platform_html[start:end]


def _extract_mode_block(section_html: str, pattern: re.Pattern[str], mode_name: str) -> str:
    for match, block_html in _iter_match_blocks(section_html, pattern):
        if match.group("mode") == mode_name:
            return block_html
    return ""


def _has_profile_data(section_html: str) -> bool:
    normalized = str(section_html or "")
    if not normalized:
        return False
    return "Profile-progressBar" in normalized or "stats-container option-" in normalized


def _parse_hero_comparisons(hero_view_html: str) -> Dict[str, list[Dict[str, Any]]]:
    option_lookup = {
        category_id: _clean_text(label)
        for category_id, label in _OPTION_RE.findall(hero_view_html or "")
    }
    comparisons: Dict[str, list[Dict[str, Any]]] = {}
    for match, block_html in _iter_match_blocks(hero_view_html, _PROGRESS_BLOCK_RE):
        category_id = match.group(1)
        category_label = _normalize_key(option_lookup.get(category_id, category_id))
        comparisons[category_label] = []
        for icon_url, hero_id, hero_color, hero_name, raw_value in _PROGRESS_ENTRY_RE.findall(block_html):
            comparisons[category_label].append(
                {
                    "hero_id": _clean_text(hero_id),
                    "hero_name": _clean_text(hero_name),
                    "hero_icon_url": _clean_text(icon_url),
                    "hero_color": _clean_text(hero_color),
                    "raw_value": _clean_text(raw_value),
                }
            )
    return comparisons


def _parse_career_stats(stats_html: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    option_lookup = {
        value: _clean_text(label)
        for value, label in _OPTION_RE.findall(stats_html or "")
    }
    stats_by_hero: Dict[str, Dict[str, Dict[str, str]]] = {}
    for match, block_html in _iter_match_blocks(stats_html, _STATS_CONTAINER_RE):
        option_key = match.group(1)
        option_label = option_lookup.get(option_key, option_key)
        hero_key = _normalize_key(option_label)
        category_map: Dict[str, Dict[str, str]] = {}
        for _, category_html in _iter_match_blocks(block_html, _CATEGORY_BLOCK_RE):
            category_label = _normalize_key(_extract_text(_CATEGORY_HEADER_RE, category_html))
            if not category_label:
                continue
            stats_map: Dict[str, str] = {}
            for stat_name, stat_value in _STAT_ITEM_RE.findall(category_html):
                normalized_name = _normalize_key(stat_name)
                if normalized_name and normalized_name not in stats_map:
                    stats_map[normalized_name] = _clean_text(stat_value)
            if stats_map:
                category_map[category_label] = stats_map
        if category_map:
            stats_by_hero[hero_key] = category_map
    return stats_by_hero


def _build_summary_stats(
    stats_by_hero: Dict[str, Dict[str, Dict[str, str]]],
    comparisons: Dict[str, list[Dict[str, Any]]],
) -> Dict[str, Any]:
    all_heroes = stats_by_hero.get("all heroes") or stats_by_hero.get("allheroes") or {}
    average = all_heroes.get("average") or {}
    game = all_heroes.get("game") or {}
    time_played_raw = _first_stat(game, "time played")
    time_played_seconds = _parse_duration_to_seconds(time_played_raw)
    if time_played_seconds <= 0:
        time_played_seconds = int(
            sum(
                _parse_duration_to_seconds(str(item.get("raw_value") or ""))
                for item in comparisons.get("time played", [])
            )
        )
    return {
        "time_played_raw": time_played_raw or _format_seconds_as_clock(time_played_seconds),
        "game_time_hours": round(time_played_seconds / 3600.0, 2) if time_played_seconds > 0 else 0.0,
        "ave_kill": _parse_numeric(_first_stat(average, "eliminations - avg per 10 min")),
        "ave_hero_damage": _parse_numeric(_first_stat(average, "hero damage done - avg per 10 min")),
        "ave_healing": _parse_numeric(_first_stat(average, "healing done - avg per 10 min")),
        "ave_resist_damage": _parse_numeric(
            _first_stat(
                average,
                "damage blocked - avg per 10 min",
                "damage mitigated - avg per 10 min",
                "damage taken - avg per 10 min",
            )
        ),
        "ave_death": _parse_numeric(_first_stat(average, "deaths - avg per 10 min")),
    }


def _build_selected_payload(summary_stats: Dict[str, Any]) -> Dict[str, Any]:
    ave_kill = float(summary_stats.get("ave_kill") or 0.0)
    ave_hero_damage = float(summary_stats.get("ave_hero_damage") or 0.0)
    ave_healing = float(summary_stats.get("ave_healing") or 0.0)
    ave_resist_damage = float(summary_stats.get("ave_resist_damage") or 0.0)
    ave_death = float(summary_stats.get("ave_death") or 0.0)
    return {
        "presetsSummaryData": {
            "aveKill": ave_kill,
            "aveHeroDamage": ave_hero_damage,
            "aveCure": ave_healing,
            "aveResistDamage": ave_resist_damage,
            "aveDeath": ave_death,
            "serverMapCountData": {
                "maxKill": max(1.0, ave_kill * 1.1),
                "maxDamage": max(1.0, ave_hero_damage * 1.1),
                "maxCure": max(1.0, ave_healing * 1.1),
                "maxResistDamage": max(1.0, ave_resist_damage * 1.1),
                "maxDeath": max(1.0, ave_death * 1.1),
            },
        }
    }


def _build_hero_rows(
    comparisons: Dict[str, list[Dict[str, Any]]],
    stats_by_hero: Dict[str, Dict[str, Dict[str, str]]],
) -> tuple[HeroUsageRow, ...]:
    comparison_win_sum = {
        _hero_key(item): _safe_int(_parse_numeric(item.get("raw_value")))
        for item in comparisons.get("games won", [])
    }
    comparison_win_rate = {
        _hero_key(item): _parse_numeric(item.get("raw_value"))
        for item in comparisons.get("win percentage", [])
    }
    hero_rows = []
    for item in comparisons.get("time played", []):
        game_time_seconds = _parse_duration_to_seconds(str(item.get("raw_value") or ""))
        if game_time_seconds <= 0:
            continue
        hero_name = str(item.get("hero_name") or "").strip()
        hero_stats = stats_by_hero.get(_normalize_key(hero_name)) or {}
        game_stats = hero_stats.get("game") or {}
        match_sum = _safe_int(_parse_numeric(_first_stat(game_stats, "games played")))
        win_sum = _safe_int(_parse_numeric(_first_stat(game_stats, "game won", "games won", "hero win")))
        if win_sum <= 0:
            win_sum = comparison_win_sum.get(_hero_key(item), 0)
        win_rate = _parse_numeric(_first_stat(game_stats, "win percentage"))
        if win_rate <= 0:
            win_rate = comparison_win_rate.get(_hero_key(item), 0.0)
        if match_sum <= 0 and win_rate > 0 and win_sum > 0:
            match_sum = int(round(win_sum / max(0.01, win_rate / 100.0)))

        hero_rows.append(
            HeroUsageRow(
                payload={
                    "heroName": hero_name,
                    "heroIconUrl": str(item.get("hero_icon_url") or "").strip(),
                    "heroColor": str(item.get("hero_color") or "").strip(),
                    "blizzardHeroId": str(item.get("hero_id") or "").strip(),
                    "timePlayed": str(item.get("raw_value") or "").strip(),
                    "matchSum": match_sum,
                    "winSum": win_sum,
                    "winRate": win_rate,
                },
                hero_guid=str(item.get("hero_id") or hero_name or "").strip(),
                hero_level=0,
                game_time=float(game_time_seconds),
                match_sum=match_sum,
                win_sum=win_sum,
                win_rate=win_rate,
                rank_overlay=None,
                billboards=(),
            )
        )
    hero_rows.sort(key=lambda row: row.game_time, reverse=True)
    return tuple(hero_rows[:10])


def _hero_key(item: Dict[str, Any]) -> str:
    hero_id = str(item.get("hero_id") or "").strip().lower()
    if hero_id:
        return hero_id
    return _normalize_key(item.get("hero_name"))


def _hero_row_to_dict(row: HeroUsageRow) -> Dict[str, Any]:
    return {
        "hero_guid": row.hero_guid,
        "hero_name": str(row.payload.get("heroName") or row.hero_guid),
        "hero_icon_url": str(row.payload.get("heroIconUrl") or ""),
        "hero_color": str(row.payload.get("heroColor") or ""),
        "time_played": str(row.payload.get("timePlayed") or ""),
        "game_time_seconds": int(row.game_time),
        "match_sum": row.match_sum,
        "win_sum": row.win_sum,
        "win_rate": row.win_rate,
    }


def _first_stat(stats: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = stats.get(_normalize_key(key))
        if value:
            return value
    return ""


def _clean_text(value: Any) -> str:
    text = _STRIP_TAG_RE.sub("", str(value or ""))
    return " ".join(unescape(text).replace("\xa0", " ").split()).strip()


def _normalize_key(value: Any) -> str:
    return _clean_text(value).lower()


def _extract_text(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    if match is None:
        return ""
    return _clean_text(match.group(1))


def _extract_int(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text or "")
    if match is None:
        return 0
    return _safe_int(match.group(1))


def _iter_match_blocks(text: str, pattern: re.Pattern[str]) -> Iterable[tuple[re.Match[str], str]]:
    matches = list(pattern.finditer(text or ""))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text or "")
        yield match, str(text or "")[start:end]


def _parse_numeric(value: Any) -> float:
    text = _clean_text(value)
    if not text:
        return 0.0
    if "%" in text:
        text = text.replace("%", "")
    if ":" in text:
        return float(_parse_duration_to_seconds(text))
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_duration_to_seconds(value: str) -> int:
    text = _clean_text(value)
    if not text or ":" not in text:
        return 0
    parts = [segment.strip() for segment in text.split(":")]
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
        return hours * 3600 + minutes * 60 + seconds
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    return 0


def _format_seconds_as_clock(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
