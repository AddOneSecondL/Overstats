from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from ...constants.backgrounds import build_random_map_background

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.query_tool import get_cached_asset_path
    from overstats.src.modules.risk_status import draw_risk_status_badge
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.query_tool import get_cached_asset_path
    from src.modules.risk_status import draw_risk_status_badge

from .engine import ROLE_LABELS


CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
HEADER_HEIGHT = 146
CANVAS_PADDING = 28
GRID_GAP = 4
MIN_TILE_SIDE = 144
MIN_TILE_AREA = MIN_TILE_SIDE * MIN_TILE_SIDE

POSITIVE_FILL = (192, 67, 59)
NEGATIVE_FILL = (38, 176, 105)
NEUTRAL_FILL = (122, 129, 140)
ROLE_FALLBACK_FILLS = {
    "tank": (74, 128, 236),
    "dps": (234, 110, 48),
    "healer": (52, 195, 163),
    "open": (138, 147, 163),
}
ROLE_ICON_FILES = {
    "tank": "tank.png",
    "dps": "dps.png",
    "healer": "healer.png",
}
BASE_TILE_FILL = (18, 23, 32)
TEXT_PRIMARY = (244, 247, 252)
TEXT_SECONDARY = (210, 219, 231)
TEXT_MUTED = (152, 162, 178)


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


@dataclass(frozen=True)
class _Rect:
    x: float
    y: float
    width: float
    height: float


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


def render_hero_treemap(
    *,
    player: Dict[str, Any],
    season: Dict[str, Any],
    mode: str,
    hero_count: int,
    total_game_time_sec: float,
    heroes: Sequence[Dict[str, Any]],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (8, 12, 18, 255))
    background = _build_treemap_background((CANVAS_WIDTH, CANVAS_HEIGHT))
    if background is not None:
        canvas.alpha_composite(background)
    canvas.alpha_composite(_build_canvas_overlay((CANVAS_WIDTH, CANVAS_HEIGHT), has_background=background is not None))
    draw = ImageDraw.Draw(canvas, "RGBA")
    fonts = _load_fonts()

    _draw_header(
        draw,
        player=player,
        season=season,
        mode=mode,
        hero_count=hero_count,
        total_game_time_sec=total_game_time_sec,
        fonts=fonts,
    )

    content_rect = _Rect(
        x=CANVAS_PADDING,
        y=HEADER_HEIGHT + 14,
        width=CANVAS_WIDTH - CANVAS_PADDING * 2,
        height=CANVAS_HEIGHT - HEADER_HEIGHT - CANVAS_PADDING - 14,
    )
    tile_rects = _layout_treemap(heroes, content_rect)
    for hero, rect in zip(heroes, tile_rects):
        _draw_tile(canvas, hero=hero, rect=rect, fonts=fonts)

    output = BytesIO()
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _load_fonts() -> Dict[str, Any]:
    return {
        "header_title": _load_summary_font(38, bold=True),
        "header_meta": _load_summary_font(17, bold=False),
        "header_emphasis": _load_summary_font(18, bold=True),
        "tile_name": _load_summary_font(34, bold=True),
        "tile_role": _load_summary_font(17, bold=False),
        "tile_meta": _load_summary_font(18, bold=False),
        "tile_delta": _load_summary_font(42, bold=True),
        "avatar_fallback": _load_summary_font(28, bold=True),
    }


def _load_summary_font(size: int, *, bold: bool) -> Any:
    return load_font(
        size,
        name="simhei.ttf",
        fallback="en.ttf",
        prefer_cjk=True,
        bold=bold,
    )


def _build_treemap_background(size: tuple[int, int]) -> Any | None:
    background = build_random_map_background(
        size,
        blur_radius=22,
        overlay=(7, 11, 17, 92),
        brightness=0.76,
        color=0.86,
    )
    if background is not None:
        return background
    return _load_local_background(size)


