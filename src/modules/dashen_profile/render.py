from __future__ import annotations

from ..map_modes import draw_map_mode_icon

from ..subroles import draw_subrole_badge, get_subrole

from ..dashen_promo import append_dashen_promo

from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import time
from typing import Any, Dict, Sequence

try:
    from overstats.src.constants.backgrounds import build_random_map_background
    from overstats.src.modules.query_tool import get_cached_asset_path, load_query_tool
except ModuleNotFoundError:
    from src.constants.backgrounds import build_random_map_background
    from src.modules.query_tool import get_cached_asset_path, load_query_tool

try:
    from overstats.src.modules.font_resolver import load_font, resolve_resource_dir
    from overstats.src.modules.risk_status import draw_risk_status_badge
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font, resolve_resource_dir
    from src.modules.risk_status import draw_risk_status_badge

try:
    from overstats.src.constants.ranks import get_rank_name, get_rank_score, get_rank_sub_tier, rank_info_to_icon_level, rank_name_to_icon_level
except ModuleNotFoundError:
    from src.constants.ranks import get_rank_name, get_rank_score, get_rank_sub_tier, rank_info_to_icon_level, rank_name_to_icon_level

from ..dashen_summary.runtime.summary_style import (
    C,
    RADIUS_CARD,
    RADIUS_CHIP,
    RADIUS_TILE,
    horizontal_scrim,
    mix,
    sticker_outline,
    themed,
    tinted,
    vertical_scrim,
    with_alpha,
)
from ..dashen_summary.runtime.summary_typography import SmoothDraw, smooth_mask
from .engine import HeroBillboardEntry, HeroUsageRow, ProfileRenderContext, RolePanelEntry


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESOURCE_DIR = resolve_resource_dir()
QUERY_TOOL_ASSET_DIR = RESOURCE_DIR / "query_tool_assets"
ROLE_ICON_FILENAMES = {
    "tank": "tank.png",
    "dps": "dps.png",
    "healer": "healer.png",
}

STR_NO_TITLE = "无头衔"
STR_INFO_SWITCH_MODE = "[INFO] 在指令后附加*号可切换为查询竞技模式比赛数据"
STR_WEEK_COMMENT = "本周表现"
STR_HONOR = "点赞/被赞"
STR_REPORTED = "被举报"
STR_ROLE_TANK = "重装"
STR_ROLE_DPS = "输出"
STR_ROLE_HEALER = "支援"
STR_ROLE_OPEN = "开放"
STR_RANK_SUFFIX = "强"
STR_LEVEL_SUFFIX = "级"
STR_LEFTOVER_OPEN = "开放地区百强未列出部分"
STR_LEFTOVER_PRESET = "预设百强未列出部分"
STR_UNKNOWN_MAP = "未知地图"
STR_STAT_KILL = "消灭"
STR_STAT_DAMAGE = "伤害"
STR_STAT_CURE = "治疗"
STR_STAT_RESIST = "抵挡"
STR_STAT_SURVIVE = "生存"
STR_STAT_DEATH = "阵亡"
STR_STAT_AVG = "均"
STR_STAT_RECENT = "近"
STR_STAT_SERVER = "服"
STR_STATS_TITLE = "数据概览"
PAGE_W = 2560
PAGE_MARGIN = 40
PAGE_BOTTOM = 32
SECTION_GAP = 20
COL_A = (40, 820)
COL_B = (880, 800)
COL_C = (1700, 820)
HEADER_H = 192
CARD_HEAD = 66
STATS_CARD_H = 496
TOP_HEROES_CARD_H = 330
ROLE_HEAD = 66
ROLE_ROW_PITCH = 72
ROLE_ROW_PITCH_MAX = 84
USAGE_ROW_PITCH = 50
RECENT_ROW_PITCH = 40
BILLBOARD_LABEL_H = 36
BILLBOARD_MIN_H = 150
# Roomiest first; each step fits more chips into the same card.
BILLBOARD_DENSITIES = (
    {"chip_w": 172, "row_h": 46, "font": 23},
    {"chip_w": 136, "row_h": 42, "font": 21},
    {"chip_w": 112, "row_h": 38, "font": 19},
    {"chip_w": 94, "row_h": 34, "font": 17},
)
HERO_ROW_LIMIT = 10
PROVINCE_RANK_LIMIT = 4
RECENT_MATCH_LIMIT = 24
_FONT_CACHE: Dict[Any, Any] = {}
_MAP_COVER_CACHE: Dict[Any, Any] = {}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")


def _resize_image(image: Any, size: tuple[int, int]) -> Any:
    return image.resize(size, _resampling_lanczos())


def _cover_fit(image: Any, size: tuple[int, int]) -> Any:
    from PIL import ImageOps

    return ImageOps.fit(image, size, method=_resampling_lanczos())


def _rounded_mask(size: int, radius: float) -> Any:
    return smooth_mask(size, size, radius)


def _paste_circle(canvas: Any, draw: Any, image: Any, x: int, y: int, size: int, ring_color: Any, ring_width: float) -> None:
    fitted = _cover_fit(image.convert("RGBA"), (size, size))
    canvas.paste(fitted, (x, y), _rounded_mask(size, size / 2))
    draw.ellipse((x - 1, y - 1, x + size, y + size), outline=ring_color, width=ring_width)


def _readable_hero_color(color: Any) -> tuple[int, int, int]:
    """Hero colours run very dark or very pale; pull them toward the page's text colour."""
    red, green, blue = color[:3]
    return mix(C.INK, (red, green, blue), .22)


def _fit_ui_font(draw: Any, text: str, max_width: int, largest: int, smallest: int, *, bold: bool = False) -> Any:
    for size in range(largest, smallest - 1, -1):
        font = _ui_font(size, bold=bold)
        if _measure_text_width(draw, text, font) <= max_width:
            return font
    return _ui_font(smallest, bold=bold)


def _paste_map_cover(canvas: Any, box: tuple[int, int, int, int], map_info: Dict[str, Any], radius: int, scrim: tuple[int, ...]) -> bool:
    from PIL import Image

    icon_url = str(map_info.get("icon") or "").strip()
    width, height = box[2] - box[0], box[3] - box[1]
    if not icon_url:
        return False
    key = (icon_url, width, height, scrim, C.NAME)
    cover = _MAP_COVER_CACHE.get(key)
    if cover is None:
        local_path = _find_cached_asset_path(icon_url, category="maps")
        if local_path is None or not local_path.exists():
            return False
        try:
            with Image.open(local_path) as source:
                cover = _cover_fit(source.convert("RGBA"), (width, height))
        except Exception:
            return False
        cover = Image.alpha_composite(cover, horizontal_scrim(cover.size, scrim))
        if len(_MAP_COVER_CACHE) >= 256:
            _MAP_COVER_CACHE.clear()
        _MAP_COVER_CACHE[key] = cover
    canvas.paste(cover, box[:2], smooth_mask(width, height, radius))
    return True


