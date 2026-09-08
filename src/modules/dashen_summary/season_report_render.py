"""Adaptive season-report image, sharing the daily summary's assets and typography."""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import re
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .engine import _load_runtime
from .season_report import RESOURCE_DIR, fmt, mapping, mode_name, number, rows
from ...constants.ranks import get_rank_name, get_rank_sub_tier, rank_name_cn, rank_name_to_icon_level
from ..dashen_match.render import _perk_guid_candidates, _perk_lookup
from .season_report_ranks import QUEUE_LABELS, ROLE_LABELS

WHITE = (240, 246, 254)
MUTED = (158, 175, 197)
BLUE = (131, 213, 255)
GREEN = (139, 228, 181)
GOLD = (255, 207, 116)
PURPLE = (197, 156, 255)
RED = (219, 145, 149)


def tint(color, amount=0.16):
    return tuple(round(base + (channel - base) * amount) for base, channel in zip((20, 30, 45), color))


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
            return []
    return value if isinstance(value, list) else []


def rank_label(info):
    name = get_rank_name(info)
    if not rank_name_to_icon_level(name):
        return ""
    tier = get_rank_sub_tier(info)
    return f"{rank_name_cn(name)}{tier if tier else ''}"


def stadium_rank(label):
    value = str(label or "").replace("\u200c", "").strip()
    names = ("菜鸟", "新秀", "斗士", "精英", "专家", "全明星", "传奇")
    english = ("Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Grandmaster")
    base = re.sub(r"\d+\s*$", "", value).strip()
    for level, (cn, en) in enumerate(zip(names, english), 1):
        if base.casefold() in {cn, en.casefold()}:
            return level, value.replace(base, cn, 1)
    return 0, value or "—"


