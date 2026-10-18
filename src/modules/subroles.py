"""Local official subrole icons, resolved by the game's hero configuration."""
from functools import lru_cache
import json
from pathlib import Path

from PIL import Image, ImageDraw

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "res"


@lru_cache(maxsize=2)
def _index(stamp):
    data = json.loads((RESOURCE_DIR / "query_tool.json").read_text(encoding="utf-8-sig"))
    result = {}
    for guid, hero in data.get("heroConfig", {}).items():
        subrole = hero.get("Subrole")
        if subrole:
            result[guid] = result[hero.get("Name", "")] = subrole
    for hero in data.get("heroList", []):
        subrole = result.get(hero.get("name"))
        if subrole:
            for field in ("id", "heroGuid"):
                if hero.get(field):
                    result[str(hero[field])] = subrole
    return result


def get_subrole(hero):
    try:
        entries = _index((RESOURCE_DIR / "query_tool.json").stat().st_mtime_ns)
        if isinstance(hero, dict):
            for key in ("hero_name", "hero_cn", "Name", "name", "hero_guid", "heroGuid", "heroId", "id"):
                found = entries.get(str(hero.get(key) or ""))
                if found:
                    return found
            return {}
        return entries.get(str(hero or ""), {})
    except (OSError, ValueError, TypeError):
        return {}


@lru_cache(maxsize=100)
def _badge(key, size):
    path = RESOURCE_DIR / "subroles" / f"{key.lower()}.png"
    with Image.open(path) as source:
        icon = source.convert("RGBA")
    icon.thumbnail((max(1, size - 6), max(1, size - 6)), Image.Resampling.LANCZOS)
    # Official SVGs use a monochrome silhouette; tint consistently on dark cards.
    white = Image.new("RGBA", icon.size, (233, 242, 253, 255))
    white.putalpha(icon.getchannel("A"))
    badge = Image.new("RGBA", (size, size))
    ImageDraw.Draw(badge).rounded_rectangle((0, 0, size - 1, size - 1), radius=max(3,size//4), fill=(24,36,52,245), outline=(106,134,164,210))
    badge.alpha_composite(white, ((size-icon.width)//2, (size-icon.height)//2))
    return badge


def draw_subrole_badge(canvas, hero, x, y, size=22):
    subrole = get_subrole(hero)
    if not subrole or size < 14:
        return False
    try:
        badge = _badge(subrole["key"], int(size))
        canvas.paste(badge, (int(x), int(y)), badge)
        return True
    except (OSError, ValueError, KeyError):
        return False
