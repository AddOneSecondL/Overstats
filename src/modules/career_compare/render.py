from __future__ import annotations

from io import BytesIO
import math

from PIL import Image, ImageDraw, ImageOps

from ..dashen_hero_treemap.render import (
    _load_summary_font, _truncate_text, _fit_font, _wrap_text, _open_cached_asset,
    RESOURCE_DIR, RenderedImage,
)
from ..dashen_summary.runtime.summary_typography import SummaryDraw
from ..dashen_promo import append_dashen_promo
from .metrics import display, paired_metrics, winner

BG = (12, 20, 32)
CARD = (19, 30, 44)
WHITE = (233, 240, 248)
MUTED = (146, 164, 186)
GREEN = (108, 232, 185)
COLORS = ((123, 197, 235), (239, 196, 115))
MODE_NAMES = {"quick": "快速比赛", "competitive": "竞技比赛",
              "stadium_quick": "角斗领域 · 快速", "stadium_competitive": "角斗领域 · 竞技"}


def _font(size, bold=False):
    return _load_summary_font(size, bold=bold)


def _center(draw, x, y, text, size, color=WHITE):
    font = _font(size)
    draw.text((x - draw.textlength(text, font=font) / 2, y), text, font=font, fill=color)


def _raw(value):
    return "—" if value is None else f"{value:,.2f}".rstrip("0").rstrip(".")


def _radar(canvas, draw, axes, cy):
    cx, radius = 840, 148
    angles = [-math.pi/2 + i*math.tau/6 for i in range(6)]

    def point(index, value):
        return (cx + radius*value*math.cos(angles[index]), cy + radius*value*math.sin(angles[index]))

    for fraction in (.25, .5, .75, 1.):
        polygon = [point(i, fraction) for i in range(6)]
        draw.line(polygon + polygon[:1], fill=(55, 75, 96), width=2)
    for i in range(6):
        draw.line([(cx, cy), point(i, 1)], fill=(45, 64, 85), width=1)
    for side in range(2):
        values = [axis["normalized"][side] for axis in axes]
        points = [point(i, value) if value is not None else None for i, value in enumerate(values)]
        if all(p is not None for p in points):
            overlay = Image.new("RGBA", canvas.size)
            ImageDraw.Draw(overlay).polygon(points, fill=(*COLORS[side], 42))
            canvas.alpha_composite(overlay)
            draw.line(points + points[:1], fill=COLORS[side], width=4)
        for p in points:
            if p:
                draw.ellipse((p[0]-4, p[1]-4, p[0]+4, p[1]+4), fill=COLORS[side])
    offsets = ((0,-218),(224,-109),(224,109),(0,195),(-224,109),(-224,-109))
    for axis, (dx, dy) in zip(axes, offsets):
        x, y = cx + dx, cy + dy
        _center(draw, x, y, axis["label"], 23)
        _center(draw, x, y+31, f'{_raw(axis["values"][0])} / {_raw(axis["values"][1])}', 18, MUTED)
    if not any(any(v is not None for v in a["normalized"]) for a in axes):
        draw.rounded_rectangle((cx-99,cy-26,cx+99,cy+26),radius=9,fill=CARD)
        _center(draw,cx,cy-12,"暂无雷达数据",23,MUTED)


def _legend(draw, players, y):
    font = _font(20)
    names = [_truncate_text(draw, player["display_name"], font, 300) for player in players]
    widths = [int(draw.textlength(name, font=font)) + 56 for name in names]
    x = (1680 - sum(widths) - 18) // 2
    for side, (name, width) in enumerate(zip(names, widths)):
        draw.rounded_rectangle((x, y, x+width, y+40), radius=10,
                               fill=(25, 39, 55), outline=(47, 66, 86))
        draw.rounded_rectangle((x+13, y+13, x+27, y+27), radius=3, fill=COLORS[side])
        draw.text((x+37, y+9), name, font=font, fill=WHITE)
        x += width + 18


