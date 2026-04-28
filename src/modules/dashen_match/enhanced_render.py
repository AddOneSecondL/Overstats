from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import math
import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.src.modules.dashen_summary.runtime.db import IDPoolDB
    from overstats.src.client.apiclient import _find_cached_remote_image_path
    from overstats.src.modules.dashen_summary.runtime.stat_reference import (
        HERO_AVG_SKIP_VALUE_GUIDS,
        classify_hero_average_band,
        get_cached_statmap_summary,
        get_hero_avg_percent_guids,
        is_hero_avg_percent_stat,
        is_hero_avg_raw_stat,
        normalize_dashen_hero_stat_value,
        normalize_hero_rank_score,
    )
except ModuleNotFoundError:
    from src.client.apiclient import _find_cached_remote_image_path
    from src.modules.dashen_summary.runtime.db import IDPoolDB
    from src.modules.dashen_summary.runtime.stat_reference import (
        HERO_AVG_SKIP_VALUE_GUIDS,
        classify_hero_average_band,
        get_cached_statmap_summary,
        get_hero_avg_percent_guids,
        is_hero_avg_percent_stat,
        is_hero_avg_raw_stat,
        normalize_dashen_hero_stat_value,
        normalize_hero_rank_score,
    )

from .render import (
    RenderedImage,
    _cached_path_for_url,
    _extract_player_perks,
    _find_hero,
    _find_map,
    _fit_text,
    _font,
    _font_chinese,
    _font_meta,
    _font_num_display,
    _hero_icon_url,
    _load_role_icon_asset,
    _load_ow_config,
    _paste_perk_icon,
    _resize_image,
    _resolve_player_hero,
    _text_size,
    _text_width,
)


MATCH_STATS_DB = IDPoolDB()
GAME_TIME_GUID = "603482350067646497"
KILL_GUID = "603482350067646495"
ASSIST_GUID = "603482350067648392"
DEATH_GUID = "603482350067646506"
FINAL_HIT_GUID = "603482350067648623"
TITLE_COLOR_RE = re.compile(r"^#([0-9A-Fa-f]{6})$")
MAX_GROUP_TITLES_PER_PLAYER = 3
HIGHLIGHT_COLORS = {
    "above_median": (96, 216, 135, 255),
    "top20": (90, 169, 255, 255),
    "top10": (177, 135, 255, 255),
    "top5": (255, 176, 74, 255),
    "top2": (255, 220, 120, 255),
}


def _pil_to_rendered(image: Any) -> RenderedImage:
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _open_rendered(rendered: RenderedImage) -> Any:
    from PIL import Image

    with Image.open(BytesIO(rendered.content)) as image:
        return image.convert("RGBA")


def _measure(draw: Any, text: Any, font: Any) -> int:
    return _text_width(draw, str(text or ""), font)


def _normalize_title_color(raw_color: Any) -> Optional[str]:
    text = str(raw_color or "").strip()
    match = TITLE_COLOR_RE.fullmatch(text)
    if not match:
        return None
    return f"#{match.group(1).upper()}"


def _contrast_text_color(bg_hex: Any) -> tuple[int, int, int]:
    normalized = _normalize_title_color(bg_hex) or "#4B5563"
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return (24, 28, 38) if luminance >= 186 else (255, 255, 255)


def _group_titles(bnet_id: Any) -> list[dict[str, Any]]:
    cache_key = str(bnet_id or "").strip()
    if not cache_key or cache_key.lower() == "none":
        return []
    try:
        return MATCH_STATS_DB.get_group_titles(cache_key) or []
    except Exception:
        return []


def _truncate(draw: Any, text: Any, font: Any, max_width: int, suffix: str = "...") -> str:
    content = str(text or "")
    if max_width <= 0:
        return ""
    if _text_size(draw, content, font)[0] <= max_width:
        return content
    suffix_w = _text_size(draw, suffix, font)[0]
    if suffix_w >= max_width:
        return content[:1]
    built = ""
    for char in content:
        candidate = built + char
        if _text_size(draw, candidate, font)[0] + suffix_w > max_width:
            break
        built = candidate
    return (built or content[:1]) + suffix


def _fit_font_for_badge(draw: Any, text: str, max_text_width: int, max_size: int, min_size: int) -> Any:
    for size in range(max_size, min_size - 1, -1):
        font = _font(size)
        if _text_size(draw, text, font)[0] <= max_text_width:
            return font
    return _font(min_size)


