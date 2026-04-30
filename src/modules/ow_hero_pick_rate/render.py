from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from ...constants.backgrounds import build_random_map_background

try:
    from overstats.src.modules.query_tool import get_cached_asset_path
    from overstats.src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        QUICK_STRENGTH_THEME,
    )
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path
    from src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        QUICK_STRENGTH_THEME,
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
DEFAULT_THEME = dict(QUICK_STRENGTH_THEME)


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_pick_rate_ranking(
    *,
    game_mode: str,
    mmr: str,
    snapshot: Dict[str, Any],
    heroes: Sequence[Dict[str, Any]],
    theme: Optional[Dict[str, Any]] = None,
) -> RenderedImage:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    active_theme = _resolve_theme(theme)
    scale = 2
    base_width = 1500
    column_count = 2 if len(heroes) > 1 else 1
    rows_per_column = max(1, (len(heroes) + column_count - 1) // column_count)
    base_height = max(860, 270 + rows_per_column * 64)
    width = base_width * scale
    height = base_height * scale
    canvas = Image.new("RGBA", (width, height), (11, 17, 28, 255))
    draw = _new_draw(canvas)
    fonts = _load_fonts(scale)

    _draw_background(canvas, scale=scale)
    _draw_panel(
        draw,
        (36 * scale, 24 * scale, width - 36 * scale, 156 * scale),
        fill=(14, 22, 36, 220),
        outline=(47, 62, 88, 255),
        radius=16 * scale,
    )
    _draw_panel(
        draw,
        (36 * scale, 170 * scale, width - 36 * scale, height - 24 * scale),
        fill=(12, 19, 31, 226),
        outline=(47, 62, 88, 255),
        radius=16 * scale,
    )

    _draw_ranking_header(
        draw,
        fonts=fonts,
        scale=scale,
        theme=active_theme,
        game_mode=game_mode,
        mmr=mmr,
        snapshot=snapshot,
        heroes=heroes,
    )
    _draw_ranking_rows(
        canvas,
        draw,
        fonts=fonts,
        scale=scale,
        theme=active_theme,
        heroes=heroes,
        top=192 * scale,
        bottom=height - 46 * scale,
    )

    output = BytesIO()
    canvas = canvas.resize((base_width, base_height), Image.LANCZOS)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def render_pick_rate_history(
    *,
    game_mode: str,
    mmr: str,
    hero: Dict[str, Any],
    latest: Dict[str, Any],
    history_total: int,
    history_limit: int,
    series: Sequence[Dict[str, Any]],
    theme: Optional[Dict[str, Any]] = None,
) -> RenderedImage:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    active_theme = _resolve_theme(theme)
    scale = 2
    base_width = 1500
    base_height = 980
    width = base_width * scale
    height = base_height * scale
    canvas = Image.new("RGBA", (width, height), (11, 17, 28, 255))
    draw = _new_draw(canvas)
    fonts = _load_fonts(scale)

    _draw_background(canvas, scale=scale)
    _draw_panel(
        draw,
        (36 * scale, 24 * scale, width - 36 * scale, 158 * scale),
        fill=(14, 22, 36, 220),
        outline=(47, 62, 88, 255),
        radius=16 * scale,
    )
    _draw_panel(
        draw,
        (36 * scale, 172 * scale, width - 36 * scale, height - 24 * scale),
        fill=(12, 19, 31, 226),
        outline=(47, 62, 88, 255),
        radius=16 * scale,
    )

    _draw_history_header(
        canvas,
        draw,
        fonts=fonts,
        scale=scale,
        theme=active_theme,
        game_mode=game_mode,
        mmr=mmr,
        hero=hero,
        latest=latest,
        history_total=history_total,
        history_limit=history_limit,
        series=series,
    )
    _draw_history_chart(
        draw,
        fonts=fonts,
        scale=scale,
        theme=active_theme,
        series=series,
    )

    output = BytesIO()
    canvas = canvas.resize((base_width, base_height), Image.LANCZOS)
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _draw_ranking_header(
    draw: Any,
    *,
    fonts: Dict[str, Any],
    scale: int,
    theme: Dict[str, Any],
    game_mode: str,
    mmr: str,
    snapshot: Dict[str, Any],
    heroes: Sequence[Dict[str, Any]],
) -> None:
    title = "英雄选取率榜单"
    subtitle = f"{_game_mode_label(game_mode)} · {_mmr_label(mmr)} · 最新快照 S{snapshot.get('season')} · {snapshot.get('ds')}"
    draw.text((70 * scale, 40 * scale), title, font=fonts["font_title_cn"], fill=(242, 247, 255, 255))
    draw.text((72 * scale, 96 * scale), subtitle, font=fonts["font_sub"], fill=(165, 184, 210, 255))

    if not heroes:
        return

    top_hero = heroes[0]
    chips = [
        ("英雄总数", str(int(snapshot.get("hero_count") or len(heroes)))),
        ("Top1", str(top_hero.get("hero_name") or "--")),
        ("最高选取率", _ratio_text(float(top_hero.get("selection_ratio") or 0))),
    ]
    chip_x = 860 * scale
    for label, value in chips:
        _draw_stat_chip(
            draw,
            (chip_x, 38 * scale, chip_x + 160 * scale, 120 * scale),
            label=label,
            value=value,
            fonts=fonts,
            theme=theme,
            scale=scale,
        )
        chip_x += 176 * scale


def _draw_ranking_rows(
    canvas: Any,
    draw: Any,
    *,
    fonts: Dict[str, Any],
    scale: int,
    theme: Dict[str, Any],
    heroes: Sequence[Dict[str, Any]],
    top: int,
    bottom: int,
) -> None:
    if not heroes:
        draw.text((78 * scale, top + 32 * scale), "暂无可用的英雄选取率快照", font=fonts["font_panel_title"], fill=(186, 198, 214, 255))
        return

    column_count = 2 if len(heroes) > 1 else 1
    gap = 26 * scale
    usable_width = 1500 * scale - 72 * scale * 2
    column_width = int((usable_width - gap * (column_count - 1)) / column_count)
    rows_per_column = max(1, (len(heroes) + column_count - 1) // column_count)
    row_height = 58 * scale
    max_ratio = max(float(item.get("selection_ratio") or 0) for item in heroes) or 1.0
    bar_fill = _enhance_rgba(tuple(theme.get("range_color") or DEFAULT_THEME["range_color"]), brightness=1.18, contrast=1.12, alpha=228)
    line_color = _enhance_rgba(tuple(theme.get("line_color") or DEFAULT_THEME["line_color"]), brightness=1.06, contrast=1.04, alpha=255)

    for index, item in enumerate(heroes):
        column_index = index // rows_per_column
        row_index = index % rows_per_column
        left = 72 * scale + column_index * (column_width + gap)
        y = top + row_index * row_height
        box = (left, y, left + column_width, y + row_height - 10 * scale)
        draw.rounded_rectangle(box, radius=14 * scale, fill=(18, 29, 45, 206), outline=(50, 68, 97, 255), width=max(scale, 1))

        _paste_icon_or_placeholder(
            canvas,
            draw,
            item,
            position=(left + 10 * scale, y + 8 * scale),
            size=36 * scale,
            font=fonts["font_meta"],
        )
        draw.text((left + 58 * scale, y + 6 * scale), str(item.get("hero_name") or "--"), font=fonts["font_panel_title"], fill=(242, 247, 255, 255))
        draw.text((left + 58 * scale, y + 28 * scale), _hero_role_label(item.get("hero_role")), font=fonts["font_meta"], fill=(156, 175, 201, 255))

        rank_box = (left + 6 * scale, y + 6 * scale, left + 44 * scale, y + 40 * scale)
        draw.rounded_rectangle(rank_box, radius=10 * scale, fill=_enhance_rgba(line_color, brightness=0.94, contrast=1.0, alpha=216))
        _draw_text_center(draw, str(item.get("rank") or index + 1), rank_box, font=fonts["font_rank"], fill=(255, 255, 255, 255))

        ratio = max(0.0, min(float(item.get("selection_ratio") or 0) / max_ratio, 1.0))
        bar_left = left + 205 * scale
        bar_right = left + column_width - 152 * scale
        bar_top = y + 14 * scale
        bar_bottom = y + 34 * scale
        draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_bottom), radius=10 * scale, fill=(27, 40, 60, 218))
        draw.rounded_rectangle(
            (bar_left, bar_top, int(bar_left + max(6 * scale, (bar_right - bar_left) * ratio)), bar_bottom),
            radius=10 * scale,
            fill=bar_fill,
            outline=line_color,
            width=max(scale, 1),
        )
        draw.text((left + column_width - 142 * scale, y + 8 * scale), _ratio_text(float(item.get("selection_ratio") or 0)), font=fonts["font_panel_title"], fill=(248, 252, 255, 255))
        draw.text(
            (left + column_width - 142 * scale, y + 30 * scale),
            f"胜 {float(item.get('win_ratio') or 0):.1f}% · KDA {float(item.get('kda') or 0):.2f}",
            font=fonts["font_meta"],
            fill=(156, 175, 201, 255),
        )


