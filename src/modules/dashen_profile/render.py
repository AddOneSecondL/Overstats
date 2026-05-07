from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import time
from typing import Any, Dict, Sequence

try:
    from overstats.src.modules.query_tool import get_cached_asset_path, load_query_tool
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path, load_query_tool

from .engine import HeroBillboardEntry, HeroUsageRow, ProfileRenderContext, RolePanelEntry


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESOURCE_DIR = PROJECT_ROOT / "overstats" / "res"
QUERY_TOOL_ASSET_DIR = RESOURCE_DIR / "query_tool_assets"
ROLE_ICON_FILENAMES = {
    "tank": "tank.png",
    "dps": "dps.png",
    "healer": "healer.png",
}

STR_NO_TITLE = "无头衔"
STR_INFO_SWITCH_MODE = "[INFO] 在指令后附加*号可切换为查询竞技模式比赛数据"
STR_RACE_PROGRESS = "竞逐进度估算"
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
COLOR_COMPETITIVE = "#C95472"


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


def render_profile_summary(context: ProfileRenderContext) -> RenderedImage:
    try:
        from PIL import ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    config = _load_ow_config()
    image = _load_background()
    draw = ImageDraw.Draw(image)
    fonts = _load_fonts()

    _draw_avatar(image, context.avatar_bytes, (66, 60), (162, 162))
    _draw_name_block(
        image,
        draw,
        config,
        battletag=context.battletag,
        battlenum=context.battlenum,
        title=context.title,
        level=context.level,
        fonts=fonts,
    )
    _draw_header(draw, context.game_time, fonts)
    _draw_race_progress(draw, context.race_progress, fonts)
    _draw_layout_panels(
        image,
        show_billboard_panel=bool(context.leftover_open_billboards or context.leftover_preset_billboards),
    )
    _draw_role_panel(image, draw, context.role_entries, fonts)
    _draw_stats_block(
        image,
        draw,
        context.selected_payload,
        quick_mode=context.quick_mode,
        fonts=fonts,
    )
    _draw_week_action(draw, context.selected_payload, fonts)
    _draw_province_rank(draw, context.selected_payload, fonts)
    _draw_top_heroes(image, draw, config, context.top_heroes, fonts)
    _draw_hero_usage_block(
        image,
        draw,
        config,
        context.hero_rows,
        hero_title=context.hero_title,
        quick_mode=context.quick_mode,
        fonts=fonts,
    )
    _draw_leftover_billboards(
        image,
        draw,
        config,
        context.leftover_open_billboards,
        context.leftover_preset_billboards,
        fonts,
    )
    _draw_recent_match_timeline(image, config, context.recent_matches, fonts)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _draw_name_block(
    image: Any,
    draw: Any,
    config: Dict[str, Any],
    *,
    battletag: str,
    battlenum: str,
    title: str,
    level: int,
    fonts: Dict[str, Any],
) -> int:
    if battletag.isascii():
        display_name = battletag.upper()
        title_font = fonts["font_en_large"]
    else:
        display_name = battletag
        title_font = fonts["font_cn_large"]

    draw.text((280, 90), display_name, font=title_font, fill="white", spacing=5)
    text_width = _measure_text_width(draw, display_name, title_font)

    if title and title != STR_NO_TITLE:
        draw.text((280, 178), title, font=fonts["font_cn_small"], fill="lightgray", spacing=5)

    if level > 0:
        icon = _load_appreciation_icon(config, level)
        if icon is not None:
            icon = _resize_image(icon, (64, 64))
            image.paste(icon, (280 + text_width + 10, 80), icon)

    if battlenum:
        _draw_mixed_text(
            draw,
            280 + text_width + 10,
            148,
            f"#{battlenum}",
            label_font=fonts["font_en_small"],
            number_font=fonts["font_en_small"],
            fill="white",
        )
    return text_width


def _draw_header(draw: Any, game_time: float, fonts: Dict[str, Any]) -> None:
    draw.text((65, 344), "TIME PLAYED", font=fonts["font_en_header"], fill="#24324B")
    draw.text((778, 344), "MOST PLAYED HEROES IN SEASON", font=fonts["font_en_header"], fill="#24324B")
    draw.text((1690, 244), "RECENT MATCH", font=fonts["font_en_header"], fill="#24324B")
    draw.line((1690, 282, 2490, 282), fill="#95A3BD", width=2)
    draw.text((800, 758), "ROLE", font=fonts["font_en_small2"], fill="#1c2238")
    draw.text((1000, 758), "CURRENT", font=fonts["font_en_small2"], fill="#1c2238")
    draw.text((1200, 758), "SEASON HIGH", font=fonts["font_en_small2"], fill="#1c2238")
    draw.text((1400, 758), "MATCH SUM", font=fonts["font_en_small2"], fill="#1c2238")
    draw.text((70, 230), STR_INFO_SWITCH_MODE, font=fonts["font_cn_small_ex"], fill="#1c2238")
    _draw_mixed_text(
        draw,
        418,
        286,
        f"{int(game_time):,} HRS",
        label_font=fonts["font_en_50"],
        number_font=fonts["font_en_huge"],
        fill="#1c2238",
    )


def _draw_layout_panels(image: Any, *, show_billboard_panel: bool = False) -> None:
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    hero_box = (772, 392, 1602, 668)
    role_box = (772, 742, 1602, 1096)
    for box in (hero_box, role_box):
        draw.rounded_rectangle(box, radius=24, fill=(255, 255, 255, 34), outline=(255, 255, 255, 145), width=3)
        draw.rounded_rectangle(
            (box[0] + 10, box[1] + 10, box[2] - 10, box[3] - 10),
            radius=18,
            outline=(255, 255, 255, 52),
            width=1,
        )

    draw.line((hero_box[0] + 22, hero_box[1] + 18, hero_box[2] - 22, hero_box[1] + 18), fill=(255, 255, 255, 32), width=1)
    draw.line((role_box[0], 812, role_box[2], 812), fill=(255, 255, 255, 112), width=2)
    for divider_x in (956, 1182, 1402):
        draw.line((divider_x, 770, divider_x, 1076), fill=(255, 255, 255, 44), width=1)

    if show_billboard_panel:
        billboard_box = (772, 1098, 1602, 1264)
        draw.rounded_rectangle(billboard_box, radius=24, fill=(255, 255, 255, 26), outline=(255, 255, 255, 128), width=3)
        draw.rounded_rectangle(
            (billboard_box[0] + 10, billboard_box[1] + 10, billboard_box[2] - 10, billboard_box[3] - 10),
            radius=18,
            outline=(255, 255, 255, 44),
            width=1,
        )
        draw.line((billboard_box[0] + 20, billboard_box[1] + 42, billboard_box[2] - 20, billboard_box[1] + 42), fill=(255, 255, 255, 42), width=1)

    image.alpha_composite(overlay)


