from __future__ import annotations

from ..map_modes import draw_map_mode_icon

from ..subroles import draw_subrole_badge, get_subrole

from ..dashen_promo import append_dashen_promo

from collections import defaultdict
from io import BytesIO
import math
import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from overstats.src.constants.ranks import get_rank_score
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
    from src.constants.ranks import get_rank_score
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

try:
    from overstats.src.modules.risk_status import draw_risk_status_badge, measure_risk_status_badge
except ModuleNotFoundError:
    from src.modules.risk_status import draw_risk_status_badge, measure_risk_status_badge

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
    _perk_guid_candidates,
    _perk_lookup,
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


def _pil_to_rendered(image: Any, *, add_promo: bool = True) -> RenderedImage:
    output = BytesIO()
    if add_promo:
        image = append_dashen_promo(image)
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


def decorate_image_with_player_title_header(
    base_image: Any,
    player_name: str,
    bnet_id: Any = None,
    subtitle: str = "",
    risk_status: Any = None,
) -> Any:
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
    name_width = _measure(draw, display_name, font_name)
    badge_x = 24 + name_width + 12
    badge_width, _ = draw_risk_status_badge(
        draw,
        badge_x,
        19,
        risk_status,
        font=_font_chinese(12),
        compact=True,
        padding_x=7,
        padding_y=3,
        max_width=132,
    )
    title_list = _group_titles(bnet_id)
    if title_list:
        title_x = badge_x + badge_width + 10 if badge_width else 24 + name_width + 18
        _draw_title_badges(draw, title_list, title_x, 30, canvas.width - 24, badge_height=28, badge_gap=10, max_badge_width=138, min_badge_width=58, max_font_size=16, min_font_size=11)
    if sub_parts:
        draw.text((24, 54), " | ".join(sub_parts), font=font_sub, fill=(180, 185, 195, 255))
    draw.line([(0, header_height - 1), (canvas.width, header_height - 1)], fill=(55, 61, 74, 255), width=1)
    return canvas


