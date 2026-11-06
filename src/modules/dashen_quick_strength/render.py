from __future__ import annotations

from ..map_modes import draw_map_mode_icon

from ..dashen_promo import append_dashen_promo

from dataclasses import dataclass
import datetime as dt
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...constants.backgrounds import build_random_map_background
from ...constants.ranks import RANK_LABELS_CN, RANK_ORDER, strength_score_to_icon_level

from ..dashen_summary.runtime.summary_style import (
    C,
    RADIUS_CARD,
    RADIUS_CHIP,
    horizontal_scrim,
    mix,
    sticker_outline,
    themed,
    tinted,
    vertical_scrim,
    with_alpha,
)
from ..dashen_summary.runtime.summary_typography import SmoothDraw, smooth_mask
from .engine import score_to_rank

try:
    from overstats.src.modules.query_tool import get_cached_asset_path
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.risk_status import (
        draw_risk_status_badge,
    )
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.risk_status import (
        draw_risk_status_badge,
    )


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
RANK_BREAKPOINTS = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500]
RESULT_LABELS = {1: "胜", -1: "负", 0: "平"}
DEFAULT_STRENGTH_THEME = {
    "tone": "quick",
    "range_color": (140, 214, 255, 188),
    "line_color": (86, 154, 255, 255),
    "avatar_ring_color": (92, 151, 245, 255),
    "avatar_badge_text": "QS",
}
QUICK_STRENGTH_THEME = dict(DEFAULT_STRENGTH_THEME)
COMPETITIVE_STRENGTH_THEME = {
    "tone": "competitive",
    "range_color": (255, 104, 104, 204),
    "line_color": (255, 72, 72, 255),
    "avatar_ring_color": (255, 84, 84, 255),
    "avatar_badge_text": "CS",
}
TOP_TIER_ICON_LEVELS = {6, 7, 8}
PAGE_W = 2000
PAGE_MARGIN = 32
SECTION_GAP = 18
HEADER_H = 190
CHART_HEAD = 70
CHART_PAD = 26
AXIS_W = 96
PLOT_H = 620
MATCH_LABEL_H = 112
CHART_CARD_H = CHART_HEAD + PLOT_H + MATCH_LABEL_H + CHART_PAD + 10
HISTOGRAM_H = 190
LEGEND_H = 66
TILE_INSET = 4
ROLE_TRACK_W = 56
ROLE_TRACK_OUTLINE = 5
ALL_ROLE_TRACK_W = 14
RESULT_STRIP_H = 12
SUMMARY_ICON_H = 76
_FONT_CACHE: Dict[Any, Any] = {}
_MAP_CACHE: Dict[Any, Any] = {}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


@themed
def render_quick_strength(
    *,
    player_name: str,
    bnet_id: str,
    summary: Dict[str, Any],
    matches: Sequence[Dict[str, Any]],
    avatar_bytes: Optional[bytes] = None,
    risk_status: Any = None,
    config: Optional[Dict[str, Any]] = None,
    theme: Optional[Dict[str, Any]] = None,
    title_text: str = "快速强度指数",
    chart_title_text: str = "快速强度趋势",
    match_scope_text: str = "快速",
) -> RenderedImage:
    try:
        from PIL import Image  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    height = PAGE_MARGIN * 2 + SECTION_GAP * 3 + HEADER_H + CHART_CARD_H + HISTOGRAM_H + LEGEND_H
    canvas = _page_background((PAGE_W, height))
    draw = _new_draw(canvas)
    render_config = config if isinstance(config, dict) else {}
    active_theme = _resolve_theme(theme)
    tone = C.STRENGTH_TONES[active_theme["tone"]]

    top = PAGE_MARGIN
    _draw_header(
        canvas,
        draw,
        top=top,
        player_name=player_name,
        bnet_id=bnet_id,
        summary=summary,
        matches=matches,
        avatar_bytes=avatar_bytes,
        risk_status=risk_status,
        config=render_config,
        tone=tone,
        badge_text=str(active_theme.get("avatar_badge_text") or "QS"),
        title_text=title_text,
        match_scope_text=match_scope_text,
    )
    top += HEADER_H + SECTION_GAP
    _draw_chart(
        canvas,
        draw,
        top=top,
        matches=matches,
        config=render_config,
        tone=tone,
        chart_title_text=chart_title_text,
    )
    top += CHART_CARD_H + SECTION_GAP
    _draw_rank_distribution(draw, top=top, matches=matches, tone=tone)
    top += HISTOGRAM_H + SECTION_GAP
    _draw_legend(draw, top=top, tone=tone)

    output = BytesIO()
    canvas = append_dashen_promo(canvas, compact=True)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _new_draw(image: Any) -> Any:
    return SmoothDraw(
        image,
        "RGBA",
        numeric_font_path=RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
        latin_font_path=RESOURCE_DIR / "en2.ttf",
    )


