"""Night and day themes for summary images. Colors carry meaning; keep them in sync here.

Renders overlap, so the active theme lives in a ContextVar and is read through ``C``:
a render that crosses the day/night boundary keeps one theme from start to finish.
"""
from contextvars import ContextVar
import datetime
from functools import wraps
import inspect
from math import ceil
import os
from types import SimpleNamespace

from PIL import Image, ImageFilter

RADIUS_CARD = 14
RADIUS_TILE = 10
RADIUS_CHIP = 6

DEFAULT_DAY_START_HOUR = 7
DEFAULT_DAY_END_HOUR = 19

NIGHT = SimpleNamespace(
    NAME="night",
    INK=(241, 245, 251),
    TEXT=(208, 218, 231),
    MUTED=(152, 167, 187),
    FAINT=(112, 127, 148),
    ACCENT=(249, 158, 26),
    WIN=(88, 214, 160),
    LOSS=(242, 108, 130),
    DRAW=(243, 195, 109),
    INFO=(120, 200, 245),
    TEAL=(112, 224, 212),
    PURPLE=(197, 156, 255),
    HUMAN=(70, 212, 255),
    HUMAN_DEEP=(22, 104, 214),
    BOT=(255, 138, 36),
    BOT_DEEP=(226, 36, 76),
    HUMAN_TEXT=(70, 212, 255),
    BOT_TEXT=(255, 138, 36),
    SURFACE=(14, 20, 30, 226),
    SURFACE_RAISED=(28, 37, 51, 235),
    SURFACE_SUNKEN=(9, 14, 22, 170),
    STROKE=(255, 255, 255, 26),
    HAIRLINE=(255, 255, 255, 18),
    SCRIM=(9, 14, 22),
    ROLE_COLORS={"Tank": (112, 172, 242), "Damage": (242, 134, 108), "Support": (92, 212, 166)},
    GRADE_COLORS={"S": (243, 195, 109), "A": (153, 219, 163), "B": (105, 198, 204), "C": (164, 147, 203), "D": (187, 146, 149)},
    WEATHER_COLORS={"晴": (240, 150, 44), "云": (112, 184, 224), "阴": (104, 114, 132), "雨": (66, 108, 176)},
    BAND_COLORS={
        "above_median": (96, 216, 135),
        "top20": (90, 169, 255),
        "top10": (177, 135, 255),
        "top5": (255, 176, 74),
        "top2": (255, 220, 120),
    },
    RAINBOW=[(255, 110, 110), (255, 176, 74), (255, 218, 117), (117, 223, 174), (139, 216, 255), (177, 135, 255)],
    MEDAL_D=(190, 130, 250),
    MEDAL_M=(200, 206, 216),
    PAGE_OVERLAY=(5, 8, 14, 166),
    PAGE_BRIGHTNESS=.78,
    PAGE_COLOR=.86,
    PAGE_FADE=96,
    REPORT_WASH=(5, 10, 18, 55),
    BANNER_SCRIM=(240, 226, 196, 232),
    AWARD_SCRIM=(232, 196, 120, 190),
    MAP_SCRIM=(234, 200, 140, 200, 236),
    ROW_SCRIM=(236, 196, 208, 238),
    STAT_TINT=(9, 14, 22, 80),
    STAT_SCRIM=(200, 96, 190),
    TILE_COVER_TINT=(8, 15, 26, 70),
    TILE_TINT=.2,
    CHIP=(10, 16, 25, 214),
    CHIP_TEXT=(241, 245, 251),
    CHIP_WIN=(88, 214, 160),
    CHIP_LOSS=(242, 108, 130),
    CHIP_MUTED=(152, 167, 187),
    MODE_COMP=(239, 184, 103),
    MODE_QUICK=(120, 200, 245),
    STREAK_TEXT=(12, 18, 27),
    STAT_LABEL=(208, 218, 231),
    STAT_RATE=(208, 218, 231),
    STAT_MAP=(152, 167, 187),
    NOTCH=(9, 14, 22),
    SEAM=(255, 255, 255),
    SEAM_GLOW=(44, 84),
    ACTIVITY_PALETTE=[(108, 202, 228), (241, 189, 115), (150, 216, 168), (183, 161, 229), (237, 151, 164), (132, 169, 234), (219, 199, 142)],
    GRID_MAJOR=(51, 69, 91),
    GRID_MINOR=(35, 50, 69),
    AXIS_TEXT=(139, 163, 187),
    AXIS_LABEL=(149, 173, 198),
    AXIS_EMPTY=(160, 180, 202),
    CHART_BASE=(18, 24, 34),
    CHART_AREA=(24, 47, 63),
    CHART_TOTAL=(235, 242, 251),
    LOOT_SCALE=((91, 117, 153), (123, 137, 191), (176, 128, 213), (239, 187, 101)),
    LOOT_EMPTY=(48, 61, 78),
    LOOT_MID=(219, 225, 236),
    LOOT_MARKER=(20, 29, 43),
    USAGE_FILL_ALPHA=72,
    PROFILE_BANNER_SCRIM=(242, 232, 206, 216, 240),
    RECENT_ROW_SCRIM=(150, 226, 244, 248),
    STRENGTH_TONES={
        "quick": {"range": (132, 208, 255), "line": (92, 164, 255), "on_line": (9, 14, 22)},
        "competitive": {"range": (255, 136, 128), "line": (255, 86, 86), "on_line": (9, 14, 22)},
    },
    STRENGTH_MAP_SCRIM=176,
    STRENGTH_RESULT_TINT=.34,
    RANK_COLORS=(
        (207, 120, 86), (196, 201, 200), (217, 164, 59),
        (149, 213, 179), (95, 227, 157), (93, 163, 241),
        (140, 230, 94), (135, 115, 249), (190, 123, 224),
    ),
    MATCH_MODES={
        "unranked": (120, 170, 255),
        "stadium_qp": (92, 214, 136),
        "stadium_comp": (236, 176, 76),
        "competitive": (242, 124, 156),
        "competitive_6v6": (196, 156, 255),
        "unranked_6v6": (86, 214, 214),
    },
    # Pale artwork needs help on paper; on the dark theme these stay unset.
    ROLE_ICON=None,
    MAP_ICON=None,
    STICKER=None,
    PORTRAIT_EDGE=None,
    PERK_PLATE=None,
    RANK_TEXT=(208, 218, 231),
    RANK_SHIFT=3,
)

