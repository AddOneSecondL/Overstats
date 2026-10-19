"""Gameplay-mode glyphs extracted from the game's arcade map cards."""
from functools import lru_cache
import json

from PIL import Image

from .font_resolver import resolve_resource_dir

RESOURCE_DIR = resolve_resource_dir()
MODE_ICONS = {
    "攻防作战": "assault", "运载目标": "escort", "攻击/护送": "hybrid",
    "占领要点": "control", "机动推进": "push", "闪点作战": "flashpoint",
    "攻防阵线": "clash",
}


@lru_cache(maxsize=2)
def _map_index(stamp):
    data = json.loads((RESOURCE_DIR / "query_tool.json").read_text(encoding="utf-8-sig"))
    result = {}
    for item in data.get("mapList", []):
        for field in ("guid", "id", "name"):
            if item.get(field):
                result[str(item[field])] = item.get("mode", "")
    return result


def gameplay_mode(value):
    if isinstance(value, dict):
        mode = value.get("mode")
        if mode in MODE_ICONS:
            return mode
        value = value.get("mapGuid") or value.get("guid") or value.get("mapId") or value.get("name")
    if value in MODE_ICONS:
        return value
    try:
        return _map_index((RESOURCE_DIR / "query_tool.json").stat().st_mtime_ns).get(str(value), "")
    except (OSError, ValueError, TypeError):
        return ""


@lru_cache(maxsize=128)
def _icon(key, size):
    with Image.open(RESOURCE_DIR / "map_modes" / (key + ".png")) as source:
        return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def draw_map_mode_icon(canvas, value, x, y, size=22):
    key = MODE_ICONS.get(gameplay_mode(value))
    if not key:
        return False
    try:
        icon = _icon(key, max(1, int(size)))
        canvas.paste(icon, (int(x), int(y)), icon)
        return True
    except OSError:
        return False
