from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence
from urllib.parse import urlparse

import httpx

try:
    from overstats.config import config as app_config
except ModuleNotFoundError:
    from config import config as app_config

from ...constants.chara import iter_hero_alias_pairs


CN_MONTH_URL = "https://ow.blizzard.cn/news/patch-notes/live/{year:04d}/{month:02d}/"
EN_MONTH_URL = "https://overwatch.blizzard.com/en-us/news/patch-notes/live/{year:04d}/{month:02d}"
SOURCE_NAMES = {"cn": "国服", "en": "外服"}
PATCH_TRANSLATION_CACHE_VERSION = "2026-04-translate-v1"
SCAN_LIMIT = 12
HTTP_TIMEOUT = 20.0
TRANSLATION_TIMEOUT = 300.0
MAJOR_LENGTH_THRESHOLD = 2500
IMAGE_CACHE_MAX_CONCURRENCY = 6
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Referer": "https://overwatch.blizzard.com/",
}
PATCH_SECTION_TITLE_MAP = {
    "tank": "重装",
    "damage": "输出",
    "support": "支援",
    "hero updates": "英雄改动",
    "general updates": "综合更新",
    "map updates": "地图更新",
    "bug fixes": "错误修复",
    "stadium updates": "角斗领域更新",
}
PATCH_ROOT_RE = re.compile(
    r'<div[^>]+class=["\'][^"\']*\bPatchNotes-patch\b[^"\']*\bPatchNotes-live\b[^"\']*["\'][^>]*>',
    re.IGNORECASE,
)
DIV_TOKEN_RE = re.compile(r"<div\b|</div>", re.IGNORECASE)
ICON_SRC_RE_TEMPLATE = r'<img[^>]*class=["\'][^"\']*\b{class_name}\b[^"\']*["\'][^>]*src=["\'](.*?)["\']'


def _sanitize_api_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "replace-with-your" in text.lower():
        return ""
    return text