def _load_local_background(size: tuple[int, int]) -> Any | None:
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ModuleNotFoundError:
        return None

    fallback_paths = (
        RESOURCE_DIR / "profilebg.png",
        RESOURCE_DIR / "season_logo" / "bg.png",
    )
    width, height = size
    for path in fallback_paths:
        if not path.exists():
            continue
        try:
            with Image.open(path) as raw_image:
                background = raw_image.convert("RGBA")
        except Exception:
            continue
        try:
            background = ImageOps.fit(
                background,
                (width, height),
                method=_resampling_lanczos(),
                centering=(0.5, 0.5),
            )
        except Exception:
            try:
                background = background.resize((width, height), _resampling_lanczos())
            except Exception:
                continue
        background = ImageEnhance.Color(background).enhance(0.82)
        background = ImageEnhance.Brightness(background).enhance(0.68)
        background = background.filter(ImageFilter.GaussianBlur(radius=20))
        return Image.alpha_composite(background, Image.new("RGBA", (width, height), (7, 11, 17, 104)))
    return None


def _draw_header(
    draw: Any,
    *,
    player: Dict[str, Any],
    season: Dict[str, Any],
    mode: str,
    hero_count: int,
    total_game_time_sec: float,
    fonts: Dict[str, Any],
) -> None:
    box = (CANVAS_PADDING, CANVAS_PADDING, CANVAS_WIDTH - CANVAS_PADDING, HEADER_HEIGHT)
    draw.rounded_rectangle(box, radius=16, fill=(11, 15, 23, 198), outline=(255, 255, 255, 42), width=1)
    draw.line((box[0] + 20, box[1] + 64, box[2] - 20, box[1] + 64), fill=(255, 255, 255, 16), width=1)

    title = "英雄云图"
    display_name = str(player.get("display_name") or "").strip() or "未知玩家"
    season_text = _season_label(season)

    draw.text((box[0] + 24, box[1] + 20), title, font=fonts["header_title"], fill=TEXT_PRIMARY)
    player_x = box[0] + 26
    player_y = box[1] + 74
    draw.text((player_x, player_y), display_name, font=fonts["header_emphasis"], fill=TEXT_SECONDARY)
    player_width = _measure(draw, display_name, fonts["header_emphasis"])[0]
    badge_width, _ = draw_risk_status_badge(
        draw,
        player_x + player_width + 12,
        player_y - 2,
        player.get("risk_status"),
        font=fonts["header_meta"],
        padding_x=9,
        padding_y=4,
    )
    mode_x = player_x + player_width + (badge_width + 24 if badge_width else 12)
    draw.text((mode_x, player_y), f"|  {_mode_label(mode)}", font=fonts["header_emphasis"], fill=TEXT_SECONDARY)
    _draw_header_meta_row(
        draw,
        x=box[0] + 26,
        y=box[1] + 102,
        hero_count=hero_count,
        total_game_time_sec=total_game_time_sec,
        fonts=fonts,
    )

    season_w = _measure(draw, season_text, fonts["header_meta"])[0]
    draw.text((box[2] - 26 - season_w, box[1] + 24), season_text, font=fonts["header_meta"], fill=TEXT_SECONDARY)


def _mode_label(mode: str) -> str:
    return "竞技" if str(mode or "").strip().lower() == "competitive" else "快速"


def _season_label(season: Dict[str, Any]) -> str:
    logical = season.get("logical")
    request = season.get("request")
    if logical in (None, "") and request in (None, ""):
        return "赛季 AUTO"
    if request in (None, ""):
        return f"S{logical}"
    return f"S{logical} / req {request}"


def _format_hours(game_time_sec: float) -> str:
    if game_time_sec <= 0:
        return "0H"
    if game_time_sec < 3600:
        return f"{max(1, int(game_time_sec / 60))}M"
    return f"{game_time_sec / 3600:.1f}H"