def _resolve_theme(theme: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved = dict(DEFAULT_STRENGTH_THEME)
    if isinstance(theme, dict):
        resolved.update({key: value for key, value in theme.items() if value is not None})
    return resolved


def _page_background(size: Tuple[int, int]) -> Any:
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


def _card(draw: Any, box: Tuple[int, int, int, int], tone: Dict[str, Any], title: str, *, size: int = 32) -> int:
    x1, y1 = box[:2]
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)
    draw.polygon([(x1 + 26, y1 + 20), (x1 + 34, y1 + 20), (x1 + 29, y1 + 46), (x1 + 21, y1 + 46)], fill=tone["line"])
    font = _ui_font(size, bold=True)
    draw.text((x1 + 46, y1 + 33), title, font=font, fill=C.INK, anchor="lm")
    return x1 + 46 + _measure_text(draw, title, font)


def _draw_header(
    canvas: Any,
    draw: Any,
    *,
    top: int,
    player_name: str,
    bnet_id: str,
    summary: Dict[str, Any],
    matches: Sequence[Dict[str, Any]],
    avatar_bytes: Optional[bytes],
    risk_status: Any,
    config: Dict[str, Any],
    tone: Dict[str, Any],
    badge_text: str,
    title_text: str,
    match_scope_text: str,
) -> None:
    from PIL import Image

    left, right = PAGE_MARGIN, PAGE_W - PAGE_MARGIN
    bottom = top + HEADER_H
    box = (left, top, right - 1, bottom - 1)
    size = (right - left, HEADER_H)
    cover = _map_cover(config, matches[-1].get("map_guid"), size) if matches else None
    if cover is not None:
        cover = Image.alpha_composite(cover, horizontal_scrim(size, C.PROFILE_BANNER_SCRIM))
        canvas.paste(cover, (left, top), smooth_mask(size[0], size[1], RADIUS_CARD + 4))
    else:
        draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE)
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, outline=C.STROKE, width=1)

    _draw_avatar(canvas, draw, avatar_bytes, (left + 30, top + 30), 130, tone, badge_text)

    display_name = str(player_name or bnet_id or "Unknown").strip()
    raw_bnet_id = str(bnet_id or "").strip()
    if "#" in display_name:
        name_text, suffix_text = display_name.split("#", 1)
        suffix_text = f"#{suffix_text.strip()}"
    elif raw_bnet_id and "#" in raw_bnet_id:
        name_text, suffix_text = raw_bnet_id.split("#", 1)
        suffix_text = f"#{suffix_text.strip()}"
    else:
        name_text = display_name
        suffix_text = raw_bnet_id if raw_bnet_id and raw_bnet_id != display_name else ""

    title_x = left + 190
    region_right = left + 730
    name_font = _ui_font(46, bold=True) if _contains_cjk(name_text) else _display_font(60)
    rendered_name = _fit_text(draw, name_text, name_font, region_right - title_x)
    draw.text((title_x, top + 56), rendered_name, font=name_font, fill=C.INK, anchor="lm")
    name_width = _measure_text(draw, rendered_name, name_font)

    title_font = _ui_font(22, bold=True)
    title_width = _measure_text(draw, title_text, title_font) + 28
    chip_y = top + 92
    badge_x = title_x + title_width + 16
    if suffix_text:
        suffix_font = _display_font(30, oblique=False)
        draw.text((title_x, top + 106), suffix_text, font=suffix_font, fill=C.MUTED, anchor="lm")
        badge_x = title_x + _measure_text(draw, suffix_text, suffix_font) + 16
        chip_y = top + 124
    draw.rounded_rectangle((title_x, chip_y, title_x + title_width, chip_y + 36), radius=RADIUS_CHIP, fill=tone["line"])
    draw.text((title_x + 14, chip_y + 18), title_text, font=title_font, fill=tone["on_line"], anchor="lm")
    badge_width, _ = draw_risk_status_badge(
        draw,
        badge_x,
        top + 91,
        risk_status,
        font=_ui_font(20),
        padding_x=10,
        padding_y=4,
        max_width=max(100, region_right - badge_x),
    )

    content_right = max(title_x + name_width, badge_x + badge_width if badge_width else 0)
    summary_x = min(max(left + 610, content_right + 40), left + 760)
    _draw_summary_block(canvas, draw, x=summary_x, top=top, summary=summary)

    match_count = int(summary.get("match_count") or 0)
    fallback_text = (
        "已启用上赛季回退"
        if bool(summary.get("used_previous_season_fallback"))
        else "优先使用当前赛季"
    )
    draw.text(
        (right - 30, top + HEADER_H // 2),
        f"最近 {match_count} 场{match_scope_text}  ·  {fallback_text}",
        font=_ui_font(21),
        fill=C.TEXT,
        anchor="rm",
    )


def _draw_avatar(
    canvas: Any,
    draw: Any,
    avatar_bytes: Optional[bytes],
    position: Tuple[int, int],
    size: int,
    tone: Dict[str, Any],
    badge_text: str,
) -> None:
    from PIL import Image, ImageOps

    x, y = position
    avatar = None
    if avatar_bytes:
        try:
            avatar = ImageOps.fit(Image.open(BytesIO(avatar_bytes)).convert("RGBA"), (size, size), method=Image.LANCZOS)
        except Exception:
            avatar = None
    if avatar is not None:
        canvas.paste(avatar, position, smooth_mask(size, size, 18))
    else:
        draw.rounded_rectangle((x, y, x + size - 1, y + size - 1), radius=18, fill=C.SURFACE_RAISED)
        draw.text((x + size / 2, y + size / 2), badge_text, font=_display_font(52, oblique=False), fill=C.INK, anchor="mm")
    draw.rounded_rectangle((x - 4, y - 4, x + size + 3, y + size + 3), radius=21, outline=tone["line"], width=3)


def _draw_summary_block(
    canvas: Any,
    draw: Any,
    *,
    x: int,
    top: int,
    summary: Dict[str, Any],
) -> None:
    avg_score = float(summary.get("overall_avg_score") or 0)
    avg_rank = _rank_text_cn(summary.get("overall_avg_rank") or "Unranked")
    score_range = summary.get("score_range") if isinstance(summary.get("score_range"), dict) else {}
    range_min = int(score_range.get("min") or 0)
    range_max = int(score_range.get("max") or 0)

    rank_level = _rank_icon_level_from_score(avg_score)
    icon_size = _summary_rank_icon_size(rank_level)
    icon = _load_rank_flat_icon(avg_score, size=icon_size)
    text_x = x
    if icon is not None:
        if C.STICKER:
            icon = sticker_outline(icon, C.STICKER)
        canvas.paste(icon, (x, top + (HEADER_H - icon.height) // 2), icon)
        text_x += icon.width + 18

    label_font, value_font = _ui_font(20), _ui_font(32, bold=True)
    draw.text((text_x, top + 56), "平均段位估计", font=label_font, fill=C.MUTED, anchor="lm")
    rank_font = _ui_font(44, bold=True)
    draw.text((text_x, top + 108), avg_rank, font=rank_font, fill=C.INK, anchor="lm")

    stats_x = text_x + max(_measure_text(draw, "平均段位估计", label_font), _measure_text(draw, avg_rank, rank_font)) + 40
    score_text = f"{avg_score:.1f}" if avg_score > 0 else "--"
    range_text = f"{range_min} - {range_max}" if range_min > 0 and range_max > 0 else "--"
    for label, value in (("平均强度", score_text), ("强度范围", range_text)):
        draw.text((stats_x, top + 56), label, font=label_font, fill=C.MUTED, anchor="lm")
        draw.text((stats_x, top + 108), value, font=value_font, fill=C.INK, anchor="lm")
        stats_x += max(_measure_text(draw, label, label_font), _measure_text(draw, value, value_font)) + 40


def _draw_chart(
    canvas: Any,
    draw: Any,
    *,
    top: int,
    matches: Sequence[Dict[str, Any]],
    config: Dict[str, Any],
    tone: Dict[str, Any],
    chart_title_text: str,
) -> None:
    box = (PAGE_MARGIN, top, PAGE_W - PAGE_MARGIN - 1, top + CHART_CARD_H - 1)
    title_right = _card(draw, box, tone, chart_title_text)
    draw.text(
        (title_right + 28, top + 33),
        "粗条=职责区间  细条=全职责区间  "
        "条内横条=玩家段位分布  厚度=同段位人数",
        font=_ui_font(20),
        fill=C.MUTED,
        anchor="lm",
    )

    axis_left = box[0] + CHART_PAD
    inner_left = axis_left + AXIS_W
    inner_right = box[2] - CHART_PAD
    inner_top = top + CHART_HEAD
    inner_bottom = inner_top + PLOT_H

    if not matches:
        draw.text(
            ((inner_left + inner_right) // 2, inner_top + PLOT_H // 2),
            "暂无快速比赛数据",
            font=_ui_font(30, bold=True),
            fill=C.MUTED,
            anchor="mm",
        )
        return

    score_values = _collect_chart_scores(matches)
    if not score_values:
        score_min = 500
        score_max = 5000
    else:
        score_min = max(400, min(score_values) - 180)
        score_max = min(5000, max(score_values) + 180)
        score_min = (score_min // 100) * 100
        score_max = ((score_max + 99) // 100) * 100
        if score_max - score_min < 1200:
            center = (score_min + score_max) / 2
            score_min = int(center - 600)
            score_max = int(center + 600)

    def y_for(score: float) -> int:
        if score_max <= score_min:
            return int((inner_top + inner_bottom) / 2)
        ratio = (float(score) - score_min) / max(score_max - score_min, 1)
        ratio = max(0.0, min(1.0, ratio))
        return int(inner_bottom - ratio * (inner_bottom - inner_top))

    column_width = (inner_right - inner_left) / len(matches)
    columns = [
        (int(inner_left + idx * column_width) + TILE_INSET, int(inner_left + (idx + 1) * column_width) - TILE_INSET)
        for idx in range(len(matches))
    ]
    x_positions = [(left + right) // 2 for left, right in columns]

    for (left, right), match in zip(columns, matches):
        _draw_match_tile(canvas, draw, match, config, (left, inner_top, right, inner_bottom))

    _draw_rank_axis(draw, inner_left, columns, y_for, score_min, score_max)

    line_points: List[Tuple[int, int]] = []
    for x, match in zip(x_positions, matches):
        _draw_range_track(
            draw,
            x=x,
            full_range=match.get("all_role_range") or {},
            cutout_range=match.get("role_range") or {},
            y_for=y_for,
            width=ALL_ROLE_TRACK_W,
            fill=tone["range"],
        )
        _draw_range_track(
            draw,
            x=x,
            full_range=match.get("role_range") or {},
            y_for=y_for,
            width=ROLE_TRACK_W,
            outline=tone["range"],
        )
        _draw_score_distribution_bars(
            draw,
            x=x,
            scores=list(match.get("team_scores") or []) + list(match.get("enemy_scores") or []),
            y_for=y_for,
            track_width=ROLE_TRACK_W,
            fill=tone["range"],
            inner_top=inner_top,
            inner_bottom=inner_bottom,
        )

        avg_score = float(match.get("avg_score") or 0)
        if avg_score > 0:
            line_points.append((x, y_for(avg_score)))

    if len(line_points) >= 2:
        draw.line(line_points, fill=with_alpha(C.SCRIM, 215), width=10, joint="curve")
        draw.line(line_points, fill=tone["line"], width=5, joint="curve")
    for x, y in line_points:
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=C.SCRIM)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=tone["line"])

    label_top = inner_bottom + 10
    for idx, ((left, right), match) in enumerate(zip(columns, matches), start=1):
        _draw_match_label(canvas, draw, match, config, idx, (left, label_top, right, label_top + MATCH_LABEL_H - 1))


def _draw_rank_axis(
    draw: Any,
    inner_left: int,
    columns: Sequence[Tuple[int, int]],
    y_for: Any,
    score_min: int,
    score_max: int,
) -> None:
    rail_left = inner_left - 14
    for rank_index, lower in enumerate(RANK_BREAKPOINTS):
        upper = lower + 500
        if upper <= score_min or lower >= score_max:
            continue
        draw.rounded_rectangle(
            (rail_left, y_for(min(upper, score_max)) + 1, rail_left + 5, y_for(max(lower, score_min)) - 1),
            radius=2,
            fill=C.RANK_COLORS[rank_index],
        )
    font = _ui_font(21, bold=True)
    for rank_index, breakpoint in enumerate(RANK_BREAKPOINTS):
        if breakpoint < score_min or breakpoint > score_max:
            continue
        y = y_for(breakpoint)
        color = C.RANK_COLORS[rank_index]
        for left, right in columns:
            draw.line((left, y, right - 1, y), fill=with_alpha(color, 120), width=2)
        draw.text((rail_left - 10, y), _score_to_rank_cn(breakpoint), font=font, fill=color, anchor="rm")


def _rank_distribution_counts(matches: Sequence[Dict[str, Any]]) -> List[int]:
    # Count each observed participant's role rank, matching the main chart.
    counts = [0] * (len(RANK_ORDER) * 5)
    for match in matches:
        for side in ("team_scores", "enemy_scores"):
            for score in match.get(side) or []:
                try:
                    value = int(score)
                except (TypeError, ValueError, OverflowError):
                    continue
                if value >= 500:
                    counts[min((value - 500) // 100, len(counts) - 1)] += 1
    return counts


def _draw_rank_distribution(draw: Any, *, top: int, matches: Sequence[Dict[str, Any]], tone: Dict[str, Any]) -> None:
    box = (PAGE_MARGIN, top, PAGE_W - PAGE_MARGIN - 1, top + HISTOGRAM_H - 1)
    _card(draw, box, tone, "玩家段位分布", size=26)
    counts = _rank_distribution_counts(matches)
    peak = max(max(counts), 1)
    left = box[0] + CHART_PAD
    group_width = (box[2] - CHART_PAD - left) / len(RANK_ORDER)
    bar_step = (group_width - 14) / 5
    baseline = box[3] - 46
    max_height = baseline - top - 56
    font = _ui_font(22, bold=True)
    for rank_index, rank in enumerate(RANK_ORDER):
        color = C.RANK_COLORS[rank_index]
        group_left = left + rank_index * group_width + 7
        for division_index in range(5):
            count = counts[rank_index * 5 + division_index]
            bar_left = round(group_left + division_index * bar_step)
            bar_right = round(group_left + (division_index + 1) * bar_step) - 5
            if count:
                bar_height = max(4, round(max_height * count / peak))
                draw.rounded_rectangle((bar_left, baseline - bar_height, bar_right, baseline), radius=3, fill=color)
            else:
                draw.line((bar_left, baseline, bar_right, baseline), fill=with_alpha(color, 110), width=2)
        draw.text(
            (round(left + (rank_index + 0.5) * group_width), baseline + 22),
            RANK_LABELS_CN[rank],
            font=font,
            fill=color,
            anchor="mm",
        )


def _draw_legend(draw: Any, *, top: int, tone: Dict[str, Any]) -> None:
    box = (PAGE_MARGIN, top, PAGE_W - PAGE_MARGIN - 1, top + LEGEND_H - 1)
    draw.rounded_rectangle(box, radius=RADIUS_CARD + 4, fill=C.SURFACE, outline=C.STROKE, width=1)
    y = top + LEGEND_H // 2
    x = box[0] + 26
    draw.text((x, y), "图例", font=_ui_font(26, bold=True), fill=C.INK, anchor="lm")
    x += 96
    font = _ui_font(21)
    for label, swatch in (
        ("职责区间", _swatch_role_range),
        ("全职责区间", _swatch_all_role_range),
        ("玩家段位分布", _swatch_score_ticks),
        ("平均强度线", _swatch_average_line),
    ):
        swatch(draw, x, y, tone)
        draw.text((x + 52, y), label, font=font, fill=C.TEXT, anchor="lm")
        x += 52 + _measure_text(draw, label, font) + 56


def _swatch_role_range(draw: Any, x: int, y: int, tone: Dict[str, Any]) -> None:
    draw.rounded_rectangle((x + 4, y - 13, x + 36, y + 13), radius=4, outline=tone["range"], width=3)


def _swatch_all_role_range(draw: Any, x: int, y: int, tone: Dict[str, Any]) -> None:
    draw.rounded_rectangle((x + 15, y - 14, x + 25, y + 14), radius=3, fill=tone["range"])


def _swatch_score_ticks(draw: Any, x: int, y: int, tone: Dict[str, Any]) -> None:
    for offset in (-10, 0, 10):
        draw.rounded_rectangle((x + 4, y + offset - 3, x + 36, y + offset + 3), radius=3, fill=tone["range"])


def _swatch_average_line(draw: Any, x: int, y: int, tone: Dict[str, Any]) -> None:
    draw.line((x, y, x + 40, y), fill=tone["line"], width=5)
    draw.ellipse((x + 13, y - 7, x + 27, y + 7), fill=tone["line"])


def _draw_range_track(
    draw: Any,
    *,
    x: int,
    full_range: Dict[str, Any],
    cutout_range: Optional[Dict[str, Any]] = None,
    y_for: Any,
    width: int,
    fill: Optional[Tuple[int, ...]] = None,
    outline: Optional[Tuple[int, ...]] = None,
) -> None:
    full_min = int(full_range.get("min") or 0)
    full_max = int(full_range.get("max") or 0)
    if full_min <= 0 or full_max <= 0 or full_max < full_min:
        return
    for segment_min, segment_max in _split_range_segments(full_min, full_max, cutout_range=cutout_range):
        top = y_for(segment_max)
        bottom = max(y_for(segment_min), top + 4)
        draw.rounded_rectangle(
            (x - width // 2, top, x + width // 2, bottom),
            radius=4,
            fill=fill,
            outline=outline,
            width=ROLE_TRACK_OUTLINE,
        )


def _split_range_segments(
    full_min: int,
    full_max: int,
    *,
    cutout_range: Optional[Dict[str, Any]] = None,
) -> List[Tuple[int, int]]:
    if full_min <= 0 or full_max <= 0 or full_max < full_min:
        return []
    if not isinstance(cutout_range, dict):
        return [(full_min, full_max)]
    cutout_min = int(cutout_range.get("min") or 0)
    cutout_max = int(cutout_range.get("max") or 0)
    if cutout_min <= 0 or cutout_max <= 0 or cutout_max < cutout_min:
        return [(full_min, full_max)]
    if cutout_max <= full_min or cutout_min >= full_max:
        return [(full_min, full_max)]

    segments: List[Tuple[int, int]] = []
    if full_max > cutout_max:
        segments.append((max(cutout_max, full_min), full_max))
    if full_min < cutout_min:
        segments.append((full_min, min(cutout_min, full_max)))
    return segments


def _draw_match_tile(
    canvas: Any,
    draw: Any,
    match: Dict[str, Any],
    config: Dict[str, Any],
    box: Tuple[int, int, int, int],
) -> None:
    from PIL import Image

    left, top, right, bottom = box
    size = (right - left, bottom - top)
    color = _result_color(match.get("result"))
    wash = mix(color, C.SCRIM, C.STRENGTH_RESULT_TINT)
    cover = _map_cover(config, match.get("map_guid"), size)
    if cover is not None:
        cover = Image.alpha_composite(cover, Image.new("RGBA", size, (*wash, C.STRENGTH_MAP_SCRIM)))
        canvas.paste(cover, (left, top), smooth_mask(size[0], size[1], RADIUS_CHIP))
    else:
        draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS_CHIP, fill=wash)
    draw.rounded_rectangle((left, top, right - 1, top + RESULT_STRIP_H), radius=3, fill=color)
    draw.rounded_rectangle((left, bottom - RESULT_STRIP_H - 1, right - 1, bottom - 1), radius=3, fill=color)


def _draw_match_label(
    canvas: Any,
    draw: Any,
    match: Dict[str, Any],
    config: Dict[str, Any],
    index: int,
    box: Tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    color = _result_color(match.get("result"))
    draw.rounded_rectangle(box, radius=RADIUS_CHIP + 2, fill=color)
    draw.rounded_rectangle((left + 3, top + 40, right - 3, bottom - 3), radius=RADIUS_CHIP, fill=tinted(color, .12))
    pad = 12

    draw.text((left + pad, top + 21), f"{index}.", font=_ui_font(22, bold=True), fill=C.STREAK_TEXT, anchor="lm")
    draw_map_mode_icon(canvas, match.get("map_guid"), left + pad + 42, top + 8, 26, color=C.STREAK_TEXT)
    draw.text(
        (right - pad, top + 21),
        _match_result_text(match),
        font=_ui_font(28, bold=True),
        fill=C.STREAK_TEXT,
        anchor="rm",
    )

    map_name = _map_name(config, match.get("map_guid"))
    map_font = _fit_ui_font(draw, map_name, right - left - pad, 22, 15)
    draw.text(
        ((left + right) // 2, top + 62),
        _fit_text(draw, map_name, map_font, right - left - pad),
        font=map_font,
        fill=C.INK,
        anchor="mm",
    )

    meta_font = _ui_font(19)
    avg_score = float(match.get("avg_score") or 0)
    draw.text(
        (left + pad, top + 92),
        _format_match_date(int(match.get("begin_ts") or 0)),
        font=meta_font,
        fill=C.MUTED,
        anchor="lm",
    )
    draw.text((right - pad, top + 92), f"{avg_score:.0f}" if avg_score > 0 else "--", font=meta_font, fill=C.TEXT, anchor="rm")


def _draw_score_distribution_bars(
    draw: Any,
    *,
    x: int,
    scores: Sequence[Any],
    y_for: Any,
    track_width: int,
    fill: Tuple[int, ...],
    inner_top: int,
    inner_bottom: int,
) -> None:
    half_width = track_width // 2 - 1
    for score_num, count in _group_scores(scores):
        y = y_for(score_num)
        half_height = 3 + (count - 1) * 2
        y1 = max(inner_top, y - half_height)
        y2 = min(inner_bottom, y + half_height)
        if y2 <= y1:
            continue
        draw.rounded_rectangle(
            (x - half_width, y1, x + half_width, y2),
            radius=max((y2 - y1) // 2, 1),
            fill=fill,
        )


def _map_cover(config: Dict[str, Any], map_guid: Any, size: Tuple[int, int]) -> Any:
    from PIL import Image, ImageOps

    icon_url = _map_icon_url(config, map_guid)
    if not icon_url or size[0] <= 0 or size[1] <= 0:
        return None
    key = (icon_url, size)
    cover = _MAP_CACHE.get(key)
    if cover is None:
        local_path = get_cached_asset_path(icon_url, "maps")
        if not local_path or not Path(local_path).exists():
            return None
        try:
            with Image.open(local_path) as source:
                cover = ImageOps.fit(source.convert("RGBA"), size, method=Image.LANCZOS, centering=(0.5, 0.5))
        except Exception:
            return None
        if len(_MAP_CACHE) >= 64:
            _MAP_CACHE.clear()
        _MAP_CACHE[key] = cover
    return cover


def _collect_chart_scores(matches: Sequence[Dict[str, Any]]) -> List[int]:
    values: List[int] = []
    for match in matches:
        try:
            avg_score = int(float(match.get("avg_score") or 0))
        except (TypeError, ValueError):
            avg_score = 0
        if avg_score > 0:
            values.append(avg_score)

        for range_key in (
            "role_range",
            "all_role_range",
            "current_role_range",
            "current_all_role_range",
        ):
            score_range = match.get(range_key) if isinstance(match.get(range_key), dict) else {}
            for bound_key in ("min", "max"):
                try:
                    score = int(score_range.get(bound_key) or 0)
                except (TypeError, ValueError):
                    score = 0
                if score > 0:
                    values.append(score)

        for score in list(match.get("team_scores") or []) + list(match.get("enemy_scores") or []):
            try:
                score_num = int(float(score))
            except (TypeError, ValueError):
                continue
            if score_num > 0:
                values.append(score_num)
    return values


def _group_scores(scores: Sequence[Any]) -> List[Tuple[int, int]]:
    counts: Dict[int, int] = {}
    for score in scores or []:
        try:
            score_num = int(float(score))
        except (TypeError, ValueError):
            continue
        if score_num <= 0:
            continue
        counts[score_num] = counts.get(score_num, 0) + 1
    return [(score_num, counts[score_num]) for score_num in sorted(counts.keys())]


def _load_rank_flat_icon(score: float, *, size: Tuple[int, int]) -> Any:
    from PIL import Image, ImageOps

    level = _rank_icon_level_from_score(score)
    if level <= 0:
        return None
    candidates = [
        RESOURCE_DIR / "rank_flat" / f"{level}_pure.png",
        RESOURCE_DIR / "rank_flat" / f"f{level}_pure.png",
        RESOURCE_DIR / "rank_flat" / f"{level}.png",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with Image.open(path) as source:
                resized = ImageOps.contain(source.convert("RGBA"), size, method=Image.LANCZOS)
            icon = Image.new("RGBA", size, (0, 0, 0, 0))
            icon.paste(
                resized,
                ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2),
                resized,
            )
            return icon
        except Exception:
            continue
    return None


def _summary_rank_icon_size(rank_level: int) -> Tuple[int, int]:
    if rank_level in TOP_TIER_ICON_LEVELS:
        return (SUMMARY_ICON_H * 4 // 3, SUMMARY_ICON_H)
    return (SUMMARY_ICON_H, SUMMARY_ICON_H)


def _rank_icon_level_from_score(score: float) -> int:
    return strength_score_to_icon_level(score)


def _score_to_rank_cn(score: Any) -> str:
    return _rank_text_cn(score_to_rank(score))


def _rank_text_cn(rank_text: Any) -> str:
    raw = str(rank_text or "").strip()
    if not raw:
        return RANK_LABELS_CN["Unranked"]
    if raw in RANK_LABELS_CN:
        return RANK_LABELS_CN[raw]
    for key, label in RANK_LABELS_CN.items():
        prefix = f"{key} "
        if raw.startswith(prefix):
            return f"{label}{raw[len(prefix):].strip()}"
    return raw


def _match_result_text(match: Dict[str, Any]) -> str:
    try:
        result_key = int(match.get("result") or 0)
    except (TypeError, ValueError):
        result_key = 0
    return RESULT_LABELS.get(result_key, RESULT_LABELS[0])


def _map_icon_url(config: Dict[str, Any], map_guid: Any) -> str:
    item = _map_item(config, map_guid)
    return str(item.get("icon") or "").strip() if item else ""


def _map_name(config: Dict[str, Any], map_guid: Any) -> str:
    item = _map_item(config, map_guid)
    if not item:
        return str(map_guid or "").strip() or "未知地图"
    for key in ("name", "displayName", "ename"):
        text = _normalize_display_text(item.get(key))
        if text:
            return text
    return str(map_guid or "").strip() or "未知地图"


def _map_item(config: Dict[str, Any], map_guid: Any) -> Dict[str, Any]:
    target = str(map_guid or "").strip()
    for item in config.get("mapList", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("guid") or "").strip() != target:
            continue
        return item
    return {}


def _normalize_display_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    repaired = _repair_mojibake(raw)
    return repaired or raw


def _repair_mojibake(text: str) -> str:
    best = text
    best_quality = _text_quality(text)
    for encoding in ("gbk", "cp936", "gb18030"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except Exception:
            continue
        if not candidate or candidate == best:
            continue
        candidate_quality = _text_quality(candidate)
        if candidate_quality > best_quality:
            best = candidate
            best_quality = candidate_quality
            continue
        if _cjk_ratio(text) >= 0.8 and _cjk_ratio(candidate) >= 0.8 and len(candidate) + 1 < len(best):
            best = candidate
            best_quality = candidate_quality
    return best


def _text_quality(text: str) -> int:
    score = 0
    for char in text:
        if "一" <= char <= "鿿":
            score += 3
        elif char.isascii() and (char.isalnum() or char in " -_#/.()"):
            score += 1
        elif char in ("（", "）", "·"):
            score += 1
        elif ord(char) < 32:
            score -= 2
    for token in (
        "大道",
        "街",
        "神殿",
        "寺",
        "塔",
        "城",
        "村",
        "岭",
        "区",
        "站",
        "山",
        "工业",
        "港",
        "修道院",
        "机场",
        "监测站",
        "王",
        "率",
    ):
        if token in text:
            score += 3
    return score


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk_count = sum(1 for char in text if "一" <= char <= "鿿")
    return cjk_count / max(len(text), 1)


def _ui_font(size: int, *, bold: bool = False) -> Any:
    key = ("ui", int(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = load_font(int(size), name="simhei.ttf", fallback="GrotaRoundedExtraBold.otf", prefer_cjk=True, bold=bold)
        if bold and Path(getattr(font, "path", "")).name.lower() == "simhei.ttf":
            font.emulate_bold = True
        _FONT_CACHE[key] = font
    return font


def _display_font(size: int, *, oblique: bool = True) -> Any:
    key = ("display", int(size), bool(oblique))
    font = _FONT_CACHE.get(key)
    if font is None:
        name = "bignoodletoooblique.ttf" if oblique else "BigNoodleToo.ttf"
        font = load_font(int(size), name=name, fallback="BigNoodleToo.ttf" if oblique else "en2.ttf")
        font.keep_face = True
        _FONT_CACHE[key] = font
    return font


def _fit_ui_font(draw: Any, text: str, max_width: int, largest: int, smallest: int) -> Any:
    for size in range(largest, smallest - 1, -1):
        font = _ui_font(size)
        if _measure_text(draw, text, font) <= max_width:
            return font
    return _ui_font(smallest)


def _measure_text(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(str(text or ""), font=font))
    except Exception:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[2] - box[0])


def _format_match_date(begin_ts: int) -> str:
    if begin_ts <= 0:
        return "--/--"
    try:
        return dt.datetime.fromtimestamp(begin_ts / 1000).strftime("%m/%d")
    except Exception:
        return "--/--"


def _fit_text(draw: Any, text: str, font: Any, max_width: int) -> str:
    if max_width <= 0:
        return ""
    content = str(text or "")
    if _measure_text(draw, content, font) <= max_width:
        return content
    suffix = "..."
    trimmed = content
    while trimmed and _measure_text(draw, trimmed + suffix, font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + suffix) if trimmed else suffix


def _contains_cjk(text: str) -> bool:
    for char in str(text or ""):
        if (
            "㐀" <= char <= "䶿"
            or "一" <= char <= "鿿"
            or "豈" <= char <= "﫿"
        ):
            return True
    return False


def _result_color(result: Any) -> Tuple[int, int, int]:
    try:
        result_num = int(result or 0)
    except (TypeError, ValueError):
        result_num = 0
    if result_num == 1:
        return C.WIN
    if result_num == -1:
        return C.LOSS
    return C.MUTED
