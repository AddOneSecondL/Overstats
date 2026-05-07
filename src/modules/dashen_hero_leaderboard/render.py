from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from typing import Any, Dict, Sequence

from ...constants.backgrounds import build_random_map_background

try:
    from overstats.src.modules.query_tool import get_cached_asset_path
except ModuleNotFoundError:
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
RANK_ICON_DIR = RESOURCE_DIR / "rank_flat"
TITLE_FILL = (245, 247, 252, 255)
SUBTITLE_FILL = (189, 198, 214, 255)
CARD_FILL = (23, 32, 52, 224)
CARD_OUTLINE = (66, 84, 120, 255)


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_hero_leaderboard(
    *,
    province: str,
    hero: Dict[str, Any],
    mode_label: str,
    entry_count: int,
    groups: Sequence[Dict[str, Any]],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    accent = _parse_rgba(hero.get("accent_color") or "#5E001AFF")
    width = 1110
    padding_x = 30
    padding_y = 28
    header_height = 138
    group_title_height = 44
    card_w = 190
    card_h = 56
    card_gap = 10
    cards_per_row = 5
    total_height = padding_y + header_height
    for group in groups:
        item_count = len(list(group.get("entries") or []))
        rows = max(1, (item_count + cards_per_row - 1) // cards_per_row)
        total_height += group_title_height + rows * (card_h + card_gap) + 10
    total_height = max(total_height + padding_y, 240)

    canvas = Image.new("RGBA", (width, total_height), (13, 18, 30, 255))
    draw = ImageDraw.Draw(canvas)
    fonts = _load_fonts()
    _draw_background(canvas)

    draw.rounded_rectangle(
        (20, 18, width - 20, total_height - 18),
        radius=24,
        fill=(12, 18, 31, 188),
        outline=(*accent[:3], 140),
        width=2,
    )

    _paste_hero_icon(
        canvas,
        hero,
        position=(padding_x, padding_y),
        size=78,
        ring_color=accent,
    )
    draw.text((122, padding_y), "Dashen 英雄排行榜", font=fonts["title"], fill=TITLE_FILL)
    draw.text(
        (122, padding_y + 44),
        f"{province} / {hero.get('hero_name') or '-'} / {mode_label} / 共 {entry_count} 人",
        font=fonts["subtitle"],
        fill=SUBTITLE_FILL,
    )
    draw.text(
        (122, padding_y + 78),
        "按段位分组，组内按分数降序排列",
        font=fonts["meta"],
        fill=(154, 168, 192, 255),
    )
    draw.line((padding_x, padding_y + 110, width - padding_x, padding_y + 110), fill=(*accent[:3], 220), width=3)

    y_cursor = padding_y + header_height
    for group in groups:
        entries = list(group.get("entries") or [])
        rank_label = str(group.get("rank_label") or "未定级")
        rank_icon_level = int(group.get("rank_icon_level") or 0)
        title_x = padding_x
        icon = _load_rank_icon(rank_icon_level, size=(32, 32))
        if icon is not None:
            canvas.paste(icon, (title_x, y_cursor - 2), icon)
            title_x += 40
        draw.text((title_x, y_cursor), f"{rank_label} / {len(entries)}人", font=fonts["group"], fill=accent)
        draw.line((padding_x, y_cursor + 30, width - padding_x, y_cursor + 30), fill=(*accent[:3], 170), width=2)
        y_cursor += group_title_height

        for index, entry in enumerate(entries):
            row = index // cards_per_row
            col = index % cards_per_row
            left = padding_x + col * (card_w + card_gap)
            top = y_cursor + row * (card_h + card_gap)
            right = left + card_w
            bottom = top + card_h
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=8,
                fill=CARD_FILL,
                outline=CARD_OUTLINE,
                width=1,
            )
            user_name = str(entry.get("user_name") or "-")
            user_name = user_name[:11] + ".." if len(user_name) > 11 else user_name
            draw.text(
                (left + 10, top + 7),
                f"#{int(entry.get('rank_num') or 0)} {user_name}",
                font=fonts["card_title"],
                fill=TITLE_FILL,
            )
            draw.text(
                (left + 10, top + 31),
                f"{int(entry.get('ranked_level') or 0)}分 / {int(entry.get('wins') or 0)}/{int(entry.get('match_sum') or 0)}场",
                font=fonts["card_meta"],
                fill=SUBTITLE_FILL,
            )
            rate_text = f"{float(entry.get('win_rate') or 0):.2f}%"
            rate_w = _measure_text(draw, rate_text, fonts["score"])
            draw.text((right - 10 - rate_w, top + 15), rate_text, font=fonts["score"], fill=(*accent[:3], 255))

        y_cursor += max(1, (len(entries) + cards_per_row - 1) // cards_per_row) * (card_h + card_gap) + 10

    output = BytesIO()
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _draw_background(canvas: Any) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    background = build_random_map_background(
        canvas.size,
        blur_radius=16,
        overlay=(8, 12, 18, 128),
        brightness=0.55,
        color=0.7,
    )
    if background is not None:
        canvas.alpha_composite(background)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(canvas.height):
        ratio = y / max(canvas.height - 1, 1)
        draw.line(
            (0, y, canvas.width, y),
            fill=(
                int(8 + 14 * ratio),
                int(12 + 18 * ratio),
                int(20 + 26 * ratio),
                185,
            ),
        )
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((-120, -100, 580, 420), fill=(31, 84, 170, 72))
    glow_draw.ellipse((canvas.width - 520, 40, canvas.width + 80, 520), fill=(18, 150, 172, 48))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=48))
    overlay.alpha_composite(glow)
    canvas.alpha_composite(overlay)


