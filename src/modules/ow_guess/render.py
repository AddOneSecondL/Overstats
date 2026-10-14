from __future__ import annotations

import base64
from io import BytesIO
import random

from PIL import Image, ImageFilter
from ..dashen_promo import append_dashen_promo


def image_reply(image):
    output = BytesIO()
    append_dashen_promo(image).convert("RGB").save(output, format="JPEG", quality=90)
    return {"type": "image", "media_type": "image/jpeg", "base64": base64.b64encode(output.getvalue()).decode("ascii")}


def render_stages(path, mode, rng=None):
    rng = rng or random.Random()
    with Image.open(path) as opened:
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