def _draw_race_progress(draw: Any, race_progress: Dict[str, Any] | None, fonts: Dict[str, Any]) -> None:
    if not isinstance(race_progress, dict):
        return

    progress_score = _safe_int(race_progress.get("score"))
    if progress_score <= 0:
        return

    progress_x = 280
    progress_y = 258
    progress_width = 1040
    progress_height = 18
    progress_cap = _safe_int(race_progress.get("cap")) or 4000
    progress_ratio = min(1.0, max(0.0, progress_score / max(1, progress_cap)))
    progress_right = progress_x + progress_width
    reached_count = sum(1 for checkpoint in race_progress.get("checkpoints", []) if progress_score >= checkpoint)

    progress_meta = (
        f"{progress_score}/{progress_cap}  "
        f"胜{_safe_int(race_progress.get('wins'))} "
        f"负{_safe_int(race_progress.get('losses'))} "
        f"组队胜{_safe_int(race_progress.get('group_wins'))} "
        f"节点{reached_count}/{len(race_progress.get('checkpoints', []))}"
    )
    progress_note = str(race_progress.get("note") or "")
    progress_fill_color = "#2F7D57"
    progress_bg_color = "#1c2238"

    bar_bg = [progress_x, progress_y, progress_right, progress_y + progress_height]
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(bar_bg, radius=9, fill=progress_bg_color, outline=progress_bg_color)
    else:
        draw.rectangle(bar_bg, fill=progress_bg_color, outline=progress_bg_color)

    fill_right = progress_x + int(progress_width * progress_ratio)
    fill_right = min(progress_right, max(progress_x + progress_height, fill_right))
    fill_box = [progress_x, progress_y, fill_right, progress_y + progress_height]
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(fill_box, radius=9, fill=progress_fill_color)
    else:
        draw.rectangle(fill_box, fill=progress_fill_color)

    for checkpoint in race_progress.get("checkpoints", []):
        checkpoint_value = _safe_int(checkpoint)
        checkpoint_ratio = min(1.0, max(0.0, checkpoint_value / max(1, progress_cap)))
        checkpoint_x = progress_x + int(progress_width * checkpoint_ratio)
        checkpoint_x = min(progress_right, max(progress_x, checkpoint_x))
        node_radius = 13
        node_center_y = progress_y + progress_height / 2
        node_box = [
            checkpoint_x - node_radius,
            node_center_y - node_radius,
            checkpoint_x + node_radius,
            node_center_y + node_radius,
        ]
        reached = progress_score >= checkpoint_value
        draw.ellipse(
            node_box,
            fill=progress_fill_color if reached else "#F4F6F8",
            outline="#FFFFFF" if reached else "#9AA4B2",
        )

        checkpoint_label = str(checkpoint_value)
        label_w = _measure_text_width(draw, checkpoint_label, fonts["font_num_small"])
        label_x = min(max(progress_x, checkpoint_x - label_w / 2), progress_right - label_w)
        draw.text(
            (label_x, progress_y + progress_height + 10),
            checkpoint_label,
            font=fonts["font_num_small"],
            fill="#1c2238" if reached else "#6b7280",
        )

    header_y = progress_y + progress_height + 34
    draw.text((progress_x, header_y), STR_RACE_PROGRESS, font=fonts["font_cn_small"], fill="#1c2238")
    title_w = _measure_text_width(draw, STR_RACE_PROGRESS, fonts["font_cn_small"])
    _draw_mixed_text(
        draw,
        progress_x + title_w + 16,
        header_y + 5,
        f"{progress_meta}  {progress_note}",
        label_font=fonts["font_cn_small_ex"],
        number_font=fonts["font_cn_small_ex"],
        fill="#4b5563",
    )


def _draw_role_panel(image: Any, draw: Any, entries: Sequence[RolePanelEntry], fonts: Dict[str, Any]) -> None:
    role_map = {entry.role_type: entry for entry in entries}
    for role_type, y_pos in (("tank", 817), ("dps", 891), ("healer", 964), ("open", 1038)):
        entry = role_map.get(role_type)
        role_label = {
            "tank": "TANK",
            "dps": "DAMAGE",
            "healer": "SUPPORT",
            "open": "OPEN",
        }.get(role_type, "OPEN")
        role_center_y = y_pos + 16
        role_icon = _load_role_icon(role_type, size=(28, 28))
        if role_icon is not None:
            image.paste(role_icon, (800, y_pos + 2), role_icon)
        try:
            text_box = draw.textbbox((0, 0), role_label, font=fonts["font_en_small2"])
            text_y = int(role_center_y - (text_box[3] - text_box[1]) / 2 - text_box[1])
            draw.text((840, text_y), role_label, font=fonts["font_en_small2"], fill="#1c2238")
        except Exception:
            draw.text((840, y_pos + 2), role_label, font=fonts["font_en_small2"], fill="#1c2238")

        if entry is None or entry.score <= 0:
            draw.text((1000, y_pos), "UNRANKED", font=fonts["font_en_small2"], fill="#1c2238")
            draw.text((1200, y_pos), "UNRANKED", font=fonts["font_en_small2"], fill="#1c2238")
            if entry and entry.is_history and entry.history_season:
                _draw_mixed_text(draw, 1070, y_pos + 44, entry.history_season, label_font=fonts["font_en_small2_ex"], number_font=fonts["font_en_small2_ex"], fill="#1c2238")
                _draw_mixed_text(draw, 1270, y_pos + 44, entry.history_season, label_font=fonts["font_en_small2_ex"], number_font=fonts["font_en_small2_ex"], fill="#1c2238")
            if entry:
                _draw_mixed_text(draw, 1430, y_pos, f"{entry.match_sum} | W {entry.win_sum}", label_font=fonts["font_en_small2"], number_font=fonts["font_en_small2"], fill="#1c2238")
            continue

        current_icon = _build_rank_icon(entry.score, entry.tier, fonts["font_rank_tier"], (154, 52), tier_vertical_offset=14)
        high_icon = _build_rank_icon(entry.max_score, entry.max_tier, fonts["font_rank_tier"], (154, 52), tier_vertical_offset=14)
        current_badge_y = y_pos + 6
        high_badge_y = y_pos + 6

        if current_icon is not None:
            current_icon = _apply_history_style(current_icon, entry.is_history)
            image.paste(current_icon, (970, current_badge_y), current_icon)
            if entry.is_history and entry.history_season:
                _draw_mixed_text(draw, 1075, current_badge_y + 34, entry.history_season, label_font=fonts["font_en_small2_ex"], number_font=fonts["font_en_small2_ex"], fill="#1c2238")
        else:
            _draw_mixed_text(draw, 1000, y_pos, f"{entry.score}{entry.tier}", label_font=fonts["font_en_small2"], number_font=fonts["font_en_small2"], fill="#1c2238")

        if high_icon is not None:
            high_icon = _apply_history_style(high_icon, entry.is_history)
            image.paste(high_icon, (1185, high_badge_y), high_icon)
            if entry.is_history and entry.history_season:
                _draw_mixed_text(draw, 1290, high_badge_y + 34, entry.history_season, label_font=fonts["font_en_small2_ex"], number_font=fonts["font_en_small2_ex"], fill="#1c2238")
        else:
            _draw_mixed_text(draw, 1200, y_pos, f"{entry.max_score}{entry.max_tier}", label_font=fonts["font_en_small2"], number_font=fonts["font_en_small2"], fill="#1c2238")

        _draw_mixed_text(draw, 1430, y_pos, f"{entry.match_sum} | W {entry.win_sum}", label_font=fonts["font_en_small2"], number_font=fonts["font_en_small2"], fill="#1c2238")


