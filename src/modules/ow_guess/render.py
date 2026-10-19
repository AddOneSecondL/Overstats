from __future__ import annotations

import base64
from io import BytesIO
import random

from PIL import Image, ImageFilter, ImageOps



def image_reply(image):
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=90)
    return {"type": "image", "media_type": "image/jpeg", "base64": base64.b64encode(output.getvalue()).decode("ascii")}


LABELS = {"map_crop": "地图局部", "map_blur": "地图模糊", "perk_icon_hero": "威能猜英雄",
          "hero_crop": "头像猜英雄", "hero_description": "英雄描述猜英雄",
          "skill_description_hero": "技能描述猜英雄", "skill_description_name": "技能描述猜技能名",
          "hero_color": "代表色猜英雄"}


def render_stages(path, mode, rng=None, entry=None):
    rng = rng or random.Random()
    entry = entry or {}
    if mode == "hero_color":
        return [image_reply(Image.new("RGB", (480, 280), entry["color"]))], None
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
        original = Image.new("RGBA", rgba.size, "#26384c")
        original.alpha_composite(rgba)
        original = original.convert("RGB")
    if mode == "perk_icon_hero":
        icon = ImageOps.contain(rgba, (240, 240), method=Image.Resampling.LANCZOS)
        original = Image.new("RGB", (320, 320), "#1e2735")
        original.paste(icon, ((320 - icon.width) // 2, (320 - icon.height) // 2), icon)
        return [image_reply(original)], None
    if mode == "hero_crop":
        original = ImageOps.fit(original, (420, 420), method=Image.Resampling.LANCZOS)
    else:
        original.thumbnail((960, 640), Image.Resampling.LANCZOS)
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
        stages.append(image_reply(frame))
    return stages, image_reply(original)