def _draw_avatar(canvas: Any, draw: Any, avatar_bytes: bytes | None, position: tuple[int, int], size: int) -> None:
    from PIL import Image

    x, y = position
    pasted = False
    if avatar_bytes:
        try:
            avatar = _cover_fit(Image.open(BytesIO(avatar_bytes)).convert("RGBA"), (size, size))
            canvas.paste(avatar, position, _rounded_mask(size, 18))
            pasted = True
        except Exception:
            pass
    if not pasted:
        draw.rounded_rectangle((x, y, x + size - 1, y + size - 1), radius=18, fill=C.SURFACE_RAISED)
    draw.rounded_rectangle((x - 4, y - 4, x + size + 3, y + size + 3), radius=21, outline=C.ACCENT, width=3)


def _load_role_icon(role_type: Any, *, size: tuple[int, int]) -> Any | None:
    from PIL import Image

    filename = ROLE_ICON_FILENAMES.get(_normalize_role_type(role_type))
    path = RESOURCE_DIR / filename if filename else None
    if path is None or not path.exists():
        return None
    try:
        with Image.open(path) as raw_image:
            icon = raw_image.convert("RGBA")
    except Exception:
        return None
    if C.ROLE_ICON:
        inked = Image.new("RGBA", icon.size, (*C.ROLE_ICON, 255))
        inked.putalpha(icon.getchannel("A"))
        icon = inked
    return _resize_image(icon, size)


@themed
def render_profile_summary(context: ProfileRenderContext) -> RenderedImage:
    config = _load_ow_config()
    hero_rows = list(context.hero_rows)[:HERO_ROW_LIMIT]
    matches = list(context.recent_matches)[:RECENT_MATCH_LIMIT]
    open_billboards = list(context.leftover_open_billboards)
    preset_billboards = list(context.leftover_preset_billboards)

    # Columns stack independently and loosen their rows to reach a shared bottom edge.
    wide_middle = not matches
    middle_w = COL_C[0] + COL_C[1] - COL_B[0] if wide_middle else COL_B[1]
    usage_lines = max(1, len(hero_rows))
    recent_lines = max(1, len(matches))
    left_natural = STATS_CARD_H + SECTION_GAP + CARD_HEAD + usage_lines * USAGE_ROW_PITCH + 14
    middle_fixed = TOP_HEROES_CARD_H + SECTION_GAP + ROLE_HEAD + 4 * ROLE_ROW_PITCH + 14
    right_natural = CARD_HEAD + recent_lines * RECENT_ROW_PITCH + 14 if matches else 0
    billboard_room = max(left_natural, right_natural, middle_fixed + SECTION_GAP + BILLBOARD_MIN_H) - middle_fixed - SECTION_GAP
    billboard_layout = _billboard_layout(open_billboards, preset_billboards, middle_w, billboard_room)
    billboard_h = billboard_layout["height"] if billboard_layout else 0
    middle_natural = middle_fixed + (SECTION_GAP + billboard_h if billboard_h else 0)
    columns_h = max(left_natural, middle_natural, right_natural)
    usage_pitch = min(72, USAGE_ROW_PITCH + (columns_h - left_natural) // usage_lines)
    recent_pitch = min(58, RECENT_ROW_PITCH + (columns_h - right_natural) // recent_lines)
    # Middle cards keep their own height; without leaderboards they sit centred.
    middle_spare = columns_h - middle_natural
    role_pitch = min(ROLE_ROW_PITCH_MAX, ROLE_ROW_PITCH + middle_spare // 4)
    role_h = ROLE_HEAD + 4 * ROLE_ROW_PITCH + 14 + min(4 * (ROLE_ROW_PITCH_MAX - ROLE_ROW_PITCH), middle_spare)

    header_top = 28
    body_top = header_top + HEADER_H + SECTION_GAP
    height = body_top + columns_h + PAGE_BOTTOM

    canvas = _page_background((PAGE_W, height))
    draw = SmoothDraw(
        canvas,
        "RGBA",
        numeric_font_path=RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
        latin_font_path=RESOURCE_DIR / "en2.ttf",
    )

    _draw_header(canvas, draw, config, context, matches, header_top)

    left_x, left_w = COL_A
    _draw_stats_card(canvas, draw, context.selected_payload, left_x, body_top, left_w)
    usage_top = body_top + STATS_CARD_H + SECTION_GAP
    _draw_hero_usage_card(
        canvas,
        draw,
        config,
        hero_rows,
        (left_x, usage_top, left_x + left_w - 1, body_top + columns_h - 1),
        hero_title=context.hero_title,
        quick_mode=context.quick_mode,
        pitch=usage_pitch,
    )

    middle_x = COL_B[0]
    middle_top = body_top
    if not billboard_h:
        middle_top += (columns_h - TOP_HEROES_CARD_H - SECTION_GAP - role_h) // 2
    _draw_top_heroes_card(canvas, draw, config, context.top_heroes, middle_x, middle_top, middle_w)
    role_top = middle_top + TOP_HEROES_CARD_H + SECTION_GAP
    role_bottom = role_top + role_h
    _draw_role_card(canvas, draw, context.role_entries, (middle_x, role_top, middle_x + middle_w - 1, role_bottom - 1), pitch=role_pitch)
    if billboard_h:
        _draw_billboard_card(
            canvas,
            draw,
            config,
            billboard_layout,
            (middle_x, role_bottom + SECTION_GAP, middle_x + middle_w - 1, body_top + columns_h - 1),
        )

    if matches:
        right_x, right_w = COL_C
        _draw_recent_match_card(canvas, draw, config, matches, (right_x, body_top, right_x + right_w - 1, body_top + columns_h - 1), pitch=recent_pitch)

    output = BytesIO()
    image = append_dashen_promo(canvas, compact=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)
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


def _ui_font(size: int, *, bold: bool = False) -> Any:
    key = ("ui", int(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="simhei.ttf", fallback="en.ttf", prefer_cjk=True, bold=bold)
        if bold and Path(getattr(font, "path", "")).name.lower() == "simhei.ttf":
            font.emulate_bold = True
        _FONT_CACHE[key] = font
    return font


def _plain_font(size: int) -> Any:
    key = ("plain", int(size))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="simhei.ttf", fallback="en.ttf", prefer_cjk=True)
        font.keep_face = True
        _FONT_CACHE[key] = font
    return font


def _display_font(size: int, *, oblique: bool = True) -> Any:
    key = ("display", int(size), bool(oblique))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="bignoodletoooblique.ttf" if oblique else "BigNoodleToo.ttf")
        font.keep_face = True
        _FONT_CACHE[key] = font
    return font


def _card(draw: Any, box: tuple[int, int, int, int], title: str, *, display: bool = True) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)
    draw.polygon([(x1 + 26, y1 + 21), (x1 + 34, y1 + 21), (x1 + 29, y1 + 47), (x1 + 21, y1 + 47)], fill=C.ACCENT)
    font = _display_font(38) if display else _ui_font(29, bold=True)
    draw.text((x1 + 46, y1 + 34), title, font=font, fill=C.INK, anchor="lm")


def _draw_header(canvas: Any, draw: Any, config: Dict[str, Any], context: ProfileRenderContext, matches: Sequence[Dict[str, Any]], top: int) -> None:
    left, right = PAGE_MARGIN, PAGE_W - PAGE_MARGIN
    bottom = top + HEADER_H
    box = (left, top, right, bottom)
    banner_map = _find_map(config, matches[0].get("mapGuid")) if matches else {}
    if not _paste_map_cover(canvas, box, banner_map, RADIUS_CARD + 4, C.PROFILE_BANNER_SCRIM):
        draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS_CARD + 4, fill=C.SURFACE)
    draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS_CARD + 4, outline=C.STROKE, width=1)

    _draw_avatar(canvas, draw, context.avatar_bytes, (left + 26, top + 24), 146)
    name_right = _draw_name_block(
        canvas,
        draw,
        config,
        battletag=context.battletag,
        battlenum=context.battlenum,
        title=context.title,
        level=context.level,
        risk_status=context.risk_status,
        left=left + 202,
        top=top,
    )

    time_x = max(1230, name_right + 40)
    draw.text((time_x, top + 40), "TIME PLAYED", font=_display_font(34), fill=C.MUTED, anchor="lm")
    hours = f"{int(context.game_time):,}"
    draw.text((time_x, top + 112), hours, font=_display_font(92), fill=C.INK, anchor="lm")
    hours_w = _measure_text_width(draw, hours, _display_font(92))
    draw.text((time_x + hours_w + 14, top + 124), "HRS", font=_display_font(44), fill=C.ACCENT, anchor="lm")

    _draw_province_rank(canvas, draw, context.selected_payload, top, time_x + hours_w + 110)