def _draw_header_meta_row(
    draw: Any,
    *,
    x: float,
    y: float,
    hero_count: int,
    total_game_time_sec: float,
    fonts: Dict[str, Any],
) -> None:
    cursor_x = x
    runs = (
        ("英雄", TEXT_MUTED, "header_meta"),
        (f" {int(hero_count)}", TEXT_SECONDARY, "header_emphasis"),
        ("  |  ", TEXT_MUTED, "header_meta"),
        ("总时长", TEXT_MUTED, "header_meta"),
        (f" {_format_hours(total_game_time_sec)}", TEXT_SECONDARY, "header_emphasis"),
    )
    for text, fill, font_key in runs:
        font = fonts[font_key]
        draw.text((cursor_x, y), text, font=font, fill=fill)
        cursor_x += _measure(draw, text, font)[0]


def _layout_treemap(heroes: Sequence[Dict[str, Any]], content_rect: _Rect) -> list[_Rect]:
    weights = [max(float(hero.get("game_time_sec") or 0.0), 0.0) for hero in heroes]
    if not weights:
        return []

    areas = _apply_minimum_area(weights, content_rect.width * content_rect.height, MIN_TILE_AREA)
    row_slices = _build_row_slices(areas, content_rect.width)
    rects: list[_Rect] = []
    cursor_y = content_rect.y

    for row_index, row_slice in enumerate(row_slices):
        row_areas = areas[row_slice[0] : row_slice[1]]
        row_area = sum(row_areas)
        if row_area <= 0:
            continue

        remaining_bottom = content_rect.y + content_rect.height
        if row_index == len(row_slices) - 1:
            row_height = max(remaining_bottom - cursor_y, 0.0)
        else:
            row_height = row_area / max(content_rect.width, 1.0)
        if row_height <= 0:
            continue

        cursor_x = content_rect.x
        row_right = content_rect.x + content_rect.width
        for area_index, area in enumerate(row_areas):
            if area_index == len(row_areas) - 1:
                tile_width = max(row_right - cursor_x, 0.0)
            else:
                tile_width = area / row_height
            rects.append(_Rect(cursor_x, cursor_y, tile_width, row_height))
            cursor_x += tile_width

        cursor_y += row_height

    return rects


def _build_row_slices(areas: Sequence[float], row_width: float) -> list[tuple[int, int]]:
    count = len(areas)
    if count <= 0:
        return []

    best_cost = [float("inf")] * (count + 1)
    best_break = [count] * (count + 1)
    best_cost[count] = 0.0

    for start in range(count - 1, -1, -1):
        for end in range(start + 1, count + 1):
            row_score = _row_score(areas[start:end], row_width)
            cost = row_score * row_score + best_cost[end]
            if cost < best_cost[start]:
                best_cost[start] = cost
                best_break[start] = end

    rows: list[tuple[int, int]] = []
    start = 0
    while start < count:
        end = best_break[start]
        if end <= start:
            end = start + 1
        rows.append((start, end))
        start = end
    return rows


def _row_score(row_areas: Sequence[float], row_width: float) -> float:
    if not row_areas or row_width <= 0:
        return float("inf")

    row_height = sum(row_areas) / row_width
    if row_height <= 0:
        return float("inf")

    worst_aspect = 1.0
    for area in row_areas:
        tile_width = area / row_height
        if tile_width <= 0:
            return float("inf")
        aspect = max(tile_width / row_height, row_height / tile_width)
        worst_aspect = max(worst_aspect, aspect)

    ideal_height = sum(area ** 0.5 for area in row_areas) / max(len(row_areas), 1)
    height_aspect = max(row_height / max(ideal_height, 1.0), ideal_height / max(row_height, 1.0))
    return worst_aspect * 0.82 + height_aspect * 0.18


def _apply_minimum_area(weights: Sequence[float], total_area: float, min_area: float) -> list[float]:
    normalized = [max(float(value or 0.0), 0.0) for value in weights]
    if not normalized or total_area <= 0:
        return []

    count = len(normalized)
    raw_total = sum(normalized)
    if raw_total <= 0:
        return [total_area / count for _ in normalized]

    floored_area = min(float(min_area), total_area / count)
    distributable = max(total_area - floored_area * count, 0.0)
    return [
        floored_area + distributable * (value / raw_total)
        for value in normalized
    ]