def _draw_history_header(
    canvas: Any,
    draw: Any,
    *,
    fonts: Dict[str, Any],
    scale: int,
    theme: Dict[str, Any],
    game_mode: str,
    mmr: str,
    hero: Dict[str, Any],
    latest: Dict[str, Any],
    history_total: int,
    history_limit: int,
    series: Sequence[Dict[str, Any]],
) -> None:
    _paste_icon_or_placeholder(
        canvas,
        draw,
        hero,
        position=(70 * scale, 38 * scale),
        size=84 * scale,
        font=fonts["font_panel_title"],
    )
    draw.text((182 * scale, 38 * scale), str(hero.get("hero_name") or "--"), font=fonts["font_title_cn"], fill=(242, 247, 255, 255))
    draw.text(
        (184 * scale, 92 * scale),
        f"{_game_mode_label(game_mode)} · {_mmr_label(mmr)} · {_hero_role_label(hero.get('hero_role'))}",
        font=fonts["font_sub"],
        fill=(165, 184, 210, 255),
    )

    values = [float(item.get("selection_ratio") or 0) for item in series] or [float(latest.get("selection_ratio") or 0)]
    highest = max(values)
    lowest = min(values)

    chips = [
        ("最新选取率", _ratio_text(float(latest.get("selection_ratio") or 0))),
        ("历史最高", _ratio_text(highest)),
        ("历史最低", _ratio_text(lowest)),
        ("样本点", str(history_total)),
    ]
    chip_x = 806 * scale
    for label, value in chips:
        _draw_stat_chip(
            draw,
            (chip_x, 38 * scale, chip_x + 136 * scale, 120 * scale),
            label=label,
            value=value,
            fonts=fonts,
            theme=theme,
            scale=scale,
        )
        chip_x += 152 * scale