def _draw_title_badges(
    draw: Any,
    title_list: Sequence[dict[str, Any]],
    start_x: int,
    center_y: int,
    max_x: int,
    *,
    badge_height: int = 24,
    badge_gap: int = 8,
    max_badge_width: int = 118,
    min_badge_width: int = 44,
    padding_x: int = 10,
    max_font_size: int = 14,
    min_font_size: int = 10,
) -> None:
    curr_x = int(start_x)
    top = int(center_y - badge_height / 2)
    for title_item in (title_list or [])[:MAX_GROUP_TITLES_PER_PLAYER]:
        badge_text = str((title_item or {}).get("title") or "").strip()
        if not badge_text:
            continue
        available_width = min(max_badge_width, int(max_x) - curr_x)
        if available_width < min_badge_width:
            break
        fill_hex = _normalize_title_color((title_item or {}).get("color")) or "#4B5563"
        font = _fit_font_for_badge(draw, badge_text, max(8, available_width - padding_x * 2), max_font_size, min_font_size)
        display_text = _truncate(draw, badge_text, font, max(8, available_width - padding_x * 2))
        text_w, text_h = _text_size(draw, display_text, font)
        badge_width = min(available_width, max(min_badge_width, int(text_w + padding_x * 2)))
        draw.rounded_rectangle((curr_x, top, curr_x + badge_width, top + badge_height), radius=min(8, badge_height // 2), fill=fill_hex)
        draw.text((curr_x + (badge_width - text_w) / 2, top + (badge_height - text_h) / 2), display_text, font=font, fill=_contrast_text_color(fill_hex))
        curr_x += badge_width + badge_gap


def decorate_image_with_player_title_header(base_image: Any, player_name: str, bnet_id: Any = None, subtitle: str = "") -> Any:
    from PIL import Image, ImageDraw

    if base_image is None:
        return None
    source = base_image.convert("RGBA") if getattr(base_image, "mode", "") != "RGBA" else base_image
    header_height = 88
    canvas = Image.new("RGBA", (source.width, source.height + header_height), (18, 22, 30, 255))
    canvas.paste(source, (0, header_height), source)
    draw = ImageDraw.Draw(canvas)
    font_name = _font_chinese(32)
    font_sub = _font_chinese(18)

    raw_name = str(player_name or "").strip()
    display_name = raw_name
    sub_parts: List[str] = []
    if "#" in raw_name:
        tag, num = raw_name.split("#", 1)
        display_name = tag.strip() or raw_name
        if num.strip():
            sub_parts.append(f"#{num.strip()}")
    if subtitle:
        sub_parts.append(str(subtitle).strip())

    draw.text((24, 12), display_name, font=font_name, fill=(255, 255, 255, 255))
    title_list = _group_titles(bnet_id)
    if title_list:
        name_width = _measure(draw, display_name, font_name)
        _draw_title_badges(draw, title_list, 24 + name_width + 18, 30, canvas.width - 24, badge_height=28, badge_gap=10, max_badge_width=138, min_badge_width=58, max_font_size=16, min_font_size=11)
    if sub_parts:
        draw.text((24, 54), " | ".join(sub_parts), font=font_sub, fill=(180, 185, 195, 255))
    draw.line([(0, header_height - 1), (canvas.width, header_height - 1)], fill=(55, 61, 74, 255), width=1)
    return canvas


def decorate_rendered_image_header(rendered: RenderedImage, player_name: str, bnet_id: Any = None, subtitle: str = "") -> RenderedImage:
    return _pil_to_rendered(decorate_image_with_player_title_header(_open_rendered(rendered), player_name, bnet_id=bnet_id, subtitle=subtitle))


def _load_icon_rgba(url: str, *, size: tuple[int, int]) -> Any:
    from PIL import Image

    path = _cached_path_for_url(url, ("heroes", "misc", "maps", "perk", "hero_perks"))
    if (not path or not path.exists()) and url:
        path = _find_cached_remote_image_path(url)
    if not path or not path.exists():
        return None
    try:
        with Image.open(path) as raw_icon:
            return _resize_image(raw_icon.convert("RGBA"), size)
    except Exception:
        return None


def build_target_hero_icons(hero_list: Sequence[dict[str, Any]], *, size: int = 36) -> list[Any]:
    icons = []
    config = _load_ow_config()
    for hero in list(hero_list or [])[:6]:
        hero_info = _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
        icon = _load_icon_rgba(_hero_icon_url(hero_info, hero), size=(size, size))
        if icon is not None:
            icons.append(icon)
    return icons


def _format_stat_value(value: Any, value_text: str = "", value_guid: Any = None) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value or "-")
    if is_hero_avg_percent_stat(value_text):
        percent = numeric * 100 if abs(numeric) <= 1 else numeric
        text = f"{percent:.1f}"
        if text.endswith(".0"):
            text = text[:-2]
        return f"{text}%"
    if is_hero_avg_raw_stat(value_text, value_guid) or abs(numeric) >= 100:
        return f"{int(round(numeric)):,}"
    text = f"{numeric:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return text


def _format_avg_value(value: Any, value_text: str = "") -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if is_hero_avg_percent_stat(value_text):
        return f"{numeric:.1%}"
    if abs(numeric) >= 100:
        return f"{int(round(numeric)):,}"
    text = f"{numeric:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _hero_attr_lookup(config: Dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = defaultdict(dict)
    for item in config.get("heroAttrList", []) or []:
        hero_guid = str(item.get("heroGuid") or "")
        value_guid = str(item.get("valueGuid") or "")
        if hero_guid and value_guid:
            lookup[hero_guid][value_guid] = item
    return lookup


def _build_hero_average_comparison(
    config: Dict[str, Any],
    hero_guid: Any,
    stat_map: Dict[str, Any],
    user_time_sec: Any,
    rank_score: Any = None,
) -> dict[str, dict[str, Any]]:
    hero_guid = str(hero_guid or "")
    if not hero_guid or not stat_map:
        return {}
    stat_guids = [str(guid) for guid in stat_map.keys()]
    rank_bucket = normalize_hero_rank_score(rank_score)
    rank_buckets = [rank_bucket] if rank_bucket is not None else None
    ratio_stat_guids = get_hero_avg_percent_guids(config, stat_guids)
    references = get_cached_statmap_summary(
        MATCH_STATS_DB,
        hero_guid,
        stat_guids,
        rank_buckets,
        ratio_stat_guids,
        rank_bucket is not None,
    )
    attr_lookup = _hero_attr_lookup(config).get(hero_guid, {})
    results = {}
    for guid, raw_value in (stat_map or {}).items():
        guid = str(guid)
        if guid in HERO_AVG_SKIP_VALUE_GUIDS:
            continue
        attr = attr_lookup.get(guid, {})
        normalized = normalize_dashen_hero_stat_value(raw_value, user_time_sec, attr.get("valueText", ""), guid)
        if normalized is None:
            continue
        ref = references.get((guid, rank_bucket)) or references.get((guid, None))
        if not ref:
            continue
        if guid == DEATH_GUID:
            if ref.get("bottom2") is not None and normalized <= ref["bottom2"]:
                band = "top2"
            elif ref.get("bottom5") is not None and normalized <= ref["bottom5"]:
                band = "top5"
            elif ref.get("bottom10") is not None and normalized <= ref["bottom10"]:
                band = "top10"
            elif ref.get("bottom20") is not None and normalized <= ref["bottom20"]:
                band = "top20"
            elif ref.get("avg") is not None and normalized < ref["avg"]:
                band = "above_median"
            else:
                band = "below_median"
        else:
            band = classify_hero_average_band(normalized, ref)
        results[guid] = {"band": band, "avg": ref.get("avg")}
    return results


def _hero_stat_rows(
    config: Dict[str, Any],
    hero: dict[str, Any],
    *,
    rank_info: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
    stat_map = hero.get("statMap", {}) or {}
    if not hero_guid or not stat_map:
        return []
    attr_lookup = _hero_attr_lookup(config).get(hero_guid, {})
    compare_map = _build_hero_average_comparison(
        config,
        hero_guid,
        stat_map,
        stat_map.get(GAME_TIME_GUID, 0),
        (rank_info or {}).get("rankScore"),
    )
    preferred_order = {KILL_GUID: 0, ASSIST_GUID: 1, DEATH_GUID: 2, FINAL_HIT_GUID: 3}
    rows = []
    for raw_guid, raw_value in stat_map.items():
        guid = str(raw_guid)
        attr = attr_lookup.get(guid, {})
        label = str(attr.get("valueText") or guid)
        value_type = str(attr.get("valueType") or "")
        compare = compare_map.get(guid) or {}
        rows.append(
            {
                "guid": guid,
                "label": label,
                "value_text": _format_stat_value(raw_value, label, guid),
                "value_type": value_type,
                "band": compare.get("band", "unknown"),
                "avg_text": _format_avg_value(compare.get("avg"), label),
            }
        )

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        if item["guid"] in preferred_order:
            return (0, preferred_order[item["guid"]], item["guid"])
        if "common" in item["value_type"].lower():
            group = 1
        elif "special" in item["value_type"].lower():
            group = 2
        else:
            group = 3
        return (group, 0, item["label"])

    rows.sort(key=sort_key)
    return rows


def _draw_legend(draw: Any, x: int, y: int, font: Any) -> None:
    legend = [
        ("颜色说明：", (185, 194, 210, 255)),
        ("高于均值", HIGHLIGHT_COLORS["above_median"]),
        ("  前20%", HIGHLIGHT_COLORS["top20"]),
        ("  前10%", HIGHLIGHT_COLORS["top10"]),
        ("  前5%", HIGHLIGHT_COLORS["top5"]),
        ("  前2%", HIGHLIGHT_COLORS["top2"]),
        ("  阵亡反向", (185, 194, 210, 255)),
    ]
    current_x = x
    for text, color in legend:
        draw.text((current_x, y), text, font=font, fill=color)
        current_x += _measure(draw, text, font)


def render_player_hero_detail(
    player_name: str,
    player_detail: dict[str, Any],
    *,
    match_game_time_sec: Any = None,
) -> RenderedImage:
    from PIL import Image, ImageDraw

    config = _load_ow_config()
    hero_list = list(player_detail.get("heroList") or [])
    hero_list.sort(key=lambda item: float((item.get("statMap") or {}).get(GAME_TIME_GUID, 0) or 0), reverse=True)

    card_width = 1140
    page_padding = 28
    card_gap = 18
    grid_gap = 14
    stat_row_h = 28
    legend_h = 52

    if not hero_list:
        image = Image.new("RGBA", (card_width, 220), (20, 24, 34, 255))
        draw = ImageDraw.Draw(image)
        draw.text((36, 38), f"{player_name} 对局详细", font=_font_chinese(32), fill=(255, 255, 255, 255))
        draw.text((36, 110), "这场没有可用的英雄详细数据。", font=_font_chinese(22), fill=(200, 208, 220, 255))
        return _pil_to_rendered(image)

    layout_rows = []
    total_height = page_padding + legend_h
    for hero in hero_list:
        stat_rows = _hero_stat_rows(config, hero, rank_info=player_detail.get("rankInfo") or {})
        rows_per_col = max(1, math.ceil(len(stat_rows) / 2))
        block_h = 100 + rows_per_col * stat_row_h + 18
        layout_rows.append((hero, stat_rows, block_h))
        total_height += block_h + card_gap
    total_height += page_padding

    image = Image.new("RGBA", (card_width, total_height), (18, 22, 30, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((page_padding, 20), "对局详细数据", font=_font_chinese(28), fill=(255, 255, 255, 255))
    _draw_legend(draw, page_padding, 58, _font_chinese(14))

    hero_lookup = {str(hero.get("heroGuid")): hero for hero in config.get("heroList", []) or [] if hero.get("heroGuid")}
    y = page_padding + legend_h
    for hero, stat_rows, block_h in layout_rows:
        box = (page_padding, y, card_width - page_padding, y + block_h)
        draw.rounded_rectangle(box, radius=16, fill=(33, 38, 52, 255), outline=(72, 90, 118, 180), width=2)
        header_box = (box[0], box[1], box[2], box[1] + 78)
        draw.rounded_rectangle(header_box, radius=16, fill=(43, 50, 66, 255))
        draw.rectangle((header_box[0], header_box[1] + 52, header_box[2], header_box[3]), fill=(43, 50, 66, 255))

        hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
        hero_info = hero_lookup.get(hero_guid) or _find_hero(config, hero_guid)
        hero_name = hero_info.get("name") or hero_guid or "未知英雄"
        role_type = str(hero_info.get("roleType") or "").lower()
        role_fill = {"tank": (76, 157, 255, 230), "dps": (255, 122, 94, 230), "healer": (88, 199, 126, 230)}.get(role_type, (148, 154, 170, 220))
        icon = _load_icon_rgba(_hero_icon_url(hero_info, hero), size=(54, 54))
        if icon is not None:
            image.paste(icon, (box[0] + 20, box[1] + 12), icon)
        role_icon = _load_role_icon_asset(role_type, size=(30, 30))
        hero_text_x = box[0] + 178
        if role_icon is not None:
            image.paste(role_icon, (box[0] + 98, box[1] + 17), role_icon)
            hero_text_x = box[0] + 144
        else:
            draw.rounded_rectangle((box[0] + 92, box[1] + 19, box[0] + 162, box[1] + 45), radius=12, fill=role_fill)
            draw.text((box[0] + 111, box[1] + 22), (role_type[:1] or "?").upper(), font=_font_meta(16), fill=(255, 255, 255))
        draw.text((hero_text_x, box[1] + 14), hero_name, font=_font_chinese(26), fill=(250, 252, 255, 255))

        hero_time = float((hero.get("statMap") or {}).get(GAME_TIME_GUID, 0) or 0)
        if match_game_time_sec:
            try:
                ratio = max(0.0, min(1.0, hero_time / float(match_game_time_sec)))
            except (TypeError, ValueError, ZeroDivisionError):
                ratio = 0.0
            time_line = f"{int(hero_time // 60):02d}:{int(hero_time % 60):02d} | {ratio * 100:.1f}%"
        else:
            time_line = f"{int(hero_time // 60):02d}:{int(hero_time % 60):02d}"
        draw.text((hero_text_x, box[1] + 46), time_line, font=_font_chinese(15), fill=(186, 196, 212, 255))

        perks = _extract_player_perks(hero)
        for perk_index, perk in enumerate(list(perks or [])[:2]):
            px = box[2] - 124 + perk_index * 48
            py = box[1] + 18
            draw.rounded_rectangle((px, py, px + 42, py + 42), radius=10, fill=(240, 244, 250, 255))
            _paste_perk_icon(image, perk, (px + 6, py + 6), 30)

        inner_left = box[0] + 20
        inner_top = box[1] + 92
        inner_width = box[2] - box[0] - 40
        column_w = (inner_width - grid_gap) // 2
        for index, row in enumerate(stat_rows):
            column = index % 2
            row_index = index // 2
            row_x = inner_left + column * (column_w + grid_gap)
            row_y = inner_top + row_index * stat_row_h
            fill = (40, 45, 59, 255) if row_index % 2 == 0 else (33, 38, 50, 255)
            draw.rounded_rectangle((row_x, row_y, row_x + column_w, row_y + 22), radius=8, fill=fill)
            value_color = HIGHLIGHT_COLORS.get(row["band"], (246, 248, 255, 255))
            draw.text((row_x + 12, row_y + 2), _fit_text(draw, row["label"], _font_chinese(14), column_w - 120), font=_font_chinese(14), fill=(194, 202, 216, 255))
            draw.text((row_x + column_w - 14, row_y + 1), row["value_text"], font=_font_num_display(15), fill=value_color, anchor="ra")
            if row["avg_text"] not in {"", "-"}:
                draw.text((row_x + column_w - 14, row_y + 12), f"均值 {row['avg_text']}", font=_font_chinese(10), fill=(150, 160, 175, 255), anchor="ra")
        y += block_h + card_gap

    return _pil_to_rendered(image)


def render_all_players_waterfall(
    all_player_data: Sequence[dict[str, Any]],
    *,
    match_game_time_sec: Any = None,
) -> RenderedImage:
    # Keep the overshop-compatible layout here:
    # teammates in one horizontal row, enemies in one horizontal row.

    from PIL import Image, ImageDraw

    config = _load_ow_config()
    players = [dict(item) for item in all_player_data if isinstance(item, dict) and item.get("heroList")]
    if not players:
        image = Image.new("RGBA", (960, 180), (18, 22, 30, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.text((32, 42), "暂无可渲染的全员详细数据", font=_font_chinese(28), fill=(255, 255, 255, 255))
        draw.text((32, 98), "本场没有抓取到足够的公开英雄详细。", font=_font_chinese(18), fill=(180, 188, 202, 255))
        return _pil_to_rendered(image)

    pad = 24
    player_w = 330
    col_gap = 12
    team_row_gap = 28 if any(item.get("team_type") == "teammate" for item in players) and any(item.get("team_type") != "teammate" for item in players) else 0
    header_h = 78
    title_row_h = 22
    after_title_gap = 7
    stat_row_h = 20
    stat_gap = 4
    hero_header_h = 47
    hero_gap = 7
    bottom_pad = 38
    promoted_stat_guids = {KILL_GUID, ASSIST_GUID, DEATH_GUID, GAME_TIME_GUID}

    bg_color = (24, 24, 34, 255)
    card_color = (38, 40, 52, 255)
    header_color = (47, 50, 64, 255)
    row_color_a = (45, 48, 60, 255)
    row_color_b = (35, 38, 49, 255)
    teammate_color = (78, 180, 122, 255)
    enemy_color = (215, 78, 82, 255)
    text_dim = (188, 192, 202, 255)
    text_main = (245, 247, 250, 255)
    accent_gold = (255, 212, 96, 255)

    role_order = {"tank": 0, "dps": 1, "healer": 2}
    role_badges = {
        "tank": ("T", (83, 163, 255, 255), (23, 43, 68, 255)),
        "dps": ("D", (255, 111, 103, 255), (71, 31, 30, 255)),
        "healer": ("S", (85, 214, 142, 255), (25, 63, 42, 255)),
    }
    hero_lookup = {str(hero.get("heroGuid")): hero for hero in config.get("heroList", []) or [] if hero.get("heroGuid")}

    def _player_heroes(player: dict[str, Any]) -> list[dict[str, Any]]:
        heroes = [hero for hero in list(player.get("heroList") or []) if isinstance(hero, dict)]
        heroes.sort(key=lambda item: float((item.get("statMap") or {}).get(GAME_TIME_GUID, 0) or 0), reverse=True)
        return heroes

    def _played_roles(player: dict[str, Any]) -> list[str]:
        roles = set()
        for hero in _player_heroes(player):
            hero_info = hero_lookup.get(str(hero.get("heroGuid") or hero.get("heroId") or "")) or _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
            role_type = str(hero_info.get("roleType") or "").lower()
            if role_type in role_order:
                roles.add(role_type)
        return sorted(roles, key=lambda item: role_order.get(item, 99))

    def _primary_role(player: dict[str, Any]) -> str:
        heroes = _player_heroes(player)
        if not heroes:
            return ""
        hero = heroes[0]
        hero_info = hero_lookup.get(str(hero.get("heroGuid") or hero.get("heroId") or "")) or _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
        return str(hero_info.get("roleType") or "").lower()

    def _player_sort_key(player: dict[str, Any]) -> tuple[int, str]:
        return (role_order.get(_primary_role(player), 99), str(player.get("name") or "").lower())

    def _split_name(full_name: Any) -> tuple[str, str]:
        text = str(full_name or "").strip()
        if "#" in text:
            tag, num = text.split("#", 1)
            return tag.strip() or text, f"#{num.strip()}"
        return text or "未知玩家", ""

    def _format_seconds(value: Any) -> str:
        try:
            return str(int(round(float(value or 0))))
        except (TypeError, ValueError):
            return "0"

    def _format_ratio(value: Any) -> str:
        try:
            seconds = float(value or 0)
            total_seconds = float(match_game_time_sec or 0)
        except (TypeError, ValueError):
            return "0%"
        if total_seconds <= 0:
            return "0%"
        percent = max(0.0, seconds / total_seconds * 100)
        text = f"{percent:.1f}"
        if text.endswith(".0"):
            text = text[:-2]
        return f"{text}%"

    def _value_fill(band: str) -> tuple[int, int, int, int]:
        return HIGHLIGHT_COLORS.get(str(band or ""), text_main)

    def _hero_block_meta(player: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], int]]:
        blocks = []
        for hero in _player_heroes(player):
            stat_rows = _hero_stat_rows(config, hero, rank_info=player.get("rankInfo") or {})
            stat_rows = [row for row in stat_rows if row["guid"] not in promoted_stat_guids]
            rows_per_col = max(1, math.ceil(len(stat_rows) / 2)) if stat_rows else 0
            block_h = hero_header_h + rows_per_col * stat_row_h + hero_gap
            hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
            hero_info = hero_lookup.get(hero_guid) or _find_hero(config, hero_guid)
            blocks.append((hero, hero_info, stat_rows, block_h))
        return blocks

    def _player_panel_height(player: dict[str, Any]) -> int:
        content_h = sum(block_h for _, _, _, block_h in _hero_block_meta(player))
        return header_h + title_row_h + after_title_gap + content_h + 8

    def _team_row_width(team_players: Sequence[dict[str, Any]]) -> int:
        if not team_players:
            return 0
        return len(team_players) * player_w + max(0, len(team_players) - 1) * col_gap

    def _team_row_height(team_players: Sequence[dict[str, Any]]) -> int:
        if not team_players:
            return 0
        return max(_player_panel_height(player) for player in team_players)

    def _draw_role_badge(x0: int, y0: int, role: str) -> None:
        role_icon = _load_role_icon_asset(role, size=(20, 20))
        if role_icon is not None:
            image.paste(role_icon, (x0, y0), role_icon)
            return
        short, outline, fill = role_badges.get(role, ("?", (190, 196, 210, 255), (50, 54, 66, 255)))
        draw.rounded_rectangle((x0, y0, x0 + 20, y0 + 20), radius=5, fill=fill, outline=outline, width=1)
        draw.text((x0 + 10, y0 + 3), short, font=_font_meta(14), fill=outline, anchor="ma")

    def _draw_player_column(player: dict[str, Any], x: int, y: int, team_color: tuple[int, int, int, int], row_h: int) -> None:
        draw.rectangle((x, y, x + player_w, y + row_h), fill=card_color, outline=(70, 74, 92, 255), width=1)
        draw.rectangle((x, y, x + player_w, y + header_h), fill=header_color, outline=team_color, width=2)
        draw.rectangle((x, y, x + 7, y + header_h), fill=team_color)

        heroes = _player_heroes(player)
        primary_hero = heroes[0] if heroes else {}
        primary_info = hero_lookup.get(str(primary_hero.get("heroGuid") or primary_hero.get("heroId") or "")) or _find_hero(config, primary_hero.get("heroGuid") or primary_hero.get("heroId"))
        avatar_url = str(player.get("icon") or player.get("avatar") or player.get("playerIcon") or "").strip()
        header_icon = _load_icon_rgba(avatar_url, size=(44, 44)) if avatar_url else None
        if header_icon is None and primary_hero:
            header_icon = _load_icon_rgba(_hero_icon_url(primary_info, primary_hero), size=(44, 44))
        icon_x = x + 15
        icon_y = y + 12
        if header_icon is not None:
            image.paste(header_icon, (icon_x, icon_y), header_icon)
        else:
            draw.rounded_rectangle((icon_x, icon_y, icon_x + 44, icon_y + 44), radius=8, fill=(70, 74, 90, 255), outline=team_color, width=2)

        display_name, battle_num = _split_name(player.get("name"))
        roles = _played_roles(player)
        role_x = x + player_w - 14 - max(0, len(roles) * 20 + (len(roles) - 1) * 5)
        if roles:
            cursor = role_x
            for role in roles:
                _draw_role_badge(cursor, y + 8, role)
                cursor += 25

        info_right = role_x - 10 if roles else x + player_w - 12
        name_x = icon_x + 54
        info_w = max(72, info_right - name_x)
        draw.text((name_x, y + 8), _fit_text(draw, display_name, _font_chinese(20), info_w), font=_font_chinese(20), fill=text_main)
        if battle_num:
            draw.text((name_x, y + 32), _fit_text(draw, battle_num, _font_meta(14), info_w), font=_font_meta(14), fill=text_dim)

        title_y = y + header_h
        title_list = _group_titles(player.get("bnet_id"))
        if title_list:
            _draw_title_badges(
                draw,
                title_list,
                x + 10,
                title_y + 11,
                x + player_w - 10,
                badge_height=18,
                badge_gap=6,
                max_badge_width=126,
                min_badge_width=54,
                padding_x=7,
                max_font_size=11,
                min_font_size=9,
            )

        current_y = title_y + title_row_h + after_title_gap
        for hero, hero_info, stat_rows, block_h in _hero_block_meta(player):
            stat_map = hero.get("statMap", {}) or {}
            hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
            hero_name = hero_info.get("name") or hero_guid or "未知英雄"
            row_map = {row["guid"]: row for row in _hero_stat_rows(config, hero, rank_info=player.get("rankInfo") or {})}

            draw.rectangle((x + 8, current_y, x + player_w - 8, current_y + hero_header_h), fill=(30, 32, 42, 255))
            icon = _load_icon_rgba(_hero_icon_url(hero_info, hero), size=(28, 28))
            if icon is not None:
                image.paste(icon, (x + 14, current_y + 4), icon)

            kill_row = row_map.get(KILL_GUID, {})
            assist_row = row_map.get(ASSIST_GUID, {})
            death_row = row_map.get(DEATH_GUID, {})
            kad_parts = [
                (str(kill_row.get("value_text") or "0"), _value_fill(str(kill_row.get("band") or ""))),
                ("/", text_main),
                (str(assist_row.get("value_text") or "0"), _value_fill(str(assist_row.get("band") or ""))),
                ("/", text_main),
                (str(death_row.get("value_text") or "0"), _value_fill(str(death_row.get("band") or ""))),
            ]
            kad_width = sum(_measure(draw, text, _font_num_display(13)) for text, _ in kad_parts)
            draw.text((x + 48, current_y + 4), _fit_text(draw, hero_name, _font_chinese(17), player_w - 68 - kad_width), font=_font_chinese(17), fill=accent_gold)
            kad_x = x + player_w - 16 - kad_width
            for text, fill in kad_parts:
                draw.text((kad_x, current_y + 4), text, font=_font_num_display(13), fill=fill)
                kad_x += _measure(draw, text, _font_num_display(13))

            play_seconds = float(stat_map.get(GAME_TIME_GUID, 0) or 0)
            playtime_text = f"游戏时间{_format_seconds(play_seconds)}秒 | 占比{_format_ratio(play_seconds)}"
            draw.text((x + 14, current_y + 28), _fit_text(draw, playtime_text, _font_meta(12), player_w - 28), font=_font_meta(12), fill=text_dim)
            current_y += hero_header_h

            stat_cell_w = (player_w - 20 - stat_gap) // 2
            for index, row in enumerate(stat_rows):
                column = index % 2
                row_index = index // 2
                row_x = x + 10 + column * (stat_cell_w + stat_gap)
                row_y = current_y + row_index * stat_row_h
                draw.rectangle((row_x, row_y, row_x + stat_cell_w, row_y + stat_row_h - 1), fill=row_color_a if row_index % 2 == 0 else row_color_b)
                draw.text((row_x + 4, row_y + 4), _fit_text(draw, row["label"], _font_chinese(12), stat_cell_w - 60), font=_font_chinese(12), fill=text_dim)
                draw.text((row_x + stat_cell_w - 4, row_y + 3), row["value_text"], font=_font_num_display(13), fill=_value_fill(str(row["band"])), anchor="ra")
            current_y += math.ceil(len(stat_rows) / 2) * stat_row_h + hero_gap

    teammates = sorted([player for player in players if player.get("team_type") == "teammate"], key=_player_sort_key)
    enemies = sorted([player for player in players if player.get("team_type") != "teammate"], key=_player_sort_key)
    teammate_row_w = _team_row_width(teammates)
    enemy_row_w = _team_row_width(enemies)
    teammate_row_h = _team_row_height(teammates)
    enemy_row_h = _team_row_height(enemies)

    image_w = max(900, pad * 2 + max(teammate_row_w, enemy_row_w, 0))
    image_h = pad + teammate_row_h + team_row_gap + enemy_row_h + bottom_pad
    image = Image.new("RGBA", (image_w, image_h), bg_color)
    draw = ImageDraw.Draw(image, "RGBA")

    current_row_y = pad
    if teammates:
        cursor_x = pad
        for player in teammates:
            _draw_player_column(player, cursor_x, current_row_y, teammate_color, teammate_row_h)
            cursor_x += player_w + col_gap
        current_row_y += teammate_row_h

    if teammates and enemies:
        separator_y = current_row_y + team_row_gap // 2
        draw.line((pad, separator_y, image_w - pad, separator_y), fill=(95, 100, 120, 255), width=2)
        current_row_y += team_row_gap

    if enemies:
        cursor_x = pad
        for player in enemies:
            _draw_player_column(player, cursor_x, current_row_y, enemy_color, enemy_row_h)
            cursor_x += player_w + col_gap

    _draw_legend(draw, pad, image_h - bottom_pad + 12, _font_chinese(12))
    return _pil_to_rendered(image)


def _render_all_players_waterfall_readable(
    all_player_data: Sequence[dict[str, Any]],
    *,
    match_game_time_sec: Any = None,
) -> RenderedImage:
    from PIL import Image, ImageDraw

    config = _load_ow_config()
    players = [dict(item) for item in all_player_data if isinstance(item, dict) and item.get("heroList")]
    if not players:
        image = Image.new("RGBA", (960, 180), (18, 22, 30, 255))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.text((32, 42), "No detailed player data available", font=_font_chinese(28), fill=(255, 255, 255, 255))
        draw.text((32, 98), "No public hero detail data was captured for this match.", font=_font_meta(18), fill=(180, 188, 202, 255))
        return _pil_to_rendered(image)

    pad = 28
    section_gap = 30
    section_header_h = 48
    player_w = 500
    max_columns = 2
    col_gap = 18
    row_gap = 18
    header_h = 90
    title_row_h = 24
    after_title_gap = 10
    stat_row_h = 24
    stat_gap = 6
    hero_header_h = 54
    hero_gap = 10
    card_bottom_pad = 12
    bottom_pad = 46
    promoted_stat_guids = {KILL_GUID, ASSIST_GUID, DEATH_GUID, GAME_TIME_GUID}

    bg_color = (24, 24, 34, 255)
    card_color = (38, 40, 52, 255)
    header_color = (47, 50, 64, 255)
    section_line = (86, 94, 116, 255)
    row_color_a = (45, 48, 60, 255)
    row_color_b = (35, 38, 49, 255)
    teammate_color = (78, 180, 122, 255)
    enemy_color = (215, 78, 82, 255)
    text_dim = (188, 192, 202, 255)
    text_main = (245, 247, 250, 255)
    accent_gold = (255, 212, 96, 255)

    role_order = {"tank": 0, "dps": 1, "healer": 2}
    role_badges = {
        "tank": ("T", (83, 163, 255, 255), (23, 43, 68, 255)),
        "dps": ("D", (255, 111, 103, 255), (71, 31, 30, 255)),
        "healer": ("S", (85, 214, 142, 255), (25, 63, 42, 255)),
    }
    hero_lookup = {str(hero.get("heroGuid")): hero for hero in config.get("heroList", []) or [] if hero.get("heroGuid")}

    def _player_heroes(player: dict[str, Any]) -> list[dict[str, Any]]:
        heroes = [hero for hero in list(player.get("heroList") or []) if isinstance(hero, dict)]
        heroes.sort(key=lambda item: float((item.get("statMap") or {}).get(GAME_TIME_GUID, 0) or 0), reverse=True)
        return heroes

    def _played_roles(player: dict[str, Any]) -> list[str]:
        roles = set()
        for hero in _player_heroes(player):
            hero_info = hero_lookup.get(str(hero.get("heroGuid") or hero.get("heroId") or "")) or _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
            role_type = str(hero_info.get("roleType") or "").lower()
            if role_type in role_order:
                roles.add(role_type)
        return sorted(roles, key=lambda item: role_order.get(item, 99))

    def _primary_role(player: dict[str, Any]) -> str:
        heroes = _player_heroes(player)
        if not heroes:
            return ""
        hero = heroes[0]
        hero_info = hero_lookup.get(str(hero.get("heroGuid") or hero.get("heroId") or "")) or _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
        return str(hero_info.get("roleType") or "").lower()

    def _player_sort_key(player: dict[str, Any]) -> tuple[int, str]:
        return (role_order.get(_primary_role(player), 99), str(player.get("name") or "").lower())

    def _split_name(full_name: Any) -> tuple[str, str]:
        text = str(full_name or "").strip()
        if "#" in text:
            tag, num = text.split("#", 1)
            return tag.strip() or text, f"#{num.strip()}"
        return text or "Unknown", ""

    def _format_seconds(value: Any) -> str:
        try:
            seconds = int(round(float(value or 0)))
        except (TypeError, ValueError):
            seconds = 0
        return f"{seconds}s"

    def _format_ratio(value: Any) -> str:
        try:
            seconds = float(value or 0)
            total_seconds = float(match_game_time_sec or 0)
        except (TypeError, ValueError):
            return "0%"
        if total_seconds <= 0:
            return "0%"
        percent = max(0.0, seconds / total_seconds * 100)
        text = f"{percent:.1f}"
        if text.endswith(".0"):
            text = text[:-2]
        return f"{text}%"

    def _value_fill(band: str) -> tuple[int, int, int, int]:
        return HIGHLIGHT_COLORS.get(str(band or ""), text_main)

    def _hero_block_meta(player: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], int]]:
        blocks = []
        for hero in _player_heroes(player):
            stat_rows = _hero_stat_rows(config, hero, rank_info=player.get("rankInfo") or {})
            stat_rows = [row for row in stat_rows if row["guid"] not in promoted_stat_guids]
            rows_per_col = max(1, math.ceil(len(stat_rows) / 2)) if stat_rows else 0
            block_h = hero_header_h + rows_per_col * stat_row_h + hero_gap
            hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
            hero_info = hero_lookup.get(hero_guid) or _find_hero(config, hero_guid)
            blocks.append((hero, hero_info, stat_rows, block_h))
        return blocks

    def _player_panel_height(player: dict[str, Any]) -> int:
        content_h = sum(block_h for _, _, _, block_h in _hero_block_meta(player))
        return header_h + title_row_h + after_title_gap + content_h + card_bottom_pad

    def _section_layout(team_players: Sequence[dict[str, Any]]) -> tuple[int, list[int], int, int]:
        if not team_players:
            return 0, [], 0, 0
        cols = 1 if len(team_players) <= 1 else min(max_columns, len(team_players))
        row_heights: list[int] = []
        for start in range(0, len(team_players), cols):
            row_players = team_players[start : start + cols]
            row_heights.append(max(_player_panel_height(player) for player in row_players))
        width = cols * player_w + max(0, cols - 1) * col_gap
        height = section_header_h + sum(row_heights) + max(0, len(row_heights) - 1) * row_gap
        return cols, row_heights, width, height

    def _draw_role_badge(draw: Any, x0: int, y0: int, role: str) -> None:
        role_icon = _load_role_icon_asset(role, size=(22, 22))
        if role_icon is not None:
            image.paste(role_icon, (x0, y0), role_icon)
            return
        short, outline, fill = role_badges.get(role, ("?", (190, 196, 210, 255), (50, 54, 66, 255)))
        draw.rounded_rectangle((x0, y0, x0 + 22, y0 + 22), radius=6, fill=fill, outline=outline, width=1)
        draw.text((x0 + 11, y0 + 3), short, font=_font_meta(15), fill=outline, anchor="ma")

    def _draw_player_card(draw: Any, image: Any, player: dict[str, Any], x: int, y: int, row_h: int, team_color: tuple[int, int, int, int]) -> None:
        draw.rounded_rectangle((x, y, x + player_w, y + row_h), radius=18, fill=card_color, outline=(70, 74, 92, 255), width=1)
        draw.rounded_rectangle((x, y, x + player_w, y + header_h), radius=18, fill=header_color, outline=team_color, width=2)
        draw.rectangle((x, y, x + 8, y + header_h), fill=team_color)

        heroes = _player_heroes(player)
        primary_hero = heroes[0] if heroes else {}
        primary_info = hero_lookup.get(str(primary_hero.get("heroGuid") or primary_hero.get("heroId") or "")) or _find_hero(config, primary_hero.get("heroGuid") or primary_hero.get("heroId"))
        avatar_url = str(player.get("icon") or player.get("avatar") or player.get("playerIcon") or "").strip()
        header_icon = _load_icon_rgba(avatar_url, size=(52, 52)) if avatar_url else None
        if header_icon is None and primary_hero:
            header_icon = _load_icon_rgba(_hero_icon_url(primary_info, primary_hero), size=(52, 52))
        icon_x = x + 15
        icon_y = y + 13
        if header_icon is not None:
            image.paste(header_icon, (icon_x, icon_y), header_icon)
        else:
            draw.rounded_rectangle((icon_x, icon_y, icon_x + 52, icon_y + 52), radius=10, fill=(70, 74, 90, 255), outline=team_color, width=2)

        display_name, battle_num = _split_name(player.get("name"))
        roles = _played_roles(player)
        role_x = x + player_w - 16 - max(0, len(roles) * 22 + (len(roles) - 1) * 6)
        cursor = role_x
        for role in roles:
            _draw_role_badge(draw, cursor, y + 9, role)
            cursor += 28

        info_right = role_x - 10 if roles else x + player_w - 12
        name_x = icon_x + 62
        info_w = max(72, info_right - name_x)
        draw.text((name_x, y + 10), _fit_text(draw, display_name, _font_chinese(22), info_w), font=_font_chinese(22), fill=text_main)
        if battle_num:
            draw.text((name_x, y + 38), _fit_text(draw, battle_num, _font_meta(15), info_w), font=_font_meta(15), fill=text_dim)

        title_y = y + header_h
        title_list = _group_titles(player.get("bnet_id"))
        if title_list:
            _draw_title_badges(
                draw,
                title_list,
                x + 10,
                title_y + 11,
                x + player_w - 10,
                badge_height=20,
                badge_gap=6,
                max_badge_width=150,
                min_badge_width=54,
                padding_x=8,
                max_font_size=12,
                min_font_size=9,
            )

        current_y = title_y + title_row_h + after_title_gap
        for hero, hero_info, stat_rows, _block_h in _hero_block_meta(player):
            stat_map = hero.get("statMap", {}) or {}
            hero_guid = str(hero.get("heroGuid") or hero.get("heroId") or "")
            hero_name = hero_info.get("name") or hero_guid or "Unknown Hero"
            row_map = {row["guid"]: row for row in _hero_stat_rows(config, hero, rank_info=player.get("rankInfo") or {})}

            draw.rounded_rectangle((x + 10, current_y, x + player_w - 10, current_y + hero_header_h), radius=12, fill=(30, 32, 42, 255))
            icon = _load_icon_rgba(_hero_icon_url(hero_info, hero), size=(34, 34))
            if icon is not None:
                image.paste(icon, (x + 18, current_y + 8), icon)

            kill_row = row_map.get(KILL_GUID, {})
            assist_row = row_map.get(ASSIST_GUID, {})
            death_row = row_map.get(DEATH_GUID, {})
            kad_parts = [
                (str(kill_row.get("value_text") or "0"), _value_fill(str(kill_row.get("band") or ""))),
                ("/", text_main),
                (str(assist_row.get("value_text") or "0"), _value_fill(str(assist_row.get("band") or ""))),
                ("/", text_main),
                (str(death_row.get("value_text") or "0"), _value_fill(str(death_row.get("band") or ""))),
            ]
            kad_font = _font_num_display(15)
            hero_font = _font_chinese(18)
            kad_width = sum(_measure(draw, text, kad_font) for text, _ in kad_parts)
            draw.text((x + 60, current_y + 8), _fit_text(draw, hero_name, hero_font, player_w - 90 - kad_width), font=hero_font, fill=accent_gold)
            kad_x = x + player_w - 16 - kad_width
            for text, fill in kad_parts:
                draw.text((kad_x, current_y + 8), text, font=kad_font, fill=fill)
                kad_x += _measure(draw, text, kad_font)

            play_seconds = float(stat_map.get(GAME_TIME_GUID, 0) or 0)
            playtime_text = f"TIME {_format_seconds(play_seconds)} | USAGE {_format_ratio(play_seconds)}"
            draw.text((x + 18, current_y + 33), _fit_text(draw, playtime_text, _font_meta(13), player_w - 36), font=_font_meta(13), fill=text_dim)
            current_y += hero_header_h

            stat_cell_w = (player_w - 24 - stat_gap) // 2
            for index, row in enumerate(stat_rows):
                column = index % 2
                row_index = index // 2
                row_x = x + 12 + column * (stat_cell_w + stat_gap)
                row_y = current_y + row_index * stat_row_h
                draw.rounded_rectangle((row_x, row_y, row_x + stat_cell_w, row_y + stat_row_h - 2), radius=8, fill=row_color_a if row_index % 2 == 0 else row_color_b)
                draw.text((row_x + 8, row_y + 4), _fit_text(draw, row["label"], _font_chinese(13), stat_cell_w - 86), font=_font_chinese(13), fill=text_dim)
                draw.text((row_x + stat_cell_w - 8, row_y + 3), row["value_text"], font=_font_num_display(15), fill=_value_fill(str(row["band"])), anchor="ra")
            current_y += math.ceil(len(stat_rows) / 2) * stat_row_h + hero_gap

    teammates = sorted([player for player in players if player.get("team_type") == "teammate"], key=_player_sort_key)
    enemies = sorted([player for player in players if player.get("team_type") != "teammate"], key=_player_sort_key)
    _, _, teammate_section_w, teammate_section_h = _section_layout(teammates)
    _, _, enemy_section_w, enemy_section_h = _section_layout(enemies)

    image_w = max(860, pad * 2 + max(teammate_section_w, enemy_section_w, player_w))
    image_h = pad + teammate_section_h + (section_gap if teammates and enemies else 0) + enemy_section_h + bottom_pad
    image = Image.new("RGBA", (image_w, image_h), bg_color)
    draw = ImageDraw.Draw(image, "RGBA")

    def _draw_team_section(label: str, team_players: Sequence[dict[str, Any]], top: int, team_color: tuple[int, int, int, int]) -> int:
        cols, row_heights, _section_w, section_h = _section_layout(team_players)
        if not team_players:
            return top
        label_box_w = 168
        draw.rounded_rectangle((pad, top, pad + label_box_w, top + 32), radius=12, fill=team_color)
        draw.text((pad + 16, top + 6), label, font=_font_meta(20), fill=(255, 255, 255, 255))
        draw.text((pad + label_box_w + 12, top + 7), f"{len(team_players)} PLAYERS", font=_font_meta(18), fill=text_dim)
        line_y = top + 16
        draw.line((pad + label_box_w + 150, line_y, image_w - pad, line_y), fill=section_line, width=2)

        row_y = top + section_header_h
        for row_index, row_h in enumerate(row_heights):
            row_players = list(team_players[row_index * cols : (row_index + 1) * cols])
            row_w = len(row_players) * player_w + max(0, len(row_players) - 1) * col_gap
            cursor_x = pad + max(0, (image_w - pad * 2 - row_w) // 2)
            for player in row_players:
                _draw_player_card(draw, image, player, cursor_x, row_y, row_h, team_color)
                cursor_x += player_w + col_gap
            row_y += row_h + row_gap
        return top + section_h

    current_row_y = pad
    if teammates:
        current_row_y = _draw_team_section("TEAMMATES", teammates, current_row_y, teammate_color)
        if enemies:
            current_row_y += section_gap

    if enemies:
        _draw_team_section("ENEMIES", enemies, current_row_y, enemy_color)

    _draw_legend(draw, pad, image_h - bottom_pad + 14, _font_chinese(13))
    return _pil_to_rendered(image)


def calculate_match_scores(match_data: dict[str, Any]) -> dict[str, int]:
    try:
        team = match_data.get("teammateList", [])
        enemy = match_data.get("enemyList", [])
        game_time = match_data.get("gameTimeSec", 1)

        def sum_stat(player_list: Sequence[dict[str, Any]], key: str) -> float:
            return sum(float(player.get(key, 0) or 0) for player in player_list)

        s_time = min(100.0, (float(game_time or 0) / 1200.0) * 100.0)
        t_obj = sum_stat(team, "targetCompetingTime")
        e_obj = sum_stat(enemy, "targetCompetingTime")
        s_obj = (t_obj / (t_obj + e_obj) * 100.0) if (t_obj + e_obj) > 0 else 50.0
        t_block = sum_stat(team, "resistDamage")
        e_block = sum_stat(enemy, "resistDamage")
        s_block = (t_block / (t_block + e_block) * 100.0) if (t_block + e_block) > 0 else 50.0
        t_heal = sum_stat(team, "cure")
        t_death = sum_stat(team, "death")
        e_heal = sum_stat(enemy, "cure")
        e_death = sum_stat(enemy, "death")
        t_hd = t_heal / max(1.0, t_death)
        e_hd = e_heal / max(1.0, e_death)
        s_hd = (t_hd / (t_hd + e_hd) * 100.0) if (t_hd + e_hd) > 0 else 50.0
        total_death = t_death + e_death
        s_death = ((1.0 - (t_death / total_death)) * 100.0) if total_death > 0 else 50.0
        anti_pressure = s_time * 0.15 + s_obj * 0.2 + s_block * 0.2 + s_hd * 0.25 + s_death * 0.2

        t_elim = sum_stat(team, "kill")
        t_fb = sum_stat(team, "finalHit")
        t_assist = sum_stat(team, "assist")
        teamwork = min(100.0, (((t_elim - t_fb) + t_assist) / t_elim) * 60.0) if t_elim > 0 else 40.0

        t_dmg = sum_stat(team, "heroDamage")
        e_dmg = sum_stat(enemy, "heroDamage")
        e_elim = sum_stat(enemy, "kill")
        e_fb = sum_stat(enemy, "finalHit")
        s_dmg = (t_dmg / (t_dmg + e_dmg) * 100.0) if (t_dmg + e_dmg) > 0 else 50.0
        s_kill = (t_elim / (t_elim + e_elim) * 100.0) if (t_elim + e_elim) > 0 else 50.0
        s_fb = (t_fb / (t_fb + e_fb) * 100.0) if (t_fb + e_fb) > 0 else 50.0
        aggressiveness = s_dmg * 0.4 + s_kill * 0.3 + s_fb * 0.3

        def balance(v1: float, v2: float) -> float:
            if v1 + v2 == 0:
                return 1.0
            return 1.0 - abs(v1 - v2) / (v1 + v2)

        balance_score = (balance(t_dmg, e_dmg) + balance(t_elim, e_elim) + balance(t_heal, e_heal)) / 3.0 * 100.0
        match_quality = s_time * 0.4 + balance_score * 0.6
        return {
            "anti_pressure": int(anti_pressure),
            "teamwork": int(teamwork),
            "aggressiveness": int(aggressiveness),
            "match_quality": int(match_quality),
        }
    except Exception:
        return {"anti_pressure": 0, "teamwork": 0, "aggressiveness": 0, "match_quality": 0}


def generate_match_summary_text(match_data: dict[str, Any], target_player_id: str) -> str:
    config = _load_ow_config()
    map_info = _find_map(config, match_data.get("mapGuid"))
    map_name = map_info.get("name") or "未知地图"
    map_mode = map_info.get("mode") or "未知模式"
    result_text = "胜利" if match_data.get("matchRet") == 1 else "平局" if match_data.get("matchRet") == 0 else "失败"
    score = f"{match_data.get('teamScore')} : {match_data.get('opponentScore')}"
    game_time_sec = int(match_data.get("gameTimeSec") or 0)
    duration = f"{game_time_sec // 60:02d}:{game_time_sec % 60:02d}"
    lines = [
        "[对局概览]",
        f"地图：{map_name}（{map_mode}）",
        f"结果：{result_text}（比分：{score}）",
        f"时长：{duration}",
        f"焦点玩家：{target_player_id}",
        "",
    ]
    header = (
        "| 玩家 | 英雄 | 击杀 | 助攻 | 死亡 | 最终击杀 | 目标时间 | 英雄伤害 | 承伤 | 治疗 | 吃疗 | 格挡 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    )

    def team_block(player_list: Sequence[dict[str, Any]], team_name: str) -> list[str]:
        block = [f"[{team_name}]", *header]
        for player in player_list:
            name = str(player.get("name") or "未知玩家")
            display_name = f"* {name}" if name == target_player_id else name
            hero_info = _resolve_player_hero(config, player)
            hero_name = hero_info.get("name") or "未知英雄"
            block.append(
                "| "
                + " | ".join(
                    [
                        display_name,
                        hero_name,
                        str(player.get("kill", 0)),
                        str(player.get("assist", 0)),
                        str(player.get("death", 0)),
                        str(player.get("finalHit", 0)),
                        str(player.get("targetCompetingTime", 0)),
                        f"{int(player.get('heroDamage', 0) or 0):,}",
                        f"{int(player.get('damageTaken', 0) or 0):,}",
                        f"{int(player.get('cure', 0) or 0):,}",
                        f"{int(player.get('healingTaken', 0) or 0):,}",
                        f"{int(player.get('resistDamage', 0) or 0):,}",
                    ]
                )
                + " |"
            )
        block.append("")
        return block

    lines.extend(team_block(match_data.get("teammateList", []), "队友"))
    lines.extend(team_block(match_data.get("enemyList", []), "对手"))
    return "\n".join(lines)


def generate_detailed_stats_text(all_player_details: Sequence[dict[str, Any]], target_player_id: str) -> str:
    config = _load_ow_config()
    lines = ["[全员英雄详细]", "以下数据来自各玩家公开的同场对局详细。", ""]
    for player in all_player_details:
        team_tag = "[队友]" if player.get("team_type") == "teammate" else "[对手]"
        player_name = str(player.get("name") or "未知玩家")
        label = f"{team_tag} {player_name}"
        if player_name == target_player_id:
            label += "（焦点）"
        lines.append(label)
        hero_list = list(player.get("heroList") or [])
        if not hero_list:
            lines.append("（没有英雄详细）")
            lines.append("")
            continue
        for hero in hero_list:
            hero_info = _find_hero(config, hero.get("heroGuid") or hero.get("heroId"))
            hero_name = hero_info.get("name") or f"未知英雄（{hero.get('heroGuid') or hero.get('heroId')}）"
            lines.append(f"- 英雄：{hero_name}")
            for row in _hero_stat_rows(config, hero, rank_info=player.get("rankInfo") or {}):
                avg_suffix = f"（均值 {row['avg_text']}）" if row.get("avg_text") not in {"", "-"} else ""
                lines.append(f"  * {row['label']}：{row['value_text']}{avg_suffix}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def build_carry_index_data(match_data: dict[str, Any]) -> list[dict[str, Any]]:
    config = _load_ow_config()
    game_time = float(match_data.get("gameTimeSec") or 600 or 600)
    time_coef = max(1.0, game_time) / 600.0
    carry_index_data: list[dict[str, Any]] = []

    for team_label, player_list in (("teammate", match_data.get("teammateList", [])), ("enemy", match_data.get("enemyList", []))):
        for player in player_list or []:
            total_damage = float(player.get("heroDamage", 0) or 0)
            total_healing = float(player.get("cure", 0) or 0)
            total_blocked = float(player.get("resistDamage", 0) or 0)
            total_kill = float(player.get("kill", 0) or 0)
            total_final_blows = float(player.get("finalBlows", player.get("finalHit", 0)) or 0)
            total_solo_kills = float(player.get("soloKills", 0) or 0)
            total_assist = float(player.get("assist", 0) or 0)
            total_healing_taken = float(player.get("healingTaken", 0) or 0)
            total_damage_taken = float(player.get("damageTaken", 0) or 0)
            total_death = float(player.get("death", 0) or 0)

            score = (
                (total_damage + total_healing + (total_blocked / 10.0))
                + (total_kill * 200.0)
                + (total_final_blows * 200.0)
                + (total_solo_kills * 300.0)
                + (total_assist * 50.0)
                + (total_healing_taken * -0.3)
                + (total_damage_taken * 0.3)
                - (total_death * 200.0)
            ) / time_coef

            hero_info = _resolve_player_hero(config, player)
            hero_icon = _load_icon_rgba(_hero_icon_url(hero_info, player), size=(24, 24))
            carry_index_data.append(
                {
                    "name": str(player.get("name") or "未知").split("#", 1)[0],
                    "team": team_label,
                    "score": int(round(score)),
                    "icon": hero_icon,
                }
            )

    carry_index_data.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return carry_index_data


def render_analysis_report(
    json_data: dict[str, Any],
    *,
    target_hero_images: Optional[Sequence[Any]] = None,
    map_name: Optional[str] = None,
    map_icon_img: Any = None,
    match_result: Optional[str] = None,
    footer_source: Optional[str] = None,
) -> RenderedImage:
    from PIL import Image, ImageDraw

    width = 800
    padding = 40
    line_spacing = 15
    font_title = _font_chinese(40)
    font_sub = _font_chinese(26)
    font_text = _font_chinese(22)
    font_score = _font_chinese(32)
    font_footer = _font_chinese(16)

    temp = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp)

    def measure(text: Any, font: Any) -> int:
        return _measure(temp_draw, text, font)

    def wrap_lines(text: Any, font: Any, max_w: int) -> list[str]:
        content = str(text or "")
        lines = []
        for segment in content.split("\n"):
            current = ""
            for char in segment:
                if measure(current + char, font) <= max_w:
                    current += char
                else:
                    lines.append(current)
                    current = char
            if current:
                lines.append(current)
        return lines

    red_black = json_data.get("red_black_list", {})
    if isinstance(red_black, str):
        red_black_text = red_black
    else:
        role_comparison = red_black.get("role_comparison", [])
        role_text = "\n".join([f"  - {item}" for item in role_comparison]) if isinstance(role_comparison, list) else str(role_comparison)
        red_black_text = f"MVP / 背锅位：{red_black.get('mvp_or_potg', '')}\n三路对比：\n{role_text}"
        outstanding = red_black.get("outstanding_performance", "")
        if outstanding:
            red_black_text += f"\n亮点补充：{outstanding}"

    sections = [
        {"type": "score", "title": "□ 焦点玩家", "id": json_data.get("player_id", "未知"), "score": json_data.get("score", "N/A")},
        {"type": "text", "title": "□ 一句话总结", "text": json_data.get("general_summary", "")},
        {"type": "text", "title": "□ 胜负关键", "text": f"胜负手：{json_data.get('key_to_win_loss', '')}"},
        {"type": "text", "title": "□ 关键数据红黑榜", "text": red_black_text},
        {"type": "text", "title": "□ 最终局势", "text": json_data.get("summary", "")},
        {"type": "carry_index", "title": "□ 全场表现评分", "data": json_data.get("carry_index_data", [])},
        {"type": "attributes", "title": "□ 团队属性与综合评价", "attr": json_data.get("attribute_scores", {}), "evaluation": json_data.get("evaluation", "")},
        {"type": "text", "title": "□ EXTRA", "text": json_data.get("extra", "")},
    ]

    total_height = 120
    for section in sections:
        total_height += 45
        if section["type"] == "score":
            total_height += 35
        elif section["type"] == "text":
            total_height += len(wrap_lines(section["text"], font_text, width - padding * 2 - 20)) * (22 + line_spacing) + 15
        elif section["type"] == "carry_index":
            total_height += len(section["data"]) * 35 + 15
        elif section["type"] == "attributes":
            total_height += 4 * 45
            total_height += len(wrap_lines(f"综合评价：{section['evaluation']}", font_text, width - padding * 2 - 20)) * (22 + line_spacing) + 15
        total_height += 30
    total_height += 70 + (28 if footer_source else 0)

    image = Image.new("RGBA", (width, int(total_height)), (20, 25, 30, 255))
    draw = ImageDraw.Draw(image)
    if map_icon_img is not None:
        target_w, target_h = width, 80
        orig_w, orig_h = map_icon_img.size
        ratio = max(target_w / orig_w, target_h / orig_h)
        new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
        resized = _resize_image(map_icon_img, (new_w, new_h))
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        cropped = resized.crop((left, top, left + target_w, top + target_h))
        overlay = Image.new("RGBA", cropped.size, (0, 0, 0, 100))
        image.paste(Image.alpha_composite(cropped.convert("RGBA"), overlay), (0, 0))
    else:
        draw.rectangle([0, 0, width, 80], fill=(235, 126, 21, 255))

    draw.text((padding, 18), ">> AI锐评", font=font_title, fill=(255, 255, 255, 255))
    header_text = f"{map_name or '本场对局'} - {match_result or '总览'}"
    draw.text((width - padding - measure(header_text, _font_chinese(22)), 27), header_text, font=_font_chinese(22), fill=(255, 255, 255, 220))

    score_colors = {
        "S": (255, 215, 0, 255),
        "A": (186, 85, 211, 255),
        "B": (65, 105, 225, 255),
        "C": (46, 139, 87, 255),
        "D": (128, 128, 128, 255),
    }

    current_y = 110
    for section in sections:
        draw.text((padding, current_y), section["title"], font=font_sub, fill=(249, 158, 26, 255))
        current_y += 45
        if section["type"] == "score":
            score_text = str(section["score"]).upper().strip()
            score_color = score_colors.get(score_text[:1] if score_text else "", (255, 255, 255, 255))
            draw.text((padding + 20, current_y), f"ID：{section['id']}", font=font_text, fill=(220, 225, 230, 255))
            prefix = f"ID：{section['id']}    评分："
            draw.text((padding + 20 + measure(f"ID：{section['id']}    ", font_text), current_y), "评分：", font=font_text, fill=(220, 225, 230, 255))
            draw.text((padding + 20 + measure(prefix, font_text), current_y - 8), score_text, font=font_score, fill=score_color)
            if target_hero_images:
                icon_x = width - padding - len(target_hero_images) * 45
                for icon in target_hero_images:
                    image.paste(icon, (int(icon_x), int(current_y - 8)), icon)
                    icon_x += 45
            current_y += 35
        elif section["type"] == "text":
            for line in wrap_lines(section["text"], font_text, width - padding * 2 - 20):
                draw.text((padding + 20, current_y), line, font=font_text, fill=(220, 225, 230, 255))
                current_y += 22 + line_spacing
            current_y += 15
        elif section["type"] == "carry_index":
            carry_data = section["data"]
            if not carry_data:
                draw.text((padding + 20, current_y), "暂无数据", font=font_text, fill=(220, 225, 230, 255))
                current_y += 35
            else:
                max_score = max(1, max(abs(int(item.get("score", 0))) for item in carry_data))
                for item in carry_data:
                    draw.text((padding + 60, current_y), str(item.get("name", ""))[:8], font=font_text, fill=(220, 225, 230, 255))
                    if item.get("icon") is not None:
                        image.paste(item["icon"], (padding + 20, current_y + 2), item["icon"])
                    score_val = int(item.get("score", 0))
                    bar_x = padding + 240
                    bar_y = current_y + 4
                    bar_w = 380
                    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 16], fill=(50, 55, 60, 255))
                    fill_w = int(bar_w * abs(score_val) / max_score)
                    if fill_w > 0:
                        fill_color = (135, 206, 250, 255) if item.get("team") == "teammate" else (255, 99, 71, 255)
                        draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + 16], fill=fill_color)
                    draw.text((bar_x + fill_w + 8, current_y + 4), str(score_val), font=_font_chinese(16), fill=(220, 225, 230, 255))
                    current_y += 35
            current_y += 15
        elif section["type"] == "attributes":
            attributes = section["attr"]
            items = [
                ("抗压", attributes.get("anti_pressure", 0)),
                ("团队", attributes.get("teamwork", 0)),
                ("进攻", attributes.get("aggressiveness", 0)),
                ("质量", attributes.get("match_quality", 0)),
            ]
            for name, raw_value in items:
                try:
                    value = max(0, min(100, int(raw_value)))
                except Exception:
                    value = 0
                draw.text((padding + 20, current_y), f"{name}: {value:3d}", font=font_text, fill=(220, 225, 230, 255))
                bar_x = padding + 220
                bar_y = current_y + 4
                draw.rectangle([bar_x, bar_y, bar_x + 360, bar_y + 16], fill=(50, 55, 60, 255))
                fill_w = int(360 * value / 100)
                if value < 40:
                    fill_color = (235, 87, 87, 255)
                elif value < 70:
                    fill_color = (242, 201, 76, 255)
                else:
                    fill_color = (39, 174, 96, 255)
                if fill_w > 0:
                    draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + 16], fill=fill_color)
                current_y += 45
            for line in wrap_lines(f"综合评价：{section['evaluation']}", font_text, width - padding * 2 - 20):
                draw.text((padding + 20, current_y), line, font=font_text, fill=(220, 225, 230, 255))
                current_y += 22 + line_spacing
            current_y += 15
        current_y += 30

    footer_y = int(total_height) - 48
    if footer_source:
        draw.text((padding, footer_y - 20), f"提示词来源：{footer_source}", font=font_footer, fill=(156, 166, 182, 255))
    footer = f"生成时间：{json_data.get('generated_at') or ''}".strip()
    draw.text((padding, footer_y), footer, font=font_footer, fill=(156, 166, 182, 255))
    return _pil_to_rendered(image)


def map_icon_image_for_match(match_data: dict[str, Any]) -> Any:
    config = _load_ow_config()
    map_info = _find_map(config, match_data.get("mapGuid"))
    return _load_icon_rgba(str(map_info.get("icon") or ""), size=(800, 120))


def map_name_for_match(match_data: dict[str, Any]) -> str:
    config = _load_ow_config()
    map_info = _find_map(config, match_data.get("mapGuid"))
    return str(map_info.get("name") or "未知地图")
