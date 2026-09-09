"""Editorial image layout for the hero guide; all content remains data-driven."""
from io import BytesIO
from collections import OrderedDict
import math
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageOps

from .render import (RenderedImage, _wrap_text, _load_card_icon,
                     _open_cached_or_remote_rgba, _to_rgba, load_font)
from .stat_icons import stat_icon
from .parameter_style import numeric_colors, TIERS

BG = (12, 17, 25)
SURFACE = (23, 31, 44)
WHITE = (239, 244, 252)
BODY = (193, 206, 223)
MUTED = (135, 153, 176)
LINE = (47, 61, 80)
S = 2
W = 1120


def readable_accent(value):
    color = _to_rgba(value)
    if sum(channel * weight for channel, weight in zip(color, (.2126, .7152, .0722))) < 110:
        return tuple(round(channel*.55+255*.45) for channel in color[:3]) + (255,)
    return color


@lru_cache(maxsize=64)
def font(size, bold=False):
    return load_font(size * S, prefer_cjk=True, bold=bold)


@lru_cache(maxsize=32)
def number_font(size):
    return load_font(size*S, name="num.ttf", fallback="GrotaRoundedExtraBold.otf")


def number_lines(value, width, size, bold=False):
    """Measure and wrap mixed numeric/CJK runs using their actual fonts."""
    regular, numeric = font(size, bold), number_font(size)
    lines, current, used = [], [], 0
    for token in re.findall(r"\d+(?:[.,]\d+)*|[A-Za-z]+|[^\S\n]+|\n|.", str(value or "")):
        if token == "\n":
            lines.append(current)
            current, used = [], 0
            continue
        face = numeric if token[0].isdigit() else regular
        parts = list(token) if face.getlength(token) > width*S else [token]
        for part in parts:
            length = face.getlength(part)
            if current and used+length > width*S:
                lines.append(current)
                current, used = [], 0
            if not current and part.isspace():
                continue
            current.append((part, face))
            used += length
    if current:
        lines.append(current)
    return lines


def panel(width, height, color=SURFACE):
    return Image.new("RGBA", (width * S, height * S), color)


def text(draw, value, x, y, width, size=18, color=BODY, bold=False, numeric=False, tones=()):
    if numeric:
        palette = iter(tones)
        for runs in number_lines(value, width, size, bold):
            cursor = x*S
            for run, face in runs:
                run_color = next(palette, color) if run[0].isdigit() else color
                draw.text((cursor, (y+size)*S), run, font=face, fill=run_color, anchor="ls")
                cursor += face.getlength(run)
            y += size+9
        return y
    face = font(size, bold)
    lines = _wrap_text(draw, str(value or ""), face, width * S)
    for line in lines:
        draw.text((x * S, y * S), line, font=face, fill=color)
        y += size + 9
    return y


def measure(value, width, size=18, bold=False, numeric=False):
    if numeric:
        return len(number_lines(value, width, size, bold))*(size+9)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    return len(_wrap_text(draw, str(value or ""), font(size, bold), width * S)) * (size + 9)


def line(draw, x, y, right, color=LINE):
    draw.line((x * S, y * S, right * S, y * S), fill=color, width=S)


def cover(payload, accent, icon_url, image_url):
    name = payload.get("hero_cn") or payload.get("hero") or "未知英雄"
    overview = payload.get("overview") or "暂无英雄简介"
    name_h = measure(name, 600, 66, True)
    name_bottom = 78 + name_h
    intro_y = name_bottom + 58
    h = max(440, intro_y + measure(overview, 540, 19) + 56)
    image = panel(W, h, (20, 28, 40))
    draw = ImageDraw.Draw(image)
    # A restrained diagonal field gives the portrait a distinct visual plane.
    skew = round(h*.42)
    field_top, gold_top = 720, 1030
    draw.polygon([(field_top*S, 0), (W*S, 0), (W*S, h*S), ((field_top-skew)*S, h*S)], fill=(29, 40, 55))
    draw.polygon([(gold_top*S, 0), (W*S, 0), (W*S, h*S), ((gold_top-skew)*S, h*S)], fill=tuple(int(v*.48) for v in accent[:3]))
    for x in range(field_top+32, gold_top, 36):
        draw.line(((x-skew*24/h)*S, 24*S, (x-skew*(h-24)/h)*S, (h-24)*S), fill=(52, 65, 81), width=S)
    portrait = _open_cached_or_remote_rgba(image_url, categories=("heroes", "misc"))
    if portrait is None:
        portrait = _open_cached_or_remote_rgba(icon_url, categories=("heroes", "misc"))
    if portrait is not None:
        portrait = ImageOps.contain(portrait, (450*S, (h-40)*S))
        image.alpha_composite(portrait, (int(850*S-portrait.width/2), (h-16)*S-portrait.height))
    text(draw, "英雄档案", 34, 24, 650, 13, MUTED)
    draw.rectangle((34*S, 61*S, 76*S, 65*S), fill=accent)
    text(draw, name, 32, 78, 600, 66, WHITE, True)
    text(draw, str(payload.get("hero_en") or "").upper(), 36, name_bottom+10, 590, 22, accent)
    y = text(draw, overview, 36, intro_y, 540, 19)
    text(draw, f"{payload.get('role_cn') or '英雄'}  /  技能与机制档案", 36, max(y+24, h-48), 550, 14, MUTED)
    return image