_DAY_INK = (46, 37, 28)
DAY = SimpleNamespace(
    **{
        **vars(NIGHT),
        "NAME": "day",
        "INK": _DAY_INK,
        "TEXT": (78, 66, 54),
        "MUTED": (108, 94, 78),
        "FAINT": (112, 97, 80),
        "ACCENT": (178, 86, 6),
        "WIN": (30, 118, 80),
        "LOSS": (176, 44, 58),
        "DRAW": (142, 94, 6),
        "INFO": (26, 92, 156),
        "TEAL": (8, 112, 106),
        "PURPLE": (92, 66, 156),
        "HUMAN": (0, 142, 214),
        "HUMAN_DEEP": (22, 66, 156),
        "BOT": (236, 124, 22),
        "BOT_DEEP": (176, 28, 52),
        "HUMAN_TEXT": (16, 92, 170),
        "BOT_TEXT": (176, 70, 0),
        "SURFACE": (251, 245, 230, 244),
        "SURFACE_RAISED": (243, 234, 214, 255),
        "SURFACE_SUNKEN": (238, 228, 206, 235),
        "STROKE": (70, 50, 28, 44),
        "HAIRLINE": (70, 50, 28, 34),
        "SCRIM": (246, 238, 220),
        "ROLE_COLORS": {"Tank": (36, 92, 168), "Damage": (182, 66, 36), "Support": (24, 122, 86)},
        "GRADE_COLORS": {"S": (160, 104, 0), "A": (36, 118, 66), "B": (0, 106, 118), "C": (92, 66, 156), "D": (136, 72, 80)},
        "WEATHER_COLORS": {"晴": (206, 128, 36), "云": (132, 176, 196), "阴": (138, 128, 114), "雨": (72, 104, 150)},
        "BAND_COLORS": {
            "above_median": (30, 118, 72),
            "top20": (30, 88, 176),
            "top10": (98, 62, 170),
            "top5": (178, 86, 6),
            "top2": (150, 106, 0),
        },
        # Yellow disappears on paper, so the rainbow runs through deeper inks.
        "RAINBOW": [(190, 44, 56), (196, 96, 0), (150, 112, 0), (24, 126, 76), (22, 98, 176), (104, 58, 184)],
        "MEDAL_D": (98, 62, 170),
        "MEDAL_M": (108, 94, 78),
        "PAGE_OVERLAY": (240, 230, 208, 242),
        "PAGE_BRIGHTNESS": 1.02,
        "PAGE_COLOR": .05,
        "PAGE_FADE": 70,
        "REPORT_WASH": None,
        "BANNER_SCRIM": (246, 236, 190, 225),
        "AWARD_SCRIM": (238, 214, 140, 214),
        "MAP_SCRIM": (240, 216, 150, 214, 242),
        "ROW_SCRIM": (242, 226, 232, 244),
        "STAT_TINT": None,
        "STAT_SCRIM": (238, 206, 232),
        "TILE_COVER_TINT": None,
        "TILE_TINT": .15,
        "CHIP": (46, 37, 28, 226),
        "CHIP_TEXT": (250, 244, 230),
        "CHIP_WIN": (120, 220, 170),
        "CHIP_LOSS": (255, 140, 150),
        "CHIP_MUTED": (200, 190, 175),
        "STREAK_TEXT": (255, 255, 255),
        "STAT_LABEL": _DAY_INK,
        "STAT_RATE": _DAY_INK,
        "STAT_MAP": (78, 66, 54),
        "NOTCH": (255, 255, 255),
        "SEAM": _DAY_INK,
        "SEAM_GLOW": (30, 60),
        "ACTIVITY_PALETTE": [(30, 110, 140), (186, 110, 20), (40, 124, 76), (100, 74, 170), (176, 60, 88), (40, 84, 172), (132, 106, 28)],
        "GRID_MAJOR": (*_DAY_INK, 30),
        "GRID_MINOR": (*_DAY_INK, 18),
        "AXIS_TEXT": (108, 94, 78),
        "AXIS_LABEL": (108, 94, 78),
        "AXIS_EMPTY": (108, 94, 78),
        "CHART_BASE": (255, 255, 255),
        "CHART_AREA": (226, 214, 186),
        "CHART_TOTAL": _DAY_INK,
        "LOOT_SCALE": ((150, 138, 118), (150, 130, 150), (130, 90, 160), (178, 110, 20)),
        "LOOT_EMPTY": (216, 205, 182),
        "LOOT_MID": _DAY_INK,
        "LOOT_MARKER": (243, 234, 214),
        "USAGE_FILL_ALPHA": 52,
        "PROFILE_BANNER_SCRIM": (246, 236, 200, 216, 242),
        "RECENT_ROW_SCRIM": (214, 240, 250, 252),
        "STRENGTH_TONES": {
            "quick": {"range": (26, 92, 156), "line": (22, 66, 156), "on_line": (255, 255, 255)},
            "competitive": {"range": (176, 44, 58), "line": (150, 24, 40), "on_line": (255, 255, 255)},
        },
        "STRENGTH_MAP_SCRIM": 214,
        "STRENGTH_RESULT_TINT": .26,
        "RANK_COLORS": (
            (146, 74, 36), (96, 106, 112), (150, 104, 0),
            (46, 120, 96), (20, 128, 76), (26, 96, 176),
            (66, 128, 20), (82, 62, 196), (136, 58, 168),
        ),
        "MATCH_MODES": {
            "unranked": (36, 84, 190),
            "stadium_qp": (30, 118, 70),
            "stadium_comp": (150, 94, 0),
            "competitive": (172, 50, 84),
            "competitive_6v6": (98, 62, 170),
            "unranked_6v6": (8, 112, 112),
        },
        "ROLE_ICON": _DAY_INK,
        "MAP_ICON": (78, 66, 54),
        "STICKER": _DAY_INK,
        "PORTRAIT_EDGE": (*_DAY_INK, 120),
        "PERK_PLATE": (46, 37, 28, 226),
        "RANK_TEXT": _DAY_INK,
        "RANK_SHIFT": 7,
    }
)