def _draw_tile(canvas: Any, *, hero: Dict[str, Any], rect: _Rect, fonts: Dict[str, Any]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    left = int(round(rect.x)) + GRID_GAP
    top = int(round(rect.y)) + GRID_GAP
    right = int(round(rect.x + rect.width)) - GRID_GAP
    bottom = int(round(rect.y + rect.height)) - GRID_GAP
    if right - left < 48 or bottom - top < 48:
        return

    width = right - left
    height = bottom - top
    min_side = min(width, height)
    delta = float(hero.get("win_rate_delta") or 0.0)
    accent = _delta_color(delta)
    role_key = str(hero.get("hero_role") or "").strip().lower()
    role_fill = ROLE_FALLBACK_FILLS.get(role_key, ROLE_FALLBACK_FILLS["open"])
    tile_radius = _clamp(min_side // 12, 8, 18)
    header_height = _clamp(int(height * 0.24), 54, 84)
    pad = max(10, min_side // 15)
    avatar_size = _clamp(header_height - pad * 2, 34, 72)
    compact = min_side < 196 or width < 250
    very_compact = min_side < 148 or width < 180

    tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile, "RGBA")
    _fill_tile_background(
        tile_draw,
        width,
        height,
        accent=accent,
        role_fill=role_fill,
        strength=min(abs(delta) / 22.0, 1.0),
        radius=tile_radius,
    )
    tile_draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=tile_radius,
        outline=(255, 255, 255, 38),
        width=1,
    )

    header_box = (0, 0, width - 1, header_height)
    tile_draw.rounded_rectangle(
        header_box,
        radius=max(tile_radius - 2, 8),
        fill=(20, 24, 33, 222),
    )
    tile_draw.rectangle((0, header_height // 2, width - 1, header_height), fill=(20, 24, 33, 222))
    tile_draw.line((0, header_height, width - 1, header_height), fill=(255, 255, 255, 18), width=1)
    tile_draw.rectangle((0, 0, max(3, width // 90), height), fill=(*role_fill, 210))

    avatar_x = pad
    avatar_y = max((header_height - avatar_size) // 2, 8)
    avatar_box = (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size)
    tile_draw.rounded_rectangle(
        avatar_box,
        radius=max(8, avatar_size // 6),
        fill=(255, 255, 255, 18),
        outline=(255, 255, 255, 42),
        width=1,
    )

    icon = _open_cached_asset(hero.get("icon_url"), ("heroes", "misc"))
    if icon is not None:
        inner = ImageOps.fit(icon, (avatar_size - 6, avatar_size - 6), method=_resampling_lanczos())
        mask = Image.new("L", inner.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, inner.size[0], inner.size[1]),
            radius=max(8, inner.size[0] // 6),
            fill=255,
        )
        tile.paste(inner, (avatar_x + 3, avatar_y + 3), mask)
    else:
        _draw_fallback_avatar(tile_draw, hero=hero, box=avatar_box)

    name_x = avatar_box[2] + max(10, pad // 2)
    content_right = width - pad
    name_font = _fit_font(
        tile_draw,
        hero.get("hero_name"),
        _clamp(min_side // (4 if compact else 3), 18, 40),
        max(content_right - name_x - 36, 30),
        bold=True,
    )
    role_font = _load_summary_font(_clamp(int(name_font.size * 0.44), 11, 18), bold=False)
    meta_font = _load_summary_font(_clamp(min_side // 10, 12, 20), bold=False)
    delta_font = _fit_font(
        tile_draw,
        _format_delta(delta),
        _clamp(min_side // (5 if compact else 4), 18, 54),
        max(width - pad * 2, 40),
        bold=True,
    )

    role_icon_size = _clamp(int(name_font.size * 0.72), 14, 22)
    role_icon = _load_role_icon(role_key, role_icon_size)
    role_label = ROLE_LABELS.get(role_key, ROLE_LABELS["open"])

    name_text = _truncate_text(tile_draw, str(hero.get("hero_name") or ""), name_font, max(content_right - name_x - role_icon_size - 10, 26))
    name_y = avatar_y + max((avatar_size - int(_measure(tile_draw, name_text, name_font)[1]) - int(_measure(tile_draw, role_label, role_font)[1]) - 3) // 2, 0)
    tile_draw.text((name_x, name_y), name_text, font=name_font, fill=TEXT_PRIMARY)

    role_icon_x = name_x + _measure(tile_draw, name_text, name_font)[0] + 8
    if role_icon is not None and role_icon_x + role_icon_size <= content_right + 4:
        tile.paste(role_icon, (int(role_icon_x), int(name_y + 2)), role_icon)

    role_y = name_y + _measure(tile_draw, name_text, name_font)[1] + 2
    if not very_compact:
        tile_draw.text((name_x, role_y), role_label, font=role_font, fill=TEXT_SECONDARY)

    delta_text = _format_delta(delta)
    delta_size = _measure(tile_draw, delta_text, delta_font)
    delta_y = _clamp((height - delta_size[1]) / 2, header_height + 12, height - pad - delta_size[1] - 16)
    tile_draw.text(
        ((width - delta_size[0]) / 2, delta_y),
        delta_text,
        font=delta_font,
        fill=accent,
    )

    meta_text = (
        f"{float(hero.get('win_rate') or 0.0):.2f}% / "
        f"{int(hero.get('match_sum') or 0)}场 / "
        f"{str(hero.get('game_time_text') or '')}"
    )
    meta_lines = _wrap_text(tile_draw, meta_text, meta_font, max(width - pad * 2, 40), 2, allow_space_join=False)
    meta_height = sum(int(_measure(tile_draw, line, meta_font)[1]) + 2 for line in meta_lines)
    role_block_bottom = role_y + (_measure(tile_draw, role_label, role_font)[1] if not very_compact else 0)
    meta_y = max(height - pad - meta_height, role_block_bottom + 12)
    for line in meta_lines:
        tile_draw.text((pad, meta_y), line, font=meta_font, fill=TEXT_MUTED)
        meta_y += _measure(tile_draw, line, meta_font)[1] + 2

    canvas.paste(tile, (left, top), tile)


def _draw_fallback_avatar(draw: Any, *, hero: Dict[str, Any], box: tuple[int, int, int, int]) -> None:
    role_key = str(hero.get("hero_role") or "").strip().lower()
    fill = ROLE_FALLBACK_FILLS.get(role_key, ROLE_FALLBACK_FILLS["open"])
    draw.rounded_rectangle(box, radius=max(8, (box[2] - box[0]) // 6), fill=(*fill, 188))
    fallback = str(hero.get("hero_name") or "?")[:2]
    fallback_font = _load_summary_font(_clamp((box[2] - box[0]) // 3, 14, 28), bold=True)
    fallback_box = _measure(draw, fallback, fallback_font)
    draw.text(
        (
            box[0] + ((box[2] - box[0]) - fallback_box[0]) / 2,
            box[1] + ((box[3] - box[1]) - fallback_box[1]) / 2 - 2,
        ),
        fallback,
        font=fallback_font,
        fill=TEXT_PRIMARY,
    )


def _fill_tile_background(
    draw: Any,
    width: int,
    height: int,
    *,
    accent: tuple[int, int, int, int],
    role_fill: tuple[int, int, int],
    strength: float,
    radius: int,
) -> None:
    for y in range(height):
        vertical_ratio = y / max(height - 1, 1)
        mix_ratio = 0.15 + strength * 0.34 + vertical_ratio * 0.12
        color = _mix_color(BASE_TILE_FILL, accent[:3], mix_ratio)
        shadow_mix = _mix_color(color, role_fill, 0.06 + vertical_ratio * 0.08)
        alpha = 226 if y < height * 0.72 else 242
        draw.line((0, y, width, y), fill=(shadow_mix[0], shadow_mix[1], shadow_mix[2], alpha))

    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=radius,
        outline=(255, 255, 255, 10),
        width=1,
    )


def _delta_color(delta: float) -> tuple[int, int, int, int]:
    if delta > 0:
        return (*POSITIVE_FILL, 255)
    if delta < 0:
        return (*NEGATIVE_FILL, 255)
    return (*NEUTRAL_FILL, 255)


def _format_delta(delta: float) -> str:
    if delta > 0:
        return f"+{delta:.2f}%"
    if delta < 0:
        return f"{delta:.2f}%"
    return "0.00%"


def _mix_color(base: Sequence[int], accent: Sequence[int], ratio: float) -> tuple[int, int, int]:
    clamped = max(0.0, min(float(ratio), 1.0))
    return tuple(
        int(base[index] + (accent[index] - base[index]) * clamped)
        for index in range(3)
    )


def _fit_font(draw: Any, text: Any, start_size: int, max_width: int, *, bold: bool) -> Any:
    size = max(start_size, 8)
    while size > 10:
        font = _load_summary_font(size, bold=bold)
        if _measure(draw, str(text or ""), font)[0] <= max_width:
            return font
        size -= 2
    return _load_summary_font(10, bold=bold)


def _measure(draw: Any, text: str, font: Any) -> tuple[float, float]:
    bbox = draw.textbbox((0, 0), str(text or ""), font=font)
    return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])


def _wrap_text(
    draw: Any,
    text: str,
    font: Any,
    max_width: int,
    max_lines: int,
    *,
    allow_space_join: bool = True,
) -> list[str]:
    normalized = " ".join(str(text or "").replace("\n", " ").split())
    if not normalized:
        return [""]
    tokens: Iterable[str]
    separator = ""
    if allow_space_join and " " in normalized:
        tokens = normalized.split(" ")
        separator = " "
    else:
        tokens = list(normalized)

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


def _truncate_text(draw: Any, text: str, font: Any, max_width: int) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if _measure(draw, value, font)[0] <= max_width:
        return value
    trimmed = value
    while trimmed and _measure(draw, f"{trimmed}...", font)[0] > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}..." if trimmed else "..."


def _open_cached_asset(url: Any, categories: Sequence[str]) -> Any | None:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return None

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


@lru_cache(maxsize=12)
def _load_role_icon(role_key: str, size: int) -> Any | None:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return None

    icon_file = ROLE_ICON_FILES.get(role_key)
    if not icon_file:
        return None
    path = RESOURCE_DIR / icon_file
    if not path.exists():
        return None
    try:
        with Image.open(path) as raw:
            image = raw.convert("RGBA").resize((size, size), _resampling_lanczos())
    except Exception:
        return None

    alpha = image.getchannel("A")
    tint = ROLE_FALLBACK_FILLS.get(role_key, ROLE_FALLBACK_FILLS["open"])
    colored = Image.new("RGBA", image.size, (*tint, 0))
    colored.putalpha(alpha)
    return colored


def _build_canvas_overlay(size: tuple[int, int], *, has_background: bool) -> Any:
    from PIL import Image, ImageDraw

    width, height = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    gradient_alpha = 104 if has_background else 146
    stripe_alpha = 10 if has_background else 8

    for y in range(height):
        ratio = y / max(height - 1, 1)
        draw.line(
            (0, y, width, y),
            fill=(
                int(8 + 8 * ratio),
                int(12 + 12 * ratio),
                int(18 + 22 * ratio),
                gradient_alpha,
            ),
        )

    stripe_step = 64
    for offset in range(-height, width + height, stripe_step):
        draw.line((offset, 0, offset + height, height), fill=(255, 255, 255, stripe_alpha), width=1)

    grid_step = 120
    for x in range(0, width, grid_step):
        draw.line((x, 0, x, height), fill=(255, 255, 255, 6), width=1)
    for y in range(0, height, grid_step):
        draw.line((0, y, width, y), fill=(255, 255, 255, 5), width=1)
    return overlay


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")


def _clamp(value: float, lower: int, upper: int) -> int:
    return int(max(lower, min(int(value), upper)))


__all__ = [
    "MIN_TILE_AREA",
    "MIN_TILE_SIDE",
    "RenderedImage",
    "_apply_minimum_area",
    "_layout_treemap",
    "render_hero_treemap",
]