def decorate_rendered_image_header(
    rendered: RenderedImage,
    player_name: str,
    bnet_id: Any = None,
    subtitle: str = "",
    risk_status: Any = None,
) -> RenderedImage:
    return _pil_to_rendered(
        decorate_image_with_player_title_header(
            _open_rendered(rendered),
            player_name,
            bnet_id=bnet_id,
            subtitle=subtitle,
            risk_status=risk_status,
        ),
        add_promo=False,  # The input render already contains its footer.
    )


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
        results[guid] = {"band": band, "avg": ref.get("avg"), "normalized": normalized}
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
        get_rank_score(rank_info or {}),
    )
    preferred_order = {KILL_GUID: 0, ASSIST_GUID: 1, DEATH_GUID: 2, FINAL_HIT_GUID: 3}
    rows = []
    for raw_guid, raw_value in stat_map.items():
        guid = str(raw_guid)
        attr = attr_lookup.get(guid, {})
        label = str(attr.get("valueText") or guid)
        value_type = str(attr.get("valueType") or "")
        compare = compare_map.get(guid) or {}
        ratio = None
        try:
            if compare.get("avg") and compare.get("normalized") is not None:
                ratio = float(compare["normalized"]) / float(compare["avg"])
        except (TypeError, ValueError, ZeroDivisionError):
            ratio = None
        rows.append(
            {
                "guid": guid,
                "label": label,
                "value_text": _format_stat_value(raw_value, label, guid),
                "value_type": value_type,
                "band": compare.get("band", "unknown"),
                "avg_text": _format_avg_value(compare.get("avg"), label),
                # Normalized value over the reference average; drives the delta and mini bar.
                "avg_ratio": ratio if ratio is not None and math.isfinite(ratio) and ratio >= 0 else None,
                "lower_is_better": guid == DEATH_GUID,
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


LATIN_RUN_RE = re.compile(r"([!-~](?:[ !-~]*[!-~])?)")
DELTA_UP = (96, 216, 135, 255)
DELTA_DOWN = (236, 112, 99, 255)


FALLBACK_STAT_LABELS = {
    KILL_GUID: "消灭",
    ASSIST_GUID: "助攻",
    DEATH_GUID: "阵亡",
    FINAL_HIT_GUID: "最后一击",
    GAME_TIME_GUID: "游戏时间",
}


def _display_label(row: dict[str, Any]) -> str:
    """Stats missing from the config come through labelled with their raw id."""
    label = str(row.get("label") or "")
    if label.isdigit():
        return FALLBACK_STAT_LABELS.get(str(row.get("guid") or label), "未知数据")
    return label


def _mixed_runs(text: Any, size: int) -> list[tuple[str, Any]]:
    """simhei draws Latin and digits wide and spaced out; give ASCII runs the Latin face."""
    return [
        (part, _font_meta(size) if LATIN_RUN_RE.fullmatch(part) else _font_chinese(size))
        for part in LATIN_RUN_RE.split(str(text or ""))
        if part
    ]


def _mixed_width(draw: Any, text: Any, size: int) -> int:
    return int(sum(draw.textlength(part, font=font) for part, font in _mixed_runs(text, size)))


def _draw_mixed(draw: Any, xy: tuple[float, float], text: Any, size: int, fill: Any) -> int:
    """Draw like a top-left anchored simhei string, with every run on the CJK baseline."""
    x, y = xy
    baseline = y + _font_chinese(size).getmetrics()[0]
    for part, font in _mixed_runs(text, size):
        draw.text((x, baseline), part, font=font, fill=fill, anchor="ls")
        x += draw.textlength(part, font=font)
    return int(x - xy[0])


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
        current_x += _draw_mixed(draw, (current_x, y), text, int(getattr(font, "size", 14)), color)


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
    # Tall enough for the value with its average beneath it, without the two overlapping.
    stat_row_h = 39
    stat_tile_h = 34
    # Right-hand columns of each stat tile: value/average, vs-average delta, mini bar.
    stat_value_w = 86
    stat_delta_w = 46
    stat_bar_w = 84
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
        # Bottom inset matches the 20px side inset of the stat grid.
        block_h = 107 + rows_per_col * stat_row_h
        layout_rows.append((hero, stat_rows, block_h))
        total_height += block_h + card_gap
    total_height += page_padding

    image = Image.new("RGBA", (card_width, total_height), (18, 22, 30, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text((page_padding, 20), "对局详细数据", font=_font_chinese(28), fill=(255, 255, 255, 255))
    _draw_legend(draw, page_padding, 58, _font_chinese(14))

    hero_lookup = {str(hero.get("heroGuid")): hero for hero in config.get("heroList", []) or [] if hero.get("heroGuid")}
    perk_lookup = _perk_lookup(config)
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
        draw_subrole_badge(image, hero_info, box[0]+54, box[1]+46, 22)
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
            time_line = f"{int(hero_time // 60):02d}:{int(hero_time % 60):02d}  |  {ratio * 100:.1f}%"
        else:
            time_line = f"{int(hero_time // 60):02d}:{int(hero_time % 60):02d}"
        draw.text((hero_text_x, box[1] + 48), time_line, font=_font_num_display(15), fill=(186, 196, 212, 255))

        perks = _extract_player_perks(hero)
        for perk_index, perk in enumerate(list(perks or [])[:2]):
            px = box[2] - 124 + perk_index * 48
            py = box[1] + 18
            draw.rounded_rectangle((px, py, px + 42, py + 42), radius=10, fill=(240, 244, 250, 255))
            if not _paste_perk_icon(image, _perk_icon_url(perk_lookup, perk), (px + 6, py + 6), 30):
                # Icon not cached: an empty slot reads better than a blank white tile.
                draw.rounded_rectangle((px, py, px + 42, py + 42), radius=10, fill=(52, 60, 78, 255), outline=(98, 112, 136, 255), width=2)
                draw.text((px + 21, py + 22), "?", font=_font_num_display(18), fill=(150, 162, 182, 255), anchor="mm")

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
            draw.rounded_rectangle((row_x, row_y, row_x + column_w, row_y + stat_tile_h), radius=8, fill=fill)
            value_color = HIGHLIGHT_COLORS.get(row["band"], (246, 248, 255, 255))
            has_avg = row["avg_text"] not in {"", "-"}
            ratio = row.get("avg_ratio") if has_avg else None
            value_right = row_x + column_w - 14
            delta_right = value_right - stat_value_w - 10
            bar_right = delta_right - stat_delta_w - 10
            bar_left = bar_right - stat_bar_w
            label_limit = (bar_left if ratio is not None else value_right - stat_value_w) - row_x - 24
            draw.text((row_x + 12, row_y + stat_tile_h // 2), _fit_text(draw, _display_label(row), _font_chinese(14), label_limit), font=_font_chinese(14), fill=(194, 202, 216, 255), anchor="lm")
            value_y = row_y + 2 if has_avg else row_y + (stat_tile_h - 16) // 2
            draw.text((value_right, value_y), row["value_text"], font=_font_num_display(15), fill=value_color, anchor="ra")
            if has_avg:
                avg_font = _font_num_display(10)
                avg_y = row_y + stat_tile_h - 3
                draw.text((value_right, avg_y), row["avg_text"], font=avg_font, fill=(150, 160, 175, 255), anchor="rd")
                avg_w = draw.textlength(row["avg_text"], font=avg_font)
                draw.text((value_right - avg_w - 4, avg_y), "均值", font=_font_chinese(10), fill=(150, 160, 175, 255), anchor="rd")
            if ratio is not None:
                # Thin track: the tick marks the average, the fill reaches 2x average at most.
                mid_y = row_y + stat_tile_h // 2
                draw.rounded_rectangle((bar_left, mid_y - 3, bar_right, mid_y + 3), radius=3, fill=(24, 28, 38, 255))
                fill_w = int(stat_bar_w * min(ratio, 2.0) / 2.0)
                bar_color = value_color if row["band"] in HIGHLIGHT_COLORS else (112, 122, 140, 255)
                if fill_w >= 6:
                    draw.rounded_rectangle((bar_left, mid_y - 3, bar_left + fill_w, mid_y + 3), radius=3, fill=bar_color)
                tick_x = bar_left + stat_bar_w // 2
                draw.line((tick_x, mid_y - 6, tick_x, mid_y + 6), fill=(210, 216, 228, 200), width=2)
                change = ratio - 1.0
                better = change < 0 if row.get("lower_is_better") else change > 0
                if abs(change) < 0.005:
                    delta_text, delta_color = "±0%", (150, 160, 175, 255)
                else:
                    pct = min(abs(change) * 100, 999)
                    delta_text = f"{'▲' if change > 0 else '▼'}{pct:.0f}%"
                    delta_color = DELTA_UP if better else DELTA_DOWN
                arrow, number = (delta_text[0], delta_text[1:]) if delta_text[0] in "▲▼" else ("", delta_text)
                number_font = _font_num_display(12)
                draw.text((delta_right, mid_y), number, font=number_font, fill=delta_color, anchor="rm")
                if arrow:
                    draw.text((delta_right - draw.textlength(number, font=number_font) - 2, mid_y), arrow, font=_font_chinese(10), fill=delta_color, anchor="rm")
        y += block_h + card_gap

    return _pil_to_rendered(image)


def _perk_icon_url(perk_lookup: Dict[str, Dict[str, Any]], perk: Any) -> str:
    """Perks arrive as ids or dicts; resolve them to an icon URL the way the scoreboard does."""
    for candidate in _perk_guid_candidates(perk):
        icon = (perk_lookup.get(candidate) or {}).get("icon")
        if icon:
            return str(icon)
    if isinstance(perk, dict):
        return str(perk.get("icon") or "")
    return ""


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
        risk_status = player.get("riskStatus") or player.get("risk_status")
        risk_font = _font_chinese(10)
        risk_width, _, _ = measure_risk_status_badge(
            draw,
            risk_status,
            font=risk_font,
            compact=True,
            padding_x=5,
            padding_y=2,
            max_width=88,
        )
        name_width_limit = max(42, info_w - risk_width - (6 if risk_width else 0))
        name_font = _font_chinese(20)
        rendered_name = _fit_text(draw, display_name, name_font, name_width_limit)
        draw.text((name_x, y + 8), rendered_name, font=name_font, fill=text_main)
        if risk_width:
            rendered_name_width = _text_width(draw, rendered_name, name_font)
            draw_risk_status_badge(
                draw,
                name_x + rendered_name_width + 6,
                y + 10,
                risk_status,
                font=risk_font,
                compact=True,
                padding_x=5,
                padding_y=2,
                max_width=88,
            )
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

            draw.rectangle((x + 10, current_y, x + player_w - 10, current_y + hero_header_h), fill=(30, 32, 42, 255))
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
            # en2 has no CJK glyphs, which dropped 游戏时间 / 秒 / 占比 from this line.
            playtime_font = _font_chinese(12)
            draw.text((x + 14, current_y + 30), _fit_text(draw, playtime_text, playtime_font, player_w - 28), font=playtime_font, fill=text_dim)
            current_y += hero_header_h

            stat_cell_w = (player_w - 20 - stat_gap) // 2
            for index, row in enumerate(stat_rows):
                column = index % 2
                row_index = index // 2
                row_x = x + 10 + column * (stat_cell_w + stat_gap)
                row_y = current_y + row_index * stat_row_h
                draw.rectangle((row_x, row_y, row_x + stat_cell_w, row_y + stat_row_h - 1), fill=row_color_a if row_index % 2 == 0 else row_color_b)
                draw.text((row_x + 4, row_y + 4), _fit_text(draw, _display_label(row), _font_chinese(12), stat_cell_w - 60), font=_font_chinese(12), fill=text_dim)
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
        risk_status = player.get("riskStatus") or player.get("risk_status")
        risk_font = _font_chinese(10)
        risk_width, _, _ = measure_risk_status_badge(
            draw,
            risk_status,
            font=risk_font,
            compact=True,
            padding_x=5,
            padding_y=2,
            max_width=92,
        )
        name_width_limit = max(44, info_w - risk_width - (6 if risk_width else 0))
        name_font = _font_chinese(22)
        rendered_name = _fit_text(draw, display_name, name_font, name_width_limit)
        draw.text((name_x, y + 10), rendered_name, font=name_font, fill=text_main)
        if risk_width:
            rendered_name_width = _text_width(draw, rendered_name, name_font)
            draw_risk_status_badge(
                draw,
                name_x + rendered_name_width + 6,
                y + 13,
                risk_status,
                font=risk_font,
                compact=True,
                padding_x=5,
                padding_y=2,
                max_width=92,
            )
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
                draw.text((row_x + 8, row_y + 4), _fit_text(draw, _display_label(row), _font_chinese(13), stat_cell_w - 86), font=_font_chinese(13), fill=text_dim)
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
                    "risk_status": player.get("riskStatus") or player.get("risk_status"),
                }
            )

    carry_index_data.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return carry_index_data


EMPTY_SECTION_TEXT = {"", "无", "暂无", "none", "null", "n/a", "-"}
TONE_COLORS = {
    "good": (39, 174, 96, 255),
    "bad": (235, 87, 87, 255),
    "even": (104, 113, 128, 255),
}


def _comparison_tone(text: str) -> str:
    if any(word in text for word in ("持平", "均势", "五五", "相当", "接近", "差不多")):
        return "even"
    if any(word in text for word in ("对方", "敌方", "落后", "劣势", "被压", "吃亏", "下风", "被打穿")):
        return "bad"
    if any(word in text for word in ("我方", "领先", "优势", "压制", "上风", "更强", "碾压")):
        return "good"
    return "even"


def render_analysis_report(
    json_data: dict[str, Any],
    *,
    target_hero_images: Optional[Sequence[Any]] = None,
    risk_status: Any = None,
    map_name: Optional[str] = None,
    map_icon_img: Any = None,
    match_result: Optional[str] = None,
    footer_source: Optional[str] = None,
) -> RenderedImage:
    from PIL import Image, ImageDraw

    width = 800
    padding = 40
    line_spacing = 15
    text_size = 22
    line_h = 22 + line_spacing
    text_x = padding + 20
    text_w = width - padding * 2 - 20
    font_title = _font_chinese(40)
    font_sub = _font_chinese(26)
    font_text = _font_chinese(text_size)
    font_score = _font_chinese(28)
    font_risk = _font_chinese(11)
    body_color = (220, 225, 230, 255)
    muted_color = (156, 166, 182, 255)
    accent_color = (249, 158, 26, 255)
    highlight_color = (255, 214, 140, 255)

    temp = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp)

    def measure(text: Any, font: Any) -> int:
        return _measure(temp_draw, text, font)

    def text_width(text: Any) -> int:
        return _mixed_width(temp_draw, text, text_size)

    def wrap_rich(segments: Sequence[tuple[Any, Any]], max_w: int) -> list[list[tuple[str, Any]]]:
        """Wrap coloured runs; Latin words and numbers stay whole, CJK breaks per character."""
        lines: list[list[tuple[str, Any]]] = []
        current: list[tuple[str, Any]] = []
        used = 0

        def push(text: str, color: Any) -> None:
            nonlocal used
            if current and current[-1][1] == color:
                current[-1] = (current[-1][0] + text, color)
            else:
                current.append((text, color))
            used += text_width(text)

        def flush() -> None:
            nonlocal current, used
            if current:
                lines.append(current)
            current, used = [], 0

        for text, color in segments:
            for index, segment in enumerate(str(text or "").split("\n")):
                if index:
                    flush()
                for token in re.findall(r"[A-Za-z0-9_'%.+-]+|.", segment):
                    token_w = text_width(token)
                    if used + token_w <= max_w:
                        push(token, color)
                        continue
                    flush()
                    if token.isspace():
                        continue
                    for char in token if token_w > max_w else [token]:
                        if current and used + text_width(char) > max_w:
                            flush()
                        push(char, color)
        flush()
        return lines

    def draw_rich(segments: Sequence[tuple[Any, Any]], y: int, dry: bool, x: int = text_x, max_w: int = text_w) -> int:
        for line in wrap_rich(segments, max_w):
            if not dry:
                cursor = x
                for text, color in line:
                    cursor += _draw_mixed(draw, (cursor, y), text, text_size, color)
            y += line_h
        return y

    red_black = json_data.get("red_black_list", {})
    sections: list[dict[str, Any]] = [
        {"type": "score", "title": "焦点玩家", "id": json_data.get("player_id", "未知"), "score": json_data.get("score", "N/A")},
        {"type": "text", "title": "一句话总结", "segments": [(json_data.get("general_summary", ""), body_color)]},
        {"type": "text", "title": "胜负关键", "segments": [("胜负手：", muted_color), (json_data.get("key_to_win_loss", ""), highlight_color)]},
        {"type": "red_black", "title": "关键数据红黑榜", "data": red_black},
        {"type": "text", "title": "最终局势", "segments": [(json_data.get("summary", ""), body_color)]},
        {"type": "carry_index", "title": "全场表现评分", "data": json_data.get("carry_index_data", [])},
        {"type": "attributes", "title": "团队属性与综合评价", "attr": json_data.get("attribute_scores", {}), "evaluation": json_data.get("evaluation", "")},
        {"type": "text", "title": "EXTRA", "segments": [(json_data.get("extra", ""), body_color)]},
    ]
    # Sections the model left empty only add a heading over "无"; skip them.
    sections = [
        section for section in sections
        if section["type"] != "text" or str(section["segments"][-1][0] or "").strip().lower() not in EMPTY_SECTION_TEXT
    ]

    score_colors = {
        "S": (255, 215, 0, 255),
        "A": (186, 85, 211, 255),
        "B": (65, 105, 225, 255),
        "C": (46, 139, 87, 255),
        "D": (128, 128, 128, 255),
    }

    def draw_title(section: dict[str, Any], y: int, dry: bool) -> int:
        if not dry:
            draw.rectangle((padding, y + 3, padding + 5, y + 29), fill=accent_color)
            draw.text((padding + 18, y), section["title"], font=font_sub, fill=accent_color)
            if section["type"] == "carry_index" and section["data"]:
                legend_x = width - padding
                for label, color in (("敌方", (255, 99, 71, 255)), ("我方", (135, 206, 250, 255))):
                    legend_x -= _mixed_width(draw, label, 16)
                    _draw_mixed(draw, (legend_x, y + 7), label, 16, muted_color)
                    draw.rectangle((legend_x - 20, y + 10, legend_x - 8, y + 22), fill=color)
                    legend_x -= 34
        return y + 45

    def draw_score(section: dict[str, Any], y: int, dry: bool) -> int:
        if dry:
            return y + 35
        score_text = str(section["score"]).upper().strip()
        score_color = score_colors.get(score_text[:1] if score_text else "", (255, 255, 255, 255))
        id_prefix = "ID："
        id_text = str(section["id"])
        prefix_width = text_width(id_prefix)
        badge_width, _, _ = measure_risk_status_badge(
            draw, risk_status, font=font_risk, compact=True, padding_x=6, padding_y=3, max_width=118,
        )
        icon_left = width - padding - len(target_hero_images or ()) * 45
        score_label_width = measure("评分：", font_text)
        pill_w = max(52, int(draw.textlength(score_text, font=font_score)) + 26)
        reserved_right = score_label_width + pill_w + 28
        available_id_width = max(
            60,
            icon_left - 12 - text_x - prefix_width - reserved_right - (badge_width + 12 if badge_width else 12),
        )
        rendered_id = _fit_text(draw, id_text, font_text, available_id_width)
        _draw_mixed(draw, (text_x, y), id_prefix, text_size, body_color)
        cursor_x = text_x + prefix_width
        cursor_x += _draw_mixed(draw, (cursor_x, y), rendered_id, text_size, body_color)
        if badge_width:
            drawn_width, _ = draw_risk_status_badge(
                draw, cursor_x + 7, y - 2, risk_status, font=font_risk, compact=True, padding_x=6, padding_y=3, max_width=118,
            )
            cursor_x += drawn_width + 14
        else:
            cursor_x += 12
        draw.text((cursor_x, y), "评分：", font=font_text, fill=body_color)
        pill_x = cursor_x + score_label_width
        center_y = y + 11
        draw.rounded_rectangle((pill_x, center_y - 18, pill_x + pill_w, center_y + 18), radius=10, fill=score_color)
        luminance = 0.299 * score_color[0] + 0.587 * score_color[1] + 0.114 * score_color[2]
        draw.text((pill_x + pill_w // 2, center_y + 1), score_text, font=font_score,
                  fill=(28, 24, 18, 255) if luminance > 160 else (255, 255, 255, 255), anchor="mm")
        if target_hero_images:
            icon_x = icon_left
            for icon in target_hero_images:
                image.paste(icon, (int(icon_x), int(y - 8)), icon)
                icon_x += 45
        return y + 35

    def draw_red_black(section: dict[str, Any], y: int, dry: bool) -> int:
        data = section["data"]
        if isinstance(data, str):
            return draw_rich([(data, body_color)], y, dry) + 15
        y = draw_rich([("MVP / 背锅位：", muted_color), (data.get("mvp_or_potg", ""), highlight_color)], y, dry)
        y = draw_rich([("三路对比：", muted_color)], y, dry)
        role_comparison = data.get("role_comparison", [])
        if not isinstance(role_comparison, list):
            y = draw_rich([(f"  {role_comparison}", body_color)], y, dry)
            role_comparison = []
        for item in role_comparison:
            item = str(item or "").strip()
            match = re.match(r"([^：:]{1,6})[：:]\s*(.*)$", item, re.S)
            tone = TONE_COLORS[_comparison_tone(match.group(2) if match else item)]
            if match:
                label, rest = match.group(1).strip(), match.group(2)
                chip_w = text_width(label) + 20
                chip_x = text_x + 20
                if not dry:
                    draw.rounded_rectangle((chip_x, y - 3, chip_x + chip_w, y + 27), radius=8, fill=tone)
                    _draw_mixed(draw, (chip_x + 10, y + 1), label, text_size, (255, 255, 255, 255))
                rest_x = chip_x + chip_w + 12
                y = draw_rich([(rest, body_color)], y, dry, x=rest_x, max_w=text_x + text_w - rest_x)
            else:
                if not dry:
                    draw.ellipse((text_x + 24, y + 7, text_x + 34, y + 17), fill=tone)
                y = draw_rich([(item, body_color)], y, dry, x=text_x + 46, max_w=text_w - 46)
        outstanding = data.get("outstanding_performance", "")
        if outstanding:
            y = draw_rich([("亮点补充：", muted_color), (outstanding, body_color)], y, dry)
        return y + 15

    def draw_carry(section: dict[str, Any], y: int, dry: bool) -> int:
        carry_data = section["data"]
        if not carry_data:
            if not dry:
                draw.text((text_x, y), "暂无数据", font=font_text, fill=body_color)
            return y + 35 + 15
        if dry:
            return y + len(carry_data) * 35 + 15
        max_score = max(1, max(abs(int(item.get("score", 0))) for item in carry_data))
        rank_font = _font_num_display(15)
        value_font = _font_num_display(16)
        for rank, item in enumerate(carry_data, 1):
            name_x = padding + 60
            item_badge_width, _, _ = measure_risk_status_badge(
                draw, item.get("risk_status"), font=font_risk, compact=True, padding_x=5, padding_y=2, max_width=80,
            )
            name_width_limit = max(38, 180 - (item_badge_width + 7 if item_badge_width else 0))
            item_name = _fit_text(draw, str(item.get("name", "")), font_text, name_width_limit)
            draw.text((padding + 12, y + 13), str(rank), font=rank_font,
                      fill=accent_color if rank <= 3 else muted_color, anchor="rm")
            name_w = _draw_mixed(draw, (name_x, y), item_name, text_size, body_color)
            if item_badge_width:
                draw_risk_status_badge(
                    draw, name_x + name_w + 5, y + 1, item.get("risk_status"), font=font_risk,
                    compact=True, padding_x=5, padding_y=2, max_width=80,
                )
            if item.get("icon") is not None:
                image.paste(item["icon"], (padding + 20, y + 2), item["icon"])
            score_val = int(item.get("score", 0))
            bar_x = padding + 240
            bar_y = y + 4
            bar_w = 380
            draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 16], fill=(50, 55, 60, 255))
            fill_w = int(bar_w * abs(score_val) / max_score)
            if fill_w > 0:
                fill_color = (135, 206, 250, 255) if item.get("team") == "teammate" else (255, 99, 71, 255)
                draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + 16], fill=fill_color)
            # One right-aligned column, so the numbers no longer chase the bar ends.
            draw.text((width - padding, bar_y + 8), str(score_val), font=value_font, fill=body_color, anchor="rm")
            y += 35
        return y + 15

    def draw_attributes(section: dict[str, Any], y: int, dry: bool) -> int:
        attributes = section["attr"]
        items = [
            ("抗压", attributes.get("anti_pressure", 0)),
            ("团队", attributes.get("teamwork", 0)),
            ("进攻", attributes.get("aggressiveness", 0)),
            ("质量", attributes.get("match_quality", 0)),
        ]
        for name, raw_value in items:
            if not dry:
                try:
                    value = max(0, min(100, int(raw_value)))
                except Exception:
                    value = 0
                _draw_mixed(draw, (text_x, y), name, text_size, body_color)
                draw.text((padding + 190, y + 12), str(value), font=_font_num_display(20), fill=body_color, anchor="rm")
                bar_x = padding + 220
                bar_y = y + 4
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
                # Gaps at 25/50/75 give the bar a scale.
                for step in (90, 180, 270):
                    draw.line((bar_x + step, bar_y, bar_x + step, bar_y + 16), fill=(20, 25, 30, 255), width=2)
            y += 45
        y = draw_rich([("综合评价：", muted_color), (section["evaluation"], body_color)], y, dry)
        return y + 15

    def draw_sections(dry: bool) -> int:
        y = 110
        for section in sections:
            y = draw_title(section, y, dry)
            if section["type"] == "score":
                y = draw_score(section, y, dry)
            elif section["type"] == "text":
                y = draw_rich(section["segments"], y, dry) + 15
            elif section["type"] == "red_black":
                y = draw_red_black(section, y, dry)
            elif section["type"] == "carry_index":
                y = draw_carry(section, y, dry)
            elif section["type"] == "attributes":
                y = draw_attributes(section, y, dry)
            y += 30
        return y

    draw = temp_draw
    total_height = draw_sections(True) + 10 + 70 + (28 if footer_source else 0)

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
    draw_map_mode_icon(image, map_name, width - padding - measure(header_text, _font_chinese(22)) - 32, 27, 24)
    draw.text((width - padding - measure(header_text, _font_chinese(22)), 27), header_text, font=_font_chinese(22), fill=(255, 255, 255, 220))

    draw_sections(False)

    footer_y = int(total_height) - 48
    if footer_source:
        _draw_mixed(draw, (padding, footer_y - 20), f"提示词来源：{footer_source}", 16, muted_color)
    footer = f"生成时间：{json_data.get('generated_at') or ''}".strip()
    _draw_mixed(draw, (padding, footer_y), footer, 16, muted_color)
    return _pil_to_rendered(image)


def map_icon_image_for_match(match_data: dict[str, Any]) -> Any:
    config = _load_ow_config()
    map_info = _find_map(config, match_data.get("mapGuid"))
    return _load_icon_rgba(str(map_info.get("icon") or ""), size=(800, 120))


def map_name_for_match(match_data: dict[str, Any]) -> str:
    config = _load_ow_config()
    map_info = _find_map(config, match_data.get("mapGuid"))
    return str(map_info.get("name") or "未知地图")