def _paste_hero_icon(
    canvas: Any,
    hero: Dict[str, Any],
    *,
    position: tuple[int, int],
    size: int,
    ring_color: tuple[int, int, int, int],
) -> None:
    icon = _load_hero_icon(hero, size=size, ring_color=ring_color)
    if icon is None:
        return
    canvas.paste(icon, position, icon)


def _load_hero_icon(payload: Dict[str, Any], *, size: int, ring_color: tuple[int, int, int, int]) -> Any:
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ModuleNotFoundError:
        return None
    hero_icon_url = str(payload.get("icon_url") or "").strip()
    if not hero_icon_url:
        return None
    local_path = get_cached_asset_path(hero_icon_url, "heroes")
    if not local_path or not Path(local_path).exists():
        return None
    try:
        with Image.open(local_path) as source:
            icon = ImageOps.fit(source.convert("RGBA"), (size - 8, size - 8), method=_resampling_lanczos())
    except Exception:
        return None
    mask = Image.new("L", icon.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, icon.size[0], icon.size[1]), fill=255)
    icon.putalpha(mask)
    outer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    outer_draw = ImageDraw.Draw(outer)
    outer_draw.ellipse((0, 0, size - 1, size - 1), fill=ring_color)
    outer_draw.ellipse((4, 4, size - 5, size - 5), fill=(0, 0, 0, 0))
    outer.paste(icon, (4, 4), icon)
    return outer


def _load_rank_icon(rank_icon_level: int, *, size: tuple[int, int]) -> Any:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return None
    if rank_icon_level <= 0:
        return None
    path = RANK_ICON_DIR / f"{rank_icon_level}_pure.png"
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            return image.convert("RGBA").resize(size, _resampling_lanczos())
    except Exception:
        return None


def _load_fonts() -> Dict[str, Any]:
    try:
        from PIL import ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    return {
        "title": _load_font("simhei.ttf", 34, windows_fallback=True),
        "subtitle": _load_font("simhei.ttf", 21, windows_fallback=True),
        "meta": _load_font("simhei.ttf", 16, windows_fallback=True),
        "group": _load_font("simhei.ttf", 22, windows_fallback=True),
        "card_title": _load_font("simhei.ttf", 17, windows_fallback=True),
        "card_meta": _load_font("simhei.ttf", 13, windows_fallback=True),
        "score": _load_font("num.ttf", 20),
    }


def _load_font(name: str, size: int, *, windows_fallback: bool = False) -> Any:
    from PIL import ImageFont

    candidates = [RESOURCE_DIR / name]
    if windows_fallback:
        windir = os.getenv("WINDIR")
        if windir:
            fonts_dir = Path(windir) / "Fonts"
            if name.lower() == "simhei.ttf":
                candidates.extend([fonts_dir / "simhei.ttf", fonts_dir / "msyh.ttc", fonts_dir / "msyhbd.ttc"])
            else:
                candidates.extend([fonts_dir / name, fonts_dir / "arial.ttf"])
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _measure_text(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])


def _parse_rgba(value: str) -> tuple[int, int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255)
    if len(text) == 8:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16))
    return (94, 0, 26, 255)


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")


__all__ = [
    "RenderedImage",
    "render_hero_leaderboard",
]
