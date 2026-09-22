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

from .engine import ROLE_LABELS, cloud_summary
from .requests import is_quick
from ..dashen_summary.runtime.summary_typography import SummaryDraw


CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
HEADER_HEIGHT = 190
CANVAS_PADDING = 28
GRID_GAP = 6
MIN_TILE_SIDE = 144
MIN_TILE_AREA = MIN_TILE_SIDE * MIN_TILE_SIDE

POSITIVE_FILL = (101, 221, 178)
NEGATIVE_FILL = (244, 123, 133)
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
    draw = SummaryDraw(canvas, "RGBA", numeric_font_path=RESOURCE_DIR / "GrotaRoundedExtraBold.otf")
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
    draw.text((530, 145), cloud_summary(heroes), font=fonts["header_emphasis"], fill=(239, 191, 94))

    content_rect = _Rect(
        x=CANVAS_PADDING,
        y=HEADER_HEIGHT + 14,
        width=CANVAS_WIDTH - CANVAS_PADDING * 2,
        height=CANVAS_HEIGHT - HEADER_HEIGHT - CANVAS_PADDING - 54,
    )
    tile_rects = _layout_treemap(heroes, content_rect)
    for hero, rect in zip(heroes, tile_rects):
        _draw_tile(canvas, hero=dict(hero, time_share=float(hero.get("game_time_sec") or 0) / max(total_game_time_sec, 1)), rect=rect, fonts=fonts)

    draw.text((36, CANVAS_HEIGHT - 34), "模式参数：quick 快速 · competitive 竞技 · quick6v6 快速6v6 · competitive6v6 竞技6v6", font=fonts["header_meta"], fill=TEXT_MUTED)
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
    draw.rounded_rectangle((28, 28, CANVAS_WIDTH-28, HEADER_HEIGHT), radius=20, fill=(17, 26, 39, 240), outline=(78, 99, 127, 110))
    draw.rounded_rectangle((48, 50, 53, 96), radius=2, fill=(239, 191, 94))
    draw.text((70, 46), "英雄云图", font=fonts["header_title"], fill=TEXT_PRIMARY)
    display_name = _truncate_text(draw, str(player.get("display_name") or "未知玩家"), fonts["header_emphasis"], 650)
    draw.text((72, 106), display_name, font=fonts["header_emphasis"], fill=TEXT_SECONDARY)
    name_width = _measure(draw, display_name, fonts["header_emphasis"])[0]
    draw_risk_status_badge(draw, 84 + name_width, 104, player.get("risk_status"), font=fonts["header_meta"], padding_x=9, padding_y=4)
    if not is_quick(mode):
        try:
            from PIL import Image, ImageOps
            with Image.open(RESOURCE_DIR / "comp.png") as raw:
                mode_icon = ImageOps.contain(raw.convert("RGBA"), (22, 22), method=_resampling_lanczos())
            draw._image.paste(mode_icon, (72, 145), mode_icon)
        except (OSError, ValueError):
            pass
    else:
        draw.polygon([(84,145),(76,157),(82,157),(79,167),(93,153),(85,153)], fill=(112,204,226))
    draw.text((104, 145), f"{_mode_label(mode)}  /  {_season_label(season)}", font=fonts["header_meta"], fill=(125, 186, 231))
    for x, value, label, color in ((1160, str(hero_count), "使用英雄", (125, 186, 231)), (1485, _format_hours(total_game_time_sec), "英雄累计时长", (239, 191, 94))):
        draw.line((x-35, 61, x-35, 151), fill=(72, 89, 113, 130), width=1)
        draw.text((x, 60), value, font=_load_summary_font(44, bold=True), fill=color)
        draw.text((x+2, 124), label, font=fonts["header_meta"], fill=TEXT_MUTED)


def _mode_label(mode: str) -> str:
    return ("快速" if is_quick(mode) else "竞技") + (" 6v6" if mode.endswith("6v6") else " 5v5")