def health_segments(stats):
    parts = [("health", "生命", (232, 239, 248)), ("armor", "护甲", (235, 186, 92)),
             ("shield", "护盾", (103, 184, 239))]
    segments = []
    for key, label, color in parts:
        amount = max(0, int(stats.get(key) or 0))
        for offset in range(0, amount, 25):
            segments.append((min(25, amount-offset)/25, color))
    return parts, segments


def perk_mark(draw, x, y, color, major=False):
    if major:
        points = [(x+12*math.cos(math.radians(a)), y+12*math.sin(math.radians(a)))
                  for a in (30, 90, 150, 210, 270, 330)]
        draw.polygon([(int(px*S), int(py*S)) for px, py in points], outline=color, width=S)
    else:
        draw.polygon([(x*S, (y-12)*S), ((x+12)*S, y*S), (x*S, (y+12)*S), ((x-12)*S, y*S)], outline=color, width=S)
    r = 6 if major else 5
    draw.polygon([(x*S, (y-r)*S), ((x+r)*S, y*S), (x*S, (y+r)*S), ((x-r)*S, y*S)], fill=color)


def vitals(payload, accent):
    stats = payload.get("stats") or {}
    parts, segments = health_segments(stats)
    columns = 16
    rows = max(1, math.ceil(len(segments)/columns))
    legend_y = 62+rows*22+10
    h = max(162, legend_y+43)
    image = panel(W, h, (18, 25, 35))
    draw = ImageDraw.Draw(image)
    line(draw, 0, 0, W, accent)
    text(draw, "总生命", 26, 20, 185, 14, MUTED)
    text(draw, str(stats.get("total_hp") or "—"), 26, 56, 190, 46, WHITE, numeric=True)
    text(draw, "生命构成", 235, 20, 200, 14, MUTED)
    text(draw, "每格 25 点", 463, 22, 128, 12, MUTED, numeric=True)
    for index, (fraction, color) in enumerate(segments):
        x = 235+(index % columns)*22
        y = 62+(index // columns)*22
        draw.rounded_rectangle((x*S, y*S, (x+18)*S, (y+16)*S), radius=3*S, fill=(42, 53, 69))
        draw.rounded_rectangle((x*S, y*S, (x+18*fraction)*S, (y+16)*S), radius=min(3*S, int(9*fraction*S)), fill=color)
    text(draw, "  ·  ".join(f"{label} {stats[key]}" for key, label, _ in parts if stats.get(key)),
         235, legend_y, 370, 13, numeric=True)
    text(draw, "威能解锁", 656, 20, 420, 14, MUTED)
    for x, label, key, color, major in [
            (656, "次级威能", "minor_perk_xp", (119, 218, 177), False),
            (881, "主要威能", "major_perk_xp", (235, 168, 215), True)]:
        fill = (24, 39, 39) if not major else (40, 31, 46)
        draw.rectangle((x*S, 50*S, (x+207)*S, (h-16)*S), fill=fill)
        line(draw, x, 50, x+207, color)
        perk_mark(draw, x+25, 76, color, major)
        text(draw, label, x+49, 65, 148, 14, color)
        value = str(stats.get(key) or "—")
        size = 32 if len(value) <= 5 else 25
        text(draw, value, x+16, 99, 141, size, WHITE, numeric=True)
        text(draw, "经验", x+160, 111, 43, 12, MUTED)
    return image


def section(title, number, count, accent):
    image = panel(W, 74, BG)
    draw = ImageDraw.Draw(image)
    text(draw, f"{number:02d}", 0, 22, 58, 24, accent, numeric=True)
    text(draw, title, 58, 21, 600, 25, WHITE, True)
    text(draw, f"{count:02d} 项资料", W-110, 29, 110, 13, MUTED, numeric=True)
    line(draw, 0, 69, W)
    return image


def card_block(card, width, accent):
    if width > 800 and (card.get("notes") or card.get("mode_notes")):
        primary = card_block(dict(card, notes=[], mode_notes=[], tags=[]), 610, accent)
        details = card_block(dict(card, name_cn="机制详解", name_en="", hero_cn="", icon_url="",
                                  description="", stats=[]), width-630, accent)
        image = panel(width, max(primary.height, details.height)//S)
        image.alpha_composite(primary, (0, 0))
        image.alpha_composite(details, (630*S, 0))
        ImageDraw.Draw(image).line((620*S, 24*S, 620*S, image.height-24*S), fill=LINE, width=S)
        return image
    pad = 26
    inner = width - pad*2
    name = card.get("name_cn") or card.get("name_en") or "未命名条目"
    icon = _load_card_icon(card)
    title_x = pad+68 if icon is not None else pad
    title_width = width-title_x-pad
    title_h = measure(name, title_width, 25, True)
    english = card.get("name_en") if card.get("name_en") != name else ""
    title_h += measure(english, title_width, 13)
    y = max(84, 26+title_h+18)
    desc = card.get("description") or ""
    # Build measured drawing operations first, so every paragraph fits.
    ops = [(name, title_x, 22, title_width, 25, WHITE, True)]
    if english:
        ops.append((english, title_x, 22+measure(name, title_width, 25, True), title_width, 13, MUTED, False))
    if desc:
        ops.append((desc, pad, y, inner, 18, BODY, False))
        y += measure(desc, inner, 18)+22
    stats = list(card.get("stats") or [])
    stat_rows = []
    for stat in stats:
        value = str(stat.get("value") or "—")
        size = 26 if len(value) <= 12 and re.search(r"\d", value) else 17
        label = stat.get("label") or ""
        row_h = max(46, measure(value, int(inner*.68), size, numeric=True)+12,
                    measure(label, int(inner*.29)-28, 13)+18)
        stat_rows.append((y, label, value, size, stat.get("key") or ""))
        y += row_h
    if stats:
        y += 20
    notes = [("机制说明", card.get("notes") or []), ("6v6 · 模式差异", card.get("mode_notes") or [])]
    note_start = y
    for label, values in notes:
        if not values:
            continue
        ops.append((label, pad, y+14, inner, 14, accent, True))
        y += 44
        for value in values:
            ops.append(("· " + str(value), pad, y, inner, 15, MUTED, False))
            y += measure("· " + str(value), inner, 15)+7
        y += 8
    tags = list(card.get("tags") or [])
    tag_positions = []
    if tags:
        y += 16
        cursor, row_h = pad, 0
        for tag in dict.fromkeys(str(t).strip() for t in tags if str(t).strip()):
            tag_width = min(inner, math.ceil(font(13).getlength(tag)/S)+24)
            tag_height = measure(tag, tag_width-24, 13)+12
            if cursor > pad and cursor+tag_width > width-pad:
                cursor, y, row_h = pad, y+row_h+8, 0
            tag_positions.append((tag, cursor, y, tag_width, tag_height))
            cursor += tag_width+8
            row_h = max(row_h, tag_height)
        y += row_h+8
    image = panel(width, int(y+pad))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 4*S, 64*S), fill=accent)
    if y > note_start+8:
        draw.rectangle((14*S, note_start*S, (width-14)*S, (y+10)*S), fill=(19, 26, 37))
    if icon is not None:
        icon = ImageOps.contain(icon, (48*S, 48*S))
        image.alpha_composite(icon, (pad*S, 24*S))
    for row_y, label, value, size, key in stat_rows:
        line(draw, pad, row_y, width-pad)
        image.alpha_composite(stat_icon(key, label, size=18*S), (pad*S, (row_y+11)*S))
        text(draw, label, pad+28, row_y+10, int(inner*.29)-28, 13, MUTED)
        text(draw, value, pad+int(inner*.32), row_y+7, int(inner*.68), size, WHITE,
             numeric=True, tones=numeric_colors(key, value, label))
    for tag, x, top, tag_width, tag_height in tag_positions:
        draw.rounded_rectangle((x*S, top*S, (x+tag_width)*S, (top+tag_height)*S), radius=7*S,
                               fill=(36, 48, 65), outline=(65, 83, 106), width=S)
        text(draw, tag, x+12, top+6, tag_width-24, 13, BODY)
    for op in ops:
        text(draw, *op)
    return image