def _draw_stats_block(
    image: Any,
    draw: Any,
    payload_data: Dict[str, Any],
    *,
    quick_mode: bool,
    fonts: Dict[str, Any],
) -> None:
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
    if not quick_mode:
        labels.append(
            (STR_STAT_DEATH, summary.get("aveDeath", 0), recent.get("aveDeath", 0), server.get("death", 0), (server.get("maxDeath") or 1) * 1.5)
        )

    curr_y = 415
    for label, val_ave, val_recent, val_server, val_max in labels:
        _draw_ow_stat_group(draw, curr_y, label, val_ave, val_recent, val_server, val_max, fonts)
        curr_y += 55

    _draw_ow_radar_chart(image, 650, 520, 90, radar_data, fonts["font_cn_small"])


def _draw_ow_stat_group(
    draw: Any,
    y_base: int,
    label_txt: str,
    val_ave: Any,
    val_recent: Any,
    val_server: Any,
    val_max: Any,
    fonts: Dict[str, Any],
) -> None:
    start_x_label = 60
    start_x_bar = 120
    bar_width = 300
    start_x_num = 440

    max_value = _safe_float(val_max)
    if max_value <= 0:
        max_value = 1

    ave = _safe_float(val_ave)
    recent = _safe_float(val_recent)
    server = _safe_float(val_server)

    def get_width(value: float) -> int:
        ratio = max(0.0, min(value / max_value, 1.0))
        return int(bar_width * ratio)

    draw.rectangle([start_x_label - 10, y_base, start_x_label - 5, y_base + 35], fill="#F99E1A")
    draw.text((start_x_label, y_base + 5), label_txt, font=fonts["font_cn_small"], fill="#1c2238")

    sub_y_ave = y_base
    sub_y_rec = y_base + 14
    sub_y_svr = y_base + 28

    draw.rectangle([start_x_bar, sub_y_ave + 2, start_x_bar + bar_width, sub_y_ave + 8], fill="#292E3B")
    draw.rectangle([start_x_bar, sub_y_ave + 2, start_x_bar + get_width(ave), sub_y_ave + 8], fill="gold")

    draw.rectangle([start_x_bar, sub_y_rec + 1, start_x_bar + bar_width, sub_y_rec + 10], fill="#292E3B")
    draw.rectangle([start_x_bar, sub_y_rec + 1, start_x_bar + get_width(recent), sub_y_rec + 10], fill="blue")

    draw.rectangle([start_x_bar, sub_y_svr + 2, start_x_bar + bar_width, sub_y_svr + 8], fill="#292E3B")
    draw.rectangle([start_x_bar, sub_y_svr + 2, start_x_bar + get_width(server), sub_y_svr + 8], fill="red")

    _draw_mixed_text(draw, start_x_num, sub_y_ave - 2, f"{STR_STAT_AVG}: {_fmt_num(ave)}", label_font=fonts["font_cn_small_ex"], number_font=fonts["font_cn_small_ex"], fill="#1c2238")
    _draw_mixed_text(draw, start_x_num, sub_y_rec - 2, f"{STR_STAT_RECENT}: {_fmt_num(recent)}", label_font=fonts["font_cn_small_ex"], number_font=fonts["font_cn_small_ex"], fill="#1c2238")
    _draw_mixed_text(draw, start_x_num, sub_y_svr - 2, f"{STR_STAT_SERVER}: {_fmt_num(server)}", label_font=fonts["font_cn_small_ex"], number_font=fonts["font_cn_small_ex"], fill="#1c2238")


def _draw_ow_radar_chart(
    bg_img: Any,
    center_x: int,
    center_y: int,
    radius: int,
    data_dict: Dict[str, tuple[Any, Any, str]],
    font_cn_small: Any,
) -> None:
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    draw_line = ImageDraw.Draw(bg_img)

    angles = [-90, -18, 54, 126, 198]
    keys = ["damage", "kill", "death", "resist", "cure"]

    for ratio in (1.0, 0.66, 0.33):
        points = []
        for angle in angles:
            rad = math.radians(angle)
            points.append((center_x + radius * ratio * math.cos(rad), center_y + radius * ratio * math.sin(rad)))
        draw_line.polygon(points, outline="#3A404D", width=2)

    label_offset = 20
    for index, angle in enumerate(angles):
        rad = math.radians(angle)
        tip_x = center_x + radius * math.cos(rad)
        tip_y = center_y + radius * math.sin(rad)
        draw_line.line((center_x, center_y, tip_x, tip_y), fill="#3A404D", width=2)
        text = data_dict[keys[index]][2]
        txt_x = center_x + (radius + label_offset) * math.cos(rad)
        txt_y = center_y + (radius + label_offset) * math.sin(rad)
        text_width = _measure_font_length(font_cn_small, text)
        draw_line.text((txt_x - text_width / 2, txt_y - 10), text, font=font_cn_small, fill="#F0F0F0")

    points = []
    for index, key in enumerate(keys):
        value, max_value, _ = data_dict[key]
        current = _safe_float(value)
        top = _safe_float(max_value)
        if top <= 0:
            top = 1
        ratio = 1.0 - (current / (top * 1.5)) if key == "death" else current / top
        ratio = max(0.05, min(1.0, ratio))
        rad = math.radians(angles[index])
        points.append((center_x + radius * ratio * math.cos(rad), center_y + radius * ratio * math.sin(rad)))

    draw_ov.polygon(points, fill=(249, 158, 26, 100))
    draw_ov.line(points + [points[0]], fill=(249, 158, 26, 255), width=3)
    bg_img.alpha_composite(overlay)


