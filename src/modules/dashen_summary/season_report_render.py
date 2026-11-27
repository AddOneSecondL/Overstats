"""Adaptive season-report image, sharing the daily summary's assets and typography."""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import re
from io import BytesIO

from PIL import Image, ImageChops, ImageOps

from ...constants.ranks import (
    RAW_RANK_ID_TO_NAME, display_rank_label, get_rank_name, get_rank_score, get_rank_sub_tier,
    is_unranked_placeholder, rank_name_cn, rank_name_to_icon_level, raw_rank_score_parts, stadium_rank,
)
from ...constants.rank_queues import QUEUE_LABELS, RANK_QUEUE_ORDER, ROLE_LABELS, queue_mode
from ..dashen_promo import append_dashen_promo
from .engine import _load_runtime
from .season_report import RESOURCE_DIR, fmt, mapping, mode_name, rows
from .season_report_fields import first_value, name_text, number
from .season_report_ranks import rank_role
from .season_loot import count_value, loot_panel_height, render_loot_panel
from .runtime.summary_perks import PerkCatalog, guid
from .runtime.summary_style import C, RADIUS_CARD, RADIUS_TILE, themed, tinted as tint


def plain_text(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html.unescape(str(value)))).strip()


def perk_title(value):
    # Some config names append a description after an HTML line break.
    return plain_text(re.split(r"<br\s*/?>|\n", str(value or ""), maxsplit=1, flags=re.I)[0])


def is_percentage_label(label):
    return any(word in label for word in ("命中率", "胜率", "准确率", "暴击率"))


def date_text(value):
    try:
        return dt.datetime.strptime(str(value), "%Y%m%d").strftime("%Y/%m/%d")
    except (ValueError, TypeError):
        return "—"


def rank_heroes(row):
    value = row.get("most_play_hero_guid")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(key for value in values if (key := guid(value)).isdecimal() and key != "0"))


def rank_label(info, is_stadium=False):
    name = get_rank_name(info)
    if is_unranked_placeholder(info) or str(name).casefold() in {"none", "unranked"}:
        return rank_name_cn("Unranked")
    tier = get_rank_sub_tier(info)
    if is_stadium:
        level, label = stadium_rank(f"{name}{tier or ''}")
        return label if level else ""
    if not rank_name_to_icon_level(name):
        parts = raw_rank_score_parts(get_rank_score(info))
        if parts is None:
            return ""
        name, tier = RAW_RANK_ID_TO_NAME[parts[0]], parts[1]
    return f"{rank_name_cn(name)}{tier if tier else ''}"


def report_rank_label(value, queue_type=None):
    label = name_text(display_rank_label(value))
    if not label:
        return ""
    if queue_type == "stadium":
        return stadium_rank(label)[1]
    base = re.sub(r"\s*\d+$", "", label)
    return rank_name_cn(base) + label[len(base):] if rank_name_to_icon_level(base) else label


def has_match_detail(row):
    return any(name_text(row.get(key)) for key in ("hero_name", "hero_icon", "map_name")) or any(
        guid(row.get(key)) not in {"", "0"} for key in ("hero", "map")
    ) or any(number(row.get(key)) is not None for key in (
        "kill", "assist", "death", "result", "team_score", "opponent_score", "damage", "cure", "resist_damage",
    )) or bool(row.get("rank") or row.get("perks"))


