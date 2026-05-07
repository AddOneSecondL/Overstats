from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ...constants.backgrounds import build_random_map_background


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RES_DIR = PROJECT_ROOT / "res"
WINDOWS_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)
LOCAL_FONT_CANDIDATES = (
    RES_DIR / "GrotaRoundedExtraBold.otf",
    RES_DIR / "BigNoodleToo.ttf",
    RES_DIR / "en2.ttf",
    RES_DIR / "en.ttf",
)
FINAL_BG = (12, 17, 26)
BACKGROUND_TOP = (8, 13, 21)
BACKGROUND_BOTTOM = (18, 28, 43)
BACKGROUND_GLOW_PRIMARY = (50, 112, 255, 72)
BACKGROUND_GLOW_SECONDARY = (27, 198, 255, 52)
BACKGROUND_LINE = (255, 255, 255, 18)
CARD_BG = (24, 31, 45)
CARD_ALT_BG = (31, 40, 57)
CARD_SOFT_BG = (19, 25, 37)
CARD_OUTLINE = (75, 95, 132)
TEXT_PRIMARY = (244, 247, 255)
TEXT_SECONDARY = (221, 229, 241)
TEXT_MUTED = (166, 186, 214)
TEXT_ACCENT = (139, 208, 255)
TEXT_WARNING = (255, 217, 145)
TEXT_SUCCESS = (182, 255, 204)
TEXT_DANGER = (255, 167, 167)
CANVAS_WIDTH = 1520
CANVAS_MARGIN = 36
CARD_GAP = 20
TEMP_CARD_HEIGHT = 42000
HEADER_RADIUS = 18
CARD_RADIUS = 16
IMAGE_RADIUS = 14
LABEL_RADIUS = 11


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_patch_notes(
    candidate: Mapping[str, Any],
    *,
    summary_text: str,
    asset_paths: Mapping[str, Path],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    canvas = Image.new("RGBA", (CANVAS_WIDTH, TEMP_CARD_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")

    fonts = {
        "headline": _load_font(50, bold=True),
        "section": _load_font(34, bold=True),
        "title": _load_font(28, bold=True),
        "body": _load_font(22),
        "small": _load_font(19),
        "label": _load_font(18, bold=True),
    }

    y = CANVAS_MARGIN
    y = _draw_header_card(draw, candidate, summary_text, fonts, y)

    for section in candidate.get("sections") or []:
        y = _draw_section_title(draw, section.get("title", ""), fonts, y)
        intro = list(section.get("intro") or [])
        if intro:
            y = _draw_text_card(
                draw,
                title="概览",
                body_lines=intro,
                fonts=fonts,
                y=y,
                accent=TEXT_ACCENT,
            )

        for hero_update in section.get("hero_updates") or []:
            y = _draw_hero_card(canvas, draw, hero_update, asset_paths, fonts, y)
        for map_update in section.get("map_updates") or []:
            y = _draw_map_card(canvas, draw, map_update, asset_paths, fonts, y)
        for general_update in section.get("general_updates") or []:
            lines = []
            lines.extend(general_update.get("paragraphs") or [])
            lines.extend(f"• {item}" for item in (general_update.get("bullets") or []))
            if general_update.get("dev_note"):
                lines.append(f"开发者说明：{general_update.get('dev_note')}")
            y = _draw_text_card(
                draw,
                title=general_update.get("title", "补丁条目"),
                body_lines=lines,
                fonts=fonts,
                y=y,
                accent=TEXT_SUCCESS if general_update.get("dev_note") else TEXT_ACCENT,
            )

    final_height = max(y + CANVAS_MARGIN, 240)
    canvas = canvas.crop((0, 0, CANVAS_WIDTH, final_height))
    background = _build_background(CANVAS_WIDTH, final_height)
    background.alpha_composite(canvas)

    output = BytesIO()
    background.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def render_patch_fallback(candidate: Mapping[str, Any], *, summary_text: str) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    width = 1200
    margin = 56
    fonts = {
        "headline": _load_font(34, bold=True),
        "meta": _load_font(20, bold=True),
        "body": _load_font(20),
    }

    title_lines = _wrap_text(str(candidate.get("title") or ""), fonts["headline"], width - margin * 2)
    summary_lines = _wrap_text(summary_text, fonts["meta"], width - margin * 2)
    body_lines = _wrap_text(str(candidate.get("text") or ""), fonts["body"], width - margin * 2)

    height = (
        margin * 2
        + max(1, len(title_lines)) * 46
        + 24
        + max(1, len(summary_lines)) * 28
        + 28
        + max(1, len(body_lines)) * 28
        + 48
    )
    image = _build_background(width, height)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (24, 24, width - 24, height - 24),
        radius=HEADER_RADIUS,
        fill=CARD_BG + (242,),
        outline=CARD_OUTLINE,
        width=2,
    )

    y = margin
    for line in title_lines:
        draw.text((margin, y), line, font=fonts["headline"], fill=TEXT_PRIMARY)
        y += 46
    y += 12
    for line in summary_lines:
        draw.text((margin, y), line, font=fonts["meta"], fill=TEXT_ACCENT)
        y += 28
    y += 12
    for line in body_lines:
        draw.text((margin, y), line, font=fonts["body"], fill=TEXT_SECONDARY)
        y += 28

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _draw_header_card(draw: Any, candidate: Mapping[str, Any], summary_text: str, fonts: Mapping[str, Any], y: int) -> int:
    title_lines = _wrap_text(str(candidate.get("title") or "补丁说明"), fonts["headline"], CANVAS_WIDTH - CANVAS_MARGIN * 2 - 40)
    summary_lines = []
    for line in str(summary_text or "").splitlines():
        wrapped = _wrap_text(line, fonts["small"], CANVAS_WIDTH - CANVAS_MARGIN * 2 - 40)
        summary_lines.extend(wrapped or [""])

    meta_lines = [
        f"来源：{candidate.get('source_name', '')}",
        f"分类：{candidate.get('bucket_name', '')}",
        f"日期：{candidate.get('date_text', '')}",
    ]
    meta_height = len(meta_lines) * 28
    body_height = len(summary_lines) * 24
    title_height = len(title_lines) * 58
    card_h = 36 + title_height + 20 + meta_height + 20 + body_height + 28
    card_box = (
        CANVAS_MARGIN,
        y,
        CANVAS_WIDTH - CANVAS_MARGIN,
        y + card_h,
    )
    draw.rounded_rectangle(card_box, radius=HEADER_RADIUS, fill=CARD_BG + (242,), outline=CARD_OUTLINE, width=2)

    inner_x = card_box[0] + 22
    inner_y = card_box[1] + 20
    for line in title_lines:
        draw.text((inner_x, inner_y), line, font=fonts["headline"], fill=TEXT_PRIMARY)
        inner_y += 58
    inner_y += 4
    for line in meta_lines:
        draw.text((inner_x, inner_y), line, font=fonts["label"], fill=TEXT_WARNING)
        inner_y += 28
    inner_y += 8
    for line in summary_lines:
        draw.text((inner_x, inner_y), line, font=fonts["small"], fill=TEXT_SECONDARY)
        inner_y += 24
    return card_box[3] + 28


def _draw_section_title(draw: Any, title: str, fonts: Mapping[str, Any], y: int) -> int:
    draw.text((CANVAS_MARGIN, y), str(title or "补丁章节"), font=fonts["section"], fill=TEXT_ACCENT)
    return y + 54


def _draw_text_card(
    draw: Any,
    *,
    title: str,
    body_lines: Sequence[str],
    fonts: Mapping[str, Any],
    y: int,
    accent: tuple[int, int, int],
) -> int:
    wrapped_lines = []
    for line in body_lines:
        if not str(line or "").strip():
            continue
        wrapped_lines.extend(_wrap_text(str(line), fonts["body"], CANVAS_WIDTH - CANVAS_MARGIN * 2 - 44))

    card_h = 26 + 36 + 16 + max(1, len(wrapped_lines)) * 28 + 22
    box = (CANVAS_MARGIN, y, CANVAS_WIDTH - CANVAS_MARGIN, y + card_h)
    draw.rounded_rectangle(box, radius=CARD_RADIUS, fill=CARD_SOFT_BG + (242,), outline=CARD_OUTLINE, width=1)
    inner_x = box[0] + 22
    inner_y = box[1] + 18
    draw.text((inner_x, inner_y), str(title or "补丁条目"), font=fonts["title"], fill=accent)
    inner_y += 44
    for line in wrapped_lines:
        draw.text((inner_x, inner_y), line, font=fonts["body"], fill=TEXT_SECONDARY)
        inner_y += 28
    return box[3] + CARD_GAP


def _draw_hero_card(
    canvas: Any,
    draw: Any,
    hero_update: Mapping[str, Any],
    asset_paths: Mapping[str, Path],
    fonts: Mapping[str, Any],
    y: int,
) -> int:
    right_w = CANVAS_WIDTH - CANVAS_MARGIN * 2 - 44
    text_w = right_w - 118
    line_groups: list[tuple[str, tuple[int, int, int]]] = []
    for change in hero_update.get("general_changes") or []:
        line_groups.append((f"• {change}", TEXT_SECONDARY))
    for ability in hero_update.get("abilities") or []:
        line_groups.append((str(ability.get("name") or "技能调整"), TEXT_WARNING))
        for change in ability.get("changes") or []:
            line_groups.append((f"  - {change}", TEXT_SECONDARY))
    if hero_update.get("dev_note"):
        line_groups.append((f"开发者说明：{hero_update.get('dev_note')}", TEXT_SUCCESS))

    wrapped_lines: list[tuple[str, tuple[int, int, int]]] = []
    for text, color in line_groups:
        lines = _wrap_text(text, fonts["body"], text_w)
        wrapped_lines.extend((line, color) for line in lines)

    card_h = max(148, 30 + 36 + 12 + len(wrapped_lines) * 28 + 24)
    box = (CANVAS_MARGIN, y, CANVAS_WIDTH - CANVAS_MARGIN, y + card_h)
    draw.rounded_rectangle(box, radius=CARD_RADIUS, fill=CARD_ALT_BG + (242,), outline=CARD_OUTLINE, width=1)

    icon_box = (box[0] + 20, box[1] + 20, box[0] + 108, box[1] + 108)
    _paste_card_image(canvas, asset_paths.get(str(hero_update.get("icon_url") or "")), icon_box)

    text_x = icon_box[2] + 18
    text_y = box[1] + 18
    draw.text((text_x, text_y), str(hero_update.get("name") or "英雄改动"), font=fonts["title"], fill=TEXT_PRIMARY)
    text_y += 40
    if hero_update.get("group_title"):
        draw.text((text_x, text_y), str(hero_update.get("group_title") or ""), font=fonts["small"], fill=TEXT_MUTED)
        text_y += 28
    for line, color in wrapped_lines:
        draw.text((text_x, text_y), line, font=fonts["body"], fill=color)
        text_y += 28
    return box[3] + CARD_GAP


def _draw_map_card(
    canvas: Any,
    draw: Any,
    map_update: Mapping[str, Any],
    asset_paths: Mapping[str, Path],
    fonts: Mapping[str, Any],
    y: int,
) -> int:
    image_h = 220
    half_gap = 10
    image_w = int((CANVAS_WIDTH - CANVAS_MARGIN * 2 - 44 - half_gap) / 2)
    line_groups: list[tuple[str, tuple[int, int, int]]] = []
    if map_update.get("comparison_label"):
        line_groups.append((str(map_update.get("comparison_label") or ""), TEXT_WARNING))
    for paragraph in map_update.get("paragraphs") or []:
        line_groups.append((str(paragraph), TEXT_SECONDARY))
    for bullet in map_update.get("bullets") or []:
        line_groups.append((f"• {bullet}", TEXT_SECONDARY))

    wrapped_lines: list[tuple[str, tuple[int, int, int]]] = []
    for text, color in line_groups:
        lines = _wrap_text(text, fonts["body"], CANVAS_WIDTH - CANVAS_MARGIN * 2 - 44)
        wrapped_lines.extend((line, color) for line in lines)

    card_h = 28 + 36 + 18 + image_h + 18 + max(1, len(wrapped_lines)) * 28 + 22
    box = (CANVAS_MARGIN, y, CANVAS_WIDTH - CANVAS_MARGIN, y + card_h)
    draw.rounded_rectangle(box, radius=CARD_RADIUS, fill=CARD_SOFT_BG + (242,), outline=CARD_OUTLINE, width=1)

    text_x = box[0] + 22
    text_y = box[1] + 18
    draw.text((text_x, text_y), str(map_update.get("name") or "地图更新"), font=fonts["title"], fill=TEXT_ACCENT)
    text_y += 46

    left_box = (text_x, text_y, text_x + image_w, text_y + image_h)
    right_box = (left_box[2] + half_gap, text_y, left_box[2] + half_gap + image_w, text_y + image_h)
    _paste_card_image(canvas, asset_paths.get(str(map_update.get("before_image_url") or "")), left_box)
    _paste_card_image(canvas, asset_paths.get(str(map_update.get("after_image_url") or "")), right_box)
    _draw_box_label(draw, left_box, "变更前", fonts["small"])
    _draw_box_label(draw, right_box, "变更后", fonts["small"])

    text_y = left_box[3] + 18
    for line, color in wrapped_lines:
        draw.text((text_x, text_y), line, font=fonts["body"], fill=color)
        text_y += 28
    return box[3] + CARD_GAP


def _draw_box_label(draw: Any, box: Sequence[int], text: str, font: Any) -> None:
    label_w = max(76, int(_text_width(text, font)) + 24)
    draw.rounded_rectangle(
        (box[0] + 12, box[1] + 12, box[0] + 12 + label_w, box[1] + 42),
        radius=LABEL_RADIUS,
        fill=(0, 0, 0, 150),
    )
    draw.text((box[0] + 24, box[1] + 18), text, font=font, fill=TEXT_PRIMARY)


def _paste_card_image(canvas: Any, image_path: Path | None, box: Sequence[int]) -> None:
    from PIL import Image, ImageDraw

    width = int(box[2] - box[0])
    height = int(box[3] - box[1])
    holder = Image.new("RGBA", (width, height), CARD_BG + (255,))
    if image_path is not None and image_path.exists():
        try:
            with Image.open(image_path) as source_image:
                source = source_image.convert("RGB")
                ratio = max(width / float(source.width), height / float(source.height))
                resized = source.resize(
                    (max(1, int(source.width * ratio)), max(1, int(source.height * ratio))),
                    _resampling_lanczos(),
                )
                left = max(0, (resized.width - width) // 2)
                top = max(0, (resized.height - height) // 2)
                holder.paste(resized.crop((left, top, left + width, top + height)), (0, 0))
        except Exception:
            pass

    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=IMAGE_RADIUS, fill=255)
    holder.putalpha(mask)
    canvas.alpha_composite(holder, (int(box[0]), int(box[1])))


def _build_background(width: int, height: int) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    background = build_random_map_background(
        (width, height),
        blur_radius=18,
        overlay=(9, 14, 22, 112),
        brightness=0.78,
        color=0.88,
    )
    if background is None:
        background = Image.new("RGBA", (width, height), FINAL_BG + (255,))
        gradient_alpha = 255
    else:
        gradient_alpha = 118

    gradient_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient_layer, "RGBA")
    max_height = max(1, height - 1)
    for y in range(height):
        blend = y / float(max_height)
        color = tuple(
            int(BACKGROUND_TOP[index] + (BACKGROUND_BOTTOM[index] - BACKGROUND_TOP[index]) * blend)
            for index in range(3)
        )
        draw.line((0, y, width, y), fill=color + (gradient_alpha,))
    background.alpha_composite(gradient_layer)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse(
        (-180, -80, int(width * 0.58), int(height * 0.34)),
        fill=BACKGROUND_GLOW_PRIMARY,
    )
    glow_draw.ellipse(
        (int(width * 0.48), int(height * 0.08), width + 220, int(height * 0.58)),
        fill=BACKGROUND_GLOW_SECONDARY,
    )

    stripe_step = 170
    for offset in range(-height, width + height, stripe_step):
        glow_draw.line((offset, 0, offset + height, height), fill=BACKGROUND_LINE, width=2)

    glow = glow.filter(ImageFilter.GaussianBlur(26))
    background.alpha_composite(glow)
    return background


def _wrap_text(text: str, font: Any, max_width: int) -> list[str]:
    if not text:
        return []
    token_pattern = re.compile(r"[一-鿿]|[A-Za-z0-9][A-Za-z0-9'’/().,+%:-]*|\s+|.", re.UNICODE)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        paragraph = paragraph.rstrip()
        if not paragraph.strip():
            continue

        current_line = ""
        for token in token_pattern.findall(paragraph):
            if not current_line and token.isspace():
                continue
            test_line = current_line + token
            if not current_line or _text_width(test_line, font) <= max_width:
                current_line = test_line
                continue
            stripped = current_line.rstrip()
            if stripped:
                lines.append(stripped)
            current_line = token.lstrip()
            if current_line and _text_width(current_line, font) > max_width:
                hard_line = ""
                for char in current_line:
                    if not hard_line or _text_width(hard_line + char, font) <= max_width:
                        hard_line += char
                    else:
                        lines.append(hard_line.rstrip())
                        hard_line = char
                current_line = hard_line
        if current_line.strip():
            lines.append(current_line.rstrip())
    return lines


def _text_width(text: str, font: Any) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(text))
    bbox = font.getbbox(text)
    return float((bbox[2] - bbox[0]) if bbox else 0)


def _load_font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    windows_candidates = list(WINDOWS_FONT_CANDIDATES)
    if bold:
        windows_candidates = [WINDOWS_FONT_CANDIDATES[1], WINDOWS_FONT_CANDIDATES[2], WINDOWS_FONT_CANDIDATES[0], WINDOWS_FONT_CANDIDATES[3]]
    local_candidates = [str(path) for path in LOCAL_FONT_CANDIDATES]
    for candidate in windows_candidates + local_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")