def _draw_history_chart(
    draw: Any,
    *,
    fonts: Dict[str, Any],
    scale: int,
    theme: Dict[str, Any],
    series: Sequence[Dict[str, Any]],
) -> None:
    x1 = 74 * scale
    y1 = 202 * scale
    x2 = 1426 * scale
    y2 = 928 * scale
    inner_left = x1 + 76 * scale
    inner_right = x2 - 38 * scale
    inner_top = y1 + 38 * scale
    inner_bottom = y2 - 86 * scale

    draw.text((x1, y1 - 28 * scale), "英雄选取率历史曲线", font=fonts["font_panel_title"], fill=(238, 245, 252, 255))
    draw.text((x1 + 188 * scale, y1 - 24 * scale), "折线展示最新历史点；纵轴为选取率，横轴为快照时间。", font=fonts["font_meta"], fill=(144, 162, 186, 255))

    if not series:
        draw.text((inner_left, inner_top + 64 * scale), "暂无可用的历史选取率数据", font=fonts["font_panel_title"], fill=(186, 198, 214, 255))
        return

    values = [float(item.get("selection_ratio") or 0) for item in series]
    min_value = min(values)
    max_value = max(values)
    floor_value = 0.0 if min_value > 1 else max(0.0, min_value - 0.5)
    ceil_value = max_value + max(1.0, (max_value - floor_value) * 0.12)

    def y_for(value: float) -> int:
        if ceil_value <= floor_value:
            return int((inner_top + inner_bottom) / 2)
        ratio = (float(value) - floor_value) / max(ceil_value - floor_value, 1.0)
        ratio = max(0.0, min(1.0, ratio))
        return int(inner_bottom - ratio * (inner_bottom - inner_top))

    tick_count = 5
    for idx in range(tick_count):
        tick_value = floor_value + (ceil_value - floor_value) * idx / max(tick_count - 1, 1)
        y = y_for(tick_value)
        draw.line((inner_left, y, inner_right, y), fill=(36, 51, 74, 198), width=max(scale, 1))
        draw.text((x1, y - 10 * scale), _ratio_text(tick_value), font=fonts["font_axis"], fill=(216, 226, 239, 255))

    line_color = _enhance_rgba(tuple(theme.get("line_color") or DEFAULT_THEME["line_color"]), brightness=1.04, contrast=1.04, alpha=255)
    fill_color = _enhance_rgba(tuple(theme.get("range_color") or DEFAULT_THEME["range_color"]), brightness=1.12, contrast=1.08, alpha=112)
    point_color = _enhance_rgba(line_color, brightness=1.08, contrast=1.02, alpha=255)

    if len(series) == 1:
        x_positions = [int((inner_left + inner_right) / 2)]
    else:
        step = (inner_right - inner_left) / max(len(series) - 1, 1)
        x_positions = [int(inner_left + step * idx) for idx in range(len(series))]

    line_points = [(x, y_for(float(item.get("selection_ratio") or 0))) for x, item in zip(x_positions, series)]

    if len(line_points) >= 2:
        polygon = [(line_points[0][0], inner_bottom)] + line_points + [(line_points[-1][0], inner_bottom)]
        draw.polygon(polygon, fill=fill_color)
        draw.line(line_points, fill=line_color, width=max(3 * scale, 5))

    for point_x, point_y in line_points:
        draw.ellipse(
            (point_x - 5 * scale, point_y - 5 * scale, point_x + 5 * scale, point_y + 5 * scale),
            fill=point_color,
            outline=(255, 255, 255, 210),
            width=max(scale, 1),
        )

    label_step = max(1, len(series) // 6)
    for idx, (x, item) in enumerate(zip(x_positions, series)):
        if idx % label_step != 0 and idx != len(series) - 1:
            continue
        label = f"S{int(item.get('season') or 0)}"
        date_text = str(item.get("ds") or "")[5:] or str(item.get("ds") or "")
        label_width = _measure_text(draw, label, fonts["font_meta"])
        date_width = _measure_text(draw, date_text, fonts["font_meta"])
        draw.text((int(x - label_width / 2), inner_bottom + 22 * scale), label, font=fonts["font_meta"], fill=(224, 233, 244, 255))
        draw.text((int(x - date_width / 2), inner_bottom + 44 * scale), date_text, font=fonts["font_meta"], fill=(168, 184, 204, 255))


def _draw_stat_chip(
    draw: Any,
    box: Tuple[int, int, int, int],
    *,
    label: str,
    value: str,
    fonts: Dict[str, Any],
    theme: Dict[str, Any],
    scale: int,
) -> None:
    line_color = tuple(theme.get("line_color") or DEFAULT_THEME["line_color"])
    fill_color = _enhance_rgba(line_color, brightness=0.78, contrast=0.96, alpha=188)
    draw.rounded_rectangle(box, radius=14 * scale, fill=fill_color, outline=(255, 255, 255, 38), width=max(scale, 1))
    draw.text((box[0] + 16 * scale, box[1] + 12 * scale), label, font=fonts["font_meta"], fill=(214, 224, 236, 255))
    draw.text((box[0] + 16 * scale, box[1] + 38 * scale), value, font=fonts["font_panel_title"], fill=(248, 252, 255, 255))


def _paste_icon_or_placeholder(
    canvas: Any,
    draw: Any,
    payload: Dict[str, Any],
    *,
    position: Tuple[int, int],
    size: int,
    font: Any,
) -> None:
    icon = _load_hero_icon(payload, size=size)
    if icon is not None:
        canvas.paste(icon, position, icon)
        return
    x, y = position
    draw.ellipse((x, y, x + size, y + size), fill=(32, 49, 73, 255))
    text = str(payload.get("hero_name") or payload.get("hero_guid") or "?")[:1]
    _draw_text_center(draw, text, (x, y, x + size, y + size), font=font, fill=(236, 243, 252, 255))


def _load_hero_icon(payload: Dict[str, Any], *, size: int) -> Any:
    from PIL import Image, ImageDraw, ImageOps

    hero_icon_url = str(payload.get("icon_url") or "").strip()
    if not hero_icon_url:
        return None
    local_path = get_cached_asset_path(hero_icon_url, "heroes")
    if not local_path or not Path(local_path).exists():
        return None
    try:
        with Image.open(local_path) as source:
            icon = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.LANCZOS)
    except Exception:
        return None
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    icon.putalpha(mask)
    return icon