@themed
async def render_report(report, role_id):
    s = _load_runtime().summary
    season, overview = report["season"], report["overview"]
    queue_order = {key: index for index, key in enumerate(RANK_QUEUE_ORDER)}
    ranks = sorted(report["ranks"], key=lambda row: queue_order.get(row.get("queue_key"), len(queue_order)))
    heroes, focus = report["heroes"], report["focus"]
    focus_rows = [row for row in rows(focus.get("stat_map")) if name_text(row.get("index_name")) and number(row.get("index_value")) is not None]
    low = report.get("low_win_heroes", [])
    highlights = [row for row in report.get("highlights", [])
                  if number(row.get("value")) is not None or has_match_detail(row)]
    true_matches = sorted(report.get("true_matches", []), key=lambda r: number(r.get("match_type")) or 0)
    detailed_matches = [row for row in true_matches if has_match_detail(row)]
    category_counts = [row for row in true_matches if not has_match_detail(row) and number(row.get("match_cnt")) is not None]
    perk_catalog = PerkCatalog(s.OW_CONFIG)
    map_aliases = {
        guid(value): str(item["guid"]) for item in rows(s.OW_CONFIG.get("mapList")) if item.get("guid")
        for value in (item.get("guid"), item.get("id")) if value
    }

    def hero_name(hero, fallback=None):
        return name_text(s._hero_name(guid(hero))) or name_text(fallback)

    def map_key(row):
        key = guid(row.get("map"))
        return map_aliases.get(key, key)

    def match_hero_icon(row):
        return s._hero_icon_url(guid(row.get("hero"))) or row.get("hero_icon")

    def perks_for(row):
        choices = [
            {"guid": key, "level": count_value(first_value(perk.get("perkLevel"), perk.get("level"))) or 0}
            for perk in rows(row.get("perks"))
            if (key := guid(perk.get("guid") or perk.get("id") or perk.get("perkGuid") or perk.get("value")))
        ]
        found = [{**perk, "name": perk_title(perk["name"])} for perk in perk_catalog.resolve(row.get("hero"), choices)]
        return [perk for perk in found if perk["icon"] or name_text(perk["name"])][:2]

    metric_specs = [
        ("活跃天数", "active_day_cnt", "active_day_rate", 0, C.INFO),
        ("在线小时", "online_time", "online_time_rate", 0, C.INFO),
        ("胜率", "win_rate", "win_rate_rate", 1, C.WIN),
        ("消灭", "kill_sum", "kill_rnk_rate", 0, C.INK),
        ("助攻", "assist_sum", "assist_rnk_rate", 0, C.INK),
        ("伤害", "damage_sum", "damage_rnk_rate", 0, C.DRAW),
        ("治疗", "cure_sum", "cure_rnk_rate", 0, C.WIN),
        ("承伤", "resist_damage_sum", "resist_damage_rate", 0, C.PURPLE),
    ]
    metric_specs = [spec for spec in metric_specs if number(overview.get(spec[1])) is not None]
    footprint_specs = [
        ("活跃天数", overview.get("active_day_cnt"), 0, "", C.INFO),
        ("收到赞赏", season.get("get_honors_cnt"), 0, "", C.WIN),
        ("送出赞赏", season.get("send_honors_cnt"), 0, "", C.WIN),
        ("单日最长在线", season.get("oneday_max_online_time"), 2, " 小时", C.INFO),
        ("在线时长超越", season.get("ahead_rate"), 2, "%", C.WIN),
        ("角斗领域场次", season.get("stadium_match_cnt"), 0, "", C.INFO),
        ("角斗领域经济", season.get("stadium_worth"), 0, "", C.WIN),
    ]
    footprint = [(label, fmt(value, decimals, suffix), color) for label, value, decimals, suffix, color in footprint_specs
                 if number(value) is not None]
    longest_day = date_text(season.get("oneday_max_online_dt"))
    if longest_day != "—":
        footprint.append(("在线最久的一天", longest_day, C.INK))
    favourite_mode = mode_name(season.get("mode_most_play"))
    favourite_count = number(season.get("mode_most_play_match_cnt"))
    if favourite_mode or favourite_count is not None:
        favourite = ([favourite_mode] if favourite_mode else []) + ([fmt(favourite_count, suffix=" 场")] if favourite_count is not None else [])
        footprint.append(("最常玩的模式", " · ".join(favourite), C.INK))

    sections = {}
    cursor = 270

    def section(key, height):
        nonlocal cursor
        sections[key] = (cursor, height)
        cursor += height + 26

    paired = bool(ranks and len(ranks) <= 2 and footprint)
    rank_columns = 1 if paired else min(2, len(ranks))
    footprint_columns = 3 if paired else 4
    rank_h = 75 + math.ceil(len(ranks) / rank_columns) * 131 if ranks else 0
    footprint_h = 75 + math.ceil(len(footprint) / footprint_columns) * 70 if footprint else 0
    if paired:
        section("ranks", max(rank_h, footprint_h))
        sections["footprint"] = sections["ranks"]
    else:
        if ranks:
            section("ranks", rank_h)
        if footprint:
            section("footprint", footprint_h)
    if metric_specs:
        section("overview", 78 + math.ceil(len(metric_specs) / 4) * 115)
    if heroes:
        section("heroes", 78 + len(heroes) * 96)
    if focus_rows:
        section("focus", max(285, 92 + math.ceil(len(focus_rows) / 3) * 86))
    if highlights:
        section("highlights", 74 + math.ceil(len(highlights) / 3) * 354)
    count_h = math.ceil(len(category_counts) / 3) * 88
    if detailed_matches or category_counts:
        section("true", 74 + math.ceil(len(detailed_matches) / 3) * 354 + count_h + (10 if count_h else 0))
    if low:
        section("low", 60 + math.ceil(len(low) / 3) * 70)
    if report["friends"] or report["lootbox"]:
        loot_width = 645 if report["friends"] else 1300
        section("bottom", max(235, 82 + len(report["friends"]) * 68,
                              loot_panel_height(loot_width) if report["lootbox"] else 0))

    urls = [report.get("icon")]
    urls.extend(r.get("friend_icon") for r in report["friends"])
    guids = [r.get("role_most_play_hero_guid") for r in heroes] + [focus.get("role_most_play_hero_guid")]
    guids.extend(g for r in ranks for g in rank_heroes(r)[:3])
    guids.extend(r.get("hero_guid") for r in low)
    for row in highlights + detailed_matches:
        urls.append(match_hero_icon(row))
        urls.append(s._map_icon_url(map_key(row)))
        urls.extend(p["icon"] for p in perks_for(row))
    urls.extend(s._hero_icon_url(guid(g)) for g in guids if g)
    await s._prefetch_summary_images(urls)
    canvas = await s._make_period_background((1400, cursor + 24), [])
    # Additional dark tint keeps the extended page and smaller labels legible.
    if C.REPORT_WASH:
        canvas = Image.alpha_composite(canvas.convert("RGBA"), Image.new("RGBA", canvas.size, C.REPORT_WASH))
    draw = s._summary_draw(canvas)

    def text(x, y, value, size=20, color=C.INK, width=570, bold=False):
        font = s._load_font(size, bold=bold or size >= 26)
        value = s._truncate_to_width(draw, plain_text(value), font, width)
        draw.text((x, y), value, font=font, fill=color)

    def panel(x, y, w, h, title, color=C.INFO, quiet=False):
        draw.rounded_rectangle((x, y, x + w, y + h), radius=RADIUS_CARD, fill=C.SURFACE, outline=C.STROKE, width=1)
        draw.polygon([(x + 25, y + 19), (x + 31, y + 19), (x + 27, y + 39), (x + 21, y + 39)], fill=color)
        text(x + 40, y + 15, title, 21 if quiet else 24, C.MUTED if quiet else C.INK, w - 64, bold=True)
        if not quiet:
            draw.line((x + 20, y + 54, x + w - 20, y + 54), fill=C.HAIRLINE, width=1)

    def paste(asset, x, y, w, h, radius=10, contain=False):
        asset = asset.convert("RGBA")
        if contain:
            fitted = ImageOps.contain(asset, (w, h), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (x + (w - fitted.width) // 2, y + (h - fitted.height) // 2), fitted)
        else:
            fitted = s._cover_fit(asset, (w, h))
            mask = ImageChops.multiply(fitted.getchannel("A"), s._rounded_mask((w, h), radius))
            canvas.paste(fitted, (x, y), mask)

    async def picture(url, x, y, w, h, radius=10, contain=False):
        asset = await s._load_summary_image(url)
        if asset is not None:
            paste(asset, x, y, w, h, radius, contain)
        else:
            draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=C.SURFACE_RAISED, outline=C.STROKE)

    def local_icon(path, x, y, w, h, gray=False, tint_icon=False, emblem=False):
        try:
            with Image.open(path) as raw:
                asset = raw.convert("RGBA")
            if gray:
                alpha = asset.getchannel("A")
                asset = ImageOps.grayscale(asset).convert("RGBA")
                asset.putalpha(alpha)
            if tint_icon and C.ROLE_ICON:
                inked = Image.new("RGBA", asset.size, (*C.ROLE_ICON, 255))
                inked.putalpha(asset.getchannel("A"))
                asset = inked
            if emblem and C.STICKER:
                asset = s._sticker_outline(ImageOps.contain(asset, (w - 6, h - 6), Image.Resampling.LANCZOS), C.STICKER)
            paste(asset, x, y, w, h, contain=True)
        except (OSError, ValueError):
            pass

    def badge(label, x, y, size=72, queue_type=None):
        if queue_type == "unknown":
            return
        if queue_type == "stadium":
            level, _ = stadium_rank(label)
            if level:
                local_icon(RESOURCE_DIR / "rank_flat" / f"f{level}_pure.png", x, y, size, size, emblem=True)
                return
            if str(label or "").strip() not in {"未完成定级", "未定级", "Unranked", "None"}:
                return
        level = rank_name_to_icon_level(re.sub(r"\d+\s*$", "", str(label or "")).strip())
        unranked = str(label or "").strip() in {"未完成定级", "未定级", "Unranked", "None"}
        if level or unranked:
            local_icon(RESOURCE_DIR / "rank_flat" / f"{level or 8}_pure.png", x, y, size, size, gray=not level, emblem=True)

    def metric(x, y, label, value, color=C.INFO, big=False, width=170):
        text(x, y, value, 42 if big else 29, color, width)
        text(x, y + (53 if big else 38), label, 17, C.MUTED, width)

    def pill(x, y, label, color=C.INFO, max_width=220):
        font = s._load_font(16, bold=True)
        label = s._truncate_to_width(draw, plain_text(label), font, max_width - 24)
        width = int(draw.textlength(label, font=font)) + 24
        draw.rounded_rectangle((x, y, x + width, y + 30), radius=8,
                               fill=tint(color), outline=tint(color, 0.4))
        draw.text((x + 12, y + 5), label, font=font, fill=color)
        return width

    # Identity leads the page; the season is a small context badge.
    await picture(report.get("icon"), 55, 54, 112, 112, 56)
    display_name = name_text(report.get("player_name")) or str(role_id)
    name, marker, discriminator = display_name.rpartition("#")
    if not marker:
        name, discriminator = display_name, ""
    text(190, 52, name, 46, C.INK, 560)
    if discriminator:
        text(192, 112, f"#{discriminator}", 23, C.MUTED, 550)
    season_label = f"第 {season.get('season', '—')} 赛季"
    offset = pill(190, 154, season_label)
    preferred_role = overview.get("role_most_play")
    role_text = ROLE_LABELS.get(rank_role({"mode_type": preferred_role}))
    role_text = role_text or (preferred_role if preferred_role in ROLE_LABELS.values() else "")
    if role_text:
        offset += 10 + pill(200 + offset, 154, role_text, C.WIN)
    preferred = mode_name(overview.get("mode_most_play")) or favourite_mode
    if preferred:
        pill(210 + offset, 154, preferred, C.INFO)
    first_day = date_text(overview.get("first_landing_day"))
    if first_day != "—":
        text(190, 207, f"初次登陆  {first_day}", 17, C.MUTED, 520)
    metric(790, 65, "总场次", fmt(first_value(season.get("match_cnt"), overview.get("match_cnt"))), C.INFO, True)
    win = number(overview.get("win_rate"))
    metric(975, 65, "赛季胜率", fmt(win * 100 if win is not None else None, 1, "%"), C.WIN, True)
    metric(1170, 65, "在线小时", fmt(first_value(season.get("online_time"), overview.get("online_time")), 2), C.INFO, True, 175)
    highest = report_rank_label(overview.get("max_rank_level"))
    if highest:
        badge(highest, 790, 167, 56)
        text(860, 170, highest, 28, C.DRAW, 260)
        text(861, 207, "赛季最高", 16, C.MUTED)

    if "ranks" in sections:
        y, h = sections["ranks"]
        rank_width = 615 if paired else 1300
        panel(50, y, rank_width, h, "排位表现")
        rank_step = (rank_width - 50) // rank_columns
        for i, row in enumerate(ranks):
            x, ry = 75 + i % rank_columns * rank_step, y + 71 + i // rank_columns * 131
            rank_hero_icons = [url for key in rank_heroes(row) if (url := s._hero_icon_url(key))][:3]
            role = row.get("role_type")
            queue_type = row.get("queue_type", "unknown")
            role_label = "综合" if queue_type == "open" else ROLE_LABELS.get(role)
            queue_label = row.get("queue_label") or QUEUE_LABELS.get(queue_type, QUEUE_LABELS["unknown"])
            label = " · ".join(dict.fromkeys(part for part in (queue_label, role_label) if part))
            current = report_rank_label(row.get("final_rank_level"), queue_type)
            highest = report_rank_label(row.get("max_rank_level"), queue_type)
            show_badge = current and (queue_type != "unknown" or current in {"未定级", "未完成定级"})
            tx = x + 92 if show_badge else x
            if show_badge:
                badge(current, x, ry + 12, 74, None if queue_type == "unknown" else queue_type)
            icon_name = {"tank": "tank.png", "dps": "dps.png", "healer": "healer.png"}.get(role)
            if icon_name:
                local_icon(RESOURCE_DIR / icon_name, tx, ry + 3, 19, 19, tint_icon=True)
            text(tx + 27 if icon_name else tx, ry, label, 17, C.INFO, 435, True)
            if current:
                text(tx, ry + 23, current, 25, C.INK, 420, True)
            stats = ([f"最高 {highest}"] if highest else []) + [
                fmt(row[key], decimals, suffix) for key, decimals, suffix in (("match_cnt", 0, " 场"), ("win_rate", 1, "%"))
                if number(row.get(key)) is not None
            ]
            if stats:
                text(tx, ry + (58 if current else 29), "  ·  ".join(stats), 17, C.MUTED, 460)
            for j, url in enumerate(rank_hero_icons):
                await picture(url, tx + j * 41, ry + 86, 30, 30, 15)
            region = name_text(row.get("ip_province"))
            position = number(row.get("player_rank"))
            parts = ([region] if region else []) + ([f"第 {fmt(position)} 名"] if position is not None and position > 0 else [])
            if parts:
                text(tx + 41 * len(rank_hero_icons), ry + 93, " · ".join(parts), 17, C.INFO, 320)
            if i + rank_columns < len(ranks):
                draw.line((x, ry + 122, x + rank_step - 30, ry + 122), fill=C.HAIRLINE)

    if "footprint" in sections:
        y, h = sections["footprint"]
        x, w = (705, 645) if paired else (50, 1300)
        panel(x, y, w, h, "赛季足迹", C.WIN)
        step = (w - 48) // footprint_columns
        for i, (label, value, color) in enumerate(footprint):
            px = x + 25 + i % footprint_columns * step
            py = y + 70 + i // footprint_columns * 70
            text(px, py, value, 21 if label == "最常玩的模式" else 27, color, step - 12)
            text(px, py + 36, label, 17, C.MUTED, step - 12)

    if "overview" in sections:
        y, h = sections["overview"]
        panel(50, y, 1300, h, "赛季数据")
        if overview.get("match_cnt") is not None:
            text(1140, y + 19, f"{fmt(overview['match_cnt'])} 场", 18, C.MUTED, 185)
        for i, (label, key, rate_key, decimals, color) in enumerate(metric_specs):
            x, ty = 77 + (i % 4) * 320, y + 76 + (i // 4) * 115
            value = number(overview.get(key))
            formatted = fmt(value * 100 if key == "win_rate" and value is not None else value, decimals, "%" if key == "win_rate" else "")
            text(x, ty, formatted, 32, color, 275)
            text(x, ty + 40, label, 18, C.INK, 270)
            if overview.get(rate_key) is not None:
                text(x, ty + 72, f"排名比例 {fmt(overview[rate_key], 2, '%')}", 15, C.MUTED, 280)
            if i % 4 != 3:
                draw.line((x + 292, ty + 4, x + 292, ty + 85), fill=C.HAIRLINE, width=1)

    if "heroes" in sections:
        y, h = sections["heroes"]
        panel(50, y, 1300, h, "代表英雄")
        for i, row in enumerate(heroes):
            ty = y + 78 + i * 96
            hero = guid(row.get("role_most_play_hero_guid"))
            await picture(s._hero_icon_url(hero), 75, ty - 3, 70, 70, 35)
            role = rank_role({"role_type": row.get("role_type")})
            text(163, ty, hero_name(hero, row.get("role_most_play_hero_name")) or ROLE_LABELS.get(role, "职责数据"), 25, C.INFO, 205, True)
            text(163, ty + 38, f"{fmt(row.get('role_match_cnt'))} 场 · {fmt(row.get('role_win_rate'), 1, '%')}", 17, C.MUTED, 208)
            for j, (label, key, color) in enumerate([("消灭", "kill", C.INK), ("助攻", "assist", C.INK), ("伤害", "damage", C.DRAW), ("治疗", "cure", C.WIN), ("承伤", "resist_damage", C.PURPLE)]):
                metric(390 + j * 185, ty, label, fmt(row.get(key)), color, width=178)

    if "focus" in sections:
        y, h = sections["focus"]
        hero = guid(focus.get("role_most_play_hero_guid"))
        name = hero_name(hero, focus.get("role_most_play_hero_name"))
        panel(50, y, 1300, h, f"英雄专项 · {name}" if name else "英雄专项", C.WIN)
        await picture(s._hero_icon_url(hero), 84, y + 86, 172, 172, 20)
        for i, row in enumerate(focus_rows):
            x, ty = 325 + (i % 3) * 330, y + 78 + (i // 3) * 86
            label = str(row.get("index_name") or "—")
            is_pct = is_percentage_label(label)
            value = fmt(row.get("index_value"), 1 if is_pct or "效率" in label else 0, "%" if is_pct else "")
            text(x, ty, value, 29, C.INFO, 285)
            text(x, ty + 39, label, 17, C.MUTED, 285)

    async def match_tile(row, x, y, w, title, count=None):
        draw.rounded_rectangle((x, y, x + w, y + 332), radius=RADIUS_TILE, fill=C.SURFACE_RAISED)
        map_guid = map_key(row)
        map_icon = s._map_icon_url(map_guid)
        if map_icon:
            await picture(map_icon, x, y, w, 116, 10)
        # Backplates keep metadata readable over any map thumbnail.
        category = queue_mode(row.get("game_mode"))
        match_rank = rank_label(mapping(row.get("rank")), category == "stadium")
        if match_rank:
            draw.rounded_rectangle((x + 10, y + 10, x + 155, y + 54), radius=8, fill=C.CHIP)
            badge(match_rank, x + 15, y + 12, 38, category)
            text(x + 63, y + 22, match_rank, 17, C.CHIP_TEXT, 88)
        result = number(row.get("result"))
        if result in (-1, 0, 1):
            result_label = {1: "胜利", -1: "失败", 0: "平局"}[result]
            result_color = {1: C.CHIP_WIN, -1: C.CHIP_LOSS, 0: C.CHIP_MUTED}[result]
            draw.rounded_rectangle((x + w - 71, y + 10, x + w - 10, y + 42), radius=7, fill=C.CHIP)
            text(x + w - 59, y + 17, result_label, 16, result_color, 48)
        hero_icon = match_hero_icon(row)
        if hero_icon:
            await picture(hero_icon, x + w - 76, y + 79, 62, 62, 31)
        value = fmt(count, suffix=" 场") if number(count) is not None else fmt(row.get("value"))
        if value != "—":
            text(x + 16, y + 131, value, 31, C.WIN, w - 105)
        text(x + 17, y + 173, title, 17, C.INK, w - 34)
        map_name = name_text(s._map_name(map_guid)) or name_text(row.get("map_name"))
        hero = hero_name(row.get("hero"), row.get("hero_name"))
        metadata = " · ".join(part for part in (hero, map_name) if part)
        if metadata:
            mode_icon = map_name and s.draw_map_mode_icon(canvas, map_guid, x + 15, y + 204, 18)
            offset = 39 if mode_icon else 17
            text(x + offset, y + 204, metadata, 16, C.MUTED, w - offset - 17)
        stats = [f"{label} {fmt(row[key])}" for key, label in (("kill", "消灭"), ("assist", "助攻"), ("death", "死亡"))
                 if number(row.get(key)) is not None]
        if all(number(row.get(key)) is not None for key in ("team_score", "opponent_score")):
            stats.append(f"{fmt(row['team_score'])}:{fmt(row['opponent_score'])}")
        if stats:
            text(x + 17, y + 232 if metadata else y + 204, "  ·  ".join(stats), 15, C.MUTED, w - 34)
        for i, perk in enumerate(perks_for(row)):
            px, py = x + 16 + i * ((w - 32) // 2), y + 270
            level = perk.get("level")
            color = C.PURPLE if level == 2 else C.INFO
            draw.rounded_rectangle((px, py, px + 38, py + 38), radius=7, fill=C.PERK_PLATE or tint(color, 0.2), outline=tint(color, 0.6))
            if perk.get("icon"):
                await picture(perk["icon"], px + 5, py + 5, 28, 28, contain=True)
            elif level in (1, 2):
                text(px + 13, py + 8, fmt(level), 16, color, 20)
            text(px + 46, py + 3, name_text(perk.get("name")) or "威能", 14, color, (w - 32) // 2 - 50)
            if level in (1, 2):
                text(px + 46, py + 23, "次级威能" if level == 1 else "主要威能", 12, C.MUTED, 130)

    if "highlights" in sections:
        y, h = sections["highlights"]
        panel(50, y, 1300, h, "单场高光", C.WIN)
        for i, row in enumerate(highlights):
            title = {"heroDamage": "最高伤害", "resistDamage": "最高承伤", "cure": "最高治疗"}.get(row.get("metric"), "对局高光")
            await match_tile(row, 74 + i % 3 * 427, y + 75 + i // 3 * 354, 398, title)

    if "true" in sections:
        y, h = sections["true"]
        panel(50, y, 1300, h, "对局表现", C.PURPLE)
        for i, row in enumerate(category_counts):
            x, ty = 74 + i % 3 * 427, y + 68 + i // 3 * 88
            draw.rounded_rectangle((x, ty, x + 398, ty + 74), radius=RADIUS_TILE, fill=C.SURFACE_RAISED)
            title = f"对局类型 {fmt(row['match_type'])}" if number(row.get("match_type")) is not None else "对局统计"
            text(x + 17, ty + 10, title, 17, C.MUTED, 340)
            text(x + 17, ty + 34, fmt(row.get("match_cnt"), suffix=" 场"), 24, C.PURPLE, 340)
        for i, row in enumerate(detailed_matches):
            title = f"对局类型 {fmt(row['match_type'])}" if number(row.get("match_type")) is not None else "赛季对局"
            columns = min(3, len(detailed_matches))
            step = 1280 // columns
            await match_tile(row, 74 + i % columns * step, y + 75 + count_h + i // columns * 354, step - 28, title, row.get("match_cnt"))

    if "low" in sections:
        y, h = sections["low"]
        panel(50, y, 1300, h, "低胜率英雄", C.LOSS, quiet=True)
        for i, row in enumerate(low):
            x, ty = 78 + i % 3 * 427, y + 58 + i // 3 * 70
            hero = guid(row.get("hero_guid"))
            await picture(s._hero_icon_url(hero), x, ty, 42, 42, 21)
            text(x + 56, ty, hero_name(hero, row.get("hero_name")) or "英雄记录", 18, C.MUTED, 190)
            text(x + 56, ty + 28, f"{fmt(row.get('match_cnt'))} 场", 14, C.MUTED, 180)
            text(x + 275, ty + 7, fmt(row.get("win_rate"), 1, "%"), 21, C.LOSS, 115)

    if "bottom" in sections:
        y, h = sections["bottom"]
        have_friends, have_loot = bool(report["friends"]), bool(report["lootbox"])
        if have_friends:
            panel(50, y, 615 if have_loot else 1300,
                  max(235, 82 + len(report["friends"]) * 68), "组队好友", C.WIN)
            for i, row in enumerate(report["friends"]):
                ty = y + 78 + i * 68
                await picture(row.get("friend_icon"), 77, ty, 46, 46, 23)
                text(137, ty + 3, name_text(row.get("friend_name")) or "组队记录", 21, C.INK, 255)
                friend_stats = [fmt(row[key], decimals, suffix)
                                for key, decimals, suffix in (("with_friend_match_cnt", 0, " 场"), ("with_friend_win_rate", 1, "%"))
                                if number(row.get(key)) is not None]
                if friend_stats:
                    text(413, ty + 7, " · ".join(friend_stats), 17, C.WIN, 226)
        if have_loot:
            lx, lw = (705, 645) if have_friends else (50, 1300)
            render_loot_panel(canvas, lx, y, lw, report["lootbox"], s._load_font, s._summary_draw)
    out = BytesIO()
    canvas = append_dashen_promo(canvas, compact=False)
    canvas.convert("RGB").save(out, "PNG")
    return out.getvalue(), "image/png"
