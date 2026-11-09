from __future__ import annotations

from ..subroles import draw_subrole_badge, get_subrole

from ..dashen_promo import append_dashen_promo

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Sequence

from ...constants.backgrounds import build_random_map_background
from ..dashen_summary.runtime.summary_style import C, RADIUS_CARD, RADIUS_TILE, themed, vertical_scrim
from ..dashen_summary.runtime.summary_typography import SmoothDraw, smooth_mask

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

PAGE_W = 2000
PAGE_MARGIN = 40
PAGE_TOP = 32
PAGE_BOTTOM = 32
SECTION_GAP = 20
HEADER_H = 150
SECTION_HEAD = 70
PERK_CARD_H = 410
DUEL_H = 104
SECTION_H = SECTION_HEAD + PERK_CARD_H + DUEL_H
PAGE_H = PAGE_TOP + HEADER_H + SECTION_GAP + SECTION_H + PAGE_BOTTOM
SECTION_PAD = 22
ICON_BOX = 104
ICON_PLATE = 86
ICON_SIZE = 54
ICON_TEXT = (22, 25, 32)
_FONT_CACHE: Dict[Any, Any] = {}

ROLE_LABELS = {
    "tank": "重装",
    "dps": "输出",
    "damage": "输出",
    "healer": "支援",
    "support": "支援",
}
ROLE_THEME_KEYS = {
    "tank": "Tank",
    "dps": "Damage",
    "damage": "Damage",
    "healer": "Support",
    "support": "Support",
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


@themed
def render_hero_perk_overview(
    *,
    hero: Dict[str, Any],
    minor: Dict[str, Any],
    major: Dict[str, Any],
) -> RenderedImage:
    try:
        from PIL import Image  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    canvas = _page_background((PAGE_W, PAGE_H))
    draw = SmoothDraw(
        canvas,
        "RGBA",
        numeric_font_path=RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
        latin_font_path=RESOURCE_DIR / "en2.ttf",
    )
    left, right = PAGE_MARGIN, PAGE_W - PAGE_MARGIN - 1
    _draw_header(canvas, draw, hero=hero, bounds=(left, PAGE_TOP, right, PAGE_TOP + HEADER_H - 1))

    section_top = PAGE_TOP + HEADER_H + SECTION_GAP
    section_bottom = section_top + SECTION_H - 1
    section_width = (right - left - SECTION_GAP) // 2
    left_team = C.STRENGTH_TONES["quick"]["line"]
    right_team = C.STRENGTH_TONES["competitive"]["line"]
    for bounds, bucket, fallback, accent in (
        ((left, section_top, left + section_width, section_bottom), minor, "次级威能", C.TEAL),
        ((right - section_width, section_top, right, section_bottom), major, "主要威能", C.MATCH_MODES["competitive"]),
    ):
        _draw_section(
            canvas,
            draw,
            bounds=bounds,
            title=_bucket_title(bucket, fallback),
            bucket=bucket,
            header_accent=accent,
            left_team=left_team,
            right_team=right_team,
        )

    output = BytesIO()
    canvas = append_dashen_promo(canvas)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _page_background(size: tuple[int, int]) -> Any:
    from PIL import Image

    background = build_random_map_background(
        size,
        blur_radius=50,
        overlay=C.PAGE_OVERLAY,
        brightness=C.PAGE_BRIGHTNESS,
        color=C.PAGE_COLOR,
    )
    if background is None:
        return Image.new("RGBA", size, (*C.SCRIM, 255))
    return Image.alpha_composite(background, vertical_scrim(size, 0, C.PAGE_FADE))


def _draw_card_shell(draw: Any, box: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)


def _draw_header(canvas: Any, draw: Any, *, hero: Dict[str, Any], bounds: tuple[int, int, int, int]) -> None:
    from PIL import ImageOps

    left, top, right, bottom = bounds
    _draw_card_shell(draw, bounds)
    avatar_size = 110
    avatar_x = left + 24
    avatar_y = top + (bottom - top - avatar_size) // 2
    hero_icon = _open_cached_asset(hero.get("icon_url"), ("heroes", "misc"))
    if hero_icon is not None:
        fitted = ImageOps.fit(hero_icon, (avatar_size, avatar_size), method=_lanczos())
        canvas.paste(fitted, (avatar_x, avatar_y), smooth_mask(avatar_size, avatar_size, RADIUS_TILE + 4))
    else:
        draw.rounded_rectangle(
            (avatar_x, avatar_y, avatar_x + avatar_size - 1, avatar_y + avatar_size - 1),
            radius=RADIUS_TILE + 4,
            fill=C.SURFACE_RAISED,
        )
        fallback = str(hero.get("hero_name") or "?")[:2]
        draw.text((avatar_x + avatar_size // 2, avatar_y + avatar_size // 2), fallback, font=_ui_font(40, bold=True), fill=C.INK, anchor="mm")
    draw.rounded_rectangle(
        (avatar_x - 1, avatar_y - 1, avatar_x + avatar_size, avatar_y + avatar_size),
        radius=RADIUS_TILE + 5,
        outline=C.STROKE,
        width=1,
    )

    text_x = avatar_x + avatar_size + 28
    hero_name = str(hero.get("hero_name") or "未知英雄")
    draw.text((text_x, top + 52), hero_name, font=_ui_font(50, bold=True), fill=C.INK, anchor="lm")

    role_key = str(hero.get("hero_role") or "").strip().lower()
    role_text = ROLE_LABELS.get(role_key, str(hero.get("hero_role") or "未知职责"))
    role_fill = C.ROLE_COLORS.get(ROLE_THEME_KEYS.get(role_key), C.MUTED)
    chip_right = _draw_role_badge(draw, (text_x, top + 92), role_text, fill=role_fill)
    subrole = get_subrole(hero)
    if subrole:
        draw_subrole_badge(canvas, hero, chip_right + 14, top + 92, 38)
        draw.text((chip_right + 62, top + 111), subrole["displayName"], font=_ui_font(22), fill=C.TEXT, anchor="lm")


def _draw_section(
    canvas: Any,
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    title: str,
    bucket: Dict[str, Any],
    header_accent: tuple[int, ...],
    left_team: tuple[int, ...],
    right_team: tuple[int, ...],
) -> None:
    left, top, right, bottom = bounds
    _draw_card_shell(draw, bounds)
    draw.polygon([(left + 26, top + 20), (left + 34, top + 20), (left + 29, top + 46), (left + 21, top + 46)], fill=header_accent)
    draw.text((left + 46, top + 33), title, font=_ui_font(32, bold=True), fill=C.INK, anchor="lm")
    sample_text = f"样本 { _format_count(bucket.get('sample_count')) }"
    draw.text((right - SECTION_PAD, top + 33), sample_text, font=_ui_font(22), fill=C.TEXT, anchor="rm")

    perks = [item for item in list(bucket.get("perks") or []) if isinstance(item, dict)][:2]
    if not perks:
        draw.text(
            ((left + right) // 2, (top + bottom) // 2),
            "暂无该档位的可用威能数据",
            font=_ui_font(24),
            fill=C.FAINT,
            anchor="mm",
        )
        return

    inner_gap = 18
    card_top = top + SECTION_HEAD
    card_bottom = card_top + PERK_CARD_H - 1
    card_width = (right - left - SECTION_PAD * 2 - inner_gap) // 2
    left_card = (left + SECTION_PAD, card_top, left + SECTION_PAD + card_width, card_bottom)
    right_card = (left_card[2] + inner_gap, card_top, right - SECTION_PAD, card_bottom)

    left_perk = perks[0] if len(perks) > 0 else {}
    right_perk = perks[1] if len(perks) > 1 else {}
    _draw_perk_card(canvas, draw, bounds=left_card, perk=left_perk, team_fill=left_team, header_accent=header_accent)
    if right_perk:
        _draw_perk_card(canvas, draw, bounds=right_card, perk=right_perk, team_fill=right_team, header_accent=header_accent)
    else:
        draw.rounded_rectangle(right_card, radius=RADIUS_TILE + 2, fill=C.SURFACE_SUNKEN, outline=C.STROKE, width=1)
        draw.text(
            ((right_card[0] + right_card[2]) // 2, (right_card[1] + right_card[3]) // 2),
            "暂无第二个威能",
            font=_ui_font(24),
            fill=C.FAINT,
            anchor="mm",
        )

    _draw_duel_bar(
        draw,
        bounds=(left + SECTION_PAD, bottom - 42, right - SECTION_PAD, bottom - 20),
        left_perk=left_perk,
        right_perk=right_perk,
        left_team=left_team,
        right_team=right_team,
    )


def _draw_perk_card(
    canvas: Any,
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    perk: Dict[str, Any],
    team_fill: tuple[int, ...],
    header_accent: tuple[int, ...],
) -> None:
    from PIL import Image

    left, top, right, bottom = bounds
    pad = 20
    draw.rounded_rectangle(bounds, radius=RADIUS_TILE + 2, fill=C.SURFACE_SUNKEN, outline=C.STROKE, width=1)
    draw.rounded_rectangle((left, top, right, top + 6), radius=3, fill=header_accent)

    icon_x, icon_y = left + pad, top + 24
    draw.rounded_rectangle(
        (icon_x, icon_y, icon_x + ICON_BOX - 1, icon_y + ICON_BOX - 1),
        radius=RADIUS_TILE,
        fill=C.PERK_PLATE or C.SURFACE_RAISED,
    )
    plate_x = icon_x + (ICON_BOX - ICON_PLATE) // 2
    plate_y = icon_y + (ICON_BOX - ICON_PLATE) // 2
    perk_bg = _open_local_rgba(PERK_BG_PATH)
    if perk_bg is not None:
        perk_bg = perk_bg.resize((ICON_PLATE, ICON_PLATE), Image.LANCZOS)
        canvas.paste(perk_bg, (plate_x, plate_y), perk_bg)

    perk_icon = _open_cached_asset(perk.get("icon_url"), ("perk", "misc"))
    if perk_icon is not None:
        icon_w, icon_h = _contain_size(perk_icon.width, perk_icon.height, ICON_SIZE, ICON_SIZE)
        perk_icon = perk_icon.resize((icon_w, icon_h), Image.LANCZOS)
        perk_icon = _swap_nearly_white_to_black(perk_icon)
        canvas.paste(perk_icon, (plate_x + (ICON_PLATE - icon_w) // 2, plate_y + (ICON_PLATE - icon_h) // 2), perk_icon)
    else:
        fallback = str(perk.get("name") or "?")[:2]
        draw.text(
            (icon_x + ICON_BOX // 2, icon_y + ICON_BOX // 2),
            fallback,
            font=_ui_font(24, bold=True),
            fill=ICON_TEXT if perk_bg is not None else C.INK,
            anchor="mm",
        )

    name_left = icon_x + ICON_BOX + 18
    name = str(perk.get("name") or "未知威能")
    name_font = _ui_font(29, bold=True)
    name_lines = _wrap_text(draw, name, name_font, max(1, right - name_left - pad), 2, allow_space_join=False)
    name_top = icon_y + ICON_BOX // 2 - (len(name_lines) - 1) * 18
    for index, line in enumerate(name_lines):
        draw.text((name_left, name_top + index * 36), line, font=name_font, fill=C.INK, anchor="lm")

    desc_top = icon_y + ICON_BOX + 22
    desc = str(perk.get("desc") or "暂无描述")
    desc_font = _ui_font(22)
    for index, line in enumerate(_wrap_text(draw, desc, desc_font, max(1, right - left - pad * 2), 5)):
        draw.text((left + pad, desc_top + index * 31), line, font=desc_font, fill=C.TEXT)

    footer_y = bottom - 82
    draw.line((left + pad, footer_y - 12, right - pad, footer_y - 12), fill=C.HAIRLINE, width=1)
    middle = (left + right) // 2
    label_font, value_font = _ui_font(20), _ui_font(32, bold=True)
    draw.text((left + pad, footer_y), "使用数", font=label_font, fill=C.MUTED)
    draw.text((left + pad, footer_y + 28), _format_count(perk.get("pick_count")), font=value_font, fill=team_fill)
    draw.text((middle + 10, footer_y), "使用率", font=label_font, fill=C.MUTED)
    draw.text((middle + 10, footer_y + 28), f"{float(perk.get('pick_rate') or 0.0) * 100:.1f}%", font=value_font, fill=C.INK)


def _draw_duel_bar(
    draw: Any,
    *,
    bounds: tuple[int, int, int, int],
    left_perk: Dict[str, Any],
    right_perk: Dict[str, Any],
    left_team: tuple[int, ...],
    right_team: tuple[int, ...],
) -> None:
    left, top, right, bottom = bounds
    label_y = top - 20
    label_font = _ui_font(26, bold=True)
    left_rate = max(0.0, min(float(left_perk.get("pick_rate") or 0.0), 1.0))
    right_rate = max(0.0, min(float(right_perk.get("pick_rate") or 0.0), 1.0))

    draw.text((left, label_y), f"{left_rate * 100:.1f}%", font=label_font, fill=left_team, anchor="lm")
    draw.text((right, label_y), f"{right_rate * 100:.1f}%", font=label_font, fill=right_team, anchor="rm")

    radius = (bottom - top) // 2
    draw.rounded_rectangle(bounds, radius=radius, fill=C.SURFACE_RAISED)
    bar_width = right - left
    left_width = int(bar_width * left_rate)
    right_width = int(bar_width * right_rate)

    if left_width > 0:
        draw.rounded_rectangle((left, top, left + left_width, bottom), radius=radius, fill=left_team)
    if right_width > 0:
        draw.rounded_rectangle((right - right_width, top, right, bottom), radius=radius, fill=right_team)


def _draw_role_badge(draw: Any, position: tuple[int, int], label: str, *, fill: tuple[int, ...]) -> int:
    x, y = position
    font = _ui_font(22, bold=True)
    height = 38
    width = int(_measure(draw, label, font)[0]) + 36
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill)
    draw.text((x + width // 2, y + height // 2), label, font=font, fill=C.STREAK_TEXT, anchor="mm")
    return x + width


def _lanczos() -> Any:
    from PIL import Image

    return Image.Resampling.LANCZOS


def _ui_font(size: int, *, bold: bool = False) -> Any:
    key = (int(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="simhei.ttf", fallback="en.ttf", prefer_cjk=True, bold=bold)
        if bold and Path(getattr(font, "path", "")).name.lower() == "simhei.ttf":
            font.emulate_bold = True
        _FONT_CACHE[key] = font
    return font


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
    tokens: Iterable[str] = normalized.split(" ") if use_word_tokens else re.findall(r"[0-9]+(?:\.[0-9]+)?%?|.", normalized)
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