def _draw_background(canvas: Any, *, scale: int) -> None:
    from PIL import Image, ImageFilter

    map_background = build_random_map_background(
        canvas.size,
        blur_radius=18 * scale,
        overlay=(9, 14, 23, 92),
        brightness=0.76,
        color=0.86,
    )
    if map_background is not None:
        canvas.alpha_composite(map_background)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = _new_draw(overlay)
    gradient_alpha = 116 if map_background is not None else 255
    for idx in range(canvas.height):
        ratio = idx / max(canvas.height - 1, 1)
        red = int(8 + (22 - 8) * ratio)
        green = int(14 + (24 - 14) * ratio)
        blue = int(25 + (40 - 25) * ratio)
        draw.line((0, idx, canvas.width, idx), fill=(red, green, blue, gradient_alpha))

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow_draw = _new_draw(glow)
    glow_draw.ellipse((-120 * scale, -80 * scale, 680 * scale, 520 * scale), fill=(34, 95, 179, 125))
    glow_draw.ellipse((canvas.width - 720 * scale, 30 * scale, canvas.width + 80 * scale, 600 * scale), fill=(29, 160, 187, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=48 * scale))
    overlay.alpha_composite(glow)
    canvas.alpha_composite(overlay)


def _draw_panel(
    draw: Any,
    box: Tuple[int, int, int, int],
    *,
    fill: Tuple[int, int, int, int],
    outline: Tuple[int, int, int, int],
    radius: int,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=max(2, radius // 10))


def _resolve_theme(theme: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved = dict(DEFAULT_THEME)
    if isinstance(theme, dict):
        resolved.update({key: value for key, value in theme.items() if value is not None})
    return resolved


def _game_mode_label(game_mode: str) -> str:
    return "竞技" if str(game_mode or "").strip().lower() == "competitive" else "快速"


def _mmr_label(mmr: str) -> str:
    return "全段位" if str(mmr or "").strip().lower() == "all" else str(mmr or "--")


def _hero_role_label(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "tank":
        return "重装"
    if normalized == "dps":
        return "输出"
    if normalized in {"healer", "support"}:
        return "支援"
    return normalized or "未知职责"


def _ratio_text(value: float) -> str:
    return f"{float(value or 0):.2f}%"


def _draw_text_center(draw: Any, text: str, box: Tuple[int, int, int, int], *, font: Any, fill: Tuple[int, int, int, int]) -> None:
    text_width = _measure_text(draw, text, font)
    text_height = _measure_text_height(draw, text, font)
    x = int((box[0] + box[2] - text_width) / 2)
    y = int((box[1] + box[3] - text_height) / 2) - 2
    draw.text((x, y), text, font=font, fill=fill)


def _new_draw(image: Any) -> Any:
    from PIL import ImageDraw

    return ImageDraw.Draw(image, "RGBA")


def _load_fonts(scale: int) -> Dict[str, Any]:
    return {
        "font_title_cn": _font_chinese(30 * scale, bold=True),
        "font_panel_title": _font_chinese(17 * scale, bold=True),
        "font_sub": _font_chinese(13 * scale),
        "font_meta": _font_chinese(10 * scale),
        "font_axis": _font_chinese(11 * scale, bold=True),
        "font_rank": _font_resource("BigNoodleToo.ttf", 19 * scale, fallback="en.ttf"),
    }


def _font_resource(name: str, size: int, *, fallback: str | None = None) -> Any:
    from PIL import ImageFont

    candidates = [RESOURCE_DIR / name]
    if fallback:
        candidates.append(RESOURCE_DIR / fallback)
    candidates.extend(
        [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_chinese(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _measure_text(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(str(text or ""), font=font))
    except Exception:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[2] - box[0])


def _measure_text_height(draw: Any, text: str, font: Any) -> int:
    try:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[3] - box[1])
    except Exception:
        return int(font.size if hasattr(font, "size") else 12)


def _enhance_rgba(
    color: Tuple[int, int, int, int],
    *,
    brightness: float = 1.0,
    contrast: float = 1.0,
    alpha: Optional[int] = None,
) -> Tuple[int, int, int, int]:
    red, green, blue = (
        _clamp_color((128 + (channel - 128) * contrast) * brightness)
        for channel in color[:3]
    )
    resolved_alpha = color[3] if len(color) >= 4 else 255
    if alpha is not None:
        resolved_alpha = _clamp_color(alpha)
    return (red, green, blue, resolved_alpha)


def _clamp_color(value: float) -> int:
    return max(0, min(255, int(round(value))))


__all__ = [
    "RenderedImage",
    "QUICK_STRENGTH_THEME",
    "COMPETITIVE_STRENGTH_THEME",
    "render_pick_rate_history",
    "render_pick_rate_ranking",
]