def _season_label(season: Dict[str, Any]) -> str:
    logical = season.get("logical")
    request = season.get("request")
    if logical in (None, "") and request in (None, ""):
        return "赛季 AUTO"
    if request in (None, ""):
        return f"S{logical}"
    return f"S{logical if logical is not None else request}"


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

    left, top = round(rect.x) + GRID_GAP, round(rect.y) + GRID_GAP
    width, height = round(rect.x + rect.width) - GRID_GAP - left, round(rect.y + rect.height) - GRID_GAP - top
    if min(width, height) < 32:
        return
    pad = 14 if width < 230 else 22
    compact = width < 230 or height < 230
    accent = _delta_color(float(hero.get("win_rate_delta") or 0))
    role = str(hero.get("hero_role") or "open")
    role_color = ROLE_FALLBACK_FILLS.get(role, ROLE_FALLBACK_FILLS["open"])
    tile = Image.new("RGBA", (width, height), (20, 30, 44, 255))
    icon = _open_cached_asset(hero.get("icon_url"), ("heroes", "misc", "summary"))
    if icon is not None:
        portrait_size = max(100, min(height, int(width * .8)))
        portrait = ImageOps.contain(icon, (portrait_size, portrait_size), method=_resampling_lanczos())
        # Fade the portrait edges so square source assets blend into the card.
        alpha = portrait.getchannel("A")
        fade = Image.new("L", portrait.size)
        fd = ImageDraw.Draw(fade)
        for y in range(portrait.height):
            edge = min(1.0, y / max(portrait.height * .12, 1), (portrait.height-1-y) / max(portrait.height * .16, 1))
            fd.line((0,y,portrait.width,y), fill=int(255*max(edge,0)))
        from PIL import ImageChops
        portrait.putalpha(ImageChops.multiply(alpha, fade))
        tile.alpha_composite(portrait, (width - portrait.width + portrait.width // 8, max(0, (height-portrait.height)//2)))
    shade = Image.new("RGBA", tile.size)
    sd = ImageDraw.Draw(shade)
    for x in range(width):
        alpha = int(245 - 110 * x/max(width-1, 1))
        sd.line((x, 0, x, height), fill=(15, 24, 38, alpha))
    tile.alpha_composite(shade)
    draw = SummaryDraw(tile, "RGBA", numeric_font_path=RESOURCE_DIR / "GrotaRoundedExtraBold.otf")
    draw.line((pad, 0, min(width-pad, pad+72), 0), fill=role_color, width=5)
    role_icon = _load_role_icon(role, 18)
    if role_icon is not None:
        tile.alpha_composite(role_icon, (pad, pad+2))
    draw.text((pad+26, pad), ROLE_LABELS.get(role, "开放"), font=_load_summary_font(14, bold=False), fill=role_color)
    name = str(hero.get("hero_name") or "未知英雄")
    name_font = _fit_font(draw, name, 24 if compact else 36, width-pad*2, bold=True)
    draw.text((pad, pad+29), _truncate_text(draw, name, name_font, width-pad*2), font=name_font, fill=TEXT_PRIMARY)
    number_size = min(64, max(24, int(min(width*.23, height*.16))))
    rate_font = _fit_font(draw, f"{float(hero.get('win_rate') or 0):.1f}%", number_size, width-pad*2, bold=True)
    rate_y = pad+62 if height>=190 else pad+52
    draw.text((pad, rate_y), f"{float(hero.get('win_rate') or 0):.1f}%", font=rate_font, fill=accent)
    if width>=270:
        rate_width=_measure(draw, f"{float(hero.get('win_rate') or 0):.1f}%", rate_font)[0]
        if rate_width+pad+40<width-pad:
            draw.text((pad+rate_width+10, rate_y+rate_font.size-19), "胜率", font=_load_summary_font(14,bold=False), fill=TEXT_MUTED)
    kda=hero.get("kda")
    kda_text=f"{kda:.2f}" if kda is not None else "--"
    combat=hero.get("combat") or []
    if kda is None and len(combat)==3 and combat[2]["value"]==0 and combat[0]["value"]+combat[1]["value"]>0:
        kda_text="∞"
    kda_y=rate_y+rate_font.size+7
    kda_font=_load_summary_font(13 if height<190 or width<180 else 19,bold=True)
    draw.text((pad,kda_y),f"KDA {kda_text}",font=kda_font,fill=(238,204,129))
    meta_font = _load_summary_font(12 if compact else 17, bold=False)
    perks=list(hero.get("recent_perks") or [])
    footer_lines=2 if height>=360 or (height>=250 and not perks) else 1
    footer_y=height-pad-footer_lines*23
    if footer_y>kda_y+kda_font.size+7:
        meta=f"{_format_hours(float(hero.get('game_time_sec') or 0))} · {int(hero.get('match_sum') or 0)}场"
        draw.text((pad,footer_y),_truncate_text(draw,meta,meta_font,width-pad*2),font=meta_font,fill=TEXT_SECONDARY)
        if footer_lines==2:
            draw.text((pad,footer_y+24),f"时长占比 {float(hero.get('time_share') or 0)*100:.1f}%",font=_load_summary_font(12 if compact else 15,bold=False),fill=TEXT_MUTED)
    detail_y=kda_y+kda_font.size+(12 if perks else 24)
    detail_bottom=footer_y-14
    max_lines=7 if width>=500 else 4 if width>=300 else 2 if width>=200 else 0
    details=[]
    if combat and width>=300:
        details.append((f"{combat[0]['unit']}  " + " / ".join(f"{v['label']} {v['value']:.1f}" for v in combat),TEXT_SECONDARY))
    stats=list(hero.get("special_stats") or [])
    perks=list(hero.get("recent_perks") or [])
    perk_height=36
    side_by_side=width>=400 and len(perks)>1
    perk_slots=(min(len(perks),2) if detail_bottom-detail_y>=perk_height else 0) if side_by_side else min(len(perks),max(0,(detail_bottom-detail_y)//perk_height)) if width>=180 else 0
    perk_space=perk_height if side_by_side and perk_slots else perk_slots*perk_height
    available=min(max_lines,max(0,(detail_bottom-detail_y-perk_space)//29))
    stat_limit=max(0,available-len(details))
    for stat in stats[:stat_limit]:
        label=stat['label']; value=stat['value']
        unit="%" if "率" in label else ""
        suffix="" if unit else f" /{stat['unit']}"
        details.append((f"{label}  {value*100 if unit else value:.1f}{unit}{suffix}",TEXT_SECONDARY))
    if details and available:
        draw.line((pad,detail_y-10,min(width-pad,pad+460),detail_y-10),fill=(71,88,110,160))
    for label,color in details[:available]:
        font=_load_summary_font(16 if width>=500 else 14,bold=False)
        draw.text((pad,detail_y),_truncate_text(draw,label,font,width-pad*2),font=font,fill=color)
        detail_y+=29
    for perk_index,perk in enumerate(perks[:perk_slots]):
        perk_left=pad+perk_index*((width-pad*2)//2) if side_by_side else pad
        perk_right=perk_left+(width-pad*2)//2-8 if side_by_side else width-pad
        icon=_open_cached_asset(perk.get("icon_url"), ("heroes","perk","misc"))
        if icon is not None:
            icon=ImageOps.contain(icon,(30,30),method=_resampling_lanczos())
            tile.alpha_composite(icon,(perk_left,detail_y+3))
        else:
            draw.polygon([(perk_left+15,detail_y+3),(perk_left+28,detail_y+16),(perk_left+15,detail_y+29),(perk_left+2,detail_y+16)],outline=(186,172,230))
        text_x=perk_left+38
        name=str(perk.get("name") or "未知威能")
        name_font=_fit_font(draw,name,16,perk_right-text_x,bold=True)
        draw.text((text_x,detail_y),name,font=name_font,fill=(216,206,246))
        tier="次级" if perk["level"]==1 else "主要"
        draw.text((text_x,detail_y+21),f"近期{tier} · {perk['pick_count']}/{perk['sample_count']}次",font=_load_summary_font(11,bold=False),fill=TEXT_MUTED)
        if not side_by_side:detail_y+=perk_height
    mask = Image.new("L", tile.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,width-1,height-1), radius=14, fill=255)
    draw.rounded_rectangle((0,0,width-1,height-1), radius=14, outline=(88,109,135,100), width=1)
    canvas.paste(tile, (left, top), mask)


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
