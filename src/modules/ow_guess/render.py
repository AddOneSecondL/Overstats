from __future__ import annotations

import base64
from io import BytesIO
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..font_resolver import load_font


def image_reply(image):
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=90)
    return {"type": "image", "media_type": "image/jpeg", "base64": base64.b64encode(output.getvalue()).decode("ascii")}


LABELS = {"map_crop": "地图局部", "map_blur": "地图模糊", "perk_icon_hero": "威能猜英雄",
          "hero_crop": "头像猜英雄", "hero_description": "英雄描述猜英雄",
          "skill_description_hero": "技能描述猜英雄", "skill_description_name": "技能描述猜技能名",
          "hero_color": "代表色猜英雄"}


def card(mode, *, picture=None, text="", color=None, footer="限时 45 秒 · 直接回复答案", answer=False):
    font = load_font(28, name="simhei.ttf", prefer_cjk=True)
    small = load_font(20, name="simhei.ttf", prefer_cjk=True)
    title = load_font(34, name="simhei.ttf", prefer_cjk=True, bold=True)
    lines, line = [], ""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for char in text:
        if char == "\n" or probe.textlength(line + char, font=font) > 652:
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        lines.append(line)
    media_height = 0
    if picture is not None:
        picture = picture.copy()
        picture.thumbnail((652, 420), Image.Resampling.LANCZOS)
        media_height = picture.height + 40
    elif color:
        media_height = 240
    body_height = max(180, media_height + len(lines) * 44 + 48)
    image = Image.new("RGB", (800, body_height + 216), "#0c1622")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 776, 116), 16, fill="#18283b")
    draw.rounded_rectangle((40, 44, 46, 96), 3, fill="#f4bf68")
    draw.text((64, 36), "OVERSTATS  /  猜一猜", font=small, fill="#8fa5bc")
    draw.text((64, 66), "答案揭晓" if answer else LABELS[mode], font=title, fill="#f0f5fa")
    draw.rounded_rectangle((28, 136, 776, 140 + body_height), 18, fill="#060e18")
    draw.rounded_rectangle((24, 132, 772, 132 + body_height), 18, fill="#142235", outline="#30455c", width=1)
    y = 156
    if picture is not None:
        image.paste(picture.convert("RGB"), ((800-picture.width)//2, y))
        y += media_height
    elif color:
        draw.rounded_rectangle((90, y + 12, 710, y + 204), 18, fill=color, outline="#c4cbd4", width=2)
        y += media_height
    for line in lines:
        draw.text((74, y), line, font=font, fill="#eaf0f7")
        y += 44
    draw.text((40, image.height - 52), footer, font=small, fill="#8fa5bc")
    return image_reply(image)


def render_stages(path, mode, rng=None, entry=None):
    rng = rng or random.Random()
    entry = entry or {}
    if mode == "hero_color":
        return [card(mode, color=entry["color"])], None
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
        original = Image.new("RGBA", rgba.size, "#26384c")
        original.alpha_composite(rgba)
        original = original.convert("RGB")
    if mode == "perk_icon_hero":
        icon = ImageOps.contain(rgba, (240, 240), method=Image.Resampling.LANCZOS)
        original = Image.new("RGB", (320, 320), "#142235")
        tile = ImageDraw.Draw(original)
        tile.rounded_rectangle((4, 4, 316, 316), 24, fill="#26384c", outline="#415772", width=2)
        original.paste(icon, ((320 - icon.width) // 2, (320 - icon.height) // 2), icon)
        return [card(mode, picture=original)], None
    if mode == "hero_crop":
        original = ImageOps.fit(original, (420, 420), method=Image.Resampling.LANCZOS)
    else:
        original.thumbnail((652, 420), Image.Resampling.LANCZOS)
    width, height = original.size
    cx, cy = rng.uniform(.35, .65), rng.uniform(.35, .65)
    stages = []
    for index, fraction in enumerate((.18, .36, .64)):
        if mode in {"map_crop", "hero_crop"}:
            w, h = max(1, round(width * fraction)), max(1, round(height * fraction))
            left = max(0, min(width - w, round(width * cx - w / 2)))
            top = max(0, min(height - h, round(height * cy - h / 2)))
            frame = original.crop((left, top, left + w, top + h)).resize((width, height), Image.Resampling.LANCZOS)
        else:
            frame = original.filter(ImageFilter.GaussianBlur(radius=min(width, height) * (.065, .035, .016)[index]))
        stages.append(card(mode, picture=frame, footer=f"第 {index + 1}/3 张 · 剩余 {45-index*15} 秒 · 直接回复答案"))
    return stages, card(mode, picture=original, text=entry.get("name", ""), answer=True, footer=LABELS[mode])
