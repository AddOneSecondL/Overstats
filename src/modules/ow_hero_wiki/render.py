from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import hashlib
import math
from typing import Any, Dict, Iterable, Mapping, Sequence

import httpx

from ...constants.backgrounds import build_random_map_background

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.query_tool import get_cached_asset_path
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.query_tool import get_cached_asset_path


CARD_FILL = (18, 24, 34, 206)
CARD_INNER_FILL = (25, 33, 46, 232)
CARD_OUTLINE = (81, 103, 130, 165)
TEXT_MAIN = (244, 248, 255, 255)
TEXT_SUB = (196, 208, 225, 255)
TEXT_DIM = (146, 160, 180, 255)
PILL_FILL = (50, 60, 76, 245)
PILL_TEXT = (228, 235, 246, 255)
ERROR_ACCENT = (232, 96, 112, 255)

HEALTH_FILL = (239, 244, 250, 255)
ARMOR_FILL = (245, 195, 86, 255)
SHIELD_FILL = (108, 184, 255, 255)
HEALTH_BLOCK_BG = (43, 53, 68, 235)
XP_TRACK_BG = (39, 49, 66, 235)
MINOR_XP_FILL = (111, 224, 169, 255)
MAJOR_XP_FILL = (255, 161, 199, 255)
MODULE_FILL = (24, 32, 45, 235)
MODULE_OUTLINE = (84, 106, 132, 145)