def _draw_name_block(
    canvas: Any,
    draw: Any,
    config: Dict[str, Any],
    *,
    battletag: str,
    battlenum: str,
    title: str,
    level: int,
    risk_status: Any,
    left: int,
    top: int,
) -> int:
    if battletag.isascii():
        display_name = battletag.upper()
        name_font = _display_font(96)
    else:
        display_name = battletag
        name_font = _ui_font(70, bold=True)
    display_name = _truncate_text_to_width(draw, display_name, 800, name_font)
    draw.text((left, top + 64), display_name, font=name_font, fill=C.INK, anchor="lm")
    name_w = _measure_text_width(draw, display_name, name_font)
    cursor = left + name_w + 18

    if battlenum:
        tag = f"#{battlenum}"
        draw.text((cursor, top + 80), tag, font=_display_font(34), fill=C.MUTED, anchor="lm")
        cursor += _measure_text_width(draw, tag, _display_font(34)) + 18

    badge_width, _ = draw_risk_status_badge(
        draw,
        cursor,
        top + 48,
        risk_status,
        font=_ui_font(24, bold=True),
        padding_x=11,
        padding_y=5,
    )
    if badge_width:
        cursor += badge_width + 14

    if level > 0:
        icon = _load_appreciation_icon(config, level)
        if icon is not None:
            icon = _resize_image(icon, (64, 64))
            canvas.paste(icon, (cursor, top + 30), icon)
            cursor += 76

    if title and title != STR_NO_TITLE:
        draw.text((left + 2, top + 126), title, font=_ui_font(26), fill=C.TEXT, anchor="lm")
    draw.text((left + 2, top + 164), STR_INFO_SWITCH_MODE, font=_ui_font(18), fill=C.FAINT, anchor="lm")
    return cursor