THEMES = {NIGHT.NAME: NIGHT, DAY.NAME: DAY}
_ACTIVE_THEME = ContextVar("summary_theme", default=NIGHT)


class _ActiveTheme:
    """Attribute access always resolves against the render's own theme."""

    def __getattr__(self, name):
        return getattr(_ACTIVE_THEME.get(), name)


C = _ActiveTheme()


def _local_tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=8), name="Asia/Shanghai")


def _env_hour(name, default):
    try:
        hour = int(str(os.getenv(name, "") or "").strip())
    except ValueError:
        return default
    return hour if 0 <= hour <= 24 else default


def theme_for_time(now=None):
    """Pick by Beijing time; OVERSTATS_THEME=day|night pins one theme."""
    forced = str(os.getenv("OVERSTATS_THEME", "") or "").strip().lower()
    if forced in THEMES:
        return THEMES[forced]
    now = now or datetime.datetime.now(_local_tz())
    start = _env_hour("OVERSTATS_THEME_DAY_START", DEFAULT_DAY_START_HOUR)
    end = _env_hour("OVERSTATS_THEME_DAY_END", DEFAULT_DAY_END_HOUR)
    is_day = start <= now.hour < end if start <= end else not end <= now.hour < start
    return DAY if is_day else NIGHT


def themed(render):
    """Hold one theme for a whole render, whatever else runs meanwhile."""

    if not inspect.iscoroutinefunction(render):
        @wraps(render)
        def sync_wrapper(*args, **kwargs):
            token = _ACTIVE_THEME.set(theme_for_time())
            try:
                return render(*args, **kwargs)
            finally:
                _ACTIVE_THEME.reset(token)

        return sync_wrapper

    @wraps(render)
    async def wrapper(*args, **kwargs):
        token = _ACTIVE_THEME.set(theme_for_time())
        try:
            return await render(*args, **kwargs)
        finally:
            _ACTIVE_THEME.reset(token)

    return wrapper