def answer_block(payload, accent):
    question = payload.get("question") or ""
    answer = payload.get("answer") or "暂无可用回答"
    qh = measure(question, W-72, 23, True, numeric=True)
    ah = measure(answer, W-72, 20, numeric=True)
    image = panel(W, 104+qh+ah, (32, 37, 45))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 5*S, image.height), fill=accent)
    text(draw, "定向查询  /  资料回答", 32, 20, W-64, 13, accent)
    y = text(draw, question, 32, 52, W-72, 23, WHITE, True, numeric=True)
    text(draw, answer, 32, y+22, W-72, 20, BODY, numeric=True)
    return image


def sources(payload):
    source = payload.get("source") or {}
    rows = ["资料来源  /  " + str(source.get("fandom_url") or "Wiki 来源暂缺")]
    if source.get("modified_at"):
        rows.append("Wiki 修改时间（UTC）  " + str(source["modified_at"]).replace("T", " ").rstrip("Z"))
    grouped = OrderedDict()
    for hit in payload.get("citations") or []:
        key = (str(hit.get("title") or ""), str(hit.get("url") or ""))
        grouped.setdefault(key, []).append(str(hit.get("id")))
    rows.extend(f"[{', '.join(ids)}]  {title}  ·  {url}" for (title, url), ids in grouped.items())
    rows.append("中文名称与简介参考本地配置；数值和机制以 Wiki 资料为准。")
    height = 58+sum(measure(row, W, 12)+5 for row in rows)
    image = panel(W, height, BG)
    draw = ImageDraw.Draw(image)
    line(draw, 0, 14, W)
    y = 32
    for row in rows:
        y = text(draw, row, 0, y, W, 12, MUTED)+5
    return image


