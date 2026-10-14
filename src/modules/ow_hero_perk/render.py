from __future__ import annotations

from ..dashen_promo import append_dashen_promo

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional, Sequence

from ...constants.backgrounds import build_random_map_background

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.query_tool import get_cached_asset_path
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.query_tool import get_cached_asset_path


def _resolve_resource_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        here.parents[3] / "res",
        here.parents[4] / "overstats" / "res",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


RESOURCE_DIR = _resolve_resource_dir()
PERK_BG_PATH = RESOURCE_DIR / "perk_bg.png"

CARD_FILL = (18, 24, 34, 198)
CARD_INNER_FILL = (28, 36, 50, 216)
CARD_OUTLINE = (81, 103, 130, 180)
TEXT_MAIN = (244, 248, 255, 255)
TEXT_SUB = (190, 202, 220, 255)
TEXT_DIM = (145, 155, 170, 255)
BAR_BG = (54, 62, 76, 210)
BLUE_FILL = (65, 131, 215, 255)
RED_FILL = (217, 30, 24, 255)
MINOR_ACCENT = (117, 223, 174, 255)
MAJOR_ACCENT = (255, 158, 198, 255)

ROLE_LABELS = {
    "tank": "重装",
    "dps": "输出",
    "damage": "输出",
    "healer": "支援",
    "support": "支援",
}
ROLE_BADGE_COLORS = {
    "tank": (118, 164, 255, 235),
    "dps": (255, 146, 104, 235),
    "damage": (255, 146, 104, 235),
    "healer": (117, 223, 174, 235),
    "support": (117, 223, 174, 235),
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_hero_perk_overview(
    *,
    hero: Dict[str, Any],
    minor: Dict[str, Any],
    major: Dict[str, Any],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    scale = 2
    base_width = 1500
    base_height = 760
    width = base_width * scale
    height = base_height * scale
    canvas = Image.new("RGBA", (width, height), (9, 13, 19, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    fonts = _load_fonts(scale)

    background = build_random_map_background(
        (width, height),
        blur_radius=42,
        overlay=(5, 8, 14, 166),
        brightness=0.78,
        color=0.86,
    )
    if background is not None:
        canvas.alpha_composite(background)
    canvas.alpha_composite(_gradient_overlay((width, height)))

    padding = 50 * scale
    gap = 26 * scale
    header_height = 112 * scale
    header_box = (padding, 36 * scale, width - padding, 36 * scale + header_height)
    _draw_card_shell(draw, header_box, radius=10 * scale)
    _draw_header(canvas, draw, hero=hero, bounds=header_box, fonts=fonts, scale=scale)

    section_top = header_box[3] + 28 * scale
    section_bottom = height - 42 * scale
    section_width = int((width - (padding * 2) - gap) / 2)
    minor_box = (padding, section_top, padding + section_width, section_bottom)
    major_box = (padding + section_width + gap, section_top, width - padding, section_bottom)
    _draw_section(
        canvas,
        draw,
        bounds=minor_box,
        title=_bucket_title(minor, "次级威能"),
        bucket=minor,
        header_accent=MINOR_ACCENT,
        fonts=fonts,
        scale=scale,
    )
    _draw_section(
        canvas,
        draw,
        bounds=major_box,
        title=_bucket_title(major, "主要威能"),
        bucket=major,
        header_accent=MAJOR_ACCENT,
        fonts=fonts,
        scale=scale,
    )

    output = BytesIO()
    canvas = canvas.resize((base_width, base_height), Image.LANCZOS)
    canvas = append_dashen_promo(canvas)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _draw_header(
    canvas: Any,
    draw: Any,
    *,
    hero: Dict[str, Any],
    bounds: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    left, top, right, bottom = bounds
    avatar_size = 82 * scale
    avatar_x = left + 22 * scale
    avatar_y = top + int((bottom - top - avatar_size) / 2)
    avatar_box = (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size)
    draw.rounded_rectangle(
        avatar_box,
        radius=10 * scale,
        fill=(28, 36, 50, 220),
        outline=(96, 126, 160, 180),
        width=max(1, scale),
    )

    hero_icon = _open_cached_asset(hero.get("icon_url"), ("heroes", "misc"))
    if hero_icon is not None:
        hero_icon = hero_icon.resize((avatar_size - 8 * scale, avatar_size - 8 * scale))
        canvas.paste(hero_icon, (avatar_x + 4 * scale, avatar_y + 4 * scale), hero_icon)
    else:
        fallback = str(hero.get("hero_name") or "?")[:2]
        tw, th = _measure(draw, fallback, fonts["hero_fallback"])
        draw.text(
            (avatar_x + (avatar_size - tw) / 2, avatar_y + (avatar_size - th) / 2),
            fallback,
            font=fonts["hero_fallback"],
            fill=TEXT_MAIN,
        )

    text_x = avatar_x + avatar_size + 22 * scale
    hero_name = str(hero.get("hero_name") or "未知英雄")
    draw.text((text_x, top + 20 * scale), hero_name, font=fonts["header_name"], fill=TEXT_MAIN)

    role_key = str(hero.get("hero_role") or "").strip().lower()
    role_text = ROLE_LABELS.get(role_key, str(hero.get("hero_role") or "未知职责"))
    role_fill = ROLE_BADGE_COLORS.get(role_key, (93, 112, 140, 235))
    _draw_role_badge(
        draw,
        (text_x, top + 62 * scale),
        role_text,
        fill=role_fill,
        fonts=fonts,
        scale=scale,
    )


def _draw_section(
    canvas: Any,
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    title: str,
    bucket: Dict[str, Any],
    header_accent: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    left, top, right, bottom = bounds
    _draw_card_shell(draw, bounds, radius=10 * scale)
    title_y = top + 16 * scale
    draw.text((left + 18 * scale, title_y), title, font=fonts["section_title"], fill=TEXT_MAIN)
    sample_text = f"样本 { _format_count(bucket.get('sample_count')) }"
    sample_w, _ = _measure(draw, sample_text, fonts["section_meta"])
    draw.text((right - 18 * scale - sample_w, title_y + 4 * scale), sample_text, font=fonts["section_meta"], fill=TEXT_SUB)
    draw.line((left + 18 * scale, top + 56 * scale, right - 18 * scale, top + 56 * scale), fill=(93, 112, 140, 145), width=max(1, scale))

    perks = [item for item in list(bucket.get("perks") or []) if isinstance(item, dict)][:2]
    if not perks:
        draw.text(
            (left + 24 * scale, top + 92 * scale),
            "暂无该档位的可用威能数据",
            font=fonts["card_body"],
            fill=TEXT_DIM,
        )
        return

    inner_gap = 18 * scale
    card_top = top + 76 * scale
    card_bottom = bottom - 94 * scale
    card_width = int((right - left - 36 * scale - inner_gap) / 2)
    left_card = (left + 18 * scale, card_top, left + 18 * scale + card_width, card_bottom)
    right_card = (left_card[2] + inner_gap, card_top, right - 18 * scale, card_bottom)

    left_perk = perks[0] if len(perks) > 0 else {}
    right_perk = perks[1] if len(perks) > 1 else {}
    _draw_perk_card(
        canvas,
        draw,
        bounds=left_card,
        perk=left_perk,
        team_fill=BLUE_FILL,
        header_accent=header_accent,
        fonts=fonts,
        scale=scale,
    )
    if right_perk:
        _draw_perk_card(
            canvas,
            draw,
            bounds=right_card,
            perk=right_perk,
            team_fill=RED_FILL,
            header_accent=header_accent,
            fonts=fonts,
            scale=scale,
        )
    else:
        draw.rounded_rectangle(
            right_card,
            radius=8 * scale,
            fill=(28, 36, 50, 150),
            outline=(81, 103, 130, 90),
            width=max(1, scale),
        )
        draw.text(
            (right_card[0] + 18 * scale, right_card[1] + 24 * scale),
            "暂无第二个威能",
            font=fonts["card_title"],
            fill=TEXT_DIM,
        )

    _draw_duel_bar(
        draw,
        bounds=(left + 18 * scale, bottom - 58 * scale, right - 18 * scale, bottom - 30 * scale),
        left_perk=left_perk,
        right_perk=right_perk,
        fonts=fonts,
        scale=scale,
    )


def _draw_perk_card(
    canvas: Any,
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    perk: Dict[str, Any],
    team_fill: tuple[int, int, int, int],
    header_accent: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    from PIL import Image

    left, top, right, bottom = bounds
    draw.rounded_rectangle(
        bounds,
        radius=8 * scale,
        fill=CARD_INNER_FILL,
        outline=(81, 103, 130, 150),
        width=max(1, scale),
    )
    draw.rounded_rectangle(
        (left, top, right, top + 6 * scale),
        radius=8 * scale,
        fill=_with_alpha(header_accent, 230),
    )

    icon_box = (left + 18 * scale, top + 22 * scale, left + 108 * scale, top + 112 * scale)
    draw.rounded_rectangle(
        icon_box,
        radius=10 * scale,
        fill=(23, 31, 44, 255),
        outline=(96, 126, 160, 180),
        width=max(1, scale),
    )
    perk_bg = _open_local_rgba(PERK_BG_PATH)
    if perk_bg is not None:
        perk_bg = perk_bg.resize((74 * scale, 74 * scale), Image.LANCZOS)
        canvas.paste(perk_bg, (left + 26 * scale, top + 30 * scale), perk_bg)

    perk_icon = _open_cached_asset(perk.get("icon_url"), ("perk", "misc"))
    if perk_icon is not None:
        target = 46 * scale
        icon_w, icon_h = _contain_size(perk_icon.width, perk_icon.height, target, target)
        perk_icon = perk_icon.resize((icon_w, icon_h), Image.LANCZOS)
        perk_icon = _swap_nearly_white_to_black(perk_icon)
        paste_x = left + 26 * scale + int((74 * scale - icon_w) / 2)
        paste_y = top + 30 * scale + int((74 * scale - icon_h) / 2)
        canvas.paste(perk_icon, (paste_x, paste_y), perk_icon)
    else:
        fallback = str(perk.get("name") or "?")[:2]
        tw, th = _measure(draw, fallback, fonts["perk_fallback"])
        draw.text(
            (left + 63 * scale - tw / 2, top + 67 * scale - th / 2),
            fallback,
            font=fonts["perk_fallback"],
            fill=TEXT_MAIN,
        )

    info_left = left + 126 * scale
    info_width = max(1, right - info_left - 18 * scale)
    name = str(perk.get("name") or "未知威能")
    name_lines = _wrap_text(draw, name, fonts["card_title"], info_width, 2, allow_space_join=False)
    for index, line in enumerate(name_lines):
        draw.text((info_left, top + 22 * scale + index * 28 * scale), line, font=fonts["card_title"], fill=TEXT_MAIN)

    desc_top = top + 84 * scale
    desc = str(perk.get("desc") or "暂无描述")
    desc_lines = _wrap_text(draw, desc, fonts["card_body"], info_width, 4)
    for index, line in enumerate(desc_lines):
        draw.text((info_left, desc_top + index * 24 * scale), line, font=fonts["card_body"], fill=TEXT_SUB)

    footer_y = bottom - 78 * scale
    draw.text((info_left, footer_y), "使用数", font=fonts["metric_label"], fill=TEXT_DIM)
    draw.text(
        (info_left, footer_y + 26 * scale),
        _format_count(perk.get("pick_count")),
        font=fonts["metric_value"],
        fill=team_fill,
    )
    sample_label_x = info_left + 124 * scale
    draw.text((sample_label_x, footer_y), "使用率", font=fonts["metric_label"], fill=TEXT_DIM)
    draw.text(
        (sample_label_x, footer_y + 26 * scale),
        f"{float(perk.get('pick_rate') or 0.0) * 100:.1f}%",
        font=fonts["metric_value"],
        fill=TEXT_MAIN,
    )


def _draw_duel_bar(
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    left_perk: Dict[str, Any],
    right_perk: Dict[str, Any],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    left, top, right, bottom = bounds
    bar_top = top + 12 * scale
    label_y = top - 16 * scale
    left_rate = max(0.0, min(float(left_perk.get("pick_rate") or 0.0), 1.0))
    right_rate = max(0.0, min(float(right_perk.get("pick_rate") or 0.0), 1.0))

    left_label = f"{left_rate * 100:.1f}%"
    draw.text((left, label_y), left_label, font=fonts["bar_rate"], fill=BLUE_FILL)

    right_label = f"{right_rate * 100:.1f}%"
    right_w, _ = _measure(draw, right_label, fonts["bar_rate"])
    draw.text((right - right_w, label_y), right_label, font=fonts["bar_rate"], fill=RED_FILL)

    draw.rounded_rectangle((left, bar_top, right, bottom), radius=6 * scale, fill=BAR_BG)
    bar_width = right - left
    left_width = int(bar_width * left_rate)
    right_width = int(bar_width * right_rate)

    if left_width > 0:
        draw.rounded_rectangle((left, bar_top, left + left_width, bottom), radius=6 * scale, fill=BLUE_FILL)
    if right_width > 0:
        draw.rounded_rectangle((right - right_width, bar_top, right, bottom), radius=6 * scale, fill=RED_FILL)


def _draw_role_badge(
    draw: Any,
    position: tuple[int, int],
    label: str,
    *,
    fill: tuple[int, int, int, int],
    fonts: Dict[str, Any],
    scale: int,
) -> None:
    x, y = position
    text_w, text_h = _measure(draw, label, fonts["role"])
    padding_x = 12 * scale
    height = 30 * scale
    width = int(text_w + padding_x * 2)
    box = (x, y, x + width, y + height)
    draw.rounded_rectangle(box, radius=height // 2, fill=fill)
    draw.text((x + padding_x, y + int((height - text_h) / 2) - 2 * scale), label, font=fonts["role"], fill=(18, 24, 34, 255))


def _draw_card_shell(draw: Any, box: tuple[int, int, int, int], *, radius: int) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=CARD_FILL, outline=CARD_OUTLINE, width=max(1, radius // 8))


def _load_fonts(scale: int) -> Dict[str, Any]:
    return {
        "header_name": _load_summary_font(34 * scale, bold=True),
        "role": _load_summary_font(16 * scale, bold=True),
        "section_title": _load_summary_font(24 * scale, bold=True),
        "section_meta": _load_summary_font(15 * scale),
        "card_title": _load_summary_font(20 * scale, bold=True),
        "card_body": _load_summary_font(14 * scale),
        "metric_label": _load_summary_font(13 * scale),
        "metric_value": _load_summary_font(20 * scale, bold=True),
        "bar_rate": _load_summary_font(18 * scale, bold=True),
        "hero_fallback": _load_summary_font(28 * scale, bold=True),
        "perk_fallback": _load_summary_font(20 * scale, bold=True),
    }


def _load_summary_font(size: int, *, bold: bool = False) -> Any:
    adjusted = int(size)
    if adjusted <= 22:
        adjusted += 2
    elif adjusted <= 36:
        adjusted += 1
    return load_font(
        adjusted,
        name="simhei.ttf",
        fallback="en.ttf",
        prefer_cjk=True,
        bold=bold,
    )


def _bucket_title(bucket: Dict[str, Any], fallback: str) -> str:
    text = str(bucket.get("title") or "").strip()
    return text or fallback


def _open_cached_asset(url: Any, categories: Sequence[str]) -> Any | None:
    from PIL import Image

    normalized = str(url or "").strip()
    if not normalized:
        return None
    for category in categories:
        path = get_cached_asset_path(normalized, category)
        if path is None or not path.exists():
            continue
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            continue
    return None


def _open_local_rgba(path: Path) -> Any | None:
    from PIL import Image

    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _swap_nearly_white_to_black(image: Any) -> Any:
    pixels = image.load()
    for py in range(image.height):
        for px in range(image.width):
            red, green, blue, alpha = pixels[px, py]
            if alpha > 0 and red >= 245 and green >= 245 and blue >= 245:
                pixels[px, py] = (0, 0, 0, alpha)
    return image


def _gradient_overlay(size: tuple[int, int]) -> Any:
    from PIL import Image

    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    pixels = image.load()
    for y in range(height):
        vertical_ratio = y / max(1, height - 1)
        base_alpha = int(62 + 82 * vertical_ratio)
        for x in range(width):
            side_ratio = abs((x / max(1, width - 1)) - 0.5) * 2.0
            alpha = min(255, int(base_alpha + 18 * side_ratio))
            pixels[x, y] = (6, 11, 18, alpha)
    return image


def _with_alpha(color: Sequence[int], alpha: int) -> tuple[int, int, int, int]:
    red = int(color[0]) if len(color) > 0 else 255
    green = int(color[1]) if len(color) > 1 else 255
    blue = int(color[2]) if len(color) > 2 else 255
    return red, green, blue, int(alpha)


def _measure(draw: Any, text: str, font: Any) -> tuple[float, float]:
    bbox = draw.textbbox((0, 0), str(text or ""), font=font)
    return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])


def _wrap_text(
    draw: Any,
    text: str,
    font: Any,
    max_width: int,
    max_lines: int,
    allow_space_join: bool = True,
) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "").replace("<br />", " ").replace("<br/>", " ")).strip()
    if not normalized:
        return [""]

    use_word_tokens = allow_space_join and (" " in normalized)
    tokens: Iterable[str] = normalized.split(" ") if use_word_tokens else list(normalized)
    separator = " " if use_word_tokens else ""
    lines: list[str] = []
    current = ""

    for token in tokens:
        candidate = token if not current else f"{current}{separator}{token}"
        if _measure(draw, candidate, font)[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            if len(lines) >= max_lines:
                return _ellipsis_last_line(draw, lines, font, max_width)
        current = token

    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        return _ellipsis_last_line(draw, lines, font, max_width)
    return lines


def _ellipsis_last_line(draw: Any, lines: list[str], font: Any, max_width: int) -> list[str]:
    if not lines:
        return []
    last = lines[-1]
    while last and _measure(draw, f"{last}...", font)[0] > max_width:
        last = last[:-1]
    lines[-1] = f"{last}..." if last else "..."
    return lines


def _contain_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return max(1, max_width), max(1, max_height)
    ratio = min(max_width / float(width), max_height / float(height))
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def _format_count(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


__all__ = [
    "RenderedImage",
    "render_hero_perk_overview",
]