_REMOTE_IMAGE_CACHE: dict[str, bytes] = {}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_hero_wiki_overview(
    payload: Mapping[str, Any],
    *,
    accent_color: Sequence[int] = (96, 191, 255),
    icon_url: str = "",
    image_url: str = "",
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc


    scale = 2
    base_width = 1200
    canvas_width = base_width * scale
    fonts = _load_fonts(scale)

    stats = payload.get("stats") or {}
    abilities = [item for item in list(payload.get("abilities") or []) if isinstance(item, dict)]
    perks = [item for item in list(payload.get("perks") or []) if isinstance(item, dict)]
    question = str(payload.get("question") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    accent = _to_rgba(accent_color, alpha=255)

    padding = 32 * scale
    header_top = 36 * scale
    header_height = 292 * scale
    content_width = canvas_width - padding * 2
    section_gap = 22 * scale

    citations = list(payload.get("citations") or [])
    if question:
        related = {(hit.get("section"), hit.get("card_index")) for hit in citations}
        abilities = [card for i, card in enumerate(abilities) if ("abilities", i) in related]
        perks = [card for i, card in enumerate(perks) if ("perks", i) in related]
    hero_name = str(payload.get("hero_cn") or "")
    abilities = [dict(card, hero_cn=hero_name) for card in abilities]
    perks = [dict(card, hero_cn=hero_name) for card in perks]
    section_images = [
        _render_overview_panel(
            dict(payload, image_url=image_url),
            width=content_width,
            fonts=fonts,
            scale=scale,
            accent=accent,
        )
    ]
    if question:
        section_images.append(
            _render_question_panel(
                question=question,
                answer=answer or "当前问答不可用",
                width=content_width,
                fonts=fonts,
                scale=scale,
                accent=accent,
            )
        )
    if abilities:
        section_images.extend(_render_group_sections("技能", abilities, width=content_width, fonts=fonts, scale=scale))
    if perks:
        section_images.extend(_render_group_sections("威能", perks, width=content_width, fonts=fonts, scale=scale))

    source = payload.get("source") or {}
    source_lines = ["资料来源：" + str(source.get("fandom_url") or "Wiki 来源暂缺"),
                    "中文名称与简介参考本地英雄配置；数值及机制以 Wiki 资料为准。"]
    source_lines.extend(f"[{hit['id']}] {hit['title']}\n{hit['url']}" for hit in citations)
    section_images.append(_render_text_panel("资料与引用", "\n".join(source_lines), content_width, fonts, scale, accent))

    total_height = header_top + header_height + 28 * scale
    total_height += sum(image.height for image in section_images)
    total_height += max(0, len(section_images) - 1) * section_gap
    total_height += 42 * scale

    canvas = Image.new("RGBA", (canvas_width, total_height), (9, 13, 19, 255))
    background = build_random_map_background(
        (canvas_width, total_height),
        blur_radius=42,
        overlay=(5, 8, 14, 166),
        brightness=0.78,
        color=0.86,
    )
    if background is not None:
        canvas.alpha_composite(background)
    canvas.alpha_composite(_gradient_overlay((canvas_width, total_height)))

    draw = ImageDraw.Draw(canvas, "RGBA")
    header_box = (padding, header_top, canvas_width - padding, header_top + header_height)
    _draw_card_shell(draw, header_box, radius=12 * scale)
    _draw_header(
        canvas,
        draw,
        payload=payload,
        bounds=header_box,
        fonts=fonts,
        scale=scale,
        accent=accent,
        icon_url=icon_url,
        stats=stats,
    )

    current_y = header_box[3] + 24 * scale
    for section_image in section_images:
        canvas.alpha_composite(section_image, dest=(padding, current_y))
        current_y += section_image.height + section_gap

    output = BytesIO()
    canvas = canvas.resize((base_width, int(total_height / scale)), Image.LANCZOS)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def render_hero_wiki_error(title: str, message: str) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    scale = 2
    base_width = 1120
    base_height = 360
    width = base_width * scale
    height = base_height * scale
    canvas = Image.new("RGBA", (width, height), (10, 14, 20, 255))
    background = build_random_map_background(
        (width, height),
        blur_radius=42,
        overlay=(8, 10, 16, 188),
        brightness=0.76,
        color=0.84,
    )
    if background is not None:
        canvas.alpha_composite(background)
    canvas.alpha_composite(_gradient_overlay((width, height)))

    draw = ImageDraw.Draw(canvas, "RGBA")
    fonts = _load_fonts(scale)
    box = (52 * scale, 46 * scale, width - 52 * scale, height - 46 * scale)
    _draw_card_shell(draw, box, radius=14 * scale)
    draw.rounded_rectangle(
        (box[0], box[1], box[2], box[1] + 10 * scale),
        radius=14 * scale,
        fill=ERROR_ACCENT,
    )
    draw.text((box[0] + 24 * scale, box[1] + 36 * scale), str(title or "请求失败"), font=fonts["section_title"], fill=TEXT_MAIN)
    body_lines = _wrap_text(draw, str(message or "暂时无法生成英雄资料图"), fonts["body"], box[2] - box[0] - 48 * scale, max_lines=6)
    _draw_multiline(draw, box[0] + 24 * scale, box[1] + 96 * scale, body_lines, fonts["body"], TEXT_SUB, line_gap=8 * scale)

    output = BytesIO()
    canvas = canvas.resize((base_width, base_height), Image.LANCZOS)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _draw_header(
    canvas: Any,
    draw: Any,
    *,
    payload: Mapping[str, Any],
    bounds: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
    accent: tuple[int, int, int, int],
    icon_url: str,
    stats: Mapping[str, Any],
) -> None:
    from PIL import Image

    left, top, right, bottom = bounds
    draw.rounded_rectangle((left, top, right, top + 8 * scale), radius=12 * scale, fill=accent)

    avatar_size = 86 * scale
    avatar_x = left + 24 * scale
    avatar_y = top + 24 * scale
    avatar_box = (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size)
    draw.rounded_rectangle(
        avatar_box,
        radius=12 * scale,
        fill=(24, 32, 44, 238),
        outline=(101, 126, 154, 165),
        width=max(1, scale),
    )
    hero_icon = _load_hero_icon(icon_url)
    if hero_icon is not None:
        hero_icon = hero_icon.resize((avatar_size - 10 * scale, avatar_size - 10 * scale), Image.LANCZOS)
        canvas.paste(hero_icon, (avatar_x + 5 * scale, avatar_y + 5 * scale), hero_icon)
    else:
        fallback_text = str(payload.get("hero_cn") or payload.get("hero_en") or "?")[:2]
        tw, th = _measure(draw, fallback_text, fonts["fallback"])
        draw.text(
            (avatar_x + (avatar_size - tw) / 2, avatar_y + (avatar_size - th) / 2),
            fallback_text,
            font=fonts["fallback"],
            fill=TEXT_MAIN,
        )

    title_x = avatar_box[2] + 24 * scale
    title_width = right - title_x - 26 * scale
    hero_cn = str(payload.get("hero_cn") or payload.get("hero") or "未知英雄")
    hero_en = str(payload.get("hero_en") or "")
    role_text = str(payload.get("role_cn") or payload.get("role") or "未知职责")

    name_lines = _wrap_text(draw, hero_cn, fonts["header_name"], title_width, max_lines=2)
    current_y = top + 28 * scale
    current_y = _draw_multiline(draw, title_x, current_y, name_lines, fonts["header_name"], TEXT_MAIN, line_gap=6 * scale)
    if hero_en:
        current_y += 4 * scale
        draw.text((title_x, current_y), hero_en, font=fonts["header_en"], fill=TEXT_SUB)
        current_y += _measure(draw, "A", fonts["header_en"])[1]
    current_y += 12 * scale
    _draw_pill(
        draw,
        x=title_x,
        y=current_y,
        text=role_text,
        font=fonts["role"],
        fill=_with_alpha(accent, 230),
        fg=(18, 24, 34, 255),
        pad_x=14 * scale,
        pad_y=7 * scale,
    )

    module_left = left + 24 * scale
    module_right = right - 24 * scale
    module_top = top + 146 * scale
    module_bottom = bottom - 22 * scale
    module_gap = 18 * scale
    life_width = int((module_right - module_left - module_gap) * 0.42)
    life_box = (module_left, module_top, module_left + life_width, module_bottom)
    xp_box = (life_box[2] + module_gap, module_top, module_right, module_bottom)
    _draw_health_module(draw, bounds=life_box, stats=stats, fonts=fonts, scale=scale)
    _draw_xp_module(draw, bounds=xp_box, stats=stats, fonts=fonts, scale=scale)


def _draw_health_module(
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    stats: Mapping[str, Any],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    left, top, right, bottom = bounds
    _draw_module_shell(draw, bounds, radius=10 * scale)

    draw.text((left + 18 * scale, top + 14 * scale), "生命构成", font=fonts["module_title"], fill=TEXT_MAIN)

    total_hp = int(stats.get("total_hp") or 0)
    preset_bonus_hp = int(stats.get("preset_bonus_hp") or 0)
    preset_total_hp = int(stats.get("preset_mode_total_hp") or total_hp + preset_bonus_hp)
    hp_label = "HP"
    total_text = _format_number(total_hp)
    total_w, _ = _measure(draw, total_text, fonts["module_value"])
    hp_w, hp_h = _measure(draw, hp_label, fonts["module_meta"])
    total_x = right - 18 * scale - total_w - hp_w - 8 * scale
    draw.text((total_x, top + 10 * scale), total_text, font=fonts["module_value"], fill=TEXT_MAIN)
    draw.text((total_x + total_w + 8 * scale, top + 28 * scale), hp_label, font=fonts["module_meta"], fill=TEXT_DIM)

    segments = [
        ("生命", int(stats.get("health") or 0), HEALTH_FILL),
        ("护甲", int(stats.get("armor") or 0), ARMOR_FILL),
        ("护盾", int(stats.get("shield") or 0), SHIELD_FILL),
    ]
    blocks: list[tuple[str, int, tuple[int, int, int, int]]] = []
    for label, value, color in segments:
        if value <= 0:
            continue
        block_count = max(1, int(math.ceil(value / 25.0)))
        blocks.extend((label, value, color) for _ in range(block_count))

    if not blocks:
        draw.text((left + 18 * scale, top + 54 * scale), "暂无生命组件数据", font=fonts["meta"], fill=TEXT_DIM)
        return

    block_x = left + 18 * scale
    block_y = top + 50 * scale
    available_w = max(20 * scale, right - left - 36 * scale)
    block_gap = 4 * scale
    block_w = int((available_w - block_gap * max(0, len(blocks) - 1)) / max(1, len(blocks)))
    if block_w < 8 * scale:
        block_gap = 2 * scale
        block_w = int((available_w - block_gap * max(0, len(blocks) - 1)) / max(1, len(blocks)))
    block_w = max(8 * scale, min(18 * scale, block_w))
    block_h = max(16 * scale, min(22 * scale, block_w + 4 * scale))
    total_blocks_w = len(blocks) * block_w + max(0, len(blocks) - 1) * block_gap
    if total_blocks_w > available_w and len(blocks) > 1:
        block_gap = max(scale, int((available_w - len(blocks) * block_w) / (len(blocks) - 1)))

    for index, (_, _, color) in enumerate(blocks):
        x = block_x + index * (block_w + block_gap)
        draw.rounded_rectangle(
            (x, block_y, x + block_w, block_y + block_h),
            radius=max(3 * scale, block_w // 4),
            fill=color,
            outline=_with_alpha(color, 150),
            width=max(1, scale),
        )

    legend_y = block_y + block_h + 10 * scale
    legend_x = left + 18 * scale
    legend_right = right - 18 * scale
    legend_row_h = _measure(draw, "A", fonts["module_meta"])[1] + 4 * scale
    for label, value, color in segments:
        if value <= 0:
            continue
        legend_text = f"{label} {_format_number(value)}"
        entry_w = 16 * scale + _measure(draw, legend_text, fonts["module_meta"])[0] + 18 * scale
        if legend_x > left + 18 * scale and legend_x + entry_w > legend_right:
            legend_x = left + 18 * scale
            legend_y += legend_row_h + 4 * scale
        swatch_box = (legend_x, legend_y + 5 * scale, legend_x + 10 * scale, legend_y + 15 * scale)
        draw.rounded_rectangle(swatch_box, radius=3 * scale, fill=color)
        draw.text((legend_x + 16 * scale, legend_y), legend_text, font=fonts["module_meta"], fill=TEXT_SUB)
        legend_x += entry_w

    if preset_bonus_hp > 0:
        note_line_y = legend_y + legend_row_h + 10 * scale
        draw.line(
            (left + 18 * scale, note_line_y, right - 18 * scale, note_line_y),
            fill=(90, 110, 136, 150),
            width=max(1, scale),
        )
        note_text = f"预设职责模式：重装额外 +{preset_bonus_hp} 生命，总计 {preset_total_hp} HP"
        note_lines = _wrap_text(draw, note_text, fonts["tiny"], right - left - 36 * scale, max_lines=2)
        _draw_multiline(
            draw,
            left + 18 * scale,
            note_line_y + 10 * scale,
            note_lines,
            fonts["tiny"],
            TEXT_DIM,
            line_gap=4 * scale,
        )


def _draw_xp_module(
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    stats: Mapping[str, Any],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    left, top, right, bottom = bounds
    _draw_module_shell(draw, bounds, radius=10 * scale)
    draw.text((left + 18 * scale, top + 14 * scale), "威能解锁", font=fonts["module_title"], fill=TEXT_MAIN)

    minor_xp = max(0, int(stats.get("minor_perk_xp") or 0))
    major_xp = max(0, int(stats.get("major_perk_xp") or 0))
    xp_cap = _round_up(max(major_xp, 5000), 500)

    track_left = left + 22 * scale
    track_right = right - 22 * scale
    track_y = top + 50 * scale
    track_h = 10 * scale
    track_mid_y = track_y + track_h / 2
    draw.rounded_rectangle((track_left, track_y, track_right, track_y + track_h), radius=track_h // 2, fill=XP_TRACK_BG)

    highlight_end = max(minor_xp, major_xp)
    if highlight_end > 0:
        major_fill_right = _timeline_x(track_left, track_right, xp_cap, highlight_end)
        if major_fill_right > track_left:
            draw.rounded_rectangle(
                (track_left, track_y, major_fill_right, track_y + track_h),
                radius=track_h // 2,
                fill=_with_alpha(MAJOR_XP_FILL, 110),
            )
    if minor_xp > 0:
        minor_fill_right = _timeline_x(track_left, track_right, xp_cap, minor_xp)
        if minor_fill_right > track_left:
            draw.rounded_rectangle(
                (track_left, track_y, minor_fill_right, track_y + track_h),
                radius=track_h // 2,
                fill=_with_alpha(MINOR_XP_FILL, 160),
            )

    draw.text((track_left, track_y - 24 * scale), "0", font=fonts["tiny"], fill=TEXT_DIM)
    cap_text = f"{_format_number(xp_cap)} XP"
    cap_w, _ = _measure(draw, cap_text, fonts["tiny"])
    draw.text((track_right - cap_w, track_y - 24 * scale), cap_text, font=fonts["tiny"], fill=TEXT_DIM)

    minor_x = _timeline_x(track_left, track_right, xp_cap, minor_xp)
    major_x = _timeline_x(track_left, track_right, xp_cap, major_xp)
    _draw_circle_marker(draw, (minor_x, track_mid_y), radius=8 * scale, fill=MINOR_XP_FILL, outline=(240, 248, 255, 255))
    _draw_diamond_marker(draw, (major_x, track_mid_y), radius=9 * scale, fill=MAJOR_XP_FILL, outline=(240, 248, 255, 255))

    legend_top = top + 78 * scale
    legend_gap = 14 * scale
    legend_w = int((right - left - 36 * scale - legend_gap) / 2)
    legend_h = 38 * scale
    minor_box = (left + 18 * scale, legend_top, left + 18 * scale + legend_w, legend_top + legend_h)
    major_box = (minor_box[2] + legend_gap, legend_top, right - 18 * scale, legend_top + legend_h)
    _draw_xp_legend_box(
        draw,
        bounds=minor_box,
        label="次要威能",
        value=minor_xp,
        fill=MINOR_XP_FILL,
        fonts=fonts,
        scale=scale,
    )
    _draw_xp_legend_box(
        draw,
        bounds=major_box,
        label="主要威能",
        value=major_xp,
        fill=MAJOR_XP_FILL,
        fonts=fonts,
        scale=scale,
        diamond=True,
    )


def _draw_xp_legend_box(
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    label: str,
    value: int,
    fill: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
    diamond: bool = False,
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(
        bounds,
        radius=8 * scale,
        fill=(31, 40, 56, 230),
        outline=_with_alpha(fill, 110),
        width=max(1, scale),
    )
    marker_center = (left + 18 * scale, top + (bottom - top) / 2)
    if diamond:
        _draw_diamond_marker(draw, marker_center, radius=7 * scale, fill=fill, outline=None)
    else:
        _draw_circle_marker(draw, marker_center, radius=6 * scale, fill=fill, outline=None)
    value_text = f"{_format_number(value)} XP"
    label_y = top + int((bottom - top - _measure(draw, label, fonts["meta"])[1]) / 2) - scale
    value_w, value_h = _measure(draw, value_text, fonts["meta"])
    value_x = right - 14 * scale - value_w
    value_y = top + int((bottom - top - value_h) / 2) - scale
    draw.text((left + 32 * scale, label_y), label, font=fonts["meta"], fill=TEXT_DIM)
    draw.text((value_x, value_y), value_text, font=fonts["meta"], fill=TEXT_MAIN)


def _render_overview_panel(
    payload: Mapping[str, Any],
    *,
    width: int,
    fonts: Dict[str, Any],
    scale: int,
    accent: tuple[int, int, int, int],
) -> Any:
    from PIL import Image, ImageDraw

    overview = str(payload.get("overview") or "暂无英雄简介")
    temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp)
    portrait = _open_cached_or_remote_rgba(payload.get("image_url"), categories=("heroes", "misc"))
    portrait_w = 180 * scale if portrait is not None else 0
    lines = _wrap_text(temp_draw, overview, fonts["body"], width - 44 * scale - portrait_w, max_lines=None)
    line_h = _measure(temp_draw, "A", fonts["body"])[1] + 8 * scale
    height = max(72 * scale + max(line_h * len(lines), 38 * scale) + 18 * scale, 210 * scale if portrait is not None else 0)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_card_shell(draw, (0, 0, width, height), radius=12 * scale)
    if portrait is not None:
        from PIL import ImageOps
        portrait = ImageOps.contain(portrait, (portrait_w - 12 * scale, height - 70 * scale))
        image.alpha_composite(portrait, (width - portrait_w, height - portrait.height - 12 * scale))
    draw.text((22 * scale, 18 * scale), "英雄概览", font=fonts["section_title"], fill=TEXT_MAIN)
    draw.line((22 * scale, 48 * scale, width - 22 * scale, 48 * scale), fill=_with_alpha(accent, 120), width=max(1, scale))
    _draw_multiline(draw, 22 * scale, 62 * scale, lines, fonts["body"], TEXT_SUB, line_gap=8 * scale)
    return image


def _render_question_panel(
    *,
    question: str,
    answer: str,
    width: int,
    fonts: Dict[str, Any],
    scale: int,
    accent: tuple[int, int, int, int],
) -> Any:
    from PIL import Image, ImageDraw

    temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp)
    question_lines = _wrap_text(temp_draw, question, fonts["body"], width - 44 * scale, max_lines=None)
    answer_lines = _wrap_text(temp_draw, answer, fonts["body"], width - 44 * scale, max_lines=None)
    line_h = _measure(temp_draw, "A", fonts["body"])[1] + 8 * scale
    block_gap = 14 * scale
    height = 142 * scale + line_h * (len(question_lines) + len(answer_lines)) + block_gap
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_card_shell(draw, (0, 0, width, height), radius=12 * scale)
    draw.text((22 * scale, 18 * scale), "定向查询 · 资料问答", font=fonts["section_title"], fill=TEXT_MAIN)
    draw.line((22 * scale, 48 * scale, width - 22 * scale, 48 * scale), fill=_with_alpha(accent, 120), width=max(1, scale))
    draw.text((22 * scale, 62 * scale), "问题", font=fonts["small_title"], fill=TEXT_MAIN)
    y = _draw_multiline(draw, 22 * scale, 86 * scale, question_lines, fonts["body"], TEXT_SUB, line_gap=8 * scale)
    y += block_gap
    draw.text((22 * scale, y), "回答", font=fonts["small_title"], fill=TEXT_MAIN)
    _draw_multiline(draw, 22 * scale, y + 24 * scale, answer_lines, fonts["body"], TEXT_SUB, line_gap=8 * scale)
    return image


def _render_group_sections(
    section_label: str,
    cards: Sequence[Mapping[str, Any]],
    *,
    width: int,
    fonts: Dict[str, Any],
    scale: int,
) -> list[Any]:
    grouped: list[tuple[str, tuple[int, int, int], list[Mapping[str, Any]]]] = []
    index_by_title: dict[str, int] = {}
    for card in cards:
        title = str(card.get("group_title_cn") or section_label)
        accent = tuple(card.get("accent") or (96, 191, 255))
        if title not in index_by_title:
            index_by_title[title] = len(grouped)
            grouped.append((title, accent, [card]))
            continue
        grouped[index_by_title[title]][2].append(card)  # type: ignore[index]

    images = []
    for title, accent, group_cards in grouped:
        images.append(
            _render_group_panel(
                title=title,
                cards=group_cards,
                width=width,
                fonts=fonts,
                scale=scale,
                accent=_to_rgba(accent, alpha=255),
            )
        )
    return images


def _render_group_panel(
    *,
    title: str,
    cards: Sequence[Mapping[str, Any]],
    width: int,
    fonts: Dict[str, Any],
    scale: int,
    accent: tuple[int, int, int, int],
) -> Any:
    from PIL import Image, ImageDraw

    outer_pad = 18 * scale
    top_area_h = 44 * scale
    card_gap = 16 * scale
    inner_width = width - outer_pad * 2

    if len(cards) == 1:
        card_images = [_render_compact_hero_card(cards[0], width=inner_width, fonts=fonts, scale=scale)]
        placements = [(card_images[0], outer_pad, outer_pad + top_area_h)]
        content_h = card_images[0].height
    else:
        column_count = 2
        card_width = int((inner_width - card_gap) / column_count)
        card_images = [_render_compact_hero_card(card, width=card_width, fonts=fonts, scale=scale) for card in cards]
        placements = []
        col_heights = [0] * column_count
        for card_image in card_images:
            column = col_heights.index(min(col_heights))
            x = outer_pad + column * (card_width + card_gap)
            y = outer_pad + top_area_h + col_heights[column]
            placements.append((card_image, x, y))
            col_heights[column] += card_image.height + card_gap
        content_h = max(col_heights) - card_gap if placements else 0

    total_h = outer_pad + top_area_h + content_h + outer_pad
    image = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_card_shell(draw, (0, 0, width, total_h), radius=12 * scale)
    draw.text((outer_pad, 16 * scale), title, font=fonts["section_title"], fill=TEXT_MAIN)
    count_text = f"{len(cards)} 项"
    count_w, _ = _measure(draw, count_text, fonts["meta"])
    draw.text((width - outer_pad - count_w, 19 * scale), count_text, font=fonts["meta"], fill=TEXT_DIM)
    draw.line((outer_pad, 42 * scale, width - outer_pad, 42 * scale), fill=_with_alpha(accent, 110), width=max(1, scale))

    for card_image, x, y in placements:
        image.alpha_composite(card_image, dest=(x, y))
    return image


def _render_wide_hero_card(card: Mapping[str, Any], *, width: int, fonts: Dict[str, Any], scale: int) -> Any:
    from PIL import Image, ImageDraw

    stats = [item for item in list(card.get("stats") or []) if isinstance(item, Mapping)]
    stat_width = int((width - 54 * scale) * 0.39)
    stat_image = _render_stat_grid(stats, stat_width, fonts=fonts, scale=scale, columns=2)
    if stat_image is None:
        return _render_compact_hero_card(card, width=width, fonts=fonts, scale=scale)

    temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp)
    accent = _to_rgba(card.get("accent") or (96, 191, 255), alpha=255)
    pad = 20 * scale
    gap = 20 * scale
    right_width = stat_image.width
    left_width = width - pad * 2 - gap - right_width

    title = str(card.get("name_cn") or card.get("name_en") or "未知条目")
    subtitle = str(card.get("name_en") or "")
    description = str(card.get("description") or "")
    key_cn = str(card.get("key_cn") or "")
    category_cn = str(card.get("category_cn") or "")
    tags = [str(item) for item in list(card.get("tags") or []) if str(item or "").strip()]
    notes = [str(item) for item in list(card.get("notes") or []) if str(item or "").strip()]
    mode_notes = [str(item) for item in list(card.get("mode_notes") or []) if str(item or "").strip()]
    pills = [text for text in (key_cn, category_cn) if text]

    title_lines = _wrap_text(temp_draw, title, fonts["card_title"], left_width, max_lines=2)
    subtitle_lines = _wrap_text(temp_draw, subtitle, fonts["meta"], left_width, max_lines=1) if subtitle and subtitle != title else []
    desc_lines = _wrap_text(temp_draw, description, fonts["card_body"], left_width, max_lines=10) if description else []
    tag_height = _layout_pills(temp_draw, tags, fonts["pill"], left_width, scale=scale)[1] if tags else 0
    pill_height = _layout_pills(temp_draw, pills, fonts["pill"], left_width, scale=scale)[1] if pills else 0

    note_lines = []
    for note in notes:
        wrapped = _wrap_text(temp_draw, note, fonts["meta"], left_width, max_lines=None)
        for index, line in enumerate(wrapped):
            note_lines.append(("- " if index == 0 else "  ") + line)
    if False and len(notes) > 3:
        note_lines.append(f"- more {len(notes) - 3} notes")

    mode_note_lines = []
    for note in mode_notes:
        wrapped = _wrap_text(temp_draw, note, fonts["meta"], left_width, max_lines=None)
        for index, line in enumerate(wrapped):
            mode_note_lines.append((("- " if index == 0 else "  ")) + line)

    line_h_title = _measure(temp_draw, "A", fonts["card_title"])[1] + 6 * scale
    line_h_body = _measure(temp_draw, "A", fonts["card_body"])[1] + 6 * scale
    line_h_meta = _measure(temp_draw, "A", fonts["meta"])[1] + 5 * scale
    note_header_h = _measure(temp_draw, "A", fonts["small_title"])[1] + 4 * scale

    left_height = pad + 8 * scale + len(title_lines) * line_h_title
    if subtitle_lines:
        left_height += 5 * scale + len(subtitle_lines) * line_h_meta
    if pills:
        left_height += 8 * scale + pill_height
    if desc_lines:
        left_height += 10 * scale + len(desc_lines) * line_h_body
    if tags:
        left_height += 10 * scale + tag_height
    if note_lines:
        left_height += 12 * scale + note_header_h + len(note_lines) * line_h_meta
    if mode_note_lines:
        left_height += 12 * scale + note_header_h + len(mode_note_lines) * line_h_meta
    left_height += pad

    right_height = pad + 24 * scale + stat_image.height + pad
    total_h = max(220 * scale, left_height, right_height)
    image = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (0, 0, width, total_h),
        radius=12 * scale,
        fill=CARD_INNER_FILL,
        outline=_with_alpha(accent, 148),
        width=max(1, scale),
    )
    draw.rounded_rectangle((0, 0, width, 8 * scale), radius=12 * scale, fill=accent)

    current_y = pad
    current_y = _draw_multiline(draw, pad, current_y, title_lines, fonts["card_title"], TEXT_MAIN, line_gap=6 * scale)
    if subtitle_lines:
        current_y += 4 * scale
        current_y = _draw_multiline(draw, pad, current_y, subtitle_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)
    if pills:
        current_y += 8 * scale
        current_y = _draw_pill_row(draw, pills, x=pad, y=current_y, font=fonts["pill"], max_width=left_width, scale=scale)
    if desc_lines:
        current_y += 10 * scale
        current_y = _draw_multiline(draw, pad, current_y, desc_lines, fonts["card_body"], TEXT_SUB, line_gap=6 * scale)
    if tags:
        current_y += 10 * scale
        current_y = _draw_pill_row(draw, tags, x=pad, y=current_y, font=fonts["pill"], max_width=left_width, scale=scale, fill=PILL_FILL, fg=PILL_TEXT)
    if note_lines:
        current_y += 12 * scale
        draw.text((pad, current_y), "补充说明", font=fonts["small_title"], fill=TEXT_MAIN)
        current_y += 22 * scale
        current_y = _draw_multiline(draw, pad, current_y, note_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)
    if mode_note_lines:
        current_y += 10 * scale
        draw.text((pad, current_y), "6v6 改动", font=fonts["small_title"], fill=TEXT_MAIN)
        current_y += 22 * scale
        _draw_multiline(draw, pad, current_y, mode_note_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)

    divider_x = width - pad - right_width - gap // 2
    draw.line((divider_x, pad + 8 * scale, divider_x, total_h - pad - 8 * scale), fill=(74, 92, 116, 120), width=max(1, scale))

    stat_x = width - pad - right_width
    draw.text((stat_x, pad), "核心参数", font=fonts["small_title"], fill=TEXT_MAIN)
    image.alpha_composite(stat_image, dest=(stat_x, pad + 24 * scale))
    return image


def _render_compact_hero_card(card: Mapping[str, Any], *, width: int, fonts: Dict[str, Any], scale: int) -> Any:
    from PIL import Image, ImageDraw

    temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp)

    title = str(card.get("name_cn") or card.get("name_en") or "未知条目")
    subtitle = str(card.get("name_en") or "")
    description = str(card.get("description") or "")
    key_cn = str(card.get("key_cn") or "")
    category_cn = str(card.get("category_cn") or "")
    stats = [item for item in list(card.get("stats") or []) if isinstance(item, dict)]
    tags = [str(item) for item in list(card.get("tags") or []) if str(item or "").strip()]
    notes = [str(item) for item in list(card.get("notes") or []) if str(item or "").strip()]
    mode_notes = [str(item) for item in list(card.get("mode_notes") or []) if str(item or "").strip()]
    accent = _to_rgba(card.get("accent") or (96, 191, 255), alpha=255)

    pad = 16 * scale
    icon = _load_card_icon(card)
    title_x = pad + (62 * scale if icon is not None else 0)
    title_lines = _wrap_text(temp_draw, title, fonts["card_title"], width - title_x - pad, max_lines=None)
    subtitle_lines = _wrap_text(temp_draw, subtitle, fonts["meta"], width - title_x - pad, max_lines=None) if subtitle and subtitle != title else []
    desc_lines = _wrap_text(temp_draw, description, fonts["card_body"], width - pad * 2, max_lines=None) if description else []
    pills = [text for text in (key_cn, category_cn) if text]
    stat_image = _render_stat_grid(stats, width - pad * 2, fonts=fonts, scale=scale, columns=2)

    note_lines = []
    for note in notes:
        wrapped = _wrap_text(temp_draw, note, fonts["meta"], width - pad * 2, max_lines=None)
        for index, line in enumerate(wrapped):
            note_lines.append(("- " if index == 0 else "  ") + line)
    if False and len(notes) > 2:
        note_lines.append(f"- more {len(notes) - 2} notes")

    line_h_title = _measure(temp_draw, "A", fonts["card_title"])[1] + 6 * scale
    line_h_body = _measure(temp_draw, "A", fonts["card_body"])[1] + 6 * scale
    line_h_meta = _measure(temp_draw, "A", fonts["meta"])[1] + 5 * scale
    note_header_h = _measure(temp_draw, "A", fonts["small_title"])[1] + 4 * scale
    mode_note_lines = []
    for note in mode_notes:
        wrapped = _wrap_text(temp_draw, note, fonts["meta"], width - pad * 2, max_lines=None)
        for index, line in enumerate(wrapped):
            mode_note_lines.append(("- " if index == 0 else "  ") + line)
    pills_h = _layout_pills(temp_draw, pills, fonts["pill"], width - pad * 2, scale=scale)[1] if pills else 0
    tags_h = _layout_pills(temp_draw, tags, fonts["pill"], width - pad * 2, scale=scale)[1] if tags else 0

    total_h = pad + 8 * scale + len(title_lines) * line_h_title + 32 * scale
    if subtitle_lines:
        total_h += 4 * scale + len(subtitle_lines) * line_h_meta
    if pills_h:
        total_h += 8 * scale + pills_h
    if desc_lines:
        total_h += 10 * scale + len(desc_lines) * line_h_body
    if tags_h:
        total_h += 10 * scale + tags_h
    if stat_image is not None:
        total_h += 12 * scale + stat_image.height
    if note_lines:
        total_h += 12 * scale + note_header_h + len(note_lines) * line_h_meta
    if mode_note_lines:
        total_h += 12 * scale + note_header_h + len(mode_note_lines) * line_h_meta
    total_h += pad

    image = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (0, 0, width, total_h),
        radius=12 * scale,
        fill=CARD_INNER_FILL,
        outline=_with_alpha(accent, 145),
        width=max(1, scale),
    )
    draw.rounded_rectangle((0, 0, width, 8 * scale), radius=12 * scale, fill=accent)

    if icon is not None:
        from PIL import ImageOps
        icon = ImageOps.contain(icon, (50 * scale, 50 * scale))
        image.alpha_composite(icon, (pad, pad))
    current_y = pad
    current_y = _draw_multiline(draw, title_x, current_y, title_lines, fonts["card_title"], TEXT_MAIN, line_gap=6 * scale)
    if subtitle_lines:
        current_y += 4 * scale
        current_y = _draw_multiline(draw, title_x, current_y, subtitle_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)
    current_y = max(current_y, pad + 54 * scale)
    if pills:
        current_y += 8 * scale
        current_y = _draw_pill_row(draw, pills, x=pad, y=current_y, font=fonts["pill"], max_width=width - pad * 2, scale=scale)
    if desc_lines:
        current_y += 10 * scale
        current_y = _draw_multiline(draw, pad, current_y, desc_lines, fonts["card_body"], TEXT_SUB, line_gap=6 * scale)
    if tags:
        current_y += 10 * scale
        current_y = _draw_pill_row(draw, tags, x=pad, y=current_y, font=fonts["pill"], max_width=width - pad * 2, scale=scale, fill=PILL_FILL, fg=PILL_TEXT)
    if stat_image is not None:
        current_y += 12 * scale
        image.alpha_composite(stat_image, dest=(pad, current_y))
        current_y += stat_image.height
    if note_lines:
        current_y += 12 * scale
        draw.text((pad, current_y), "补充说明", font=fonts["small_title"], fill=TEXT_MAIN)
        current_y += 22 * scale
        current_y = _draw_multiline(draw, pad, current_y, note_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)
    if mode_note_lines:
        current_y += 10 * scale
        draw.text((pad, current_y), "6v6 改动", font=fonts["small_title"], fill=TEXT_MAIN)
        current_y += 22 * scale
        _draw_multiline(draw, pad, current_y, mode_note_lines, fonts["meta"], TEXT_DIM, line_gap=5 * scale)
    return image


def _load_card_icon(card: Mapping[str, Any]) -> Any | None:
    from PIL import Image

    root = Path(__file__).resolve().parents[3] / "ow_guess_assets" / "shared" / "hero_icons"
    category = "Perks" if card.get("category") == "perk" else "Abilities"
    hero = str(card.get("hero_cn") or "")
    name = str(card.get("name_cn") or "")
    if not hero or not name:
        return None
    path = (root / hero / category / (name + ".png")).resolve()
    if not path.is_relative_to(root.resolve()):
        return None
    try:
        with Image.open(path) as raw:
            return raw.convert("RGBA")
    except (OSError, ValueError):
        return None


def _render_text_panel(title: str, text: str, width: int, fonts: Dict[str, Any], scale: int, accent: Any) -> Any:
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap_text(draw, text, fonts["meta"], width - 44 * scale)
    line_h = _measure(draw, "A", fonts["meta"])[1] + 8 * scale
    height = 78 * scale + len(lines) * line_h
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    _draw_card_shell(draw, (0, 0, width, height), radius=12 * scale)
    draw.text((22 * scale, 18 * scale), title, font=fonts["section_title"], fill=TEXT_MAIN)
    draw.line((22 * scale, 48 * scale, width - 22 * scale, 48 * scale), fill=_with_alpha(accent, 120), width=scale)
    _draw_multiline(draw, 22 * scale, 62 * scale, lines, fonts["meta"], TEXT_SUB, line_gap=8 * scale)
    return image


def _render_stat_grid(
    stats: Sequence[Mapping[str, Any]],
    width: int,
    *,
    fonts: Dict[str, Any],
    scale: int,
    columns: int,
) -> Any | None:
    from PIL import Image, ImageDraw

    items = [item for item in stats if isinstance(item, Mapping) and str(item.get("label") or "").strip()]
    if not items:
        return None

    column_count = max(1, min(int(columns or 1), 2 if len(items) > 1 else 1))
    chip_gap = 10 * scale
    chip_width = width if column_count == 1 else int((width - chip_gap) / column_count)
    temp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp)
    row_specs = []
    for item in items:
        label = str(item.get("label") or "")
        value = str(item.get("value") or "")
        value_lines = _wrap_text(temp_draw, value, fonts["stat_value"], chip_width - 22 * scale, max_lines=None)
        label_h = _measure(temp_draw, label, fonts["tiny"])[1]
        value_h = _measure(temp_draw, "A", fonts["stat_value"])[1] + 4 * scale
        chip_h = 10 * scale + label_h + 6 * scale + len(value_lines) * value_h + 10 * scale
        row_specs.append((label, value_lines, chip_h))

    rows = []
    for index in range(0, len(row_specs), column_count):
        row = row_specs[index:index + column_count]
        rows.append((row, max(item[2] for item in row)))

    total_h = sum(row_h for _, row_h in rows) + max(0, len(rows) - 1) * chip_gap
    image = Image.new("RGBA", (width, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    current_y = 0
    for row, row_h in rows:
        for col, (label, value_lines, _) in enumerate(row):
            row_width = width if len(row) == 1 else chip_width
            x = 0 if len(row) == 1 else col * (chip_width + chip_gap)
            draw.rounded_rectangle(
                (x, current_y, x + row_width, current_y + row_h),
                radius=10 * scale,
                fill=(29, 38, 53, 238),
                outline=(73, 91, 117, 145),
                width=max(1, scale),
            )
            draw.text((x + 11 * scale, current_y + 10 * scale), label, font=fonts["tiny"], fill=TEXT_DIM)
            value_y = current_y + 28 * scale
            for line in value_lines:
                draw.text((x + 11 * scale, value_y), line, font=fonts["stat_value"], fill=TEXT_MAIN)
                value_y += _measure(draw, "A", fonts["stat_value"])[1] + 4 * scale
        current_y += row_h + chip_gap
    return image


def _draw_pill_row(
    draw: Any,
    pills: Sequence[str],
    *,
    x: int,
    y: int,
    font: Any,
    max_width: int,
    scale: int,
    fill: tuple[int, int, int, int] = PILL_FILL,
    fg: tuple[int, int, int, int] = PILL_TEXT,
) -> int:
    placements, total_h = _layout_pills(draw, pills, font, max_width, scale=scale)
    for pill_x, pill_y, pill_w, pill_h, text in placements:
        pad_x = max(8 * scale, int((pill_w - _measure(draw, text, font)[0]) / 2))
        pad_y = max(4 * scale, int((pill_h - _measure(draw, text, font)[1]) / 2))
        _draw_pill(draw, x=x + pill_x, y=y + pill_y, text=text, font=font, fill=fill, fg=fg, pad_x=pad_x, pad_y=pad_y)
    return y + total_h


def _draw_pill(
    draw: Any,
    *,
    x: int,
    y: int,
    text: str,
    font: Any,
    fill: tuple[int, int, int, int],
    fg: tuple[int, int, int, int],
    pad_x: int,
    pad_y: int,
) -> None:
    text_w, text_h = _measure(draw, text, font)
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h), radius=max(10, pill_h // 2), fill=fill)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=fg)


def _layout_pills(draw: Any, pills: Sequence[str], font: Any, max_width: int, *, scale: int) -> tuple[list[tuple[int, int, int, int, str]], int]:
    placements = []
    cursor_x = 0
    cursor_y = 0
    row_h = 0
    gap_x = 8 * scale
    gap_y = 8 * scale
    for pill in pills:
        text_w, text_h = _measure(draw, pill, font)
        pill_w = text_w + 22 * scale
        pill_h = text_h + 10 * scale
        if cursor_x > 0 and cursor_x + pill_w > max_width:
            cursor_x = 0
            cursor_y += row_h + gap_y
            row_h = 0
        placements.append((cursor_x, cursor_y, pill_w, pill_h, pill))
        cursor_x += pill_w + gap_x
        row_h = max(row_h, pill_h)
    total_h = cursor_y + row_h if placements else 0
    return placements, total_h


def _draw_module_shell(draw: Any, bounds: tuple[int, int, int, int], *, radius: int) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=MODULE_FILL, outline=MODULE_OUTLINE, width=max(1, radius // 8))


def _draw_card_shell(draw: Any, bounds: tuple[int, int, int, int], *, radius: int) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=CARD_FILL, outline=CARD_OUTLINE, width=max(1, radius // 8))


def _load_fonts(scale: int) -> Dict[str, Any]:
    return {
        "header_name": load_font(34 * scale, prefer_cjk=True, bold=True),
        "header_en": load_font(17 * scale, prefer_cjk=True),
        "role": load_font(15 * scale, prefer_cjk=True, bold=True),
        "section_title": load_font(20 * scale, prefer_cjk=True, bold=True),
        "small_title": load_font(15 * scale, prefer_cjk=True, bold=True),
        "module_title": load_font(15 * scale, prefer_cjk=True, bold=True),
        "module_value": load_font(30 * scale, prefer_cjk=True, bold=True),
        "body": load_font(17 * scale, prefer_cjk=True),
        "card_title": load_font(19 * scale, prefer_cjk=True, bold=True),
        "card_body": load_font(18 * scale, prefer_cjk=True),
        "meta": load_font(15 * scale, prefer_cjk=True),
        "tiny": load_font(12 * scale, prefer_cjk=True),
        "pill": load_font(13 * scale, prefer_cjk=True),
        "stat_value": load_font(16 * scale, prefer_cjk=True),
        "module_meta": load_font(13 * scale, prefer_cjk=True),
        "fallback": load_font(28 * scale, prefer_cjk=True, bold=True),
    }


def _measure(draw: Any, text: str, font: Any) -> tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(bbox[2] - bbox[0]), max(int(bbox[3] - bbox[1]), int(getattr(font, "size", 0)))
    except Exception:
        return (0, 0)


def _wrap_text(draw: Any, text: str, font: Any, max_width: int, *, max_lines: int | None = None) -> list[str]:
    words = []
    for paragraph in str(text or "").splitlines():
        stripped = paragraph.strip()
        if not stripped:
            if words:
                words.append("\n")
            continue
        if words and words[-1] != "\n":
            words.append("\n")
        for token in _split_tokens(stripped):
            words.extend(list(token) if _measure(draw, token, font)[0] > max_width else [token])

    if not words:
        return []

    lines: list[str] = []
    current = ""
    truncated = False
    for token in words:
        if token == "\n":
            if current:
                lines.append(current.rstrip())
                current = ""
            continue
        candidate = token if not current else current + token
        if _measure(draw, candidate, font)[0] <= max_width or not current:
            current = candidate
            continue
        lines.append(current.rstrip())
        current = token.lstrip()
        if max_lines is not None and len(lines) >= max_lines:
            truncated = True
            break
    if max_lines is None or len(lines) < max_lines:
        if current:
            lines.append(current.rstrip())
    elif current:
        truncated = True
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    if truncated and lines:
        ellipsis = "..."
        last = lines[-1].rstrip(".")
        while last and _measure(draw, last + ellipsis, font)[0] > max_width:
            last = last[:-1]
        lines[-1] = (last or lines[-1]).rstrip() + ellipsis
    return lines


def _split_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    buffer = ""
    for char in str(text or ""):
        if ord(char) > 127:
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
            continue
        buffer += char
        if char == " ":
            tokens.append(buffer)
            buffer = ""
    if buffer:
        tokens.append(buffer)
    return tokens


def _draw_multiline(draw: Any, x: int, y: int, lines: Iterable[str], font: Any, fill: tuple[int, int, int, int], *, line_gap: int) -> int:
    current_y = y
    line_h = _measure(draw, "A", font)[1]
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_h + line_gap
    return current_y


def _gradient_overlay(size: tuple[int, int]) -> Any:
    from PIL import Image

    width, height = size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = overlay.load()
    for y in range(height):
        alpha = int(70 + (y / max(1, height - 1)) * 108)
        for x in range(width):
            pixels[x, y] = (7, 10, 16, alpha)
    return overlay


def _find_cached_asset_path(url: str, *, categories: Sequence[str]) -> Path | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None
    for category in categories:
        path = get_cached_asset_path(normalized, category)
        if path and path.exists():
            return path
    return None


def _load_hero_icon(icon_url: str) -> Any | None:
    return _open_cached_or_remote_rgba(icon_url, categories=("heroes", "misc"))


def _open_cached_or_remote_rgba(url: Any, *, categories: Sequence[str]) -> Any | None:
    from PIL import Image

    text = str(url or "").strip()
    if not text:
        return None

    asset_path = _find_cached_asset_path(text, categories=categories)
    if asset_path is not None:
        try:
            with Image.open(asset_path) as raw_image:
                return raw_image.convert("RGBA")
        except Exception:
            pass

    cached_bytes = _REMOTE_IMAGE_CACHE.get(text)
    if cached_bytes is None:
        try:
            response = httpx.get(text, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            cached_bytes = response.content
            if cached_bytes:
                _REMOTE_IMAGE_CACHE[text] = cached_bytes
        except Exception:
            return None
    if not cached_bytes:
        return None
    try:
        return Image.open(BytesIO(cached_bytes)).convert("RGBA")
    except Exception:
        return None


def _timeline_x(left: int, right: int, cap: int, value: int) -> int:
    ratio = 0.0 if cap <= 0 else max(0.0, min(float(value) / float(cap), 1.0))
    return int(left + (right - left) * ratio)


def _draw_circle_marker(
    draw: Any,
    center: tuple[float, float],
    *,
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None,
) -> None:
    cx, cy = center
    bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(bounds, fill=fill, outline=outline)


def _draw_diamond_marker(
    draw: Any,
    center: tuple[float, float],
    *,
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None,
) -> None:
    cx, cy = center
    points = [
        (cx, cy - radius),
        (cx + radius, cy),
        (cx, cy + radius),
        (cx - radius, cy),
    ]
    draw.polygon(points, fill=fill, outline=outline)


def _format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value or "0")


def _round_up(value: int, step: int) -> int:
    if step <= 0:
        return int(value or 0)
    return int(math.ceil(max(0, int(value or 0)) / float(step)) * step)


def _with_alpha(color: Sequence[int] | tuple[int, int, int, int], alpha: int) -> tuple[int, int, int, int]:
    rgba = _to_rgba(color, alpha=alpha)
    return rgba[0], rgba[1], rgba[2], alpha


def _to_rgba(value: Any, *, alpha: int = 255) -> tuple[int, int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            r = max(0, min(255, int(value[0])))
            g = max(0, min(255, int(value[1])))
            b = max(0, min(255, int(value[2])))
            a = max(0, min(255, int(value[3]))) if len(value) > 3 else alpha
            return (r, g, b, a)
        except Exception:
            pass
    if isinstance(value, str) and value.strip().startswith("#"):
        text = value.strip().lstrip("#")
        if len(text) in {6, 8}:
            try:
                r = int(text[0:2], 16)
                g = int(text[2:4], 16)
                b = int(text[4:6], 16)
                a = int(text[6:8], 16) if len(text) == 8 else alpha
                return (r, g, b, a)
            except Exception:
                pass
    digest = hashlib.sha256(str(value or "").encode("utf-8")).digest()
    return (digest[0], digest[1], digest[2], alpha)


__all__ = [
    "RenderedImage",
    "render_hero_wiki_error",
    "render_hero_wiki_overview",
]