def _draw_week_action(draw: Any, payload_data: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    game_action = payload_data.get("gameAction")
    if not isinstance(game_action, dict):
        return
    comment = str(game_action.get("comment") or "")
    get_honor = _safe_int(game_action.get("getHonorsCnt"))
    send_honor = _safe_int(game_action.get("sendHonorsCnt"))
    reported_cnt = _safe_int(game_action.get("reportedCnt"))
    _draw_mixed_text(draw, 60, 620, f"{STR_WEEK_COMMENT}:{comment}", label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="#1c2238")
    _draw_mixed_text(draw, 60, 660, f"{STR_HONOR}: {send_honor}/{get_honor}", label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="#1c2238")
    _draw_mixed_text(draw, 60, 700, f"{STR_REPORTED}: {reported_cnt}", label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="#1c2238")


def _draw_province_rank(draw: Any, payload_data: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    user_province_rank_list = _list_dicts(payload_data.get("userProvinceRankList"))
    y = 70
    for item in user_province_rank_list:
        role_type = str(item.get("roleType") or "")
        role_name = {
            "tank": STR_ROLE_TANK,
            "dps": STR_ROLE_DPS,
            "healer": STR_ROLE_HEALER,
        }.get(role_type, STR_ROLE_OPEN)
        province = str(item.get("province") or "")
        rank_num = _safe_int(item.get("rankNum"))
        _draw_mixed_text(draw, 1690, y, f"{province}{role_name} #{rank_num}{STR_RANK_SUFFIX}", label_font=fonts["font_cn"], number_font=fonts["font_cn"], fill="gold")
        y += 50


def _draw_top_heroes(
    image: Any,
    draw: Any,
    config: Dict[str, Any],
    hero_rows: Sequence[HeroUsageRow],
    fonts: Dict[str, Any],
) -> None:
    for index, row in enumerate(list(hero_rows)[:3]):
        slot_x = 840 + index * 290
        center_x = slot_x + 64
        hero_info = _find_hero(config, row.hero_guid)
        hero_name = str(hero_info.get("name") or row.payload.get("heroName") or row.hero_guid)
        ring_color = _hero_ring_color(config, hero_name)

        _draw_centered_mixed_text_with_shadow(
            draw,
            center_x,
            610,
            f"{hero_name} {row.hero_level}{STR_LEVEL_SUFFIX}",
            label_font=fonts["font_cn_small"],
            number_font=fonts["font_cn_small"],
            fill="#20283C",
            shadow_fill=(255, 255, 255, 150),
        )
        _draw_centered_mixed_text_with_shadow(
            draw,
            center_x,
            640,
            f"W:{row.win_sum}/L:{max(0, row.match_sum - row.win_sum)}/WR {int(row.win_rate)}%",
            label_font=fonts["font_en_small"],
            number_font=fonts["font_en_small"],
            fill="#273249",
            shadow_fill=(255, 255, 255, 145),
        )

        icon = None
        for candidate_url in (
            hero_info.get("smallIconUrl"),
            hero_info.get("ddHeroIcon"),
            hero_info.get("icon"),
        ):
            icon = _load_remote_asset_image(candidate_url, category="heroes")
            if icon is not None:
                break
        if icon is not None:
            icon = _resize_image(crop_to_circle(icon, 15, ring_color), (128, 128))
            image.paste(icon, (slot_x, 448), icon)

        tier_icon = _load_level_tier_icon(_hero_level_tier(row.hero_level))
        if tier_icon is not None:
            tier_icon = _resize_image(tier_icon, (80, 80))
            image.paste(tier_icon, (slot_x + 25, 538), tier_icon)


def _draw_hero_usage_block(
    image: Any,
    draw: Any,
    config: Dict[str, Any],
    hero_rows: Sequence[HeroUsageRow],
    *,
    hero_title: str,
    quick_mode: bool,
    fonts: Dict[str, Any],
) -> None:
    from PIL import Image, ImageDraw

    _draw_mixed_text(draw, 60, 735, hero_title, label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="#1c2238")
    rows = list(hero_rows)[:10]
    max_length = rows[0].game_time if rows else 0.0

    for index, row in enumerate(rows):
        hero_info = _find_hero(config, row.hero_guid)
        hero_name = str(hero_info.get("name") or row.payload.get("heroName") or row.hero_guid)
        hero_icon_url = str(hero_info.get("icon") or "")
        ring_color = _hero_ring_color(config, hero_name)
        y = 795 + index * 43

        base_bar = create_gradient_playtime_bar(620, 40, 5, (28, 34, 56), 1)
        image.paste(base_bar, (100, y), base_bar)
        fill_bar = create_gradient_playtime_bar(620, 40, 5, ring_color[:3], _calc_playtime_ratio(row.game_time, max_length))
        image.paste(fill_bar, (100, y), fill_bar)

        icon = _load_remote_asset_image(hero_icon_url, category="heroes")
        if icon is not None:
            icon = _resize_image(icon, (40, 40))
            image.paste(icon, (60, y))

        tier_icon = _load_level_tier_icon(_hero_level_tier(row.hero_level))
        if tier_icon is not None:
            tier_icon = _resize_image(tier_icon, (32, 32))
            image.paste(tier_icon, (110, 799 + index * 43), tier_icon)

        _draw_mixed_text(draw, 140, 802 + index * 43, f"{row.hero_level}{STR_LEVEL_SUFFIX}", label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="gold")

        if row.rank_overlay is not None:
            score_box_x = 523
            score_box_y = 798 + index * 43
            score_box_width = 110
            score_box_height = 36
            rectangle = Image.new("RGBA", (score_box_width, score_box_height), (0, 0, 0, 0))
            rect_draw = ImageDraw.Draw(rectangle)
            rect_draw.rounded_rectangle((0, 0, score_box_width - 1, score_box_height - 1), radius=10, fill=row.rank_overlay.fill, outline=(255, 255, 255, 48))
            image.paste(rectangle, (score_box_x, score_box_y), rectangle)
            text_left = score_box_x + 8
            rank_icon = _load_rank_pure_icon(row.rank_overlay.rank_level)
            if rank_icon is not None:
                if row.rank_overlay.rank_level < 6:
                    rank_icon = _resize_image(rank_icon, (32, 32))
                    image.paste(rank_icon, (score_box_x + 5, score_box_y + 1), rank_icon)
                    text_left = score_box_x + 41
                else:
                    rank_icon = _resize_image(rank_icon, (42, 32))
                    image.paste(rank_icon, (score_box_x, score_box_y + 1), rank_icon)
                    text_left = score_box_x + 46
            text_fill = "white" if row.rank_overlay.fill[0] < 80 else "#1c2238"
            _draw_text_centered_in_box(
                draw,
                str(row.rank_overlay.ranked_level),
                (text_left, score_box_y - 1, score_box_x + score_box_width - 6, score_box_y + score_box_height - 1),
                font=fonts["font_rank_overlay_num"],
                fill=text_fill,
            )

        stat_chip_x = 250
        stat_chip_y = 800 + index * 43
        stat_chip_width = 224
        stat_chip_height = 30

        if not row.billboards:
            stat_chip = Image.new("RGBA", (224, 30), (0, 0, 0, 0))
            stat_draw = ImageDraw.Draw(stat_chip)
            stat_draw.rounded_rectangle((0, 0, 223, 29), radius=12, fill=(18, 24, 38, 108), outline=(255, 255, 255, 34))
            image.paste(stat_chip, (stat_chip_x, stat_chip_y), stat_chip)
            _draw_mixed_text_with_shadow(
                draw,
                264,
                802 + index * 43,
                f"W:{row.win_sum}/L:{max(0, row.match_sum - row.win_sum)}/WR {int(row.win_rate)}%",
                label_font=fonts["font_en_small"],
                number_font=fonts["font_en_small"],
                fill="#EEF3FF",
                shadow_fill=(19, 24, 37, 210),
            )
        else:
            visible_billboards = list(row.billboards)[:2]
            chip_gap = 8
            billboard_chip_width = stat_chip_width if len(visible_billboards) == 1 else (stat_chip_width - chip_gap) // 2
            for billboard_index, billboard in enumerate(visible_billboards):
                bx = stat_chip_x + billboard_index * (billboard_chip_width + chip_gap)
                billboard_chip = Image.new("RGBA", (billboard_chip_width, stat_chip_height), (0, 0, 0, 0))
                billboard_draw = ImageDraw.Draw(billboard_chip)
                billboard_draw.rounded_rectangle(
                    (0, 0, billboard_chip_width - 1, stat_chip_height - 1),
                    radius=12,
                    fill=(252, 176, 90, 228),
                    outline=(255, 255, 255, 58),
                )
                image.paste(billboard_chip, (bx, stat_chip_y), billboard_chip)
                billboard_text = _truncate_mixed_text_to_width(
                    draw,
                    f"{billboard.province}#{billboard.rank_num}{STR_RANK_SUFFIX}",
                    billboard_chip_width - 12,
                    label_font=fonts["font_cn_small"],
                    number_font=fonts["font_cn_small"],
                )
                _draw_mixed_text(
                    draw,
                    bx + 6,
                    802 + index * 43,
                    billboard_text,
                    label_font=fonts["font_cn_small"],
                    number_font=fonts["font_cn_small"],
                    fill="#1c2238",
                )

        time_chip_x = 638
        rectangle = Image.new("RGBA", (70, 32), (0, 0, 0, 0))
        rect_draw = ImageDraw.Draw(rectangle)
        rect_draw.rounded_rectangle((0, 0, 69, 31), radius=12, fill=(12, 16, 26, 230), outline=(255, 255, 255, 40))
        image.paste(rectangle, (time_chip_x, 800 + index * 43), rectangle)
        _draw_mixed_text(
            draw,
            time_chip_x + 10,
            802 + index * 43,
            _readable_playtime(row.game_time, quick_mode=quick_mode),
            label_font=fonts["font_en_small"],
            number_font=fonts["font_en_small"],
            fill="skyblue",
        )

def _draw_leftover_billboards(
    image: Any,
    draw: Any,
    config: Dict[str, Any],
    open_billboards: Sequence[HeroBillboardEntry],
    preset_billboards: Sequence[HeroBillboardEntry],
    fonts: Dict[str, Any],
) -> None:
    x_index = 0
    y_index = 0

    if open_billboards:
        draw.text((800, 1120 + y_index * 30), STR_LEFTOVER_OPEN, font=fonts["font_cn_small"], fill="#1c2238")
        y_index += 1
        for billboard in open_billboards:
            _draw_leftover_billboard_chip(image, draw, config, 800 + x_index * 200, 1120 + y_index * 30, billboard, fonts, show_hero_name=True, highlight_rank=False)
            x_index += 1
            if x_index >= 4:
                x_index = 0
                y_index += 1
        y_index += 1

    if preset_billboards:
        x_index = 0
        draw.text((800, 1120 + y_index * 30), STR_LEFTOVER_PRESET, font=fonts["font_cn_small"], fill="#1c2238")
        y_index += 1
        for billboard in preset_billboards:
            _draw_leftover_billboard_chip(image, draw, config, 800 + x_index * 200, 1120 + y_index * 30, billboard, fonts, show_hero_name=False, highlight_rank=True)
            x_index += 1
            if x_index >= 4:
                x_index = 0
                y_index += 1


def _draw_leftover_billboard_chip(
    image: Any,
    draw: Any,
    config: Dict[str, Any],
    x: int,
    y: int,
    billboard: HeroBillboardEntry,
    fonts: Dict[str, Any],
    *,
    show_hero_name: bool,
    highlight_rank: bool,
) -> None:
    hero_info = _find_hero(config, billboard.hero_guid)
    hero_name = str(hero_info.get("name") or billboard.hero_guid)
    text = f"{hero_name} #{billboard.rank_num}{STR_RANK_SUFFIX}" if show_hero_name else f"#{billboard.rank_num}{STR_RANK_SUFFIX}"
    if show_hero_name:
        text = _truncate_mixed_text_to_width(
            draw,
            text,
            134,
            label_font=fonts["font_cn_small"],
            number_font=fonts["font_cn_small"],
        )
    chip_width = min(192, max(96 if not show_hero_name else 136, _measure_mixed_text(draw, text, label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"]) + 50))
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle((x, y - 1, x + chip_width, y + 25), radius=10, fill=(235, 241, 252, 122), outline=(255, 255, 255, 170), width=2)
    else:
        draw.rectangle((x, y - 1, x + chip_width, y + 25), fill=(235, 241, 252, 122), outline=(255, 255, 255, 170), width=2)

    icon = None
    for candidate_url in (
        hero_info.get("smallIconUrl"),
        hero_info.get("ddHeroIcon"),
        hero_info.get("icon"),
    ):
        icon = _load_remote_asset_image(candidate_url, category="heroes")
        if icon is not None:
            break
    if icon is not None:
        icon = _resize_image(crop_to_circle(icon, 2, _hero_ring_color(config, hero_name)), (22, 22))
        image.paste(icon, (x + 8, y + 1), icon)
        text_x = x + 36
    else:
        text_x = x + 10
    _draw_mixed_text(
        draw,
        text_x,
        y,
        text,
        label_font=fonts["font_cn_small"],
        number_font=fonts["font_cn_small"],
        fill="#D39B1F" if highlight_rank else "#24324B",
    )


def _draw_recent_match_timeline(image: Any, config: Dict[str, Any], matches: Sequence[Dict[str, Any]], fonts: Dict[str, Any]) -> None:
    from PIL import ImageDraw

    for index, item in enumerate(list(matches)[:24]):
        bg = _load_match_bar_template()
        bgdraw = ImageDraw.Draw(bg)
        match_type = _recent_match_type(item)
        mode_bar_color = _recent_match_type_color(item, match_type)
        bgdraw.rectangle((0, 0, 8, bg.height), fill=mode_bar_color)

        map_name = _map_name(config, item.get("mapGuid"))
        begin_ts = _safe_int(item.get("beginTs"))
        if begin_ts > 10_000_000_000:
            begin_ts //= 1000
        difftime = _relative_time(begin_ts)
        hero_guid = str(item.get("heroGuid") or "")
        hero_info = _find_hero(config, hero_guid)
        hero_name = str(hero_info.get("name") or item.get("heroName") or hero_guid)
        hero_icon_url = str(hero_info.get("icon") or "")

        map_name = _truncate_text_to_width(bgdraw, map_name, 210, fonts["font_cn_small"])
        _draw_mixed_text(bgdraw, 44, 6, map_name, label_font=fonts["font_cn_small"], number_font=fonts["font_cn_small"], fill="white")
        _draw_mixed_text_with_shadow(
            bgdraw,
            544,
            8,
            difftime,
            label_font=fonts["font_en_match_small"],
            number_font=fonts["font_en_match_small"],
            fill="#19253D",
            shadow_fill=(255, 255, 255, 96),
            shadow_offset=(0, 1),
        )

        icon = _load_remote_asset_image(hero_icon_url, category="heroes")
        if icon is not None:
            icon = _resize_image(crop_to_circle(icon, 3, _hero_ring_color(config, hero_name)), (30, 30))
            bg.paste(icon, (268, 3), icon)

        _draw_recent_match_type(bg, bgdraw, item, match_type, fonts)
        _draw_recent_match_result(bg, bgdraw, item, fonts)
        image.paste(bg, (1700, 294 + 39 * index), bg)


def _draw_recent_match_type(bg: Any, bgdraw: Any, item: Dict[str, Any], match_type: str, fonts: Dict[str, Any]) -> None:
    if match_type == "IT_UNRANKED":
        _draw_mixed_text_with_shadow(
            bgdraw,
            322,
            8,
            "UNRANKED",
            label_font=fonts["font_en_match"],
            number_font=fonts["font_en_match"],
            fill="#1D5CFF",
            shadow_fill=(255, 255, 255, 70),
            shadow_offset=(0, 1),
        )
        return
    if match_type == "STADIUM QP":
        _draw_mixed_text_with_shadow(
            bgdraw,
            322,
            8,
            "STADIUM QP",
            label_font=fonts["font_en_match"],
            number_font=fonts["font_en_match"],
            fill="#15AA47",
            shadow_fill=(255, 255, 255, 70),
            shadow_offset=(0, 1),
        )
        return
    if match_type == "STADIUM COMP":
        _draw_mixed_text_with_shadow(
            bgdraw,
            322,
            8,
            "STADIUM COMP",
            label_font=fonts["font_en_match"],
            number_font=fonts["font_en_match"],
            fill="#B86F00",
            shadow_fill=(255, 255, 255, 70),
            shadow_offset=(0, 1),
        )
        return
    if match_type == "IT_RULESET":
        rank_info = item.get("rankInfo")
        if isinstance(rank_info, dict) and _safe_int(rank_info.get("rankScore")) > 0:
            _draw_mixed_text_with_shadow(
                bgdraw,
                322,
                8,
                "COMP 6V6",
                label_font=fonts["font_en_match"],
                number_font=fonts["font_en_match"],
                fill=COLOR_COMPETITIVE,
                shadow_fill=(255, 255, 255, 76),
                shadow_offset=(0, 1),
            )
            badge = _build_rank_icon(_safe_int(rank_info.get("rankScore")), str(rank_info.get("rankSubTier") or ""), fonts["font_rank_tier_recent"], (86, 28), tier_vertical_offset=16)
            if badge is not None:
                bg.paste(badge, (430, 4), badge)
        else:
            _draw_mixed_text_with_shadow(
                bgdraw,
                322,
                8,
                "UNR 6V6",
                label_font=fonts["font_en_match"],
                number_font=fonts["font_en_match"],
                fill="#2F79FF",
                shadow_fill=(255, 255, 255, 76),
                shadow_offset=(0, 1),
            )
        return

    _draw_mixed_text_with_shadow(
        bgdraw,
        322,
        8,
        "COMPETITIVE",
        label_font=fonts["font_en_match"],
        number_font=fonts["font_en_match"],
        fill=COLOR_COMPETITIVE,
        shadow_fill=(255, 255, 255, 76),
        shadow_offset=(0, 1),
    )
    rank_info = item.get("rankInfo")
    if isinstance(rank_info, dict) and _safe_int(rank_info.get("rankScore")) > 0:
        badge = _build_rank_icon(_safe_int(rank_info.get("rankScore")), str(rank_info.get("rankSubTier") or ""), fonts["font_rank_tier_recent"], (86, 28), tier_vertical_offset=16)
        if badge is not None:
            bg.paste(badge, (430, 4), badge)


def _draw_recent_match_result(bg: Any, bgdraw: Any, item: Dict[str, Any], fonts: Dict[str, Any]) -> None:
    from PIL import Image, ImageDraw

    match_ret = _safe_int(item.get("matchRet"))
    team_score = _safe_int(item.get("teamScore"))
    opponent_score = _safe_int(item.get("opponentScore"))
    if match_ret == 1:
        fill = (18, 186, 83, 255)
        label = "VICTORY!"
    elif match_ret == 0:
        fill = (130, 136, 149, 255)
        label = "TIE"
    else:
        fill = (219, 47, 61, 255)
        label = "DEFEAT!"

    panel = Image.new("RGBA", (141, 28), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle((0, 0, 140, 27), radius=10, fill=fill, outline=(255, 255, 255, 90))
    panel_draw.line((86, 4, 86, 23), fill=(255, 255, 255, 100), width=1)
    bg.paste(panel, (650, 4), panel)
    _draw_mixed_text_with_shadow(
        bgdraw,
        662,
        8,
        label,
        label_font=fonts["font_en_small2_20"],
        number_font=fonts["font_en_small2_20"],
        fill="white",
        shadow_fill=(0, 0, 0, 90),
        shadow_offset=(0, 1),
    )
    _draw_mixed_text_with_shadow(
        bgdraw,
        740,
        8,
        f"{team_score}-{opponent_score}",
        label_font=fonts["font_en_small2_20"],
        number_font=fonts["font_en_small2_20"],
        fill="white",
        shadow_fill=(0, 0, 0, 90),
        shadow_offset=(0, 1),
    )


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
    if isinstance(rank_info, dict) and rank_info:
        return "COMPETITIVE"
    return instance_type or "COMPETITIVE"


def _recent_match_type_color(item: Dict[str, Any], match_type: str) -> tuple[int, int, int, int]:
    if match_type == "IT_UNRANKED":
        return (29, 92, 255, 255)
    if match_type == "STADIUM QP":
        return (21, 170, 71, 255)
    if match_type == "STADIUM COMP":
        return (184, 111, 0, 255)
    if match_type == "IT_RULESET":
        rank_info = item.get("rankInfo")
        if isinstance(rank_info, dict) and _safe_int(rank_info.get("rankScore")) > 0:
            return hex_to_rgba(COLOR_COMPETITIVE)
        return (47, 121, 255, 255)
    return hex_to_rgba(COLOR_COMPETITIVE)


def _build_rank_icon(score: int, tier: str, tier_font: Any, size: tuple[int, int], *, tier_vertical_offset: float = 0.0) -> Any | None:
    from PIL import Image, ImageDraw

    if score <= 0:
        return None
    rank_index = _rank_level_from_score(score)
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

    normalized_level = max(1, min(8, _safe_int(rank_level)))
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


def _rank_level_from_score(score: int) -> int:
    level = (_safe_int(score) // 100) + 1
    max_level = 9 if (RESOURCE_DIR / "rank_flat" / "9.png").exists() else 8
    return max(1, min(max_level, level))


def _hero_level_tier(hero_level: int) -> int:
    if 0 <= hero_level < 25:
        return 1
    if 25 <= hero_level < 50:
        return 2
    if 50 <= hero_level < 75:
        return 3
    return 4


def _load_level_tier_icon(level_tier: int) -> Any | None:
    from PIL import Image

    path = RESOURCE_DIR / "rank_flat" / f"lv_tier{level_tier}.png"
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _load_match_bar_template() -> Any:
    from PIL import Image, ImageDraw

    width, height = 795, 36
    fallback = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fallback)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=(44, 56, 86, 245), outline=(213, 222, 241, 55))
    draw.rounded_rectangle((3, 3, width - 4, height - 4), radius=10, fill=(39, 49, 76, 238))
    draw.rounded_rectangle((314, 4, 518, height - 5), radius=8, fill=(255, 255, 255, 30), outline=(255, 255, 255, 60))
    draw.rounded_rectangle((522, 4, 645, height - 5), radius=8, fill=(242, 246, 252, 235), outline=(212, 219, 231, 120))
    draw.rounded_rectangle((648, 4, width - 5, height - 5), radius=8, fill=(255, 255, 255, 30), outline=(255, 255, 255, 80))
    draw.line((12, 1, width - 14, 1), fill=(255, 255, 255, 42), width=1)
    draw.line((18, height - 2, width - 18, height - 2), fill=(10, 15, 25, 110), width=1)
    return fallback


def _draw_avatar(image: Any, avatar_bytes: bytes | None, pos: tuple[int, int], size: tuple[int, int]) -> None:
    from PIL import Image, ImageOps

    if avatar_bytes:
        try:
            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
            avatar = ImageOps.fit(avatar, size, method=_resampling_lanczos())
            image.paste(avatar, pos, avatar)
            return
        except Exception:
            pass
    empty = Image.new("RGBA", size, (30, 35, 45, 255))
    image.paste(empty, pos)


def _load_background() -> Any:
    from PIL import Image

    fallback_paths = [
        RESOURCE_DIR / "profilebg.png",
        Path(__file__).resolve().parents[3] / "res" / "profilebg.png",
    ]
    for path in fallback_paths:
        if not path.exists():
            continue
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            continue
    return Image.new("RGBA", (2560, 1300), (245, 247, 250, 255))


def _normalize_role_type(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def _load_local_rgba(path: Path) -> Any | None:
    from PIL import Image

    if not path.exists():
        return None
    try:
        with Image.open(path) as raw_image:
            return raw_image.convert("RGBA")
    except Exception:
        return None


def _load_role_icon(role_type: Any, *, size: tuple[int, int]) -> Any | None:
    filename = ROLE_ICON_FILENAMES.get(_normalize_role_type(role_type))
    if not filename:
        return None
    icon = _load_local_rgba(RESOURCE_DIR / filename)
    if icon is None:
        return None
    return _resize_image(icon, size)


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


def _map_name(config: Dict[str, Any], map_guid: Any) -> str:
    target = str(map_guid or "")
    for item in config.get("mapList", []) or []:
        if str(item.get("guid") or "") == target:
            return str(item.get("name") or target)
    return target or STR_UNKNOWN_MAP


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


def _draw_text_centered_in_box(draw: Any, text: str, box: tuple[int, int, int, int], *, font: Any, fill: Any) -> None:
    left, top, right, bottom = box
    text = str(text or "")
    try:
        text_box = draw.textbbox((0, 0), text, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        draw_x = left + (right - left - text_width) / 2 - text_box[0]
        draw_y = top + (bottom - top - text_height) / 2 - text_box[1]
        draw.text((draw_x, draw_y), text, font=font, fill=fill)
    except Exception:
        draw.text(((left + right) / 2, (top + bottom) / 2), text, font=font, fill=fill, anchor="mm")


def _measure_font_length(font: Any, text: str) -> float:
    try:
        return float(font.getlength(text))
    except Exception:
        return float(len(text) * 12)


def _is_numeric_glyph(char: str) -> bool:
    return bool(char) and (char.isdigit() or char in "#%.,-+")


def _measure_mixed_text(draw: Any, text: str, *, label_font: Any, number_font: Any) -> int:
    width = 0
    last_kind = None
    segment = ""
    for char in str(text or ""):
        kind = _is_numeric_glyph(char)
        if last_kind is None or kind == last_kind:
            segment += char
            last_kind = kind
            continue
        width += _measure_text_width(draw, segment, number_font if last_kind else label_font)
        segment = char
        last_kind = kind
    if segment:
        width += _measure_text_width(draw, segment, number_font if last_kind else label_font)
    return width


def _truncate_mixed_text_to_width(
    draw: Any,
    text: str,
    max_width: int,
    *,
    label_font: Any,
    number_font: Any,
) -> str:
    text = str(text or "")
    if _measure_mixed_text(draw, text, label_font=label_font, number_font=number_font) <= max_width:
        return text
    ellipsis = "..."
    while text and _measure_mixed_text(draw, text + ellipsis, label_font=label_font, number_font=number_font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _draw_mixed_text(
    draw: Any,
    x: int,
    y: int,
    text: str,
    *,
    label_font: Any,
    number_font: Any,
    fill: Any,
    number_fill: Any | None = None,
) -> None:
    cursor_x = x
    last_kind = None
    segment = ""
    text = str(text or "")
    for char in text:
        kind = _is_numeric_glyph(char)
        if last_kind is None or kind == last_kind:
            segment += char
            last_kind = kind
            continue
        font = number_font if last_kind else label_font
        draw.text((cursor_x, y), segment, font=font, fill=number_fill if last_kind and number_fill is not None else fill)
        cursor_x += _measure_text_width(draw, segment, font)
        segment = char
        last_kind = kind
    if segment:
        font = number_font if last_kind else label_font
        draw.text((cursor_x, y), segment, font=font, fill=number_fill if last_kind and number_fill is not None else fill)


def _draw_mixed_text_with_shadow(
    draw: Any,
    x: int,
    y: int,
    text: str,
    *,
    label_font: Any,
    number_font: Any,
    fill: Any,
    shadow_fill: Any,
    shadow_offset: tuple[int, int] = (1, 1),
    number_fill: Any | None = None,
    shadow_number_fill: Any | None = None,
) -> None:
    offset_x, offset_y = shadow_offset
    _draw_mixed_text(
        draw,
        x + offset_x,
        y + offset_y,
        text,
        label_font=label_font,
        number_font=number_font,
        fill=shadow_fill,
        number_fill=shadow_number_fill if shadow_number_fill is not None else shadow_fill,
    )
    _draw_mixed_text(
        draw,
        x,
        y,
        text,
        label_font=label_font,
        number_font=number_font,
        fill=fill,
        number_fill=number_fill,
    )


def _draw_centered_mixed_text_with_shadow(
    draw: Any,
    center_x: int,
    y: int,
    text: str,
    *,
    label_font: Any,
    number_font: Any,
    fill: Any,
    shadow_fill: Any,
    shadow_offset: tuple[int, int] = (1, 1),
    number_fill: Any | None = None,
    shadow_number_fill: Any | None = None,
) -> None:
    width = _measure_mixed_text(draw, text, label_font=label_font, number_font=number_font)
    x = int(center_x - width / 2)
    _draw_mixed_text_with_shadow(
        draw,
        x,
        y,
        text,
        label_font=label_font,
        number_font=number_font,
        fill=fill,
        shadow_fill=shadow_fill,
        shadow_offset=shadow_offset,
        number_fill=number_fill,
        shadow_number_fill=shadow_number_fill,
    )


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


def _load_fonts() -> Dict[str, Any]:
    return {
        "font_en": _load_font("en.ttf", 40),
        "font_en_header": _load_font("bignoodletoooblique.ttf", 32),
        "font_en_50": _load_font("bignoodletoooblique.ttf", 56),
        "font_en_huge": _load_font("bignoodletoooblique.ttf", 72),
        "font_en_large": _load_font("bignoodletoooblique.ttf", 88),
        "font_en_small": _load_font("bignoodletoooblique.ttf", 24),
        "font_en_small2_ex": _load_font("bignoodletoooblique.ttf", 16),
        "font_en_small2_20": _load_font("BigNoodleToo.ttf", 20),
        "font_en_small2": _load_font("bignoodletoooblique.ttf", 30),
        "font_en_match": _load_font("BigNoodleToo.ttf", 22),
        "font_en_match_small": _load_font("BigNoodleToo.ttf", 18),
        "font_cn": _load_font("simhei.ttf", 40, windows_fallback=True),
        "font_cn_large": _load_font("simhei.ttf", 80, windows_fallback=True),
        "font_cn_small": _load_font("simhei.ttf", 25, windows_fallback=True),
        "font_cn_small_ex": _load_font("simhei.ttf", 15, windows_fallback=True),
        "font_num": _load_font("num.ttf", 30),
        "font_num_small": _load_font("num.ttf", 18),
        "font_num_medium": _load_font("num.ttf", 24),
        "font_num_large": _load_font("num.ttf", 40),
        "font_num_huge": _load_font("num.ttf", 72),
        "font_rank_tier": _load_font("num.ttf", 88),
        "font_rank_tier_small": _load_font("num.ttf", 52),
        "font_rank_tier_recent": _load_font("num.ttf", 64),
        "font_rank_overlay_num": _load_font("num.ttf", 24),
    }


def _load_font(name: str, size: int, *, windows_fallback: bool = False) -> Any:
    from PIL import ImageFont

    candidates: list[Path | str] = []
    if windows_fallback and name.lower() == "simhei.ttf":
        candidates.extend([Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/msyh.ttc")])
    candidates.append(RESOURCE_DIR / name)
    if not windows_fallback:
        candidates.extend([Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/msyh.ttc")])

    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return ImageFont.load_default()


def create_gradient_playtime_bar(
    width: int,
    height: int,
    radius: int,
    hero_color: tuple[int, int, int],
    playtime_ratio: float,
) -> Any:
    from PIL import Image, ImageDraw

    try:
        ratio = float(playtime_ratio or 0)
    except (TypeError, ValueError):
        ratio = 0.0
    ratio = max(0.0, min(ratio, 1.0))
    bar_width = int(round(width * ratio))

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if bar_width <= 0:
        return img

    bar_width = min(bar_width, width)
    if bar_width <= radius * 2:
        safe_radius = min(radius, max(0, (bar_width - 3) // 2), max(0, (height - 3) // 2))
        if safe_radius > 0 and hasattr(draw, "rounded_rectangle"):
            try:
                draw.rounded_rectangle([0, 0, bar_width - 1, height - 1], radius=safe_radius, fill=(0, 0, 0, 255))
            except ValueError:
                draw.rectangle([0, 0, bar_width - 1, height - 1], fill=(0, 0, 0, 255))
        else:
            draw.rectangle([0, 0, bar_width - 1, height - 1], fill=(0, 0, 0, 255))
    else:
        draw.rectangle([0, radius, bar_width, height - radius], fill=(0, 0, 0, 255))
        draw.pieslice([0, 0, radius * 2, radius * 2], 180, 270, fill=(0, 0, 0, 255))
        draw.pieslice([bar_width - radius * 2, 0, bar_width, radius * 2], 270, 360, fill=(0, 0, 0, 255))
        draw.pieslice([0, height - radius * 2, radius * 2, height], 90, 180, fill=(0, 0, 0, 255))
        draw.pieslice([bar_width - radius * 2, height - radius * 2, bar_width, height], 0, 90, fill=(0, 0, 0, 255))
        draw.rectangle([radius, 0, bar_width - radius, height], fill=(0, 0, 0, 255))

    for x in range(bar_width):
        gradient_ratio = (x / max(bar_width, 1)) ** 0.5
        r_val = int(hero_color[0] * gradient_ratio)
        g_val = int(hero_color[1] * gradient_ratio)
        b_val = int(hero_color[2] * gradient_ratio)
        for y in range(height):
            current = img.getpixel((x, y))
            if current[3] > 0:
                img.putpixel((x, y), (r_val, g_val, b_val, 255))

    return img


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


def crop_to_circle(
    im: Any,
    ring_width: int = 5,
    ring_color: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> Any:
    from PIL import Image, ImageDraw

    img = im.convert("RGBA")
    width, height = img.size
    size = min(width, height)
    img_cropped = img.crop(((width - size) // 2, (height - size) // 2, (width + size) // 2, (height + size) // 2))

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)
    img_cropped.putalpha(mask)

    ring_size = size + 2 * ring_width
    ring_img = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring_img)
    ring_draw.ellipse((0, 0, ring_size, ring_size), fill=ring_color)
    ring_draw.ellipse((ring_width, ring_width, ring_size - ring_width, ring_size - ring_width), fill=(0, 0, 0, 0))
    ring_img.paste(img_cropped, (ring_width, ring_width), img_cropped)
    return ring_img