def activate_theme(theme):
    """Set the theme for the current context, for fixtures built outside a render."""
    return _ACTIVE_THEME.set(theme)


def sticker_outline(image, color, width=1.5):
    """Dark die-cut edge so pale emblems keep their colour yet separate from paper."""
    scale = 4
    pad = ceil(width) + 1
    big = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    frame = Image.new("RGBA", (big.width + pad * scale * 2, big.height + pad * scale * 2), (0, 0, 0, 0))
    frame.paste(big, (pad * scale, pad * scale))
    alpha = frame.getchannel("A").point(lambda value: 255 if value > 60 else 0)
    alpha = alpha.filter(ImageFilter.MaxFilter(int(width * scale) * 2 + 1))
    edge = Image.new("RGBA", frame.size, (*color, 255))
    edge.putalpha(alpha)
    merged = Image.alpha_composite(edge, frame)
    return merged.resize((image.width + pad * 2, image.height + pad * 2), Image.Resampling.LANCZOS)


def with_alpha(color, alpha):
    return (*color[:3], int(alpha))


def mix(color, base, amount):
    """Blend toward ``color`` by ``amount``; used for tinted chips on opaque surfaces."""
    return tuple(round(b + (c - b) * amount) for b, c in zip(base[:3], color[:3]))


def tinted(color, amount=.2):
    return mix(color, C.SURFACE[:3], amount)


def horizontal_scrim(size, stops, color=None):
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
    overlay = Image.new("RGBA", size, (*(color or C.SCRIM), 255))
    overlay.putalpha(strip.resize(size))
    return overlay


def horizontal_gradient(size, start, end):
    width, height = size
    strip = Image.new("RGB", (width, 1))
    strip.putdata([mix(end, start, x / max(1, width - 1)) for x in range(width)])
    return strip.resize(size)


def vertical_scrim(size, top, bottom, color=None):
    width, height = size
    strip = Image.new("L", (1, height))
    strip.putdata([round(top + (bottom - top) * y / max(1, height - 1)) for y in range(height)])
    overlay = Image.new("RGBA", size, (*(color or C.SCRIM), 255))
    overlay.putalpha(strip.resize(size))
    return overlay