async def render_report(report, role_id):
    s = _load_runtime().summary
    season, overview = report["season"], report["overview"]
    ranks, heroes, focus = report["ranks"], report["heroes"], report["focus"]
    focus_rows = rows(focus.get("stat_map"))
    # Absence and a measured zero are intentionally different for older seasons.
    stadium = any(season.get(k) is not None for k in ("stadium_match_cnt", "stadium_worth"))
    rank_h = max(416 if stadium else 336, 90 + len(ranks) * 152)
    low = report.get("low_win_heroes", [])
    highlights = report.get("highlights", [])
    true_matches = sorted(report.get("true_matches", []), key=lambda r: number(r.get("match_type")) or 0)
    perk_lookup = _perk_lookup(s.OW_CONFIG)

    def perks_for(row):
        result = []
        for perk in rows(row.get("perks")):
            info = next((perk_lookup[k] for k in _perk_guid_candidates(perk) if k in perk_lookup), {})
            result.append({"icon": info.get("icon"), "name": perk_title(info.get("name")), "level": perk.get("perkLevel")})
        return result[:2]

    metric_specs = [
        ("活跃天数", "active_day_cnt", "active_day_rate", 0, BLUE),
        ("在线小时", "online_time", "online_time_rate", 0, BLUE),
        ("胜率", "win_rate", "win_rate_rate", 1, GREEN),
        ("消灭", "kill_sum", "kill_rnk_rate", 0, WHITE),
        ("助攻", "assist_sum", "assist_rnk_rate", 0, WHITE),
        ("伤害", "damage_sum", "damage_rnk_rate", 0, GOLD),
        ("治疗", "cure_sum", "cure_rnk_rate", 0, GREEN),
        ("承伤", "resist_damage_sum", "resist_damage_rate", 0, PURPLE),
    ]
    metric_specs = [v for v in metric_specs if overview.get(v[1]) is not None]

    sections = {}
    cursor = 270

    def section(key, height):
        nonlocal cursor
        sections[key] = (cursor, height)
        cursor += height + 26

    section("ranks", rank_h)
    if metric_specs:
        section("overview", 78 + math.ceil(len(metric_specs) / 4) * 115)
    if heroes:
        section("heroes", 78 + len(heroes) * 96)
    if focus_rows:
        section("focus", max(285, 92 + math.ceil(len(focus_rows) / 3) * 86))
    if highlights:
        section("highlights", 74 + math.ceil(len(highlights) / 3) * 354)
    if true_matches:
        section("true", 74 + math.ceil(len(true_matches) / 3) * 354)
    if low:
        section("low", 60 + math.ceil(len(low) / 3) * 70)
    if report["friends"] or report["lootbox"]:
        section("bottom", max(235, 82 + len(report["friends"]) * 68))

    urls = [report.get("icon")]
    urls.extend(r.get("friend_icon") for r in report["friends"])
    guids = [r.get("role_most_play_hero_guid") for r in heroes] + [focus.get("role_most_play_hero_guid")]
    guids.extend(g for r in ranks for g in rank_heroes(r)[:3])
    guids.extend(r.get("hero_guid") for r in low)
    for row in highlights + true_matches:
        guids.append(row.get("hero"))
        urls.append(s._map_icon_url(row.get("map")))
        urls.extend(p["icon"] for p in perks_for(row))
    urls.extend(s._hero_icon_url(g) for g in guids if g)
    await s._prefetch_summary_images(urls)
    canvas = await s._make_period_background((1400, cursor + 24), [])
    # Additional dark tint keeps the extended page and smaller labels legible.
    canvas = Image.alpha_composite(canvas.convert("RGBA"), Image.new("RGBA", canvas.size, (5, 10, 18, 55)))
    draw = ImageDraw.Draw(canvas, "RGBA")

    def text(x, y, value, size=20, color=WHITE, width=570, bold=False):
        font = s._load_font(size, bold=bold or size >= 26)
        value = s._truncate_to_width(draw, plain_text(value), font, width)
        draw.text((x, y), value, font=font, fill=color)

    def panel(x, y, w, h, title, color=BLUE, quiet=False):
        draw.rounded_rectangle((x, y, x + w, y + h), radius=12,
                               fill=(15, 23, 35, 230), outline=(57, 77, 101, 185), width=1)
        draw.rounded_rectangle((x + 20, y + 19, x + 24, y + 39), radius=2, fill=color)
        text(x + 38, y + 13, title, 21 if quiet else 25, MUTED if quiet else WHITE, w - 64, bold=True)
        if not quiet:
            draw.line((x + 20, y + 54, x + w - 20, y + 54), fill=(58, 76, 100, 140))

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
            draw.rounded_rectangle((x, y, x + w, y + h), radius=radius,
                                   fill=(28, 40, 55), outline=(57, 77, 101))

    def local_icon(path, x, y, w, h, gray=False):
        try:
            with Image.open(path) as raw:
                asset = raw.convert("RGBA")
            if gray:
                alpha = asset.getchannel("A")
                asset = ImageOps.grayscale(asset).convert("RGBA")
                asset.putalpha(alpha)
            paste(asset, x, y, w, h, contain=True)
        except (OSError, ValueError):
            pass

    def badge(label, x, y, size=72, queue_type=None):
        if queue_type == "unknown":
            return
        if queue_type == "stadium":
            level, _ = stadium_rank(label)
            if level:
                local_icon(RESOURCE_DIR / "rank_flat" / f"f{level}_pure.png", x, y, size, size)
                return
            if str(label or "").strip() not in {"未完成定级", "未定级", "Unranked", "None"}:
                return
        level = rank_name_to_icon_level(re.sub(r"\d+\s*$", "", str(label or "")).strip())
        unranked = str(label or "").strip() in {"未完成定级", "未定级", "Unranked", "None"}
        if level or unranked:
            local_icon(RESOURCE_DIR / "rank_flat" / f"{level or 8}_pure.png", x, y, size, size, gray=not level)

    def metric(x, y, label, value, color=BLUE, big=False, width=170):
        text(x, y, value, 42 if big else 29, color, width)
        text(x, y + (53 if big else 38), label, 17, MUTED, width)

    def pill(x, y, label, color=BLUE, max_width=220):
        font = s._load_font(16, bold=True)
        label = s._truncate_to_width(draw, plain_text(label), font, max_width - 24)
        width = int(draw.textlength(label, font=font)) + 24
        draw.rounded_rectangle((x, y, x + width, y + 30), radius=8,
                               fill=tint(color), outline=tint(color, 0.4))
        draw.text((x + 12, y + 5), label, font=font, fill=color)
        return width

    # Identity leads the page; the season is a small context badge.
    await picture(report.get("icon"), 55, 54, 112, 112, 56)
    display_name = report.get("player_name") or str(role_id)
    name, marker, discriminator = display_name.rpartition("#")
    if not marker:
        name, discriminator = display_name, ""
    text(190, 52, name, 46, WHITE, 560)
    if discriminator:
        text(192, 112, f"#{discriminator}", 23, MUTED, 550)
    season_label = f"第 {season.get('season', '—')} 赛季"
    offset = pill(190, 154, season_label)
    role_text = overview.get("role_most_play")
    if role_text:
        offset += 10 + pill(200 + offset, 154, role_text, GREEN)
    preferred = overview.get("mode_most_play", season.get("mode_most_play"))
    if preferred is not None:
        pill(210 + offset, 154, mode_name(preferred), BLUE)
    if overview.get("first_landing_day"):
        text(190, 207, f"初次登陆  {date_text(overview['first_landing_day'])}", 17, MUTED, 520)
    metric(790, 65, "总场次", fmt(season.get("match_cnt", overview.get("match_cnt"))), BLUE, True)
    win = number(overview.get("win_rate"))
    metric(975, 65, "赛季胜率", fmt(win * 100 if win is not None else None, 1, "%"), GREEN, True)
    metric(1170, 65, "在线小时", fmt(season.get("online_time", overview.get("online_time")), 2), BLUE, True, 175)
    highest = overview.get("max_rank_level")
    if highest:
        badge(highest, 790, 167, 56)
        text(860, 170, highest, 28, GOLD, 260)
        text(861, 207, "赛季最高", 16, MUTED)

    y, h = sections["ranks"]
    panel(50, y, 615, h, "排位表现")
    if not ranks:
        hero = focus.get("role_most_play_hero_guid") or (heroes[0].get("role_most_play_hero_guid") if heroes else None)
        if hero:
            await picture(s._hero_icon_url(hero), 95, y + 105, 150, 150, 20)
            text(278, y + 127, overview.get("role_most_play") or s._hero_name(hero), 29, BLUE, 330)
            text(278, y + 179, "暂无排位数据", 19, MUTED, 320)
        else:
            text(80, y + 92, "暂无排位数据", color=MUTED)
    for i, row in enumerate(ranks):
        ry = y + 79 + i * 152
        guids = rank_heroes(row)
        role = row.get("role_type")
        queue_type = row.get("queue_type", "unknown")
        role_label = ROLE_LABELS.get(role)
        queue_label = QUEUE_LABELS.get(queue_type, QUEUE_LABELS["unknown"])
        label = queue_label + (f" · {role_label}" if role_label else "")
        current = row.get("final_rank_level") or "—"
        highest = row.get("max_rank_level") or "—"
        if queue_type == "stadium":
            current, highest = stadium_rank(current)[1], stadium_rank(highest)[1]
        badge(row.get("final_rank_level"), 75, ry + 8, 78, queue_type)
        icon_name = {"tank": "tank.png", "dps": "dps.png", "healer": "healer.png"}.get(role)
        if icon_name:
            local_icon(RESOURCE_DIR / icon_name, 175, ry + 3, 19, 19)
        text(202 if icon_name else 175, ry, label, 17, BLUE, 435, True)
        text(175, ry + 25, current, 25, WHITE, 420, True)
        text(175, ry + 61, f"最高 {highest}   {fmt(row.get('match_cnt'))} 场   {fmt(row.get('win_rate'), 1, '%')}", 17, MUTED, 460)
        for j, guid in enumerate(guids[:3]):
            await picture(s._hero_icon_url(guid), 175 + j * 43, ry + 88, 32, 32, 16)
        region = str(row.get("ip_province") or "").strip()
        position = number(row.get("player_rank"))
        parts = ([region] if region else []) + ([f"第 {fmt(position)} 名"] if position is not None and position > 0 else [])
        if parts:
            text(320, ry + 95, " · ".join(parts), 17, BLUE, 320)

    panel(705, y, 645, h, "赛季足迹", GREEN)
    metric(735, y + 82, "活跃天数", fmt(overview.get("active_day_cnt")))
    metric(935, y + 82, "收到赞赏", fmt(season.get("get_honors_cnt")), GREEN)
    metric(1135, y + 82, "送出赞赏", fmt(season.get("send_honors_cnt")), GREEN)
    text(735, y + 167, date_text(season.get("oneday_max_online_dt")), 25, WHITE)
    text(735, y + 201, "最投入的一天", 16, MUTED)
    text(1060, y + 169, f"{fmt(season.get('oneday_max_online_time'), 2)} 小时", 25, BLUE, 250)
    if season.get("ahead_rate") is not None:
        text(735, y + 249, f"在线时长超越 {fmt(season.get('ahead_rate'), 2, '%')} 玩家", 19, GREEN, 575)
    text(735, y + 286, f"{mode_name(season.get('mode_most_play'))}  ·  {fmt(season.get('mode_most_play_match_cnt'))} 场", 22, WHITE, 575)
    if stadium:
        metric(735, y + 336, "角斗领域场次", fmt(season.get("stadium_match_cnt")), BLUE, width=260)
        metric(1040, y + 336, "角斗领域经济", fmt(season.get("stadium_worth")), GREEN, width=270)

    if "overview" in sections:
        y, h = sections["overview"]
        panel(50, y, 1300, h, "赛季数据")
        if overview.get("match_cnt") is not None:
            text(1140, y + 19, f"{fmt(overview['match_cnt'])} 场", 18, MUTED, 185)
        for i, (label, key, rate_key, decimals, color) in enumerate(metric_specs):
            x, ty = 77 + (i % 4) * 320, y + 76 + (i // 4) * 115
            value = number(overview.get(key))
            formatted = fmt(value * 100 if key == "win_rate" and value is not None else value, decimals, "%" if key == "win_rate" else "")
            text(x, ty, formatted, 32, color, 275)
            text(x, ty + 40, label, 18, WHITE, 270)
            if overview.get(rate_key) is not None:
                text(x, ty + 72, f"排名比例 {fmt(overview[rate_key], 2, '%')}", 15, MUTED, 280)
            if i % 4 != 3:
                draw.line((x + 292, ty + 4, x + 292, ty + 85), fill=(57, 77, 101, 110))

    if "heroes" in sections:
        y, h = sections["heroes"]
        panel(50, y, 1300, h, "代表英雄")
        for i, row in enumerate(heroes):
            ty = y + 78 + i * 96
            guid = row.get("role_most_play_hero_guid")
            await picture(s._hero_icon_url(guid), 75, ty - 3, 70, 70, 35)
            text(163, ty, s._hero_name(guid), 25, BLUE, 205, True)
            text(163, ty + 38, f"{fmt(row.get('role_match_cnt'))} 场 · {fmt(row.get('role_win_rate'), 1, '%')}", 17, MUTED, 208)
            for j, (label, key, color) in enumerate([("消灭", "kill", WHITE), ("助攻", "assist", WHITE), ("伤害", "damage", GOLD), ("治疗", "cure", GREEN), ("承伤", "resist_damage", PURPLE)]):
                metric(390 + j * 185, ty, label, fmt(row.get(key)), color, width=178)

    if "focus" in sections:
        y, h = sections["focus"]
        panel(50, y, 1300, h, f"英雄专项 · {s._hero_name(focus.get('role_most_play_hero_guid'))}", GREEN)
        await picture(s._hero_icon_url(focus.get("role_most_play_hero_guid")), 84, y + 86, 172, 172, 20)
        for i, row in enumerate(focus_rows):
            x, ty = 325 + (i % 3) * 330, y + 78 + (i // 3) * 86
            label = str(row.get("index_name") or "—")
            is_pct = is_percentage_label(label)
            value = fmt(row.get("index_value"), 1 if is_pct or "效率" in label else 0, "%" if is_pct else "")
            text(x, ty, value, 29, BLUE, 285)
            text(x, ty + 39, label, 17, MUTED, 285)

    async def match_tile(row, x, y, w, title, count=None):
        draw.rounded_rectangle((x, y, x + w, y + 332), radius=10, fill=(25, 35, 50, 215))
        await picture(s._map_icon_url(row.get("map")), x, y, w, 116, 10)
        # Backplates keep metadata readable over any map thumbnail.
        match_rank = rank_label(mapping(row.get("rank")))
        if match_rank:
            draw.rounded_rectangle((x + 10, y + 10, x + 155, y + 54), radius=8, fill=(8, 14, 23, 224))
            badge(match_rank, x + 15, y + 12, 38)
            text(x + 63, y + 22, match_rank, 17, WHITE, 88)
        result = number(row.get("result"))
        if result in (-1, 0, 1):
            result_label = {1: "胜利", -1: "失败", 0: "平局"}[result]
            result_color = {1: GREEN, -1: RED, 0: MUTED}[result]
            draw.rounded_rectangle((x + w - 71, y + 10, x + w - 10, y + 42), radius=7, fill=(8, 14, 23, 235))
            text(x + w - 59, y + 17, result_label, 16, result_color, 48)
        await picture(s._hero_icon_url(row.get("hero")), x + w - 76, y + 79, 62, 62, 31)
        value = fmt(count) + " 场" if count is not None else fmt(row.get("value"))
        text(x + 16, y + 131, value, 31, GREEN, w - 105)
        text(x + 17, y + 173, title, 17, WHITE, w - 34)
        text(x + 17, y + 204, f"{s._hero_name(row.get('hero'))} · {s._map_name(row.get('map'))}", 16, MUTED, w - 34)
        text(x + 17, y + 232, f"消灭 {fmt(row.get('kill'))}  助攻 {fmt(row.get('assist'))}  死亡 {fmt(row.get('death'))}", 15, MUTED, w - 34)
        for i, perk in enumerate(perks_for(row)):
            px, py = x + 16 + i * ((w - 32) // 2), y + 270
            color = BLUE if number(perk.get("level")) == 1 else PURPLE
            draw.rounded_rectangle((px, py, px + 38, py + 38), radius=7, fill=tint(color, 0.2), outline=tint(color, 0.6))
            if perk.get("icon"):
                await picture(perk["icon"], px + 5, py + 5, 28, 28, contain=True)
            else:
                text(px + 13, py + 8, fmt(perk.get("level")), 16, color, 20)
            text(px + 46, py + 3, perk.get("name") or "威能", 14, color, (w - 32) // 2 - 50)
            text(px + 46, py + 23, "次级威能" if number(perk.get("level")) == 1 else "主要威能", 12, MUTED, 130)

    if "highlights" in sections:
        y, h = sections["highlights"]
        panel(50, y, 1300, h, "单场高光", GREEN)
        for i, row in enumerate(highlights):
            title = {"heroDamage": "最高伤害", "resistDamage": "最高承伤", "cure": "最高治疗"}.get(row.get("metric"), "对局高光")
            await match_tile(row, 74 + i % 3 * 427, y + 75 + i // 3 * 354, 398, title)

    if "true" in sections:
        y, h = sections["true"]
        panel(50, y, 1300, h, "对局表现", PURPLE)
        for i, row in enumerate(true_matches):
            # The API does not provide its category labels; preserve the type rather
            # than inventing carry/throw classifications from a single example match.
            title = f"对局类型 {fmt(row.get('match_type'))}"
            columns = min(3, len(true_matches))
            step = 1280 // columns
            await match_tile(row, 74 + i % columns * step, y + 75 + i // columns * 354, step - 28, title, row.get("match_cnt"))

    if "low" in sections:
        y, h = sections["low"]
        panel(50, y, 1300, h, "低胜率英雄", RED, quiet=True)
        for i, row in enumerate(low):
            x, ty = 78 + i % 3 * 427, y + 58 + i // 3 * 70
            await picture(s._hero_icon_url(row.get("hero_guid")), x, ty, 42, 42, 21)
            text(x + 56, ty, s._hero_name(row.get("hero_guid")), 18, MUTED, 190)
            text(x + 56, ty + 28, f"{fmt(row.get('match_cnt'))} 场", 14, MUTED, 180)
            text(x + 275, ty + 7, fmt(row.get("win_rate"), 1, "%"), 21, RED, 115)

    if "bottom" in sections:
        y, h = sections["bottom"]
        have_friends, have_loot = bool(report["friends"]), bool(report["lootbox"])
        if have_friends:
            panel(50, y, 615 if have_loot else 1300, h, "组队好友", GREEN)
            for i, row in enumerate(report["friends"]):
                ty = y + 78 + i * 68
                await picture(row.get("friend_icon"), 77, ty, 46, 46, 23)
                text(137, ty + 3, row.get("friend_name") or "未知好友", 21, WHITE, 255)
                text(413, ty + 7, f"{fmt(row.get('with_friend_match_cnt'))} 场 · {fmt(row.get('with_friend_win_rate'), 1, '%')}", 17, GREEN, 226)
        if have_loot:
            lx, lw = (705, 645) if have_friends else (50, 1300)
            panel(lx, y, lw, h, "赛季收获", GOLD)
            tile_w = (lw - 64) // 3
            for i, (label, key, color) in enumerate([("补给箱", "open_lootbox_cnt", BLUE), ("史诗", "epic_cnt", PURPLE), ("传奇", "legendary_cnt", GOLD)]):
                tx = lx + 22 + i * (tile_w + 10)
                draw.rounded_rectangle((tx, y + 77, tx + tile_w, y + 207), radius=10, fill=tint(color, 0.14), outline=tint(color, 0.5))
                cx, cy = tx + tile_w - 30, y + 103
                draw.polygon([(cx, cy - 9), (cx + 9, cy), (cx, cy + 9), (cx - 9, cy)], fill=color)
                text(tx + 17, y + 96, fmt(report["lootbox"].get(key)), 37, color, tile_w - 52)
                text(tx + 18, y + 153, label, 19, color, tile_w - 32)
    out = BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    return out.getvalue(), "image/png"