def render_guide(payload, *, accent_color, icon_url, image_url):
    accent = readable_accent(accent_color)
    blocks = [cover(payload, accent, icon_url, image_url), vitals(payload, accent)]
    if payload.get("question"):
        blocks.append(answer_block(payload, accent))
    legend = panel(W, 44, BG)
    legend_draw = ImageDraw.Draw(legend)
    text(legend_draw, "参数参考分档", 0, 10, 180, 13, MUTED)
    for i, (label, color) in enumerate(zip(("低", "中", "高", "很高"), TIERS)):
        x = 150+i*74
        legend_draw.ellipse((x*S, 15*S, (x+8)*S, 23*S), fill=color)
        text(legend_draw, label, x+16, 10, 52, 13, color)
    text(legend_draw, "冷却等成本项反向分档 · 复杂条件值保持白色", 470, 10, 650, 13, MUTED)
    blocks.append(legend)
    related = {(h.get("section"), h.get("card_index")) for h in payload.get("citations") or []}
    groups = OrderedDict()
    for field in ("abilities", "perks"):
        for index, card in enumerate(payload.get(field) or []):
            if payload.get("question") and (field, index) not in related:
                continue
            title = card.get("group_title_cn") or ("威能" if field == "perks" else "技能")
            groups.setdefault(title, []).append(dict(card, hero_cn=payload.get("hero_cn")))
    for number, (title, cards) in enumerate(groups.items(), 1):
        color = readable_accent(cards[0].get("accent") or accent)
        blocks.append(section(title, number, len(cards), color))
        # Paired entries share a baseline and fixed row order, avoiding masonry
        # reading jumps. Single entries use a full-width text/parameter layout.
        for start in range(0, len(cards), 2):
            row = cards[start:start+2]
            width = (W-20)//2 if len(row) == 2 else W
            images = [card_block(c, width, color) for c in row]
            strip = panel(W, max(im.height for im in images)//S, BG)
            for i, im in enumerate(images):
                ImageDraw.Draw(strip).rectangle((i*(width+20)*S, 0,
                                                (i*(width+20)+width)*S-1, strip.height), fill=SURFACE)
                strip.alpha_composite(im, (i*(width+20)*S, 0))
            blocks.append(strip)
    blocks.append(sources(payload))
    gap = 18*S
    height = sum(block.height for block in blocks)+gap*(len(blocks)-1)+64*S
    canvas = Image.new("RGBA", (1200*S, height), BG)
    y = 32*S
    for block in blocks:
        canvas.alpha_composite(block, (40*S, y))
        y += block.height+gap
    output = BytesIO()
    canvas.resize((1200, height//S), Image.Resampling.LANCZOS).convert("RGB").save(output, format="PNG")
    return RenderedImage(output.getvalue())
