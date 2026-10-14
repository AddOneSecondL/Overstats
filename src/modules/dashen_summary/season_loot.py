"""Season loot artwork and descriptive luck indicators (not player percentiles).

The API exposes aggregate counts only, not box types or per-opening outcomes.
Counts / openings are therefore labelled 收获比, never a measured drop chance.
Official ordinary-box reference: https://ow.blizzard.cn/news/264844/
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

RESOURCE_DIR = Path(__file__).resolve().parents[3] / "res"
BASELINES = {"epic_cnt": 0.2193, "legendary_cnt": 0.051}
WHITE = (239, 245, 255)
MUTED = (155, 173, 195)
PURPLE = (196, 157, 255)
GOLD = (255, 207, 116)
BLUE = (131, 213, 255)
# Each illustration is a tier, not one sprite per opened box.
PILE_TIERS = ((1, 1, "1–9 箱"), (10, 2, "10–49 箱"),
              (50, 3, "50–99 箱"), (100, 4, "100–199 箱"),
              (200, 5, "200–499 箱"), (500, 6, "500+ 箱"))


def count_value(raw):
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
        return int(value) if math.isfinite(value) and value >= 0 and value.is_integer() else None
    except (ValueError, TypeError, OverflowError):
        return None


def pile_tier(opened):
    opened = count_value(opened)
    if not opened:
        return 0, "尚未开箱" if opened == 0 else "数量未知"
    return next((depth, label) for threshold, depth, label in reversed(PILE_TIERS) if opened >= threshold)


def loot_metric(opened, count, baseline):
    opened, count = count_value(opened), count_value(count)
    if not opened or count is None or count > opened * 4:
        return None
    rate = count / opened
    multiple = rate / baseline
    # Explicit visual scale: 0x -> left, 1x -> centre, 3x or more -> right.
    position = multiple / 2 if multiple <= 1 else 0.5 + (multiple - 1) / 4
    label = "偏非" if multiple < 0.8 else "接近基准" if multiple <= 1.2 else "偏欧" if multiple < 2 else "欧气满满"
    return {"rate": rate, "multiple": multiple, "position": min(1., max(0., position)),
            "label": label, "small_sample": opened < 20}


def loot_panel_height(width):
    return 560 if width < 900 else 388


@lru_cache(maxsize=1)
def _crate():
    try:
        with Image.open(RESOURCE_DIR / "season_loot" / "crate.png") as source:
            asset = source.convert("RGBA")
        bounds = asset.getbbox()
        return asset.crop(bounds) if bounds else None
    except OSError:
        return None


def render_loot_panel(canvas, x, y, width, loot, font_loader=None):
    """Draw a self-sized panel; tall friend lists must not stretch this card."""
    height = loot_panel_height(width)
    card = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(card)

    def font(size):
        return font_loader(size) if font_loader else ImageFont.truetype(str(RESOURCE_DIR / "simhei.ttf"), size)

    def text(px, py, value, size=18, color=MUTED, max_width=None):
        value = str(value)
        face = font(size)
        if max_width:
            while len(value) > 1 and draw.textlength(value, font=face) > max_width:
                value = value[:-2] + "…"
        draw.text((px, py), value, font=face, fill=color)

    def crate(px, py, size):
        asset = _crate()
        if asset is not None:
            sprite = ImageOps.contain(asset, (size, size), Image.Resampling.LANCZOS)
            card.alpha_composite(sprite, (int(px + (size - sprite.width) / 2), int(py + (size - sprite.height) / 2)))
        else:
            # Asset failure must not prevent a season report from rendering.
            draw.rounded_rectangle((px + 4, py + 8, px + size - 4, py + size - 6), radius=5, fill=(107, 129, 151), outline=BLUE)
            draw.line((px + 5, py + size / 2, px + size - 5, py + size / 2), fill=WHITE, width=2)

    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=12, fill=(15, 23, 35, 245), outline=(57, 77, 101))
    draw.rounded_rectangle((20, 19, 24, 39), radius=2, fill=GOLD)
    text(38, 13, "赛季收获", 25, WHITE)
    text(width - 166, 22, "开箱手气档案", 16, GOLD)
    draw.line((20, 54, width - 20, 54), fill=(58, 76, 100))

    wide = width >= 900
    opened = count_value(loot.get("open_lootbox_cnt"))
    depth, tier = pile_tier(opened)
    hero_width = 390 if wide else width - 40
    draw.rounded_rectangle((20, 70, hero_width + 20, 302 if wide else 226), radius=10, fill=(23, 35, 50))
    text(38, 86, "本赛季累计开启", 17)
    number = f"{opened:,}" if opened is not None else "—"
    text(36, 113, number, 51, BLUE, 205 if not wide else 350)
    text(39, 176, "份补给", 17, WHITE)
    text(39, 204 if not wide else 275, f"箱堆档位 · {tier}", 14, MUTED)

    if depth:
        max_width, max_height = (180, 160) if wide else (270, 130)
        size = min(76, int(max_width / (depth * .74 + .26)),
                   int(max_height / (1 + (depth - 1) * .44)))
        step_x, step_y = size * .74, size * .44
        total_h = size + (depth - 1) * step_y
        cx = 20 + hero_width * .72 if not wide else 270
        bottom = 206 if not wide else 264
        # Render from the top/back down to the front row, with stable overlap.
        for row in range(depth):
            row_w = size + row * step_x
            for col in range(row + 1):
                crate(cx - row_w / 2 + col * step_x, bottom - total_h + row * step_y, size)
    else:
        text(250 if not wide else 210, 162 if not wide else 225, "等待第一箱" if opened == 0 else "暂无箱数", 18)

    start_x, start_y = (438, 73) if wide else (24, 241)
    area_width = width - start_x - 26
    for i, (key, title, color) in enumerate((("epic_cnt", "紫色 · 史诗", PURPLE), ("legendary_cnt", "金色 · 传奇", GOLD))):
        top = start_y + i * 130
        count = count_value(loot.get(key))
        value = loot_metric(opened, count, BASELINES[key])
        text(start_x, top, title, 19, color)
        text(start_x + 154, top - 4, f"{count:,}" if count is not None else "—", 27, color, 125)
        status = "样本较少" if value and value["small_sample"] else value["label"] if value else "暂无评估"
        text(start_x + area_width - 102, top + 2, status, 17, color, 102)
        if value:
            detail = f"收获比 {value['rate']:.2%}   /   普通箱基准 {BASELINES[key]:.2%}"
            text(start_x, top + 32, detail, 16, MUTED, area_width)
        else:
            text(start_x, top + 32, "暂无有效开箱数据" if not opened else "收获数据缺失或异常", 16)
        bar_x, bar_y, bar_w = start_x + 15, top + 73, area_width - 30
        colors = ((91, 117, 153), (123, 137, 191), (176, 128, 213), (239, 187, 101))
        for offset in range(bar_w):
            p = offset / max(1, bar_w - 1) * 3
            index = min(2, int(p))
            amount = p - index
            c = tuple(round(a + (b - a) * amount) for a, b in zip(colors[index], colors[index + 1]))
            draw.line((bar_x + offset, bar_y, bar_x + offset, bar_y + 8), fill=c if value else (48, 61, 78))
        mid = bar_x + bar_w // 2
        draw.line((mid, bar_y - 4, mid, bar_y + 12), fill=(219, 225, 236), width=2)
        if value:
            marker = round(bar_x + value["position"] * (bar_w - 1))
            draw.ellipse((marker - 20, bar_y - 25, marker + 20, bar_y + 16), fill=(20, 29, 43), outline=color, width=2)
            crate(marker - 18, bar_y - 23, 36)
        text(bar_x - 14, bar_y + 22, "非 · 0×", 14)
        text(mid - 37, bar_y + 22, "基准 1×", 14)
        text(bar_x + bar_w - 65, bar_y + 22, "欧 · ≥3×", 14, GOLD)

    footer_y = height - 52
    draw.line((24, footer_y - 9, width - 24, footer_y - 9), fill=(45, 61, 80))
    text(24, footer_y, "收获比 = 品质数量 ÷ 开箱数；箱种未拆分，欧非仅作趣味参考。", 14, MUTED, width - 48)
    text(24, footer_y + 22, "箱堆按数量分档示意  ·  普通箱概率：国服官方公示", 13, (115, 137, 160), width - 48)
    canvas.alpha_composite(card, (x, y)) if canvas.mode == "RGBA" else canvas.paste(card, (x, y), card)
