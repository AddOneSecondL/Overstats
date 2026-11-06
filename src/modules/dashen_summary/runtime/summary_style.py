"""Shared visual tokens for summary images. Colors carry meaning; keep them in sync here."""
from PIL import Image

INK = (241, 245, 251)
TEXT = (208, 218, 231)
MUTED = (152, 167, 187)
FAINT = (112, 127, 148)
ACCENT = (249, 158, 26)
WIN = (88, 214, 160)
LOSS = (242, 108, 130)
DRAW = (243, 195, 109)
INFO = (120, 200, 245)
TEAL = (112, 224, 212)
HUMAN = (70, 212, 255)
HUMAN_DEEP = (22, 104, 214)
BOT = (255, 138, 36)
BOT_DEEP = (226, 36, 76)

SURFACE = (14, 20, 30, 226)
SURFACE_RAISED = (28, 37, 51, 235)
SURFACE_SUNKEN = (9, 14, 22, 170)
STROKE = (255, 255, 255, 26)
HAIRLINE = (255, 255, 255, 18)
SCRIM = (9, 14, 22)

RADIUS_CARD = 14
RADIUS_TILE = 10
RADIUS_CHIP = 6

ROLE_COLORS = {"Tank": (112, 172, 242), "Damage": (242, 134, 108), "Support": (92, 212, 166)}
GRADE_COLORS = {"S": (243, 195, 109), "A": (153, 219, 163), "B": (105, 198, 204), "C": (164, 147, 203), "D": (187, 146, 149)}
WEATHER_COLORS = {"晴": (240, 150, 44), "云": (112, 184, 224), "阴": (104, 114, 132), "雨": (66, 108, 176)}


def with_alpha(color, alpha):
    return (*color[:3], int(alpha))


def mix(color, base, amount):
    """Blend toward ``color`` by ``amount``; used for tinted chips on opaque surfaces."""
    return tuple(round(b + (c - b) * amount) for b, c in zip(base[:3], color[:3]))


def tinted(color, amount=.2):
    return mix(color, SURFACE[:3], amount)


def horizontal_scrim(size, stops, color=SCRIM):
    """Overlay whose alpha is interpolated across evenly spaced ``stops``."""
    width, height = size
    segments = max(1, len(stops) - 1)
    alpha = []
    for x in range(width):
        position = x / max(1, width - 1) * segments
        index = min(int(position), segments - 1)
        alpha.append(round(stops[index] + (stops[index + 1] - stops[index]) * (position - index)))
    strip = Image.new("L", (width, 1))
    strip.putdata(alpha)
    overlay = Image.new("RGBA", size, (*color, 255))
    overlay.putalpha(strip.resize(size))
    return overlay


def horizontal_gradient(size, start, end):
    width, height = size
    strip = Image.new("RGB", (width, 1))
    strip.putdata([mix(end, start, x / max(1, width - 1)) for x in range(width)])
    return strip.resize(size)


def vertical_scrim(size, top, bottom, color=SCRIM):
    width, height = size
    strip = Image.new("L", (1, height))
    strip.putdata([round(top + (bottom - top) * y / max(1, height - 1)) for y in range(height)])
    overlay = Image.new("RGBA", size, (*color, 255))
    overlay.putalpha(strip.resize(size))
    return overlay