def render_career_compare(data):
    width = 1680
    measure = SummaryDraw(Image.new("RGB", (1, 1)), numeric_font_path=RESOURCE_DIR/"GrotaRoundedExtraBold.otf")
    layouts = []
    for section in data["sections"]:
        groups = {}
        for pair in paired_metrics(*section["players"]):
            metric = pair[0] or pair[1]
            # These values already have dedicated overview cards.
            if metric["label"] in {"胜率", "KDA", "游戏时间"}:
                continue
            lines = _wrap_text(measure, metric["label"], _font(20), 420, 100)
            group = metric.get("group") or "详细数据"
            groups.setdefault(group, []).append((pair, lines, max(54, len(lines)*25+22)))
        groups = [(name, entries) for name, entries in groups.items()]
        table_height = sum(46 + sum(row[2] for row in entries) + 16 for _, entries in groups)
        layouts.append((section, groups, 664 + table_height))
    height = 184 + sum(item[2] + 24 for item in layouts) + 78
    canvas = Image.new("RGBA", (width, height), (*BG, 255))
    draw = SummaryDraw(canvas, numeric_font_path=RESOURCE_DIR/"GrotaRoundedExtraBold.otf")
    draw.rectangle((0, 0, width, 4), fill=COLORS[0])
    draw.text((36, 23), "生涯对比", font=_font(40, True), fill=WHITE)
    draw.text((250, 40), MODE_NAMES.get(data["mode"], data["mode"]), font=_font(23), fill=MUTED)
    if data.get("preview"):
        draw.text((1520, 42), "示例数据", font=_font(19), fill=MUTED)
    for side, player in enumerate(data["players"]):
        x = 30 + side*830
        draw.rounded_rectangle((x, 89, x+790, 171), radius=14, fill=(6, 12, 21))
        draw.rounded_rectangle((x, 84, x+790, 166), radius=14, fill=CARD, outline=(57, 77, 100))
        draw.rounded_rectangle((x+18, 107, x+24, 143), radius=3, fill=COLORS[side])
        name = _truncate_text(draw, player["display_name"], _font(32, True), 710)
        draw.text((x+42, 108), name, font=_font(32, True), fill=COLORS[side])
    y = 184
    for section, groups, section_h in layouts:
        draw.rounded_rectangle((30, y+6, 1650, y+section_h+6), radius=18, fill=(6, 12, 21))
        draw.rounded_rectangle((30, y, 1650, y+section_h), radius=18, fill=(16, 26, 39), outline=(46, 63, 82))
        draw.text((56, y+20), section["hero_name"], font=_font(32, True), fill=WHITE)
        draw.line((56, y+66, 1624, y+66), fill=(45, 62, 82), width=1)
        # The radar sits in a recessed central panel, between the two player summaries.
        draw.rounded_rectangle((446, y+84, 1234, y+642), radius=16, fill=(11, 21, 33), outline=(40, 57, 77))
        _radar(canvas, draw, section["radar"], y+314)
        _legend(draw, data["players"], y+590)
        for side, hero in enumerate(section["players"]):
            x = 50 if side == 0 else 1264
            draw.rounded_rectangle((x, y+84, x+366, y+642), radius=16, fill=CARD, outline=(45, 63, 84))
            draw.line((x+22, y+85, x+344, y+85), fill=COLORS[side], width=2)
            if hero:
                icon = _open_cached_asset(hero.get("icon_url"), ("heroes", "misc", "summary"))
                draw.rounded_rectangle((x+123, y+106, x+243, y+226), radius=16, fill=(27, 42, 58))
                if icon is not None:
                    icon = ImageOps.contain(icon.convert("RGBA"), (112, 112))
                    canvas.alpha_composite(icon, (x+183-icon.width//2, y+166-icon.height//2))
                else:
                    _center(draw, x+183, y+150, section["hero_name"], 26, COLORS[side])
                lookup = {m["label"]: m for m in hero["metrics"]}
                for j, key in enumerate(("胜率", "KDA", "游戏时间")):
                    yy = y+252+j*118
                    draw.rounded_rectangle((x+18, yy, x+348, yy+100), radius=12, fill=(25, 39, 54))
                    draw.text((x+36, yy+14), key, font=_font(18), fill=MUTED)
                    value = display(lookup.get(key))
                    draw.text((x+36, yy+46), value, font=_fit_font(draw, value, 34, 296, bold=True), fill=COLORS[side])
            else:
                _center(draw, x+183, y+322, "暂无记录", 24, MUTED)
        row_y = y+662
        for group, entries in groups:
            for side in range(2):
                x = 50+810*side
                draw.rounded_rectangle((x, row_y, x+770, row_y+40), radius=8, fill=(29, 45, 62))
                draw.rectangle((x+14, row_y+12, x+18, row_y+28), fill=COLORS[side])
                draw.text((x+30, row_y+10), group, font=_font(19, True), fill=WHITE)
            row_y += 46
            for i, (pair, lines, row_h) in enumerate(entries):
                better = winner(*pair)
                for side, metric in enumerate(pair):
                    x = 50+810*side
                    fill = (21, 52, 46) if better==side else ((23, 36, 51) if i%2==0 else (19, 30, 44))
                    draw.rounded_rectangle((x, row_y, x+770, row_y+row_h-5), radius=7, fill=fill)
                    if better==side:
                        draw.rounded_rectangle((x, row_y+9, x+3, row_y+row_h-14), radius=1, fill=GREEN)
                    label_lines = lines if metric else ["—"]
                    label_y = row_y + (row_h-5-len(label_lines)*25)//2
                    for j, line in enumerate(label_lines):
                        draw.text((x+20, label_y+j*25), line, font=_font(20), fill=WHITE if metric else MUTED)
                    value = display(metric)
                    draw.text((x+526, row_y+(row_h-30)//2), value,
                              font=_fit_font(draw, value, 25, 224, bold=True), fill=GREEN if better==side else WHITE)
                row_y += row_h
            row_y += 16
        y += section_h+24
    draw.text((50, y+8), "切换模式：快速生涯对比 / 竞技生涯对比", font=_font(21), fill=MUTED)
    if data.get("comparison") == "top20":
        draw.text((900, y+8), "全服 Top 20% · 未提供的统计显示 —", font=_font(20), fill=MUTED)
    canvas = append_dashen_promo(canvas)
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    return RenderedImage(output.getvalue())