def _analysis_model_for_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().lower()
    if "generativelanguage.googleapis.com" in normalized or "googleapis.com" in normalized:
        return str(getattr(app_config, "ANALYSIS_GOOGLE_MODEL", "gemini-3.1-flash-lite-preview") or "gemini-3.1-flash-lite-preview")
    if "deepseek" in normalized:
        return str(getattr(app_config, "ANALYSIS_DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat")
    return str(getattr(app_config, "ANALYSIS_OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini")


def _chat_completion_url(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or base.endswith("/openai"):
        return f"{base}/chat/completions"
    return f"{base}/chat/completions"


def _extract_llm_message_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise KeyError("choices")

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(str(item.get("text") or ""))
                joined = "".join(text_parts).strip()
                if joined:
                    return joined

    for key in ("content", "text", "response", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

    error_obj = payload.get("error")
    if isinstance(error_obj, dict):
        err_msg = error_obj.get("message") or error_obj.get("msg") or str(error_obj)
        raise ValueError(f"LLM error payload: {err_msg}")

    raise KeyError(f"choices; payload keys={list(payload.keys())[:10]}")


def _strip_llm_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL | re.IGNORECASE).strip()


def _extract_json_array_text(raw_text: str) -> str:
    cleaned = _strip_llm_think_tags(raw_text)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        raise ValueError("JSON array not found in LLM response")
    return match.group(0)


def normalize_image_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    return html.unescape(text)


def _normalize_term_key(text: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return re.sub(r"[^0-9a-z一-鿿]+", "", normalized)


def _build_hero_name_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for alias, hero_name in iter_hero_alias_pairs():
        normalized = _normalize_term_key(alias)
        if normalized:
            mapping[normalized] = hero_name
    return mapping


HERO_NAME_MAP = _build_hero_name_map()


def _translate_section_title_if_known(title: Any) -> str:
    normalized = _normalize_term_key(title)
    return PATCH_SECTION_TITLE_MAP.get(normalized, str(title or ""))


def _translate_hero_name_if_known(hero_name: Any) -> str:
    return HERO_NAME_MAP.get(_normalize_term_key(hero_name), str(hero_name or ""))


def _translate_ability_name_if_known(ability_name: Any) -> str:
    return str(ability_name or "")


def normalize_patch_kind(value: Any) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    if not normalized or normalized in {"最新", "自动", "auto", "latest"}:
        return "latest"
    if normalized in {"小", "小更", "小更新", "小补丁", "small"}:
        return "small"
    if normalized in {"大", "大更", "大更新", "大补丁", "big", "major"}:
        return "big"
    raise ValueError("patch_kind must be latest, small, or big.")


def serialize_patch_candidate(candidate: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(candidate, Mapping):
        return None
    payload = dict(candidate)
    date_value = payload.get("date")
    if isinstance(date_value, dt.date):
        payload["date"] = date_value.isoformat()
    payload.pop("html", None)
    return payload


def deserialize_patch_candidate(candidate: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(candidate, Mapping):
        return None
    payload = dict(candidate)
    date_text = payload.get("date")
    if isinstance(date_text, str) and date_text:
        try:
            payload["date"] = dt.date.fromisoformat(date_text)
        except ValueError:
            payload["date"] = None
    return payload


def build_patch_cache_key(candidate: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(PATCH_TRANSLATION_CACHE_VERSION.encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(candidate.get("source") or "").encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(candidate.get("date_text") or "").encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(candidate.get("title") or "").encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(candidate.get("text") or "").encode("utf-8"))
    return digest.hexdigest()


def choose_source(cn_slots: Mapping[str, Any], en_slots: Mapping[str, Any], *, slot_key: str = "latest") -> Optional[str]:
    cn_latest = cn_slots.get(slot_key)
    en_latest = en_slots.get(slot_key)
    if en_latest and cn_latest:
        if en_latest.get("date") and cn_latest.get("date") and en_latest["date"] > cn_latest["date"]:
            return "en"
        return "cn"
    if en_latest:
        return "en"
    if cn_latest:
        return "cn"
    return None


def format_patch_date(candidate: Optional[Mapping[str, Any]]) -> str:
    if not candidate or not candidate.get("date"):
        return "未找到"
    return candidate["date"].strftime("%Y-%m-%d")


def build_sources_summary(cn_slots: Mapping[str, Any], en_slots: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    return {
        "cn": {
            "source_name": SOURCE_NAMES["cn"],
            "latest": format_patch_date(cn_slots.get("latest")),
            "small": format_patch_date(cn_slots.get("small")),
            "big": format_patch_date(cn_slots.get("big")),
        },
        "en": {
            "source_name": SOURCE_NAMES["en"],
            "latest": format_patch_date(en_slots.get("latest")),
            "small": format_patch_date(en_slots.get("small")),
            "big": format_patch_date(en_slots.get("big")),
        },
    }


def build_summary_text(cn_slots: Mapping[str, Any], en_slots: Mapping[str, Any], selected_patch: Mapping[str, Any]) -> str:
    selected_date = selected_patch.get("date")
    date_text = selected_date.strftime("%Y-%m-%d") if isinstance(selected_date, dt.date) else "未知日期"
    chosen_slots = cn_slots if selected_patch.get("source") == "cn" else en_slots
    return "\n".join(
        [
            f"国服最新：{format_patch_date(cn_slots.get('latest'))}",
            f"外服最新：{format_patch_date(en_slots.get('latest'))}",
            f"当前采用：{selected_patch.get('source_name', '')} {selected_patch.get('bucket_name', '')} {date_text}",
            f"该源最近小更新：{format_patch_date(chosen_slots.get('small'))}；最近大更新：{format_patch_date(chosen_slots.get('big'))}",
        ]
    )


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def stable_url_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def is_valid_image_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return True

    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _iter_recent_months(now_date: Optional[dt.date] = None, limit: int = SCAN_LIMIT):
    current = now_date or dt.date.today()
    year = current.year
    month = current.month
    for _ in range(limit):
        yield year, month
        month -= 1
        if month <= 0:
            month = 12
            year -= 1


def _extract_live_patch_blocks(page_html: str) -> list[str]:
    blocks: list[str] = []
    search_start = 0
    while True:
        match = PATCH_ROOT_RE.search(page_html, search_start)
        if not match:
            break
        depth = 0
        block_end = None
        for div_match in DIV_TOKEN_RE.finditer(page_html, match.start()):
            token = div_match.group(0).lower()
            if token == "<div":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    block_end = div_match.end()
                    break
        if block_end is None:
            break
        blocks.append(page_html[match.start():block_end])
        search_start = block_end
    return blocks


def _extract_div_blocks_by_class(html_text: str, class_name: str) -> list[str]:
    pattern = re.compile(
        rf'<div[^>]+class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>',
        re.IGNORECASE,
    )
    blocks: list[str] = []
    search_start = 0
    while True:
        match = pattern.search(html_text, search_start)
        if not match:
            break
        depth = 0
        block_end = None
        for div_match in DIV_TOKEN_RE.finditer(html_text, match.start()):
            token = div_match.group(0).lower()
            if token == "<div":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    block_end = div_match.end()
                    break
        if block_end is None:
            break
        blocks.append(html_text[match.start():block_end])
        search_start = block_end
    return blocks


def _clean_patch_text(raw_text: Any) -> str:
    if not raw_text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", str(raw_text))
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_first_patch_field(block_html: str, tag_name: str, class_name: str) -> str:
    pattern = re.compile(
        rf'<{tag_name}[^>]*class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>(.*?)</{tag_name}>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(block_html)
    return _clean_patch_text(match.group(1)) if match else ""


def _extract_first_text_by_class(block_html: str, class_name: str) -> str:
    pattern = re.compile(
        rf'<(?P<tag>[a-z0-9]+)[^>]*class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>(?P<content>.*?)</(?P=tag)>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(block_html)
    return _clean_patch_text(match.group("content")) if match else ""


def _extract_first_img_src(block_html: str, class_name: str) -> str:
    pattern = re.compile(
        ICON_SRC_RE_TEMPLATE.format(class_name=re.escape(class_name)),
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(block_html)
    return normalize_image_url(match.group(1)) if match else ""


def _extract_list_items(block_html: str) -> list[str]:
    items = []
    for item in re.findall(r"<li[^>]*>(.*?)</li>", block_html or "", re.IGNORECASE | re.DOTALL):
        cleaned_item = _clean_patch_text(item)
        if cleaned_item:
            items.append(cleaned_item)
    return items


def _extract_paragraphs(block_html: str) -> list[str]:
    paragraphs = []
    for item in re.findall(r"<p[^>]*>(.*?)</p>", block_html or "", re.IGNORECASE | re.DOTALL):
        cleaned_item = _clean_patch_text(item)
        if cleaned_item:
            paragraphs.append(cleaned_item)
    return paragraphs


def _extract_first_block_by_class(block_html: str, class_name: str) -> str:
    blocks = _extract_div_blocks_by_class(block_html, class_name)
    return blocks[0] if blocks else ""


def _extract_map_image_urls(block_html: str) -> Dict[str, str]:
    image_urls: Dict[str, str] = {}
    for slot, src in re.findall(
        r'<blz-image[^>]*slot=["\'](before|after)["\'][^>]*src=["\'](.*?)["\']',
        block_html or "",
        re.IGNORECASE | re.DOTALL,
    ):
        image_urls[slot.lower()] = normalize_image_url(src)
    return image_urls


def _dedupe_text_items(items: Sequence[str]) -> list[str]:
    results: list[str] = []
    seen = set()
    for item in items or []:
        normalized = re.sub(r"\s+", " ", str(item or "")).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def _extract_general_updates(block_html: str, section_title: str = "") -> list[Dict[str, Any]]:
    updates = []
    for index, general_block in enumerate(_extract_div_blocks_by_class(block_html, "PatchNotesGeneralUpdate"), start=1):
        description_block = _extract_first_block_by_class(general_block, "PatchNotesGeneralUpdate-description")
        dev_block = _extract_first_block_by_class(general_block, "PatchNotesGeneralUpdate-dev")
        title = _extract_first_text_by_class(general_block, "PatchNotesGeneralUpdate-title")
        paragraphs = _extract_paragraphs(description_block)
        bullets = _extract_list_items(description_block)
        dev_note = " ".join(_extract_paragraphs(dev_block)).strip()
        if not title:
            title = section_title or f"Other Update {index}"
        if title or paragraphs or bullets or dev_note:
            updates.append(
                {
                    "title": title,
                    "paragraphs": _dedupe_text_items(paragraphs),
                    "bullets": _dedupe_text_items(bullets),
                    "dev_note": dev_note,
                }
            )
    return updates


def _extract_map_updates(block_html: str, section_title: str = "") -> list[Dict[str, Any]]:
    updates = []
    for index, map_block in enumerate(_extract_div_blocks_by_class(block_html, "PatchNotesMapUpdate"), start=1):
        image_urls = _extract_map_image_urls(map_block)
        name = _extract_first_text_by_class(map_block, "PatchNotesMapUpdate-name")
        comparison_label = _extract_first_text_by_class(map_block, "PatchNotesMapUpdate-beforeAfterText")
        paragraphs = [item for item in _extract_paragraphs(map_block) if item not in {name, comparison_label}]
        bullets = _extract_list_items(map_block)
        if not name:
            name = f"{section_title} #{index}" if section_title else f"Map Update #{index}"
        if name or paragraphs or bullets or comparison_label or image_urls:
            updates.append(
                {
                    "name": name,
                    "comparison_label": comparison_label,
                    "paragraphs": _dedupe_text_items(paragraphs),
                    "bullets": _dedupe_text_items(bullets),
                    "before_image_url": image_urls.get("before", ""),
                    "after_image_url": image_urls.get("after", ""),
                }
            )
    return updates


def _extract_hero_updates(block_html: str, group_title: str = "") -> list[Dict[str, Any]]:
    hero_updates = []
    for hero_block in _extract_div_blocks_by_class(block_html, "PatchNotesHeroUpdate"):
        hero_name = _extract_first_text_by_class(hero_block, "PatchNotesHeroUpdate-name")
        icon_url = _extract_first_img_src(hero_block, "PatchNotesHeroUpdate-icon")
        dev_note = " ".join(
            _extract_paragraphs(_extract_first_block_by_class(hero_block, "PatchNotesHeroUpdate-dev"))
        ).strip()

        general_changes: list[str] = []
        for general_block in _extract_div_blocks_by_class(hero_block, "PatchNotesHeroUpdate-generalUpdates"):
            general_changes.extend(_extract_list_items(general_block))

        abilities = []
        for ability_block in _extract_div_blocks_by_class(hero_block, "PatchNotesAbilityUpdate"):
            ability_name = _extract_first_text_by_class(ability_block, "PatchNotesAbilityUpdate-name")
            ability_icon_url = _extract_first_img_src(ability_block, "PatchNotesAbilityUpdate-icon")
            ability_changes = _extract_list_items(ability_block)
            if not ability_changes:
                ability_changes = [
                    item
                    for item in _extract_paragraphs(ability_block)
                    if item not in {ability_name, dev_note}
                ]
            if ability_name or ability_changes or ability_icon_url:
                abilities.append(
                    {
                        "name": ability_name or "通用调整",
                        "icon_url": ability_icon_url,
                        "changes": _dedupe_text_items(ability_changes),
                    }
                )

        if hero_name or general_changes or abilities or dev_note:
            hero_updates.append(
                {
                    "name": hero_name or "英雄改动",
                    "icon_url": icon_url,
                    "dev_note": dev_note,
                    "general_changes": _dedupe_text_items(general_changes),
                    "abilities": abilities,
                    "group_title": group_title,
                }
            )
    return hero_updates


def _extract_patch_sections(block_html: str) -> list[Dict[str, Any]]:
    sections = []
    for section_block in _extract_div_blocks_by_class(block_html, "PatchNotes-section"):
        title = _extract_first_patch_field(section_block, "h4", "PatchNotes-sectionTitle")
        intro_block = _extract_first_block_by_class(section_block, "PatchNotes-sectionDescription")
        intro = _dedupe_text_items(_extract_paragraphs(intro_block))
        hero_updates = _extract_hero_updates(section_block, group_title=title)
        map_updates = _extract_map_updates(section_block, section_title=title)
        general_updates = _extract_general_updates(section_block, section_title=title)

        if hero_updates:
            section_type = "hero"
        elif map_updates:
            section_type = "map"
        elif intro or general_updates:
            section_type = "general"
        else:
            continue

        sections.append(
            {
                "type": section_type,
                "title": title or "Patch Notes",
                "intro": intro,
                "hero_updates": hero_updates,
                "map_updates": map_updates,
                "general_updates": general_updates,
            }
        )
    return sections


def _flatten_hero_updates(sections: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    hero_updates = []
    for section in sections or []:
        hero_updates.extend(list(section.get("hero_updates") or []))
    return hero_updates


def _parse_patch_date(date_text: Any) -> Optional[dt.date]:
    text = str(date_text or "").strip()
    if not text:
        return None

    cn_match = re.search(r"(20\d{2})\D+(\d{1,2})\D+(\d{1,2})", text)
    if cn_match:
        year, month, day = map(int, cn_match.groups())
        try:
            return dt.date(year, month, day)
        except ValueError:
            return None

    en_match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})", text)
    if not en_match:
        return None

    month_text, day_text, year_text = en_match.groups()
    month_text = month_text.lower().rstrip(".")
    month_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month = month_map.get(month_text)
    if month is None:
        return None

    try:
        return dt.date(int(year_text), month, int(day_text))
    except ValueError:
        return None


def _build_candidate_text(candidate: Mapping[str, Any]) -> str:
    lines = [candidate.get("title", ""), candidate.get("section_title", "")]
    for section in candidate.get("sections") or []:
        lines.append(section.get("title", ""))
        lines.extend(section.get("intro") or [])

        for update in section.get("general_updates") or []:
            lines.append(update.get("title", ""))
            lines.append(update.get("dev_note", ""))
            lines.extend(update.get("paragraphs") or [])
            lines.extend(update.get("bullets") or [])

        for map_update in section.get("map_updates") or []:
            lines.append(map_update.get("name", ""))
            lines.append(map_update.get("comparison_label", ""))
            lines.extend(map_update.get("paragraphs") or [])
            lines.extend(map_update.get("bullets") or [])

        for hero_update in section.get("hero_updates") or []:
            lines.append(hero_update.get("name", ""))
            lines.append(hero_update.get("dev_note", ""))
            lines.extend(hero_update.get("general_changes") or [])
            for ability in hero_update.get("abilities") or []:
                lines.append(ability.get("name", ""))
                lines.extend(ability.get("changes") or [])

    return "\n".join(line for line in lines if line)


def _build_patch_candidate(source_key: str, month_url: str, block_html: str, block_index: int) -> Dict[str, Any]:
    title = _extract_first_patch_field(block_html, "h3", "PatchNotes-patchTitle")
    section_title = _extract_first_patch_field(block_html, "h4", "PatchNotes-sectionTitle")
    date_text = _extract_first_patch_field(block_html, "div", "PatchNotes-date") or title
    sections = _extract_patch_sections(block_html)
    plain_text = _build_candidate_text(
        {
            "title": title,
            "section_title": section_title,
            "sections": sections,
        }
    )
    if not plain_text:
        plain_text = _clean_patch_text(block_html)
    text_length = len(plain_text)
    bucket = "big" if text_length >= MAJOR_LENGTH_THRESHOLD else "small"
    return {
        "source": source_key,
        "source_name": SOURCE_NAMES[source_key],
        "url": month_url,
        "index": block_index,
        "title": title,
        "section_title": section_title,
        "date_text": date_text,
        "date": _parse_patch_date(date_text),
        "length": text_length,
        "bucket": bucket,
        "bucket_name": "大更新" if bucket == "big" else "小更新",
        "text": plain_text,
        "html": block_html,
        "sections": sections,
        "hero_updates": _flatten_hero_updates(sections),
    }


def _clone_candidate_for_translation(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    translated = copy.deepcopy(dict(candidate))
    translated["section_title"] = _translate_section_title_if_known(translated.get("section_title", ""))
    for section in translated.get("sections") or []:
        section["title"] = _translate_section_title_if_known(section.get("title", ""))
        for hero_update in section.get("hero_updates") or []:
            hero_update["name"] = _translate_hero_name_if_known(hero_update.get("name", ""))
            hero_update["group_title"] = _translate_section_title_if_known(hero_update.get("group_title", ""))
            for ability in hero_update.get("abilities") or []:
                ability["name"] = _translate_ability_name_if_known(ability.get("name", ""))
    translated["hero_updates"] = _flatten_hero_updates(translated.get("sections") or [])
    return translated


def _iter_translation_targets(candidate: Mapping[str, Any]) -> list[Dict[str, Any]]:
    targets = []

    def add(path: tuple[Any, ...], text: Any) -> None:
        normalized = str(text or "").strip()
        if normalized and re.search(r"[A-Za-z]", normalized):
            targets.append({"path": tuple(path), "text": normalized})

    add(("title",), candidate.get("title"))
    add(("section_title",), candidate.get("section_title"))

    for section_index, section in enumerate(candidate.get("sections") or []):
        add(("sections", section_index, "title"), section.get("title"))

        for intro_index, intro_text in enumerate(section.get("intro") or []):
            add(("sections", section_index, "intro", intro_index), intro_text)

        for update_index, update in enumerate(section.get("general_updates") or []):
            add(("sections", section_index, "general_updates", update_index, "title"), update.get("title"))
            add(("sections", section_index, "general_updates", update_index, "dev_note"), update.get("dev_note"))
            for paragraph_index, paragraph in enumerate(update.get("paragraphs") or []):
                add(("sections", section_index, "general_updates", update_index, "paragraphs", paragraph_index), paragraph)
            for bullet_index, bullet in enumerate(update.get("bullets") or []):
                add(("sections", section_index, "general_updates", update_index, "bullets", bullet_index), bullet)

        for map_index, map_update in enumerate(section.get("map_updates") or []):
            add(("sections", section_index, "map_updates", map_index, "name"), map_update.get("name"))
            add(("sections", section_index, "map_updates", map_index, "comparison_label"), map_update.get("comparison_label"))
            for paragraph_index, paragraph in enumerate(map_update.get("paragraphs") or []):
                add(("sections", section_index, "map_updates", map_index, "paragraphs", paragraph_index), paragraph)
            for bullet_index, bullet in enumerate(map_update.get("bullets") or []):
                add(("sections", section_index, "map_updates", map_index, "bullets", bullet_index), bullet)

        for hero_index, hero_update in enumerate(section.get("hero_updates") or []):
            add(("sections", section_index, "hero_updates", hero_index, "name"), hero_update.get("name"))
            add(("sections", section_index, "hero_updates", hero_index, "group_title"), hero_update.get("group_title"))
            add(("sections", section_index, "hero_updates", hero_index, "dev_note"), hero_update.get("dev_note"))
            for change_index, change_text in enumerate(hero_update.get("general_changes") or []):
                add(("sections", section_index, "hero_updates", hero_index, "general_changes", change_index), change_text)
            for ability_index, ability in enumerate(hero_update.get("abilities") or []):
                add(("sections", section_index, "hero_updates", hero_index, "abilities", ability_index, "name"), ability.get("name"))
                for change_index, change_text in enumerate(ability.get("changes") or []):
                    add(
                        ("sections", section_index, "hero_updates", hero_index, "abilities", ability_index, "changes", change_index),
                        change_text,
                    )
    return targets


def _set_nested_value(payload: Dict[str, Any], path: Sequence[Any], value: Any) -> None:
    current: Any = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


def _chunk_translation_targets(targets: Sequence[Mapping[str, Any]], max_items: int = 48, max_chars: int = 12000) -> list[list[Mapping[str, Any]]]:
    batches = []
    current_batch = []
    current_chars = 0
    for target in targets:
        target_chars = len(str(target.get("text") or ""))
        exceeds = current_batch and (len(current_batch) >= max_items or current_chars + target_chars > max_chars)
        if exceeds:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(target)
        current_chars += target_chars
    if current_batch:
        batches.append(current_batch)
    return batches


def _build_patch_translation_glossary(candidate: Mapping[str, Any]) -> list[tuple[str, str]]:
    glossary = []
    seen = set()

    def add(source_text: Any, translated_text: Any) -> None:
        source_text = str(source_text or "").strip()
        translated_text = str(translated_text or "").strip()
        if not source_text or not translated_text:
            return
        key = (source_text, translated_text)
        if key in seen:
            return
        seen.add(key)
        glossary.append(key)

    translated_clone = _clone_candidate_for_translation(candidate)
    for original_section, translated_section in zip(candidate.get("sections") or [], translated_clone.get("sections") or []):
        add(original_section.get("title"), translated_section.get("title"))
        for original_hero, translated_hero in zip(original_section.get("hero_updates") or [], translated_section.get("hero_updates") or []):
            add(original_hero.get("name"), translated_hero.get("name"))
            for original_ability, translated_ability in zip(original_hero.get("abilities") or [], translated_hero.get("abilities") or []):
                add(original_ability.get("name"), translated_ability.get("name"))
    return glossary


def _build_patch_translation_prompt(texts: Sequence[str], glossary: Sequence[tuple[str, str]]) -> str:
    prompt_lines = [
        "你是守望先锋补丁说明的本地化编辑。请把下面的英文逐条翻译成简体中文。",
        "要求：",
        "1. 严格使用守望先锋常用术语和国服译名。",
        "2. 英雄名、技能名、模式名优先使用术语表中的固定译法，不要自造译名。",
        "3. 只输出 JSON 字符串数组，顺序必须与输入完全一致，不要输出任何额外解释或 Markdown。",
        "4. 保留数字、括号、百分比、版本号和项目符号语义，不要遗漏任何一条。",
        "5. 已经是中文的内容保持不变；没有把握的专有名词保留英文原词。",
    ]
    if glossary:
        prompt_lines.append("术语表：")
        for source_text, translated_text in glossary:
            prompt_lines.append(f"- {source_text} => {translated_text}")
    prompt_lines.append("待翻译文本：")
    for index, text in enumerate(texts, start=1):
        prompt_lines.append(f"{index}. {json.dumps(text, ensure_ascii=False)}")
    return "\n".join(prompt_lines)


def _build_async_client(
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = HTTP_TIMEOUT,
    proxy_url: str = "",
) -> httpx.AsyncClient:
    kwargs: Dict[str, Any] = {
        "headers": dict(headers or REQUEST_HEADERS),
        "timeout": timeout,
        "follow_redirects": True,
    }
    if proxy_url:
        try:
            return httpx.AsyncClient(proxy=proxy_url, **kwargs)
        except TypeError:
            return httpx.AsyncClient(proxies=proxy_url, **kwargs)
    return httpx.AsyncClient(**kwargs)


class PatchNotesRequests:
    def __init__(
        self,
        *,
        timeout_seconds: float = HTTP_TIMEOUT,
        headers: Optional[Mapping[str, str]] = None,
        today_factory: Optional[Callable[[], dt.date]] = None,
        use_international_proxy: Optional[bool] = None,
        international_proxy: Optional[str] = None,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.headers = dict(headers or REQUEST_HEADERS)
        self.today_factory = today_factory or dt.date.today
        self.use_international_proxy = bool(
            getattr(app_config, "PATCH_NOTES_USE_INTERNATIONAL_PROXY", False)
            if use_international_proxy is None
            else use_international_proxy
        )
        self.international_proxy = str(
            getattr(app_config, "PATCH_NOTES_INTERNATIONAL_PROXY", "") if international_proxy is None else international_proxy
        ).strip()

    def proxy_for_source(self, source_key: str) -> str:
        if source_key == "en" and self.use_international_proxy and self.international_proxy:
            return self.international_proxy
        return ""

    async def fetch_patch_page_html(self, url: str, source_key: str) -> str:
        async with _build_async_client(headers=self.headers, timeout=self.timeout_seconds, proxy_url=self.proxy_for_source(source_key)) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    async def scan_patch_source(self, source_key: str, *, now_date: Optional[dt.date] = None) -> Dict[str, Optional[Dict[str, Any]]]:
        slots: Dict[str, Optional[Dict[str, Any]]] = {"latest": None, "small": None, "big": None}
        current_date = now_date or self.today_factory()
        for year, month in _iter_recent_months(now_date=current_date):
            month_url = CN_MONTH_URL.format(year=year, month=month) if source_key == "cn" else EN_MONTH_URL.format(year=year, month=month)
            try:
                page_html = await self.fetch_patch_page_html(month_url, source_key)
            except Exception as exc:
                print(f"[overstats] patch_notes fetch failed: source={source_key} url={month_url} error={type(exc).__name__}: {exc}")
                continue
            blocks = _extract_live_patch_blocks(page_html)
            if not blocks:
                continue
            for block_index, block_html in enumerate(blocks):
                candidate = _build_patch_candidate(source_key, month_url, block_html, block_index)
                if candidate["date"] is None:
                    continue
                if slots["latest"] is None:
                    slots["latest"] = candidate
                if slots[candidate["bucket"]] is None:
                    slots[candidate["bucket"]] = candidate
                if slots["latest"] and slots["small"] and slots["big"]:
                    return slots
        return slots

    async def scan_sources(self, *, now_date: Optional[dt.date] = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        cn_slots, en_slots = await asyncio.gather(
            self.scan_patch_source("cn", now_date=now_date),
            self.scan_patch_source("en", now_date=now_date),
        )
        return cn_slots, en_slots

    async def translate_patch_candidate(self, candidate: Mapping[str, Any]) -> tuple[Dict[str, Any], bool]:
        base_url = str(getattr(app_config, "ANALYSIS_BASE_URL", "") or "").strip()
        api_key = _sanitize_api_key(getattr(app_config, "ANALYSIS_API_KEY", ""))
        translated_candidate = _clone_candidate_for_translation(candidate)
        targets = _iter_translation_targets(translated_candidate)
        if not targets:
            translated_candidate["text"] = _build_candidate_text(translated_candidate)
            translated_candidate["hero_updates"] = _flatten_hero_updates(translated_candidate.get("sections") or [])
            return translated_candidate, True
        if not base_url or not api_key:
            translated_candidate["text"] = _build_candidate_text(translated_candidate)
            translated_candidate["hero_updates"] = _flatten_hero_updates(translated_candidate.get("sections") or [])
            return translated_candidate, False

        glossary = _build_patch_translation_glossary(candidate)
        for batch in _chunk_translation_targets(targets):
            source_texts = [str(item.get("text") or "") for item in batch]
            translated_texts = await self._translate_text_batch(source_texts, glossary, base_url=base_url, api_key=api_key)
            for item, translated_text in zip(batch, translated_texts):
                _set_nested_value(translated_candidate, item["path"], translated_text)

        translated_candidate["text"] = _build_candidate_text(translated_candidate)
        translated_candidate["hero_updates"] = _flatten_hero_updates(translated_candidate.get("sections") or [])
        return translated_candidate, True

    async def _translate_text_batch(
        self,
        texts: Sequence[str],
        glossary: Sequence[tuple[str, str]],
        *,
        base_url: str,
        api_key: str,
    ) -> list[str]:
        payload = {
            "model": _analysis_model_for_base_url(base_url),
            "temperature": 0.2,
            "messages": [{"role": "user", "content": _build_patch_translation_prompt(texts, glossary)}],
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=TRANSLATION_TIMEOUT) as client:
            response = await client.post(_chat_completion_url(base_url), json=payload, headers=headers)
            response.raise_for_status()
            raw_content = _extract_llm_message_content(response.json())
        translations = json.loads(_extract_json_array_text(raw_content))
        if not isinstance(translations, list):
            raise ValueError("Translation response is not a JSON array")
        if len(translations) != len(texts):
            raise ValueError(f"Translation count mismatch: expected {len(texts)}, got {len(translations)}")
        return [str(item or "").strip() for item in translations]

    async def cache_images(
        self,
        image_urls: Sequence[str],
        asset_dir: Path,
        *,
        use_proxy: bool = False,
        max_concurrency: int = IMAGE_CACHE_MAX_CONCURRENCY,
    ) -> Dict[str, Path]:
        normalized_urls = []
        seen = set()
        for image_url in image_urls:
            normalized = normalize_image_url(image_url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_urls.append(normalized)

        asset_dir.mkdir(parents=True, exist_ok=True)
        if not normalized_urls:
            return {}

        results: Dict[str, Path] = {}
        semaphore = asyncio.Semaphore(max(1, int(max_concurrency or 1)))
        proxy_url = self.proxy_for_source("en") if use_proxy else ""
        async with _build_async_client(headers=self.headers, timeout=self.timeout_seconds, proxy_url=proxy_url) as client:

            async def run(image_url: str) -> None:
                async with semaphore:
                    path = await self._cache_single_image(client, image_url, asset_dir)
                    if path is not None:
                        results[image_url] = path

            failures = await asyncio.gather(*(run(image_url) for image_url in normalized_urls), return_exceptions=True)
            for image_url, failure in zip(normalized_urls, failures):
                if isinstance(failure, Exception):
                    print(f"[overstats] patch_notes image cache failed: url={image_url} error={type(failure).__name__}: {failure}")
        return results

    async def _cache_single_image(self, client: httpx.AsyncClient, image_url: str, asset_dir: Path) -> Optional[Path]:
        normalized = normalize_image_url(image_url)
        if not normalized:
            return None

        parsed = urlparse(normalized)
        suffix = Path(parsed.path or "").suffix.lower() or ".png"
        filename = f"{stable_url_hash(normalized)}{suffix}"
        target_path = asset_dir / filename
        if target_path.exists() and is_valid_image_file(target_path):
            return target_path

        response = await client.get(normalized)
        response.raise_for_status()
        content = response.content
        if not content:
            return None

        fd, temp_path = tempfile.mkstemp(prefix="patch-notes-image.", suffix=suffix, dir=str(asset_dir))
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
            Path(temp_path).replace(target_path)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        return target_path