def _draw_province_rank(canvas: Any, draw: Any, payload_data: Dict[str, Any], top: int, left_limit: int) -> None:
    rows = _list_dicts(payload_data.get("userProvinceRankList"))[:PROVINCE_RANK_LIMIT]
    if not rows:
        return
    right = PAGE_W - PAGE_MARGIN - 26
    gap = 10
    columns = 2 if len(rows) > 2 else 1
    tile_w = min(380, (right - max(left_limit, right - 780) - gap * (columns - 1)) // columns)
    tile_h = 76
    grid_h = tile_h * ((len(rows) + columns - 1) // columns) + gap * ((len(rows) - 1) // columns)
    grid_top = top + (HEADER_H - grid_h) // 2
    grid_left = right - tile_w * columns - gap * (columns - 1)
    for index, item in enumerate(rows):
        row, column = divmod(index, columns)
        x = grid_left + column * (tile_w + gap)
        y = grid_top + row * (tile_h + gap)
        role_type = _normalize_role_type(item.get("roleType"))
        role_name = {
            "tank": STR_ROLE_TANK,
            "dps": STR_ROLE_DPS,
            "healer": STR_ROLE_HEALER,
        }.get(role_type, STR_ROLE_OPEN)
        province = str(item.get("province") or "")
        rank_num = _safe_int(item.get("rankNum"))
        draw.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=RADIUS_TILE + 2, fill=C.SURFACE_RAISED, outline=with_alpha(C.DRAW, 120), width=1)
        draw.rounded_rectangle((x, y + 12, x + 5, y + tile_h - 12), radius=2.5, fill=C.DRAW)
        text_x = x + 20
        role_icon = _load_role_icon(role_type, size=(30, 30))
        if role_icon is not None:
            canvas.paste(role_icon, (text_x, y + tile_h // 2 - 15), role_icon)
        text_x += 42
        rank_text = f"#{rank_num}{STR_RANK_SUFFIX}"
        rank_font = _fit_ui_font(draw, rank_text, tile_w // 2 - 20, 34, 22, bold=True)
        draw.text((x + tile_w - 16, y + tile_h // 2), rank_text, font=rank_font, fill=C.DRAW, anchor="rm")
        label_room = tile_w - 16 - _measure_text_width(draw, rank_text, rank_font) - 12 - (text_x - x)
        label = f"{province}{role_name}"
        label_font = _fit_ui_font(draw, label, label_room, 27, 18)
        draw.text((text_x, y + tile_h // 2), _truncate_text_to_width(draw, label, label_room, label_font), font=label_font, fill=C.INK, anchor="lm")


def _draw_stats_card(canvas: Any, draw: Any, payload_data: Dict[str, Any], x: int, y: int, width: int) -> None:
    _card(draw, (x, y, x + width - 1, y + STATS_CARD_H - 1), STR_STATS_TITLE, display=False)

    series = ((STR_STAT_AVG, C.ACCENT), (STR_STAT_RECENT, C.INFO), (STR_STAT_SERVER, C.MUTED))
    legend_font = _ui_font(18)
    cursor = x + width - 28
    for label, color in reversed(series):
        cursor -= _measure_text_width(draw, label, legend_font)
        draw.text((cursor, y + 34), label, font=legend_font, fill=C.TEXT, anchor="lm")
        cursor -= 22
        draw.rounded_rectangle((cursor, y + 27, cursor + 14, y + 41), radius=4, fill=color)
        cursor -= 18

    summary = payload_data.get("presetsSummaryData")
    if not isinstance(summary, dict) or not summary:
        summary = payload_data.get("openSummaryData") if isinstance(payload_data.get("openSummaryData"), dict) else {}
    server = summary.get("serverMapCountData") if isinstance(summary.get("serverMapCountData"), dict) else {}
    recent = payload_data.get("recentMatchCount") if isinstance(payload_data.get("recentMatchCount"), dict) else {}

    radar_data = {
        "kill": (recent.get("aveKill", 0), server.get("maxKill", 1), STR_STAT_KILL),
        "damage": (recent.get("aveDamage", 0), server.get("maxDamage", 1), STR_STAT_DAMAGE),
        "cure": (recent.get("aveCure", 0), server.get("maxCure", 1), STR_STAT_CURE),
        "resist": (recent.get("aveResistDamage", 0), server.get("maxResistDamage", 1), STR_STAT_RESIST),
        "death": (recent.get("aveDeath", 0), server.get("maxDeath", 1), STR_STAT_SURVIVE),
    }

    labels: list[tuple[str, Any, Any, Any, Any]] = [
        (STR_STAT_KILL, summary.get("aveKill", 0), recent.get("aveKill", 0), server.get("kill", 0), (server.get("maxKill") or 1) * 1.2),
        (STR_STAT_DAMAGE, summary.get("aveHeroDamage", 0), recent.get("aveDamage", 0), server.get("damage", 0), (server.get("maxDamage") or 1) * 1.1),
        (STR_STAT_CURE, summary.get("aveCure", 0), recent.get("aveCure", 0), server.get("cure", 0), (server.get("maxCure") or 1) * 1.1),
        (STR_STAT_RESIST, summary.get("aveResistDamage", 0), recent.get("aveResistDamage", 0), server.get("resistDamage", 0), (server.get("maxResistDamage") or 1) * 1.1),
    ]
    curr_y = y + CARD_HEAD
    for label, val_ave, val_recent, val_server, val_max in labels:
        _draw_stat_group(draw, x + 26, curr_y, label, val_ave, val_recent, val_server, val_max, series)
        curr_y += 72

    _draw_radar_chart(draw, x + 646, y + 208, 106, radar_data)
    _draw_week_action(draw, payload_data, x, y + STATS_CARD_H, width)


def _draw_stat_group(
    draw: Any,
    x: int,
    y_base: int,
    label_txt: str,
    val_ave: Any,
    val_recent: Any,
    val_server: Any,
    val_max: Any,
    series: Sequence[tuple[str, Any]],
) -> None:
    bar_x = x + 70
    bar_width = 262
    max_value = _safe_float(val_max)
    if max_value <= 0:
        max_value = 1

    draw.text((x, y_base + 28), label_txt, font=_ui_font(25, bold=True), fill=C.TEXT, anchor="lm")
    for index, (value, (prefix, color)) in enumerate(zip((val_ave, val_recent, val_server), series)):
        number = _safe_float(value)
        row_y = y_base + 2 + index * 19
        _draw_bar(draw, bar_x, row_y + 3, bar_width, 10, number / max_value, color)
        draw.text((bar_x + bar_width + 14, row_y + 8), f"{prefix}: {_fmt_num(number)}", font=_ui_font(18), fill=C.TEXT, anchor="lm")


def _draw_bar(draw: Any, x: float, y: float, width: float, height: float, ratio: float, color: Any) -> None:
    ratio = max(0.0, min(float(ratio or 0), 1.0))
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height / 2, fill=with_alpha(C.INK, 24))
    if ratio > 0:
        draw.rounded_rectangle((x, y, x + max(height, int(width * ratio)), y + height), radius=height / 2, fill=color)


def _draw_radar_chart(
    draw: Any,
    center_x: int,
    center_y: int,
    radius: int,
    data_dict: Dict[str, tuple[Any, Any, str]],
) -> None:
    angles = [-90, -18, 54, 126, 198]
    keys = ["damage", "kill", "death", "resist", "cure"]
    grid = with_alpha(C.INK, 54)

    def point(angle: int, distance: float) -> tuple[float, float]:
        rad = math.radians(angle)
        return center_x + distance * math.cos(rad), center_y + distance * math.sin(rad)

    for ratio in (1.0, 0.66, 0.33):
        draw.polygon([point(angle, radius * ratio) for angle in angles], outline=grid, width=1.5)

    label_font = _ui_font(23)
    for index, angle in enumerate(angles):
        draw.line((center_x, center_y, *point(angle, radius)), fill=grid, width=1.5)
        draw.text(point(angle, radius + 30), data_dict[keys[index]][2], font=label_font, fill=C.TEXT, anchor="mm")

    points = []
    for index, key in enumerate(keys):
        value, max_value, _ = data_dict[key]
        current = _safe_float(value)
        top = _safe_float(max_value)
        if top <= 0:
            top = 1
        ratio = 1.0 - (current / (top * 1.5)) if key == "death" else current / top
        ratio = max(0.05, min(1.0, ratio))
        points.append(point(angles[index], radius * ratio))

    draw.polygon(points, fill=with_alpha(C.ACCENT, 96))
    draw.line(points + [points[0]], fill=C.ACCENT, width=3)
    for px, py in points:
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=C.ACCENT)


def _draw_week_action(draw: Any, payload_data: Dict[str, Any], x: int, bottom: int, width: int) -> None:
    game_action = payload_data.get("gameAction")
    if not isinstance(game_action, dict):
        return
    comment = str(game_action.get("comment") or "")
    get_honor = _safe_int(game_action.get("getHonorsCnt"))
    send_honor = _safe_int(game_action.get("sendHonorsCnt"))
    reported_cnt = _safe_int(game_action.get("reportedCnt"))
    # Three plain lines in the body face, as this section has always read.
    font = _plain_font(25)
    top = bottom - 136
    text = _truncate_text_to_width(draw, f"{STR_WEEK_COMMENT}:{comment}", width - 52, font)
    draw.text((x + 26, top + 22), text, font=font, fill=C.INK, anchor="lm")
    draw.text((x + 26, top + 62), f"{STR_HONOR}: {send_honor}/{get_honor}", font=font, fill=C.INK, anchor="lm")
    draw.text((x + 26, top + 102), f"{STR_REPORTED}: {reported_cnt}", font=font, fill=C.INK, anchor="lm")


def _draw_top_heroes_card(canvas: Any, draw: Any, config: Dict[str, Any], hero_rows: Sequence[HeroUsageRow], x: int, y: int, width: int) -> None:
    _card(draw, (x, y, x + width - 1, y + TOP_HEROES_CARD_H - 1), "MOST PLAYED HEROES IN SEASON")
    gap = 14
    inner_x = x + 22
    tile_w = (width - 44 - gap * 2) // 3
    tile_y = y + CARD_HEAD
    tile_h = TOP_HEROES_CARD_H - CARD_HEAD - 20
    for index, row in enumerate(list(hero_rows)[:3]):
        tile_x = inner_x + index * (tile_w + gap)
        center_x = tile_x + tile_w // 2
        hero_info = _find_hero(config, row.hero_guid)
        hero_name = str(hero_info.get("name") or row.payload.get("heroName") or row.hero_guid)
        ring_color = _readable_hero_color(_resolve_row_hero_color(config, row, hero_name))
        title_text = hero_name if row.hero_level <= 0 else f"{hero_name} {row.hero_level}{STR_LEVEL_SUFFIX}"
        draw.rounded_rectangle((tile_x, tile_y, tile_x + tile_w, tile_y + tile_h), radius=RADIUS_TILE + 4, fill=C.SURFACE_SUNKEN)

        icon = None
        for candidate_url in (
            row.payload.get("heroIconUrl"),
            hero_info.get("smallIconUrl"),
            hero_info.get("ddHeroIcon"),
            hero_info.get("icon"),
        ):
            icon = _load_remote_asset_image(candidate_url, category="heroes")
            if icon is not None:
                break
        portrait_size = 124
        portrait_x = center_x - portrait_size // 2
        portrait_y = tile_y + 12
        if icon is not None:
            _paste_circle(canvas, draw, icon, portrait_x, portrait_y, portrait_size, ring_color, 5)
            draw_subrole_badge(canvas, hero_info, portrait_x + portrait_size - 24, portrait_y + portrait_size - 36, 32)

        tier_icon = _load_level_tier_icon(_hero_level_tier(row.hero_level)) if row.hero_level > 0 else None
        if tier_icon is not None:
            tier_icon = _resize_image(tier_icon, (64, 64))
            canvas.paste(tier_icon, (center_x - 32, portrait_y + portrait_size - 44), tier_icon)

        title_font = _fit_ui_font(draw, title_text, tile_w - 20, 25, 18, bold=True)
        draw.text((center_x, tile_y + tile_h - 50), title_text, font=title_font, fill=C.INK, anchor="mm")
        record = f"W:{row.win_sum}/L:{max(0, row.match_sum - row.win_sum)}/WR {int(row.win_rate)}%"
        draw.text((center_x, tile_y + tile_h - 20), record, font=_fit_ui_font(draw, record, tile_w - 20, 20, 15), fill=C.MUTED, anchor="mm")


def _draw_role_card(canvas: Any, draw: Any, entries: Sequence[RolePanelEntry], box: tuple[int, int, int, int], *, pitch: int) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)
    width = x2 - x1
    role_map = {entry.role_type: entry for entry in entries}
    current_center = x1 + int(width * .42)
    high_center = x1 + int(width * .66)
    match_center = x1 + int(width * .875)
    header_y = y1 + 34
    header_font = _display_font(30)
    draw.text((x1 + 30, header_y), "ROLE", font=header_font, fill=C.MUTED, anchor="lm")
    for center, label in ((current_center, "CURRENT"), (high_center, "SEASON HIGH"), (match_center, "MATCH SUM")):
        draw.text((center, header_y), label, font=header_font, fill=C.MUTED, anchor="mm")
    draw.line((x1 + 22, y1 + ROLE_HEAD - 8, x2 - 22, y1 + ROLE_HEAD - 8), fill=C.HAIRLINE, width=1)

    labels = {"tank": "TANK", "dps": "DAMAGE", "healer": "SUPPORT", "open": "OPEN"}
    value_font = _display_font(32)
    for index, role_type in enumerate(("tank", "dps", "healer", "open")):
        entry = role_map.get(role_type)
        row_center = y1 + ROLE_HEAD + index * pitch + pitch // 2 - 4
        if index:
            draw.line((x1 + 22, row_center - pitch // 2, x2 - 22, row_center - pitch // 2), fill=C.HAIRLINE, width=1)
        role_icon = _load_role_icon(role_type, size=(30, 30))
        if role_icon is not None:
            canvas.paste(role_icon, (x1 + 30, row_center - 15), role_icon)
        draw.text((x1 + 72, row_center), labels[role_type], font=value_font, fill=C.INK, anchor="lm")

        unranked = entry is None or entry.score <= 0
        history_label = entry.history_season if entry and entry.is_history else ""
        for center, score, tier, rank_name in (
            (current_center, entry.score if entry else 0, entry.tier if entry else "", entry.rank_name if entry else ""),
            (high_center, entry.max_score if entry else 0, entry.max_tier if entry else "", entry.max_rank_name if entry else ""),
        ):
            badge = None if unranked else _build_rank_icon(score, tier, _rank_tier_font(88), (154, 52), tier_vertical_offset=14, rank_name=rank_name)
            if badge is None:
                draw.text((center, row_center), "UNRANKED", font=value_font, fill=C.FAINT, anchor="mm")
            else:
                badge = _apply_history_style(badge, bool(entry and entry.is_history))
                canvas.paste(badge, (center - badge.width // 2, row_center - badge.height // 2), badge)
            if history_label:
                draw.text((center, row_center + 34), history_label, font=_ui_font(18), fill=C.FAINT, anchor="mm")
        if entry:
            draw.text((match_center, row_center), f"{entry.match_sum} | W {entry.win_sum}", font=value_font, fill=C.INK, anchor="mm")


def _draw_hero_usage_card(
    canvas: Any,
    draw: Any,
    config: Dict[str, Any],
    rows: Sequence[HeroUsageRow],
    box: tuple[int, int, int, int],
    *,
    hero_title: str,
    quick_mode: bool,
    pitch: int,
) -> None:
    x1, y1, x2, y2 = box
    _card(draw, box, hero_title, display=False)
    max_length = rows[0].game_time if rows else 0.0
    provinces = []
    for row in rows:
        for billboard in list(row.billboards)[:2]:
            province = str(billboard.province or "").strip()
            if province and province not in provinces:
                provinces.append(province)
    if provinces:
        header = _truncate_text_to_width(draw, " / ".join(provinces), 300, _ui_font(22))
        draw.text((x2 - 28, y1 + 34), header, font=_ui_font(22), fill=C.DRAW, anchor="rm")

    row_h = pitch - 8
    left, width = x1 + 22, x2 - x1 - 44
    for index, row in enumerate(rows):
        _draw_hero_usage_row(canvas, draw, config, row, left, y1 + CARD_HEAD + index * pitch, width, row_h, max_length, quick_mode)


def _draw_hero_usage_row(
    canvas: Any,
    draw: Any,
    config: Dict[str, Any],
    row: HeroUsageRow,
    x: int,
    y: int,
    width: int,
    height: int,
    max_length: float,
    quick_mode: bool,
) -> None:
    hero_info = _find_hero(config, row.hero_guid)
    hero_name = str(hero_info.get("name") or row.payload.get("heroName") or row.hero_guid)
    hero_icon_url = str(hero_info.get("icon") or row.payload.get("heroIconUrl") or "")
    color = _readable_hero_color(_resolve_row_hero_color(config, row, hero_name))
    center_y = y + height // 2
    right = x + width

    # Playtime lives behind the row as a tint, so no text sits on saturated hero colour.
    draw.rounded_rectangle((x, y, right, y + height), radius=RADIUS_TILE, fill=with_alpha(C.INK, 12))
    ratio = _calc_playtime_ratio(row.game_time, max_length)
    if ratio > 0:
        bar_right = x + max(height, int(width * ratio))
        draw.rounded_rectangle((x, y, bar_right, y + height), radius=RADIUS_TILE, fill=with_alpha(color, C.USAGE_FILL_ALPHA))
        draw.rounded_rectangle((x, y + height - 3, bar_right, y + height), radius=1.5, fill=color)

    icon = _load_remote_asset_image(hero_icon_url, category="heroes")
    icon_size = min(38, height - 2)
    if icon is not None:
        canvas.paste(_cover_fit(icon, (icon_size, icon_size)), (x + 4, center_y - icon_size // 2), _rounded_mask(icon_size, 8))
        draw_subrole_badge(canvas, hero_info, x + 26, center_y + 1, 18)

    hero_level = max(0, _safe_int(row.hero_level))
    tier_icon = _load_level_tier_icon(_hero_level_tier(hero_level)) if hero_level > 0 else None
    if tier_icon is not None:
        tier_icon = _resize_image(tier_icon, (32, 32))
        canvas.paste(tier_icon, (x + 50, center_y - 16), tier_icon)
    draw.text((x + 88, center_y), _hero_level_display_text(hero_level), font=_ui_font(23, bold=True), fill=C.DRAW, anchor="lm")

    chip_x, chip_w = x + 176, 340
    chip_h = min(30, height - 6)
    if not row.billboards:
        record = f"W:{row.win_sum}/L:{max(0, row.match_sum - row.win_sum)}/WR {int(row.win_rate)}%"
        draw.text((chip_x + 12, center_y), record, font=_ui_font(21), fill=C.INK, anchor="lm")
    else:
        visible = list(row.billboards)[:2]
        gap = 8
        each_w = chip_w if len(visible) == 1 else (chip_w - gap) // 2
        for index, billboard in enumerate(visible):
            left = chip_x + index * (each_w + gap)
            draw.rounded_rectangle((left, center_y - chip_h // 2, left + each_w, center_y + chip_h // 2), radius=RADIUS_TILE, fill=tinted(C.ACCENT, .28), outline=with_alpha(C.ACCENT, 150), width=1)
            text = _truncate_text_to_width(draw, f"#{billboard.rank_num}{STR_RANK_SUFFIX}", each_w - 12, _ui_font(22, bold=True))
            draw.text((left + each_w / 2, center_y), text, font=_ui_font(22, bold=True), fill=C.ACCENT, anchor="mm")

    if row.rank_overlay is not None:
        _draw_rank_overlay(canvas, draw, row.rank_overlay, chip_x + chip_w + 12, center_y, 114, chip_h)

    time_text = _readable_playtime(row.game_time, quick_mode=quick_mode)
    draw.text((right - 12, center_y), time_text, font=_ui_font(22, bold=True), fill=C.INFO, anchor="rm")


def _draw_rank_overlay(canvas: Any, draw: Any, overlay: Any, x: int, center_y: int, width: int, height: int) -> None:
    # The engine marks open-queue ranks dark and preset-queue ranks light.
    open_queue = overlay.fill[0] < 80
    fill = C.CHIP if open_queue else tinted(C.INFO, .3)
    text_fill = C.CHIP_TEXT if open_queue else C.INK
    draw.rounded_rectangle((x, center_y - height // 2, x + width, center_y + height // 2), radius=RADIUS_TILE, fill=fill, outline=C.STROKE, width=1)
    emblem = _load_rank_pure_icon(overlay.rank_level)
    text_left = x + 8
    if emblem is not None:
        bounds = emblem.getbbox()
        if bounds:
            emblem = emblem.crop(bounds)
        emblem.thumbnail((height, height - 2), _resampling_lanczos())
        if C.STICKER and not open_queue:
            emblem = sticker_outline(emblem, C.STICKER, width=1)
        canvas.paste(emblem, (x + 7, int(center_y - emblem.height / 2)), emblem)
        text_left = x + 7 + emblem.width + 4
    draw.text(((text_left + x + width - 4) / 2, center_y), str(overlay.ranked_level), font=_ui_font(23, bold=True), fill=text_fill, anchor="mm")


def _billboard_layout(
    open_billboards: Sequence[HeroBillboardEntry],
    preset_billboards: Sequence[HeroBillboardEntry],
    width: int,
    room: int,
) -> Dict[str, Any] | None:
    """Pick the roomiest chip size that fits; past the densest, show the best ranks only."""
    sections = [
        (label, sorted(entries, key=lambda item: item.rank_num))
        for label, entries in ((STR_LEFTOVER_OPEN, open_billboards), (STR_LEFTOVER_PRESET, preset_billboards))
        if entries
    ]
    if not sections:
        return None

    def height_of(columns: int, row_h: int, counts: Sequence[int]) -> int:
        return 26 + sum(BILLBOARD_LABEL_H + (count + columns - 1) // columns * row_h + 8 for count in counts)

    counts = [len(entries) for _, entries in sections]
    for density in BILLBOARD_DENSITIES:
        columns = _billboard_columns(width, density["chip_w"])
        if height_of(columns, density["row_h"], counts) <= room:
            return {"sections": sections, "density": density, "columns": columns, "hidden": 0, "height": height_of(columns, density["row_h"], counts)}

    density = BILLBOARD_DENSITIES[-1]
    columns = _billboard_columns(width, density["chip_w"])
    rows_left = max(len(sections), (room - 26 - len(sections) * (BILLBOARD_LABEL_H + 8)) // density["row_h"])
    # Share the rows by need, keeping one for every section.
    rows_needed = [(count + columns - 1) // columns for count in counts]
    rows_given = [1] * len(sections)
    rows_left -= len(sections)
    while rows_left > 0 and any(given < need for given, need in zip(rows_given, rows_needed)):
        spare = max(range(len(sections)), key=lambda i: rows_needed[i] - rows_given[i])
        rows_given[spare] += 1
        rows_left -= 1
    trimmed = [(label, entries[:given * columns]) for (label, entries), given in zip(sections, rows_given)]
    shown = sum(len(entries) for _, entries in trimmed)
    return {
        "sections": trimmed,
        "density": density,
        "columns": columns,
        "hidden": sum(counts) - shown,
        "height": height_of(columns, density["row_h"], [len(entries) for _, entries in trimmed]),
    }


def _billboard_columns(width: int, chip_w: int) -> int:
    return max(1, (width - 44 + 8) // (chip_w + 8))


def _draw_billboard_card(canvas: Any, draw: Any, config: Dict[str, Any], layout: Dict[str, Any], box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)
    density, columns = layout["density"], layout["columns"]
    chip_w = (x2 - x1 - 44 - (columns - 1) * 8) // columns
    cursor = y1 + 14
    if layout["hidden"]:
        draw.text((x2 - 26, cursor + BILLBOARD_LABEL_H // 2 - 2), f"其余 {layout['hidden']} 项未显示", font=_ui_font(20), fill=C.MUTED, anchor="rm")
    for label, entries in layout["sections"]:
        draw.text((x1 + 26, cursor + BILLBOARD_LABEL_H // 2 - 2), label, font=_ui_font(24, bold=True), fill=C.TEXT, anchor="lm")
        cursor += BILLBOARD_LABEL_H
        for index, billboard in enumerate(entries):
            row, column = divmod(index, columns)
            _draw_billboard_chip(canvas, draw, config, x1 + 22 + column * (chip_w + 8), cursor + row * density["row_h"], chip_w, density, billboard)
        cursor += (len(entries) + columns - 1) // columns * density["row_h"] + 8


def _draw_billboard_chip(canvas: Any, draw: Any, config: Dict[str, Any], x: int, y: int, width: int, density: Dict[str, int], billboard: HeroBillboardEntry) -> None:
    hero_info = _find_hero(config, billboard.hero_guid)
    hero_name = str(hero_info.get("name") or billboard.hero_guid)
    height = density["row_h"] - 6
    draw.rounded_rectangle((x, y, x + width, y + height), radius=RADIUS_TILE, fill=C.SURFACE_SUNKEN)
    icon = None
    for candidate_url in (hero_info.get("smallIconUrl"), hero_info.get("ddHeroIcon"), hero_info.get("icon")):
        icon = _load_remote_asset_image(candidate_url, category="heroes")
        if icon is not None:
            break
    text_x = x + 10
    if icon is not None:
        _paste_circle(canvas, draw, icon, x + 5, y + 3, height - 6, _readable_hero_color(_hero_ring_color(config, hero_name)), 2)
        text_x = x + height + 4
    draw.text((text_x, y + height // 2), f"#{billboard.rank_num}{STR_RANK_SUFFIX}", font=_ui_font(density["font"], bold=True), fill=C.DRAW, anchor="lm")


def _draw_recent_match_card(canvas: Any, draw: Any, config: Dict[str, Any], matches: Sequence[Dict[str, Any]], box: tuple[int, int, int, int], *, pitch: int) -> None:
    x1, y1, x2, _ = box
    _card(draw, box, "RECENT MATCH")
    left, width = x1 + 18, x2 - x1 - 36
    row_h = pitch - 5
    for index, item in enumerate(matches):
        _draw_recent_match_row(canvas, draw, config, item, left, y1 + CARD_HEAD + index * pitch, width, row_h)


def _draw_recent_match_row(canvas: Any, draw: Any, config: Dict[str, Any], item: Dict[str, Any], x: int, y: int, width: int, height: int) -> None:
    map_info = _find_map(config, item.get("mapGuid"))
    match_type = _recent_match_type(item)
    box = (x, y, x + width, y + height)
    if not _paste_map_cover(canvas, box, map_info, RADIUS_CHIP + 2, C.RECENT_ROW_SCRIM):
        draw.rounded_rectangle((x, y, x + width - 1, y + height - 1), radius=RADIUS_CHIP + 2, fill=C.SURFACE_RAISED)
    center_y = y + height // 2
    mode_color = _recent_match_type_color(item, match_type)
    draw.rounded_rectangle((x, y, x + 6, y + height - 1), radius=3, fill=mode_color)

    map_name = str(map_info.get("name") or item.get("mapName") or item.get("mapGuid") or STR_UNKNOWN_MAP)
    begin_ts = _safe_int(item.get("beginTs"))
    if begin_ts > 10_000_000_000:
        begin_ts //= 1000
    hero_guid = str(item.get("heroGuid") or "")
    hero_info = _find_hero(config, hero_guid)
    hero_name = str(hero_info.get("name") or item.get("heroName") or hero_guid)

    draw_map_mode_icon(canvas, map_info, x + 14, center_y - 11, 22, color=C.MAP_ICON)
    map_font = _ui_font(23)
    draw.text((x + 42, center_y), _truncate_text_to_width(draw, map_name, 196, map_font), font=map_font, fill=C.INK, anchor="lm")

    icon = _load_remote_asset_image(str(hero_info.get("icon") or ""), category="heroes")
    portrait = min(30, height - 2)
    if icon is not None:
        _paste_circle(canvas, draw, icon, x + 246, center_y - portrait // 2, portrait, _readable_hero_color(_hero_ring_color(config, hero_name)), 2)

    mode_label = _recent_match_mode_label(item, match_type)
    draw.text((x + 288, center_y), mode_label, font=_display_font(25, oblique=False), fill=mode_color, anchor="lm")
    rank_info = item.get("rankInfo")
    has_rank_label = match_type == "COMPETITIVE" or mode_label == "COMP 6V6"
    if has_rank_label and isinstance(rank_info, dict) and _safe_int(get_rank_score(rank_info)) > 0:
        badge = _build_rank_icon(
            _safe_int(get_rank_score(rank_info)),
            str(get_rank_sub_tier(rank_info) or ""),
            _rank_tier_font(64),
            (86, 28),
            tier_vertical_offset=16,
            rank_name=str(get_rank_name(rank_info) or ""),
        )
        if badge is not None:
            canvas.paste(badge, (x + 416, center_y - badge.height // 2), badge)

    draw.text((x + width - 150, center_y), _relative_time(begin_ts), font=_display_font(22, oblique=False), fill=C.MUTED, anchor="rm")
    _draw_recent_match_result(draw, item, x + width - 140, y + 2, 138, height - 4)


def _draw_recent_match_result(draw: Any, item: Dict[str, Any], x: int, y: int, width: int, height: int) -> None:
    match_ret = _safe_int(item.get("matchRet"))
    team_score = _safe_int(item.get("teamScore"))
    opponent_score = _safe_int(item.get("opponentScore"))
    if match_ret == 1:
        fill, label = C.WIN, "VICTORY!"
    elif match_ret == 0:
        fill, label = C.FAINT, "TIE"
    else:
        fill, label = C.LOSS, "DEFEAT!"
    draw.rounded_rectangle((x, y, x + width - 1, y + height - 1), radius=RADIUS_CHIP, fill=fill)
    center_y = y + height // 2
    font = _display_font(23, oblique=False)
    draw.text((x + 12, center_y), label, font=font, fill=C.STREAK_TEXT, anchor="lm")
    draw.text((x + width - 12, center_y), f"{team_score}-{opponent_score}", font=font, fill=C.STREAK_TEXT, anchor="rm")


def _recent_match_type(item: Dict[str, Any]) -> str:
    instance_type = str(item.get("instanceType") or "")
    game_mode = str(item.get("gameMode") or "").lower()
    rank_info = item.get("rankInfo")
    if "sportfight" in game_mode:
        return "STADIUM COMP"
    if "quickfight" in game_mode or "leisurefight" in game_mode:
        return "STADIUM QP"
    if instance_type == "IT_UNRANKED":
        return "IT_UNRANKED"
    # Ranked 6v6 carries rank info too, so this must come before the generic check.
    if instance_type == "IT_RULESET":
        return "IT_RULESET"
    if isinstance(rank_info, dict) and rank_info:
        return "COMPETITIVE"
    return instance_type or "COMPETITIVE"


def _recent_match_mode_label(item: Dict[str, Any], match_type: str) -> str:
    if match_type == "IT_UNRANKED":
        return "UNRANKED"
    if match_type == "STADIUM QP":
        return "STADIUM QP"
    if match_type == "STADIUM COMP":
        return "STADIUM COMP"
    if match_type == "IT_RULESET":
        rank_info = item.get("rankInfo")
        return "COMP 6V6" if isinstance(rank_info, dict) and _safe_int(get_rank_score(rank_info)) > 0 else "UNR 6V6"
    return "COMPETITIVE"


def _recent_match_type_color(item: Dict[str, Any], match_type: str) -> tuple[int, int, int, int]:
    if match_type == "IT_UNRANKED":
        return C.MATCH_MODES["unranked"]
    if match_type == "STADIUM QP":
        return C.MATCH_MODES["stadium_qp"]
    if match_type == "STADIUM COMP":
        return C.MATCH_MODES["stadium_comp"]
    if match_type == "IT_RULESET":
        rank_info = item.get("rankInfo")
        if isinstance(rank_info, dict) and _safe_int(get_rank_score(rank_info)) > 0:
            return C.MATCH_MODES["competitive_6v6"]
        return C.MATCH_MODES["unranked_6v6"]
    return C.MATCH_MODES["competitive"]


def _build_rank_icon(
    score: int,
    tier: str,
    tier_font: Any,
    size: tuple[int, int],
    *,
    tier_vertical_offset: float = 0.0,
    rank_name: str = "",
) -> Any | None:
    from PIL import Image, ImageDraw

    if score <= 0:
        return None
    rank_index = _rank_level_from_score(score, rank_name=rank_name)
    path = RESOURCE_DIR / "rank_flat" / f"{rank_index}.png"
    if not path.exists():
        return None
    try:
        icon = Image.open(path).convert("RGBA")
    except Exception:
        return None
    original_width, original_height = icon.size
    draw = ImageDraw.Draw(icon)
    tier_text = str(tier or "").strip()
    if tier_text:
        try:
            center_x = original_width * (332 / max(1, 460))
            center_y = original_height * (52 / max(1, 156)) + float(tier_vertical_offset or 0.0)
            box = draw.textbbox((0, 0), tier_text, font=tier_font)
            draw_x = center_x - (box[2] - box[0]) / 2 - box[0]
            draw_y = center_y - (box[3] - box[1]) / 2 - box[1]
            draw.text((draw_x, draw_y), tier_text, font=tier_font, fill=(22, 25, 32, 255))
        except Exception:
            try:
                draw.text((original_width * (332 / max(1, 460)), original_height * (52 / max(1, 156)) + float(tier_vertical_offset or 0.0)), tier_text, font=tier_font, fill=(22, 25, 32, 255), anchor="mm")
            except TypeError:
                draw.text((300, 12 + int(round(float(tier_vertical_offset or 0.0)))), tier_text, font=tier_font, fill=(22, 25, 32, 255))
    return icon.resize(size, Image.LANCZOS)


def _apply_history_style(icon: Any, is_history: bool) -> Any:
    if not is_history:
        return icon
    from PIL import ImageEnhance

    styled = icon.copy()
    r_chan, g_chan, b_chan, alpha = styled.split()
    alpha = alpha.point(lambda value: int(value * 0.5))
    styled.putalpha(alpha)
    return ImageEnhance.Color(styled).enhance(0.5)


def _load_rank_pure_icon(rank_level: int) -> Any | None:
    from PIL import Image

    normalized_level = max(1, min(9, _safe_int(rank_level)))
    path = RESOURCE_DIR / "rank_flat" / f"{normalized_level}_pure.png"
    if not path.exists():
        fallback = RESOURCE_DIR / "rank_flat" / f"f{normalized_level}_pure.png"
        path = fallback if fallback.exists() else path
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _rank_level_from_score(score: int, *, rank_name: str = "") -> int:
    named_level = rank_name_to_icon_level(rank_name)
    if named_level > 0:
        return named_level
    return rank_info_to_icon_level({"rankScore": score})


def _hero_level_tier(hero_level: int) -> int:
    if 0 <= hero_level < 25:
        return 1
    if 25 <= hero_level < 50:
        return 2
    if 50 <= hero_level < 75:
        return 3
    if 75 <= hero_level < 100:
        return 4
    return 5


def _hero_level_display_text(hero_level: int) -> str:
    level = max(0, _safe_int(hero_level))
    return f"{level}{STR_LEVEL_SUFFIX}" if level > 0 else "--"


def _rank_tier_font(size: int) -> Any:
    key = ("rank_tier", int(size))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="num.ttf")
        _FONT_CACHE[key] = font
    return font


def _load_level_tier_icon(level_tier: int) -> Any | None:
    from PIL import Image

    path = RESOURCE_DIR / "rank_flat" / f"lv_tier{level_tier}.png"
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _normalize_role_type(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def _load_appreciation_icon(config: Dict[str, Any], level: int) -> Any | None:
    level_map = config.get("appreciationLevelIcon")
    if not isinstance(level_map, dict):
        return None
    return _load_remote_asset_image(level_map.get(str(level)))


def _load_remote_asset_image(url: Any, category: str = "misc") -> Any | None:
    from PIL import Image

    text = str(url or "").strip()
    if not text:
        return None
    asset_path = _find_cached_asset_path(text, category=category)
    if asset_path is None or not asset_path.exists():
        return None
    try:
        return Image.open(asset_path).convert("RGBA")
    except Exception:
        return None


def _find_cached_asset_path(url: str, *, category: str = "misc") -> Path | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None

    path = get_cached_asset_path(normalized, category)
    if path and path.exists():
        return path

    stem = _asset_hash(normalized)
    if QUERY_TOOL_ASSET_DIR.exists():
        for candidate in QUERY_TOOL_ASSET_DIR.rglob(f"{stem}.*"):
            if candidate.is_file():
                return candidate
    return None


def _asset_hash(url: str) -> str:
    import hashlib

    return hashlib.sha256(str(url or "").strip().encode("utf-8")).hexdigest()[:24]


def _load_ow_config() -> Dict[str, Any]:
    try:
        return load_query_tool()
    except Exception as exc:
        print(f"[overstats] failed to load query_tool config for profile render: {exc}")
        return {}


def _find_hero(config: Dict[str, Any], hero_guid: str) -> Dict[str, Any]:
    for hero in config.get("heroList", []) or []:
        if str(hero.get("heroGuid") or hero.get("heroId") or hero.get("guid") or hero.get("id") or "") == hero_guid:
            return hero
    return {}


def _find_map(config: Dict[str, Any], map_guid: Any) -> Dict[str, Any]:
    target = str(map_guid or "")
    for item in config.get("mapList", []) or []:
        if isinstance(item, dict) and str(item.get("guid") or "") == target:
            return item
    return {}


def _hero_ring_color(config: Dict[str, Any], hero_name: str) -> tuple[int, int, int, int]:
    hero_config = config.get("heroConfig")
    if isinstance(hero_config, dict):
        for item in hero_config.values():
            if str(item.get("Name") or "") == hero_name:
                try:
                    return hex_to_rgba(str(item.get("Color") or "#808080"))
                except Exception:
                    break
    return (128, 128, 128, 255)


def _resolve_row_hero_color(config: Dict[str, Any], row: HeroUsageRow, hero_name: str) -> tuple[int, int, int, int]:
    resolved = _hero_ring_color(config, hero_name)
    if resolved != (128, 128, 128, 255):
        return resolved
    payload_color = str(row.payload.get("heroColor") or row.payload.get("hero_color") or "").strip()
    if not payload_color:
        return resolved
    try:
        return hex_to_rgba(payload_color)
    except Exception:
        return resolved


def _measure_text_width(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        try:
            box = draw.textbbox((0, 0), text, font=font)
            return int(box[2] - box[0])
        except Exception:
            return 0


def _truncate_text_to_width(draw: Any, text: str, max_width: int, font: Any) -> str:
    text = str(text or "")
    if _measure_text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    while text and _measure_text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _list_dicts(value: Any) -> list[Dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _relative_time(begin_ts: int) -> str:
    if begin_ts <= 0:
        return "--"
    diff = max(0, int(time.time()) - begin_ts)
    if diff < 3600:
        return f"{max(0, diff // 60)} MINUTES AGO"
    if diff < 86400:
        return f"{diff // 3600} HOURS AGO"
    return f"{diff // 86400} DAYS AGO"


def _readable_playtime(game_time: float, *, quick_mode: bool) -> str:
    if game_time < 60:
        return "< 1M" if quick_mode else "<1M"
    if game_time < 3600:
        return f"{int(game_time / 60)}M"
    return f"{int(game_time / 3600)}H"


def _calc_playtime_ratio(game_time: Any, max_length: Any) -> float:
    game_time_val = _safe_float(game_time)
    max_length_val = _safe_float(max_length)
    if game_time_val <= 0 or max_length_val <= 0:
        return 0.0
    return max(0.0, min(game_time_val / max_length_val, 1.0))


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    text = str(hex_color or "").lstrip("#")
    if len(text) == 6:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255)
    if len(text) == 8:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16))
    return (128, 128, 128, 255)
