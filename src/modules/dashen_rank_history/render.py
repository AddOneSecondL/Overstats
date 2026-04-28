from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    from overstats.src.modules.query_tool import get_cached_asset_path, load_query_tool
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path, load_query_tool

from .requests import fight_payload_has_content, payload_data, sport_payload_has_content


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESOURCE_DIR = PROJECT_ROOT / "overstats" / "res"
SEASON_LOGO_DIR = RESOURCE_DIR / "season_logo"
RANK_FLAT_DIR = RESOURCE_DIR / "rank_flat"
QUERY_TOOL_ASSET_DIR = RESOURCE_DIR / "query_tool_assets"
HISTORY_SUBTITLE = "历史段位"
ROLE_ORDER = {"tank": 0, "dps": 1, "healer": 2, "open": 3}
ROLE_LABELS = {
    "tank": "TANK",
    "dps": "DAMAGE",
    "healer": "SUPPORT",
    "open": "OPEN",
}
ROLE_ICON_FILENAMES = {
    "tank": "tank.png",
    "dps": "dps.png",
    "healer": "healer.png",
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def collect_missing_assets(seasons: Sequence[Dict[str, Any]]) -> List[str]:
    missing: List[str] = []
    seen = set()

    def _append(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        missing.append(path)

    if not (RESOURCE_DIR / "comp.png").exists():
        if any(bool(item.get("has_competitive")) for item in seasons):
            _append("overstats/res/comp.png")

    if not (RESOURCE_DIR / "fight.png").exists():
        if any(bool(item.get("has_stadium")) for item in seasons):
            _append("overstats/res/fight.png")

    for filename in ROLE_ICON_FILENAMES.values():
        if not (RESOURCE_DIR / filename).exists():
            _append(f"overstats/res/{filename}")

    for item in seasons:
        season = int(item.get("season") or 0)
        if season <= 0:
            continue
        if not (SEASON_LOGO_DIR / f"s{season}.png").exists():
            _append(f"overstats/res/season_logo/s{season}.png")
    return missing


def render_rank_history(
    *,
    player_name: str,
    subtitle: str = HISTORY_SUBTITLE,
    seasons: Sequence[Dict[str, Any]],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    config = _load_ow_config()
    season_cards = [_render_season_card(item, config) for item in seasons]

    if season_cards:
        max_per_row = 5
        columns = min(len(season_cards), max_per_row)
        rows = (len(season_cards) - 1) // max_per_row + 1
        canvas_width = 6 + columns * 512
        canvas_height = 1080 * rows
        image = _load_background(canvas_width, canvas_height, rows=rows)
        for index, card in enumerate(season_cards):
            row = index // max_per_row
            col = index % max_per_row
            image.paste(card, (6 + col * 512, 40 + row * 1080), card)
    else:
        image = _load_background(518, 1080, rows=1)
        draw = ImageDraw.Draw(image)
        fonts = _load_fonts()
        draw.rounded_rectangle((40, 160, 478, 920), radius=32, fill=(255, 255, 255, 160))
        draw.text((115, 390), "NO HISTORY", font=fonts["font_en_large"], fill=(255, 255, 255, 255))
        draw.text((120, 520), "未找到历史段位数据", font=fonts["font_cn"], fill=(255, 255, 255, 255))

    canvas = _decorate_with_header(image, player_name=player_name, subtitle=subtitle)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())


def _render_season_card(item: Dict[str, Any], config: Dict[str, Any]) -> Any:
    from PIL import Image, ImageDraw

    rect = Image.new("RGBA", (500, 1000), (255, 255, 255, 180))
    draw = ImageDraw.Draw(rect)
    fonts = _load_fonts()
    draw.rectangle((10, 10, 490, 990), fill=(255, 255, 255, 20))

    season = int(item.get("season") or 0)
    sport_payload = item.get("sport_payload")
    fight_payload = item.get("fight_payload")
    sport_data = payload_data(sport_payload)
    fight_data = payload_data(fight_payload)

    _paste_season_banner(rect, season)
    draw.text((15, 190), f"SEASON {season}", font=fonts["font_season_title"], fill=(255, 255, 255, 255))
    _draw_season_desc(draw, config, season, fonts)

    if sport_payload and sport_payload_has_content(sport_payload):
        _draw_competitive_block(rect, draw, sport_data, fonts)
        _draw_top_heroes(
            rect,
            draw,
            config,
            list(sport_data.get("frequentHeroIds") or []),
            fonts,
        )
    else:
        _draw_empty_mode_block(rect, draw, title="COMPETITIVE", top=460, fonts=fonts)
        fallback_heroes = [
            str(hero.get("heroGuid") or "")
            for hero in list(fight_data.get("heroUseSummaryList") or [])
            if isinstance(hero, dict) and str(hero.get("heroGuid") or "").strip()
        ]
        _draw_top_heroes(rect, draw, config, fallback_heroes, fonts)

    if fight_payload and fight_payload_has_content(fight_payload):
        _draw_stadium_block(rect, draw, fight_data, fonts)
    else:
        _draw_empty_mode_block(rect, draw, title="STADIUM", top=720, fonts=fonts)

    return rect


def _draw_competitive_block(rect: Any, draw: Any, sport_data: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    _paste_mode_icon(rect, "comp.png", (15, 460), (60, 60))
    draw.text((85, 480), "COMPETITIVE", font=fonts["font_en_small2"], fill=(255, 255, 255, 255))
    role_rows = sorted(list(sport_data.get("guideCountData") or []), key=lambda row: ROLE_ORDER.get(str(row.get("roleType") or ""), 99))

    inside_y = 0
    for row in role_rows:
        role_type = str(row.get("roleType") or "")
        if role_type == "open" and inside_y > 0:
            draw.line((30, 520 + inside_y * 50, 470, 520 + inside_y * 50), fill=(255, 255, 255, 120), width=2)
        _draw_role_row(
            rect,
            draw,
            row=row,
            top_y=528 + inside_y * 50,
            label_y=530 + inside_y * 50,
            mode_prefix="",
            fonts=fonts,
        )
        inside_y += 1


def _draw_stadium_block(rect: Any, draw: Any, fight_data: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    _paste_mode_icon(rect, "fight.png", (15, 720), (60, 60))
    draw.text((85, 740), "STADIUM", font=fonts["font_en_small2"], fill=(255, 255, 255, 255))
    role_rows = sorted(list(fight_data.get("roleTypeCountData") or []), key=lambda row: ROLE_ORDER.get(str(row.get("roleType") or ""), 99))

    inside_y = 6
    for row in role_rows:
        role_type = str(row.get("roleType") or "")
        if role_type == "open" and inside_y > 6:
            draw.line((30, 490 + inside_y * 50, 470, 490 + inside_y * 50), fill=(255, 255, 255, 120), width=2)
        _draw_role_row(
            rect,
            draw,
            row=row,
            top_y=498 + inside_y * 50,
            label_y=500 + inside_y * 50,
            mode_prefix="c",
            fonts=fonts,
        )
        inside_y += 1


def _draw_role_row(
    rect: Any,
    draw: Any,
    *,
    row: Dict[str, Any],
    top_y: int,
    label_y: int,
    mode_prefix: str,
    fonts: Dict[str, Any],
) -> None:
    role_type = _normalize_role_type(row.get("roleType"))
    role_icon = _load_role_icon(role_type, size=(28, 28))
    label_x = 30
    if role_icon is not None:
        rect.paste(role_icon, (28, top_y + 4), role_icon)
        label_x = 64
    draw.text((label_x, label_y), ROLE_LABELS.get(role_type, role_type.upper()), font=fonts["font_en_small2"], fill=(255, 255, 255, 255))
    last_rank_info = row.get("lastRankInfo") if isinstance(row.get("lastRankInfo"), dict) else {}
    max_rank_info = row.get("maxRankInfo") if isinstance(row.get("maxRankInfo"), dict) else {}
    _paste_rank_bar(rect, draw, last_rank_info, x=130, y=top_y, prefix=mode_prefix, fonts=fonts)
    _paste_rank_bar(rect, draw, max_rank_info, x=260, y=top_y, prefix=mode_prefix, fonts=fonts)

    match_sum = _safe_int(row.get("matchSum"))
    win_rate = _safe_float(row.get("winRate"))
    win_sum = int(match_sum * win_rate / 100) if match_sum > 0 else 0
    draw.text((390, label_y + 3), f"{win_sum} | {match_sum}", font=fonts["font_en_small2"], fill=(255, 255, 255, 255))


def _paste_rank_bar(
    rect: Any,
    draw: Any,
    rank_info: Dict[str, Any],
    *,
    x: int,
    y: int,
    prefix: str,
    fonts: Dict[str, Any],
) -> None:
    score = _safe_int(rank_info.get("rankScore"))
    tier = _safe_int(rank_info.get("rankSubTier"))
    if score <= 0:
        draw.text((x + 75, y + 5), "-", font=fonts["font_num"], fill=(0, 0, 0, 255))
        return

    rank_level = (score // 100) + 1
    asset = RANK_FLAT_DIR / f"{prefix}{rank_level}.png"
    if asset.exists():
        from PIL import Image

        rank_image = Image.open(asset).convert("RGBA").resize((115, 37), Image.LANCZOS)
        rect.paste(rank_image, (x, y), rank_image)
    draw.text((x + 75, y + 5), str(tier), font=fonts["font_num"], fill=(0, 0, 0, 255))


def _draw_top_heroes(
    rect: Any,
    draw: Any,
    config: Dict[str, Any],
    hero_guids: Sequence[str],
    fonts: Dict[str, Any],
) -> None:
    display_count = 0
    for hero_guid in hero_guids:
        hero_guid_text = str(hero_guid or "").strip()
        if not hero_guid_text:
            continue
        hero_info = _find_hero(config, hero_guid_text)
        if not hero_info:
            continue
        hero_name = str(hero_info.get("name") or hero_guid_text)
        ring_color = _hero_ring_color(config, hero_name)
        icon = _load_remote_asset_image(str(hero_info.get("icon") or ""), category="heroes")
        if icon is None:
            continue
        icon = crop_to_circle(icon, 15, ring_color).resize((128, 128))
        x = display_count * 155 + 30
        y = 300
        rect.paste(icon, (x, y), icon)

        text_width = _measure_text_width(draw, hero_name, fonts["font_cn_small"])
        draw.text(((x + (128 - text_width) / 2), y + 133), hero_name, font=fonts["font_cn_small"], fill=(255, 255, 255, 255))
        display_count += 1
        if display_count >= 3:
            break


def _draw_empty_mode_block(rect: Any, draw: Any, *, title: str, top: int, fonts: Dict[str, Any]) -> None:
    from PIL import Image

    icon_name = "comp.png" if title == "COMPETITIVE" else "fight.png"
    icon = _load_local_rgba(RESOURCE_DIR / icon_name)
    if icon is not None:
        icon = icon.resize((300, 300), Image.LANCZOS)
        alpha = icon.getchannel("A").point(lambda pixel: int(pixel * 0.4))
        icon.putalpha(alpha)
        rect.paste(icon, (100, top - 20), icon)
    draw.text((150, top + 130), "无赛季数据", font=fonts["font_cn"], fill=(255, 255, 255, 255))
    draw.text((85, top + 20), title, font=fonts["font_en_small2"], fill=(255, 255, 255, 180))


def _draw_season_desc(draw: Any, config: Dict[str, Any], season: int, fonts: Dict[str, Any]) -> None:
    season_info = config.get("seasonList", {}).get(str(season), {})
    if not isinstance(season_info, dict):
        return
    desc = str(season_info.get("desc") or "").strip()
    start = str(season_info.get("startTime") or "").strip()
    end = str(season_info.get("endTime") or "").strip()
    parts = [part for part in (desc, f"{start}-{end}" if start or end else "") if part]
    if parts:
        draw.text((15, 270), " ".join(parts), font=fonts["font_cn_small"], fill=(255, 255, 255, 255))


def _paste_season_banner(rect: Any, season: int) -> None:
    from PIL import Image

    banner = _load_local_rgba(SEASON_LOGO_DIR / f"s{season}.png")
    if banner is None:
        return
    target_width = 480
    max_height = 170
    width, height = banner.size
    if width <= 0 or height <= 0:
        return
    scale = target_width / width
    new_height = int(height * scale)
    banner = banner.resize((target_width, new_height), Image.LANCZOS)
    if new_height > max_height:
        top = (new_height - max_height) // 2
        banner = banner.crop((0, top, target_width, top + max_height))
    rect.paste(banner, (10, 10), banner)


def _paste_mode_icon(rect: Any, filename: str, position: tuple[int, int], size: tuple[int, int]) -> None:
    from PIL import Image

    icon = _load_local_rgba(RESOURCE_DIR / filename)
    if icon is None:
        return
    icon = icon.resize(size, Image.LANCZOS)
    rect.paste(icon, position, icon)


def _normalize_role_type(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def _load_role_icon(role_type: Any, *, size: tuple[int, int]) -> Any:
    from PIL import Image

    filename = ROLE_ICON_FILENAMES.get(_normalize_role_type(role_type))
    if not filename:
        return None
    icon = _load_local_rgba(RESOURCE_DIR / filename)
    if icon is None:
        return None
    return icon.resize(size, Image.LANCZOS)


def _decorate_with_header(base_image: Any, *, player_name: str, subtitle: str) -> Any:
    from PIL import Image, ImageDraw

    header_height = 88
    canvas = Image.new("RGBA", (base_image.width, base_image.height + header_height), (18, 22, 30, 255))
    canvas.paste(base_image, (0, header_height), base_image)
    draw = ImageDraw.Draw(canvas)
    fonts = _load_fonts()

    raw_name = str(player_name or "").strip()
    display_name = raw_name
    sub_parts = []
    if "#" in raw_name:
        battletag, battlenum = raw_name.split("#", 1)
        display_name = battletag.strip() or raw_name
        if battlenum.strip():
            sub_parts.append(f"#{battlenum.strip()}")
    if subtitle:
        sub_parts.append(str(subtitle).strip())

    name_text = display_name.upper() if display_name.isascii() else display_name
    draw.text((24, 12), name_text, font=fonts["font_player_name"], fill=(255, 255, 255, 255))
    if sub_parts:
        draw.text((24, 54), " · ".join(sub_parts), font=fonts["font_cn_small_ex"], fill=(180, 185, 195, 255))
    draw.line([(0, header_height - 1), (canvas.width, header_height - 1)], fill=(55, 61, 74, 255), width=1)
    return canvas


def _load_background(width: int, height: int, *, rows: int) -> Any:
    from PIL import Image

    background = _load_local_rgba(SEASON_LOGO_DIR / "bg.png")
    if background is None:
        return Image.new("RGBA", (width, height), (24, 34, 56, 255))

    if rows == 1 and background.width >= width and background.height >= height:
        return background.crop((0, 0, width, height))

    canvas = Image.new("RGBA", (width, height))
    row_background = background
    if background.width < width:
        row_background = background.resize((width, background.height), Image.LANCZOS)

    for row in range(rows):
        crop = row_background.crop((0, 0, width, min(1080, row_background.height)))
        canvas.paste(crop, (0, row * 1080))
    return canvas


def _load_remote_asset_image(url: str, *, category: str) -> Any:
    from PIL import Image

    asset_path = _find_cached_asset_path(url, category=category)
    if asset_path is None or not asset_path.exists():
        return None
    try:
        return Image.open(asset_path).convert("RGBA")
    except Exception:
        return None


def _find_cached_asset_path(url: str, *, category: str) -> Path | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None

    asset_path = get_cached_asset_path(normalized, category)
    if asset_path is not None and asset_path.exists():
        return asset_path

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
        print(f"[overstats] failed to load query_tool config for rank history render: {exc}")
        return {}


def _find_hero(config: Dict[str, Any], hero_guid: str) -> Dict[str, Any]:
    for hero in config.get("heroList", []) or []:
        if str(hero.get("heroGuid") or hero.get("heroId") or hero.get("guid") or hero.get("id") or "") == hero_guid:
            return hero
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


def _measure_text_width(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        try:
            box = draw.textbbox((0, 0), text, font=font)
            return int(box[2] - box[0])
        except Exception:
            return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _load_local_rgba(path: Path) -> Any:
    from PIL import Image

    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _font_resource(name: str, size: int, *, fallback: str | None = None) -> Any:
    from PIL import ImageFont

    candidates = [RESOURCE_DIR / name]
    if fallback:
        candidates.append(RESOURCE_DIR / fallback)
    candidates.extend(
        [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_chinese(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
    ):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _load_fonts() -> Dict[str, Any]:
    return {
        "font_en_header": _font_resource("bignoodletoooblique.ttf", 32, fallback="BigNoodleToo.ttf"),
        "font_en_large": _font_resource("bignoodletoooblique.ttf", 80, fallback="BigNoodleToo.ttf"),
        "font_player_name": _font_resource("bignoodletoooblique.ttf", 32, fallback="BigNoodleToo.ttf"),
        "font_season_title": _font_resource("bignoodletoooblique.ttf", 80, fallback="BigNoodleToo.ttf"),
        "font_en_small2": _font_resource("BigNoodleToo.ttf", 30, fallback="en2.ttf"),
        "font_cn": _font_chinese(40),
        "font_cn_small": _font_chinese(25),
        "font_cn_small_ex": _font_chinese(18),
        "font_num": _font_resource("num.ttf", 23, fallback="GrotaRoundedExtraBold.otf"),
    }


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    text = str(hex_color or "").lstrip("#")
    if len(text) == 6:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255)
    if len(text) == 8:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), int(text[6:8], 16))
    return (128, 128, 128, 255)


def crop_to_circle(
    image: Any,
    ring_width: int = 5,
    ring_color: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> Any:
    from PIL import Image, ImageDraw

    rgba = image.convert("RGBA")
    width, height = rgba.size
    size = min(width, height)
    cropped = rgba.crop(((width - size) // 2, (height - size) // 2, (width + size) // 2, (height + size) // 2))

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    cropped.putalpha(mask)

    ring_size = size + 2 * ring_width
    ring_image = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring_image)
    ring_draw.ellipse((0, 0, ring_size, ring_size), fill=ring_color)
    ring_draw.ellipse((ring_width, ring_width, ring_size - ring_width, ring_size - ring_width), fill=(0, 0, 0, 0))
    ring_image.paste(cropped, (ring_width, ring_width), cropped)
    return ring_image
