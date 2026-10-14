"""Offline, width-aware footer assembled from the approved official artwork."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from overstats.config import config as app_config
except ModuleNotFoundError:
    from config import config as app_config

ASSET_DIR = Path(__file__).resolve().parents[2] / "res" / "dashen_promo"
PROMO_URL = "https://act.ds.163.com/f0834ac50394246e/"


def is_dashen_promo_enabled() -> bool:
    return getattr(app_config, "SHOW_DASHEN_PROMO", False) is True


@lru_cache(maxsize=8)
def _asset(name: str) -> Any:
    from PIL import Image

    with Image.open(ASSET_DIR / f"{name}.png") as image:
        return image.convert("RGB" if name in {"background", "qr"} else "RGBA")


@lru_cache(maxsize=16)
def _footer(width: int, compact: bool = False) -> Any:
    from PIL import Image, ImageDraw, ImageOps

    def fit(name: str, max_width: int, max_height: int) -> Any:
        source = _asset(name)
        ratio = min(max_width / source.width, max_height / source.height)
        return source.resize((max(1, round(source.width * ratio)),
                              max(1, round(source.height * ratio))), Image.Resampling.LANCZOS)

    # QR modules always occupy an integer number of pixels, including quiet zone.
    scale = min(1.5, width / 1200)
    placements = []
    if compact and width >= 480:
        height = 128 if width >= 900 else 96
        qr_size = 111 if height == 128 else 74
        padding = 16
        qr_x, qr_y = width - padding - qr_size, (height - qr_size) // 2
        brand_width = min(180, width // 5)
        brand = fit("brand", brand_width, height - 36)
        placements.append((brand, padding, (height - brand.height) // 2))
        text_x = brand_width + padding * 3
        available = qr_x - text_x - padding
        title = fit("title", available, 34 if height == 128 else 26)
        features = fit("features", available, 24 if height == 128 else 18)
        cta = fit("cta", available, 23 if height == 128 else 18)
        gap = 6
        y = (height - title.height - features.height - cta.height - gap * 2) // 2
        for part in (title, features, cta):
            placements.append((part, text_x, y))
            y += part.height + gap
    elif width >= 900:
        height = round(240 * scale)
        for name, x, y, w, h in (
            ("brand", 26, 69, 230, 90), ("title", 308, 43, 542, 53),
            ("features", 310, 108, 525, 40), ("cta", 310, 158, 170, 41),
        ):
            placements.append((fit(name, round(w * scale), round(h * scale)),
                               round(x * scale), round(y * scale)))
        qr_size = 37 * max(1, int(185 * scale) // 37)
        qr_x, qr_y = width - round(32 * scale) - qr_size, (height - qr_size) // 2
    elif width >= 280:
        height = 160 if width < 480 else 190
        qr_size = 111 if width < 480 else (148 if width < 700 else 185)
        qr_x, qr_y = width - 16 - qr_size, (height - qr_size) // 2
        available = qr_x - 40
        rows = (("brand", 12, 36), ("title", 56, 28),
                ("features", 94, 20), ("cta", 123, 23)) if width < 480 else (
                    ("brand", 15, 44), ("title", 67, 35),
                    ("features", 110, 24), ("cta", 146, 25))
        for name, y, h in rows:
            placements.append((fit(name, available, h), 20, y))
    else:
        padding = min(16, max(1, width // 20))
        available = max(1, width - padding * 2)
        y = padding + 4
        for name, h in (("brand", 45), ("title", 34), ("features", 24)):
            part = fit(name, available, h)
            placements.append((part, (width - part.width) // 2, y))
            y += part.height + padding
        qr_size = 37 * max(1, min(5, width // 37 if available < 37 else available // 37))
        qr_x, qr_y = (width - qr_size) // 2, y
        part = fit("cta", available, 27)
        y += qr_size + padding
        placements.append((part, (width - part.width) // 2, y))
        height = y + part.height + padding

    # Extremely small inputs cannot contain a 37-module QR at native resolution.
    # Keep their width and artwork intact; normal renderer widths are >= 40px.
    if width < 37:
        qr_size = width
        qr_x = 0
    background = ImageOps.fit(_asset("background"), (width, height),
                              method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(background)
    draw.rectangle((0, 0, width - 1, max(1, round(3 * scale)) - 1), fill="#e81820")
    if width >= 900 and not compact:
        x = round(280 * scale)
        draw.line((x, round(45 * scale), x, round(195 * scale)), fill="#444444")
    for part, x, y in placements:
        background.paste(part, (x, y), part)
    background.paste(_asset("qr").resize((qr_size, qr_size), Image.Resampling.NEAREST),
                     (qr_x, qr_y))
    return background


def append_dashen_promo(image: Any, *, compact: bool = True) -> Any:
    """Extend the bottom only; disabled calls return the original image untouched."""
    if not is_dashen_promo_enabled():
        return image
    from PIL import Image

    footer = _footer(image.width, compact)
    mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
    result = Image.new(mode, (image.width, image.height + footer.height))
    result.paste(image.convert(mode), (0, 0))
    result.paste(footer, (0, image.height))
    return result
