from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Mapping

from ..font_resolver import load_font
from ...constants.chara import iter_hero_alias_pairs
from .parser import iter_entries as _entries

RENDER_VERSION = "reader-2026-10-digest-v4"
WIDTH, MAX_HEIGHT, MARGIN = 1200, 1900, 48
TOP, FOOTER, GAP = 190, 100, 18
BG, CARD = (16, 22, 32), (25, 34, 48)
WHITE, MUTED, ACCENT = (237, 242, 250), (157, 176, 198), (121, 196, 244)
LABELS = {
    "hero updates": "英雄更新", "general updates": "综合更新",
    "hotfix update": "热修复", "bug fixes": "问题修复",
    "map updates": "地图更新", "stadium updates": "角斗领域更新",
    "tank": "重装", "damage": "输出", "support": "支援",
    "competitive play updates": "竞技比赛更新", "6v6 updates": "6v6 更新",
    "patch notes": "补丁说明",
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


@lru_cache(maxsize=12)
def _font(size, bold=False):
    return load_font(size, name="simhei.ttf", prefer_cjk=True, bold=bold)


def label(value):
    return " / ".join(LABELS.get(part.strip().lower(), part.strip()) for part in str(value or "补丁说明").split(" / "))


def _wrap(text, size, width):
    font = _font(size)
    output = []
    for paragraph in str(text or "").splitlines():
        current = ""
        # Character fallback also handles an unbroken URL or very long English word.
        for token in re.findall(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*|[^A-Za-z0-9]", paragraph):
            if font.getlength(current + token) <= width:
                current += token
            else:
                if current.strip():
                    output.append(current.rstrip())
                current = ""
                for char in token.lstrip():
                    if current and font.getlength(current + char) > width:
                        output.append(current)
                        current = ""
                    current += char
        if current.strip():
            output.append(current.rstrip())
    return output


def _key(value):
    return re.sub(r"[^a-z0-9一-鿿]", "", str(value).lower())


def _hero_key(value):
    aliases = {_key(alias): _key(name) for alias, name in iter_hero_alias_pairs()}
    return aliases.get(_key(value), _key(value))


def _numeric_change(text):
    match = re.fullmatch(
        r"(.+?)从\s*(\d+(?:\.\d+)?\s*[%％秒米点发]?)\s*"
        r"(?:增加|提高|提升|降低|减少|缩短|延长|调整|变更|改)(?:至|为|到)?\s*"
        r"(\d+(?:\.\d+)?\s*[%％秒米点发]?)\s*[。.]?", str(text),
    )
    if match and _font(30).getlength(match[1]) < 600 and all(_font(30).getlength(value) < 128 for value in match.groups()[1:]):
        return [part.strip() for part in match.groups()]
    return None



def _card(section, kind, item):
    rows = []
    title = item.get("name") or item.get("title") or label(section["title"])
    def add(text, style="body"):
        if str(text or "").strip():
            rows.append({"text": str(text), "style": style})
    if kind == "hero":
        order = item.get("order") or ([{"kind": "general", "index": i} for i in range(len(item.get("general_changes") or []))]
            + [{"kind": "ability", "index": i} for i in range(len(item.get("abilities") or []))])
        for entry in order:
            if entry["kind"] == "ability":
                ability = item["abilities"][entry["index"]]
                add(ability.get("name"), "ability")
                for change in ability.get("changes") or []:
                    add(change)
            elif entry["kind"] == "dev":
                add("开发者说明：" + item.get("dev_note", ""), "note")
            else:
                add(item["general_changes"][entry["index"]], "note" if entry["kind"] == "note" else "body")
        if not any(entry["kind"] == "dev" for entry in order):
            add(item.get("dev_note"), "note")
    else:
        for paragraph in item.get("paragraphs") or []:
            add(paragraph)
        for bullet in item.get("bullets") or []:
            add(bullet)
        add(item.get("dev_note"), "note")
        if kind == "map":
            add(item.get("comparison_label"), "note")
            urls = [item.get("before_image_url"), item.get("after_image_url")]
            if any(urls):
                rows.append({"style": "images", "urls": urls})
        else:
            images = item.get("images") or []
            for start in range(0, len(images), 2):
                rows.append({"style": "images", "urls": images[start:start + 2],
                             "labels": [f"原文图片 {start + i + 1}" for i in range(len(images[start:start + 2]))]})
    return {"title": title, "section": label(section["title"]), "icon": item.get("icon_url", ""), "rows": rows}


def _layout(cards):
    pages, page, used = [], [], TOP
    for card in cards:
        title_lines = _wrap(card["title"], 36, WIDTH - 2 * MARGIN - 132)
        rows = []
        if len(title_lines) > 4:
            original_title = card["title"]
            card = dict(card, title="补丁条目")
            title_lines = ["补丁条目"]
            card["rows"] = [{"text": original_title, "style": "body"}] + card["rows"]
        title_h = max(96 if card.get("icon") else 70, 32 + len(title_lines) * 44)
        for row in card["rows"]:
            if row["style"] == "images":
                rows.append(dict(row, height=288))
                continue
            style = row["style"]
            size = 31 if style == "ability" else 30
            change = _numeric_change(row["text"]) if style == "body" else None
            if change:
                rows.append({"text": row["text"], "style": "body", "height": 48, "change": change})
                continue
            wrapped = _wrap(row["text"], size, WIDTH - MARGIN * 2 - 64)
            for i, line in enumerate(wrapped):
                rows.append({"text": line, "style": style, "height": 46 if style == "ability" else 42, "first": i == 0})
        if not rows:
            rows = [{"text": "此条目仅包含标题。", "style": "note", "height": 42}]
        offset, continuation, last_ability = 0, False, None
        while offset < len(rows):
            head = title_h + 22
            extra = []
            if continuation and last_ability and rows[offset]["style"] != "ability":
                extra = [dict(last_ability, text=last_ability["text"] + "（续）")]
            minimum = rows[offset]["height"]
            # Keep an ability heading with at least its first body line.
            if rows[offset]["style"] == "ability" and offset + 1 < len(rows):
                minimum += rows[offset + 1]["height"]
            if page and used + head + sum(r["height"] for r in extra) + minimum + 24 > MAX_HEIGHT - FOOTER:
                pages.append(page); page, used = [], TOP
            available = MAX_HEIGHT - FOOTER - used - head - 24
            chunk = list(extra)
            consumed = sum(r["height"] for r in chunk)
            start = offset
            while offset < len(rows):
                row = rows[offset]
                needed = row["height"]
                if row["style"] == "ability" and offset + 1 < len(rows):
                    needed += rows[offset + 1]["height"]
                if consumed + needed > available:
                    break
                chunk.append(row); consumed += row["height"]; offset += 1
                if row["style"] == "ability":
                    last_ability = row
            if offset == start:
                # On a fresh page the fixed header + one text row always fits.
                raise ValueError("补丁内容块超过页面可用高度。")
            height = head + consumed + 24
            page.append(dict(card, title_lines=title_lines, continuation=continuation,
                             lines=chunk, height=height, title_height=title_h))
            used += height + GAP
            continuation = True
            if offset < len(rows):
                pages.append(page); page, used = [], TOP
    if page:
        pages.append(page)
    return pages or [[]]


def build_reader(candidate, *, view="auto", section="", hero=""):
    if view not in {"auto", "overview", "detail"}:
        raise ValueError("view 必须为 auto、overview 或 detail。")
    directory, cards = [], []
    matched = not section and not hero
    for index, part in enumerate(candidate.get("sections") or []):
        sid = f"s{index + 1}"
        entries = list(_entries(part))
        names = [item.get("name", "") for kind, item in entries if kind == "hero"]
        directory.append({"id": sid, "title": label(part["title"]), "hero_names": names, "entry_count": len(entries)})
        section_match = not section or section == sid or any(_key(section) == _key(value)
            for value in [part["title"], label(part["title"]), *part["title"].split(" / "), *label(part["title"]).split(" / ")])
        if not section_match:
            continue
        for kind, item in entries:
            if hero and (kind != "hero" or _hero_key(hero) != _hero_key(item.get("name", ""))):
                continue
            matched = True
            cards.append(_card(part, kind, item))
    if not matched:
        raise LookupError("本次补丁没有匹配的章节或英雄。请从目录中选择。")
    if not cards:
        cards = [{"title": "补丁原文", "section": "正文", "icon": "", "rows": [
            {"text": candidate.get("raw_text") or candidate.get("text") or "暂无正文", "style": "body"}]}]
    details = _layout(cards)
    chosen = "detail" if section or hero or view == "detail" else "overview"
    if chosen == "overview":
        from .digest import build_digest
        pages = [[{"digest": build_digest(candidate)}]]
    else:
        pages = details
    return {"view": chosen, "pages": pages, "page_count": len(pages), "detail_page_count": len(details), "sections": directory}


def page_assets(page):
    if page and "digest" in page[0]:
        from .digest import digest_assets
        return digest_assets(page[0]["digest"])
    urls = []
    for card in page:
        if card.get("icon"):
            urls.append(card["icon"])
        for row in card["lines"]:
            if row["style"] == "images":
                urls.extend(url for url in row["urls"] if url)
    return list(dict.fromkeys(urls))


def render_patch_notes(candidate: Mapping[str, Any], *, summary_text="", asset_paths=None) -> RenderedImage:
    from PIL import Image, ImageDraw, ImageOps
    assets = asset_paths or {}
    page = candidate.get("_reader_page")
    meta = candidate.get("_reader_meta") or {}
    if page is None:
        reader = build_reader(candidate)
        page = reader["pages"][0]
        meta = {"view": reader["view"], "page": 1, "page_count": reader["page_count"]}
    if page and "digest" in page[0]:
        from .digest import render_digest
        return render_digest(candidate, page[0]["digest"], assets)
    height = min(MAX_HEIGHT, max(520, TOP + sum(card["height"] + GAP for card in page) + FOOTER))
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((MARGIN, 38, MARGIN + 6, 116), fill=ACCENT)
    draw.text((MARGIN + 24, 38), "守望先锋 · 补丁说明", font=_font(44, True), fill=WHITE)
    date = str(candidate.get("date") or candidate.get("date_text") or "")[:40]
    source = str(candidate.get("source_name") or "")
    draw.text((MARGIN + 24, 100), f"{date}   /   {source}   /   {'总览' if meta.get('view') == 'overview' else '完整正文'}", font=_font(24), fill=MUTED)
    draw.line((MARGIN, 156, WIDTH - MARGIN, 156), fill=(47, 65, 84), width=2)

    def paste(url, box):
        path = assets.get(url)
        if path:
            try:
                with Image.open(path) as raw:
                    thumb = ImageOps.fit(raw.convert("RGB"), (box[2] - box[0], box[3] - box[1]))
                    canvas.paste(thumb, box[:2])
                    return
            except (OSError, ValueError):
                pass
        draw.rectangle(box, fill=(34, 44, 59))
        draw.text((box[0] + 12, box[1] + 12), "图片不可用", font=_font(20), fill=MUTED)

    y = TOP
    for card in page:
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + card["height"]), radius=16, fill=CARD)
        tx = MARGIN + 24
        if card.get("icon") and assets.get(card["icon"]):
            paste(card["icon"], (tx, y + 20, tx + 64, y + 84)); tx += 84
        ty = y + 18
        for i, line in enumerate(card["title_lines"]):
            draw.text((tx, ty), line, font=_font(36, True), fill=WHITE)
            ty += 44
        if card["continuation"]:
            draw.text((WIDTH - MARGIN - 84, y + 24), "续", font=_font(24), fill=ACCENT)
        ty = y + card["title_height"]
        # Section context is retained on every card, including continuation pages.
        context = card.get("section", "")
        context_lines = _wrap(context, 19, WIDTH - MARGIN * 2 - 56)
        if context_lines:
            # Full section titles also remain in the directory; this is a compact breadcrumb.
            draw.text((MARGIN + 24, ty - 4), context_lines[0], font=_font(19), fill=MUTED)
        ty += 22
        for row in card["lines"]:
            if row["style"] == "images":
                x, w = MARGIN + 24, (WIDTH - MARGIN * 2 - 64) // 2
                for slot, url in enumerate(row["urls"]):
                    if url:
                        paste(url, (x + slot * (w + 16), ty + 28, x + slot * (w + 16) + w, ty + 268))
                        captions = row.get("labels") or ["变更前", "变更后"]
                        draw.text((x + slot * (w + 16), ty), captions[slot], font=_font(20), fill=MUTED)
            else:
                style = row["style"]
                color = ACCENT if style == "ability" else MUTED if style == "note" else WHITE
                if row.get("change"):
                    name, before, after = row["change"]
                    draw.text((MARGIN + 28, ty), name, font=_font(30), fill=WHITE)
                    vx = WIDTH - MARGIN - 350
                    draw.text((vx, ty), before, font=_font(30), fill=MUTED)
                    # Draw the arrow rather than depend on a Unicode glyph.
                    ax, ay = vx + 150, ty + 20
                    draw.line((ax, ay, ax + 30, ay), fill=MUTED, width=2)
                    draw.polygon([(ax + 30, ay), (ax + 22, ay - 5), (ax + 22, ay + 5)], fill=MUTED)
                    draw.text((vx + 205, ty), after, font=_font(30, True), fill=ACCENT)
                else:
                    draw.text((MARGIN + 28, ty), row["text"], font=_font(31 if style == "ability" else 30, style == "ability"), fill=color)
            ty += row["height"]
        y += card["height"] + GAP
    footer = f"第 {meta.get('page', 1)} / {meta.get('page_count', 1)} 页"
    if meta.get("view") == "overview":
        footer += "   ·   查看章节或英雄获取完整内容"
    else:
        footer += "   ·   同一补丁内分页，原文内容保留"
    draw.text((MARGIN, height - 68), footer, font=_font(23), fill=MUTED)
    buf = BytesIO()
    canvas.save(buf, format="PNG", compress_level=3)
    return RenderedImage(buf.getvalue())


def render_patch_fallback(candidate, *, summary_text=""):
    # The same bounded layout handles raw text; never silently crop a long fallback.
    return render_patch_notes(candidate, summary_text=summary_text, asset_paths={})
