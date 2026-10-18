from __future__ import annotations

import base64
from io import BytesIO
import random

from PIL import Image, ImageFilter


def image_reply(image):
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=90)
    return {"type": "image", "media_type": "image/jpeg", "base64": base64.b64encode(output.getvalue()).decode("ascii")}


def render_stages(path, mode, rng=None):
    rng = rng or random.Random()
    with Image.open(path) as opened:
        if mode == "perk_icon_hero":
            icon = opened.convert("RGBA")
            icon.thumbnail((240, 240), Image.Resampling.LANCZOS)
            card = Image.new("RGB", (320, 320), (30, 39, 53))
            card.paste(icon, ((320 - icon.width) // 2, (320 - icon.height) // 2), icon)
            reply = image_reply(card)
            return [reply], reply
        original = opened.convert("RGB")
    original.thumbnail((960, 640), Image.Resampling.LANCZOS)
    width, height = original.size
    # A single center keeps the three nested crops on the same landmark.
    cx, cy = rng.uniform(.35, .65), rng.uniform(.35, .65)
    stages = []
    for index, fraction in enumerate((.18, .36, .64)):
        if mode == "map_crop":
            w, h = max(1, round(width * fraction)), max(1, round(height * fraction))
            left = max(0, min(width - w, round(width * cx - w / 2)))
            top = max(0, min(height - h, round(height * cy - h / 2)))
            frame = original.crop((left, top, left + w, top + h)).resize((width, height), Image.Resampling.LANCZOS)
        else:
            frame = original.filter(ImageFilter.GaussianBlur(radius=min(width, height) * (.065, .035, .016)[index]))
        stages.append(image_reply(frame))
    return stages, image_reply(original)
