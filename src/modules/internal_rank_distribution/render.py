from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...constants.backgrounds import build_random_map_background
from ...constants.ranks import (
    RANK_LABELS_CN,
    RANK_NAME_TO_ICON_LEVEL,
    RANK_ORDER,
    canonical_rank_name,
)

try:
    from overstats.src.modules.font_resolver import load_font
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font


RANKS = tuple(RANK_ORDER)
RANK_COLORS: dict[str, tuple[int, int, int]] = {
    "Bronze": (207, 120, 86),
    "Silver": (196, 201, 200),
    "Gold": (217, 164, 59),
    "Platinum": (149, 213, 179),
    "Emerald": (92, 211, 156),
    "Diamond": (93, 163, 241),
    "Master": (140, 230, 94),
    "Grandmaster": (135, 115, 249),
    "Champion": (108, 92, 199),
    "Unranked": (116, 132, 154),
}
TOP_TIER_ICON_LEVELS = frozenset({6, 7, 8})


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_rank_distribution(
    *,
    season: int,
    total_count: int,
    rows: Sequence[Mapping[str, Any]],
    mode_summary: Mapping[str, Any] | None = None,
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    scale = 2
    base_width, base_height = 1400, 1098
    width, height = base_width * scale, base_height * scale
    canvas = Image.new("RGBA", (width, height), (11, 17, 28, 255))
    _draw_background(canvas, scale=scale)
    draw = ImageDraw.Draw(canvas, "RGBA")
    fonts = _load_fonts(scale)

    _draw_panel(draw, (36 * scale, 24 * scale, width - 36 * scale, 112 * scale), scale=scale)
    _draw_panel(draw, (36 * scale, 128 * scale, width - 36 * scale, 930 * scale), scale=scale)
    _draw_panel(draw, (36 * scale, 950 * scale, width - 36 * scale, height - 24 * scale), scale=scale)

    draw.text((76 * scale, 48 * scale), "本赛季段位分布", font=fonts["title"], fill=(242, 247, 255, 255))

    counts = _collect_counts(rows)
    _draw_rank_bars(draw, canvas, counts=counts, total_count=total_count, fonts=fonts, scale=scale)
    _draw_status_comparison(
        draw,
        mode_summary=mode_summary,
        fonts=fonts,
        scale=scale,
    )

    output = BytesIO()
    resampling = getattr(Image, "Resampling", Image)
    canvas.resize((base_width, base_height), getattr(resampling, "LANCZOS")).save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _load_fonts(scale: int) -> dict[str, Any]:
    return {
        "title": load_font(34 * scale, prefer_cjk=True, bold=True),
        "subtitle": load_font(17 * scale, prefer_cjk=True),
        "section": load_font(19 * scale, prefer_cjk=True, bold=True),
        "rank": load_font(17 * scale, prefer_cjk=True, bold=True),
        "small": load_font(13 * scale, prefer_cjk=True),
        "tiny": load_font(10 * scale, prefer_cjk=True),
        "bar_percent": load_font(9 * scale, prefer_cjk=True),
        "comparison": load_font(20 * scale, prefer_cjk=True, bold=True),
    }


def _draw_background(canvas: Any, *, scale: int) -> None:
    from PIL import Image, ImageDraw

    background = build_random_map_background(
        canvas.size,
        blur_radius=18 * scale,
        overlay=(8, 13, 23, 108),
        brightness=0.72,
        color=0.84,
    )
    if background is not None:
        canvas.alpha_composite(background)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    for y in range(canvas.height):
        ratio = y / max(canvas.height - 1, 1)
        draw.line(
            (0, y, canvas.width, y),
            fill=(int(7 + 14 * ratio), int(13 + 14 * ratio), int(25 + 18 * ratio), 142),
        )
    canvas.alpha_composite(overlay)


def _draw_panel(draw: Any, box: tuple[int, int, int, int], *, scale: int) -> None:
    draw.rounded_rectangle(
        box,
        radius=14 * scale,
        fill=(12, 20, 33, 222),
        outline=(47, 63, 90, 255),
        width=max(2, scale),
    )


def _collect_counts(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], int]:
    counts: dict[tuple[str, int], int] = {}
    for raw_row in rows or ():
        if not isinstance(raw_row, Mapping):
            continue
        rank_bucket = canonical_rank_name(raw_row.get("rank_bucket") or raw_row.get("rankBucket")) or "Unranked"
        if rank_bucket not in (*RANKS, "Unranked"):
            rank_bucket = "Unranked"
        try:
            division = int(raw_row.get("rank_division", raw_row.get("rankDivision", 0)) or 0)
            count = int(raw_row.get("sample_count", raw_row.get("sampleCount", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if rank_bucket == "Unranked":
            division = 0
        if count > 0:
            key = (rank_bucket, division)
            counts[key] = counts.get(key, 0) + count
    return counts


def _draw_rank_bars(
    draw: Any,
    canvas: Any,
    *,
    counts: Mapping[tuple[str, int], int],
    total_count: int,
    fonts: Mapping[str, Any],
    scale: int,
) -> None:
    plot_left = 146 * scale
    plot_right = 1318 * scale
    plot_top = 200 * scale
    plot_bottom = 760 * scale
    plot_height = plot_bottom - plot_top
    max_count = max(
        [int(counts.get((rank_bucket, division), 0) or 0) for rank_bucket in RANKS for division in range(1, 6)]
        or [1]
    )
    chart_max = max(1, max_count)

    for tick_index in range(6):
        value = chart_max * tick_index / 5
        y = int(plot_bottom - plot_height * tick_index / 5)
        draw.line((plot_left, y, plot_right, y), fill=(73, 91, 119, 150), width=max(1, scale))
        tick_text = f"{int(value):,}"
        tick_width = _measure_text(draw, tick_text, fonts["tiny"])
        draw.text(
            (plot_left - tick_width - 12 * scale, y - 8 * scale),
            tick_text,
            font=fonts["tiny"],
            fill=(153, 172, 198, 255),
        )
    draw.text((78 * scale, plot_top - 32 * scale), "数量", font=fonts["tiny"], fill=(153, 172, 198, 255))

    bar_gap = 5 * scale
    group_gap = bar_gap
    group_width = (plot_right - plot_left - group_gap * (len(RANKS) - 1)) / len(RANKS)
    bar_width = max(2 * scale, int((group_width - 4 * bar_gap) // 5))
    total_bar_width = 5 * bar_width + 4 * bar_gap
    rank_icon_cache: dict[tuple[int, tuple[int, int]], Any] = {}
    for rank_index, rank_bucket in enumerate(RANKS):
        group_left = int(plot_left + rank_index * (group_width + group_gap))
        group_right = int(group_left + group_width)
        group_center = (group_left + group_right) // 2
        rank_total = sum(int(counts.get((rank_bucket, division), 0) or 0) for division in range(1, 6))
        bars_left = group_left + (group_width - total_bar_width) // 2

        # Overwatch rank divisions are displayed from 5 down to 1 within
        # every major rank, matching the in-game reading order.
        for display_index, division in enumerate(range(5, 0, -1)):
            count = int(counts.get((rank_bucket, division), 0) or 0)
            bar_x = int(bars_left + display_index * (bar_width + bar_gap))
            bar_y = plot_bottom
            if count > 0:
                bar_y = plot_bottom - max(2 * scale, int(plot_height * count / chart_max))
                color = _division_color(RANK_COLORS.get(rank_bucket, RANK_COLORS["Unranked"]), division - 1, 5)
                draw.rounded_rectangle(
                    (bar_x, bar_y, bar_x + bar_width, plot_bottom),
                    radius=4 * scale,
                    fill=color + (238,),
                )
                percent = count / max(int(total_count or 0), 1) * 100
                percent_text = f"{percent:.1f}%"
                percent_width = _measure_text(draw, percent_text, fonts["bar_percent"])
                draw.text(
                    (bar_x + (bar_width - percent_width) // 2, max(plot_top - 18 * scale, bar_y - 17 * scale)),
                    percent_text,
                    font=fonts["bar_percent"],
                    fill=(222, 233, 247, 255),
                )
            division_text = str(division)
            division_width = _measure_text(draw, division_text, fonts["tiny"])
            draw.text(
                (bar_x + (bar_width - division_width) // 2, plot_bottom + 10 * scale),
                division_text,
                font=fonts["tiny"],
                fill=(164, 182, 207, 255),
            )

        rank_label = RANK_LABELS_CN.get(rank_bucket, rank_bucket)
        label_width = _measure_text(draw, rank_label, fonts["rank"])
        draw.text(
            (group_center - label_width // 2, 800 * scale),
            rank_label,
            font=fonts["rank"],
            fill=(238, 244, 253, 255),
        )
        total_text = f"{rank_total:,} 人"
        total_width = _measure_text(draw, total_text, fonts["tiny"])
        draw.text(
            (group_center - total_width // 2, 828 * scale),
            total_text,
            font=fonts["tiny"],
            fill=(137, 159, 186, 255),
        )
        # Rank icons intentionally sit below the x-axis labels, matching the
        # chart's grouped-bar reading order.
        icon_level = RANK_NAME_TO_ICON_LEVEL.get(rank_bucket, 0)
        icon_height = 54 * scale
        icon_width = (72 if icon_level in TOP_TIER_ICON_LEVELS else 54) * scale
        icon_bottom = 895 * scale
        _draw_rank_icon(
            canvas,
            level=icon_level,
            position=(group_center - icon_width // 2, icon_bottom - icon_height),
            size=(icon_width, icon_height),
            cache=rank_icon_cache,
        )


def _draw_status_comparison(
    draw: Any,
    *,
    mode_summary: Mapping[str, Any] | None,
    fonts: Mapping[str, Any],
    scale: int,
) -> None:
    mode_summary = mode_summary or {}

    def count(*keys: str) -> int:
        for key in keys:
            if key in mode_summary:
                try:
                    return max(0, int(mode_summary.get(key) or 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    quick_count = count(
        "pure_quick_player_count", "pureQuickPlayerCount", "quick_count", "quickCount"
    )
    competitive_count = count(
        "competitive_player_count", "competitivePlayerCount", "competitive_count", "competitiveCount"
    )
    eligible_count = quick_count + competitive_count
    quick_percent = quick_count / eligible_count * 100 if eligible_count else 0.0
    competitive_percent = competitive_count / eligible_count * 100 if eligible_count else 0.0

    draw.text(
        (92 * scale, 974 * scale),
        f"纯快速  {quick_percent:.1f}%",
        font=fonts["comparison"],
        fill=(186, 201, 220, 255),
    )
    draw.text(
        (830 * scale, 974 * scale),
        f"竞技  {competitive_percent:.1f}%",
        font=fonts["comparison"],
        fill=(205, 235, 255, 255),
    )

    center_x = 700 * scale
    bar_top = 1024 * scale
    bar_bottom = 1050 * scale
    half_width = 560 * scale
    bar_left = center_x - half_width
    bar_right = center_x + half_width
    track_fill = (30, 42, 61, 255)
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_right, bar_bottom),
        radius=8 * scale,
        fill=track_fill,
        outline=(65, 82, 108, 220),
        width=max(1, scale),
    )

    # Fill the complete track with two adjacent segments.  Normalizing here
    # prevents a stale/over-counted total from leaving an unpainted section.
    share_total = max(quick_percent + competitive_percent, 0.0)
    if share_total > 0:
        quick_share = max(0.0, min(quick_percent / share_total, 1.0))
        split_x = int(round(bar_left + (bar_right - bar_left) * quick_share))
        if split_x > bar_left:
            draw.rounded_rectangle(
                (bar_left, bar_top, split_x, bar_bottom),
                radius=8 * scale,
                fill=(116, 132, 154, 244),
            )
        if split_x < bar_right:
            draw.rounded_rectangle(
                (split_x, bar_top, bar_right, bar_bottom),
                radius=8 * scale,
                fill=(93, 163, 241, 244),
            )
        # Remove the inner rounded corners at the join so there is no dark
        # notch between the two percentage segments.
        seam_half_width = 8 * scale
        draw.rectangle(
            (max(bar_left, split_x - seam_half_width), bar_top, min(bar_right, split_x + seam_half_width), bar_bottom),
            fill=(93, 163, 241, 244) if split_x < bar_right else (116, 132, 154, 244),
        )
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_right, bar_bottom),
            radius=8 * scale,
            outline=(65, 82, 108, 220),
            width=max(1, scale),
        )
def _division_color(base: tuple[int, int, int], index: int, count: int) -> tuple[int, int, int]:
    if count <= 1:
        return base
    factors = (1.20, 1.08, 1.0, 0.91, 0.82)
    factor = factors[min(index, len(factors) - 1)]
    return tuple(max(0, min(255, int(channel * factor))) for channel in base)


def _draw_rank_icon(
    canvas: Any,
    *,
    level: int,
    position: tuple[int, int],
    size: tuple[int, int],
    cache: dict[tuple[int, tuple[int, int]], Any],
) -> None:
    if level <= 0:
        return
    key = (level, size)
    if key not in cache:
        cache[key] = _load_rank_icon(level, size=size)
    icon = cache[key]
    if icon is not None:
        canvas.paste(icon, position, icon)


def _load_rank_icon(level: int, *, size: tuple[int, int]) -> Any:
    from PIL import Image, ImageOps

    resource_dir = Path(__file__).resolve().parents[3] / "res"
    resampling = getattr(Image, "Resampling", Image)
    for filename in (f"{level}_pure.png", f"f{level}_pure.png", f"{level}.png"):
        path = resource_dir / "rank_flat" / filename
        if not path.exists():
            continue
        try:
            with Image.open(path) as image:
                source = image.convert("RGBA")
                contained = ImageOps.contain(source, size, method=getattr(resampling, "LANCZOS"))
                icon = Image.new("RGBA", size, (0, 0, 0, 0))
                icon.paste(
                    contained,
                    ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2),
                    contained,
                )
                return icon
        except Exception:
            continue
    return None


def _measure_text(draw: Any, text: str, font: Any) -> int:
    try:
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        return max(0, right - left)
    except Exception:
        return len(str(text)) * 12
