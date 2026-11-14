"""Per-hero perk observations. Missing selections are never inferred from usage time."""
from collections import Counter, defaultdict
from html import unescape
import json
import re


def guid(value):
    text = str(value or "").strip()
    try:
        return str(int(text, 16 if text.lower().startswith("0x") else 10))
    except ValueError:
        return text


def _items(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def hero_choices(player, canonical=guid):
    """Roster perks belong only to its hero; heroList entries have their own owner."""
    choices = defaultdict(dict)
    if not isinstance(player, dict):
        return {}
    for source in [player, *_items(player.get("heroList"))]:
        if not isinstance(source, dict):
            continue
        hero = canonical(source.get("heroGuid") or source.get("heroId"))
        if not hero:
            continue
        for field in ("perks", "perkList", "heroPerks", "perkGuids", "perkGuidList"):
            for item in _items(source.get(field)):
                raw = item if isinstance(item, dict) else {"guid": item}
                key = guid(raw.get("guid") or raw.get("id") or raw.get("perkGuid") or raw.get("value"))
                if not key:
                    continue
                level = str(raw.get("perkLevel") or raw.get("level") or "")
                level = int(level) if level in ("1", "2") else 0
                previous = choices[hero].get(key)
                choices[hero][key] = {"guid": key, "level": level or (previous or {}).get("level", 0)}
    return {hero: list(items.values()) for hero, items in choices.items() if items}


def period_choices(observations, canonical=guid):
    """Merge duplicate detail rows before counting each match/hero/perk once."""
    matches = defaultdict(lambda: defaultdict(dict))
    for match_key, player in observations:
        for hero, items in hero_choices(player, canonical).items():
            for item in items:
                previous = matches[match_key][hero].get(item["guid"])
                if not previous or item["level"]:
                    matches[match_key][hero][item["guid"]] = item
    counts, levels, samples = defaultdict(Counter), {}, Counter()
    for heroes in matches.values():
        for hero, items in heroes.items():
            samples[hero] += 1
            for key, item in items.items():
                counts[hero][key] += 1
                levels[hero, key] = item["level"] or levels.get((hero, key), 0)
    return {hero: {"samples": samples[hero], "choices": [
        {"guid": key, "level": levels[hero, key], "count": count}
        for key, count in counter.items()]} for hero, counter in counts.items()}


class PerkCatalog:
    def __init__(self, config):
        self.index = {}
        for item in config.get("perkList") or []:
            self._add("", item)
        for hero, items in (config.get("heroPerkList") or {}).items():
            for item in items:
                self._add(guid(hero), item)

    def _add(self, hero, item):
        if not isinstance(item, dict):
            return
        key = guid(item.get("guid") or item.get("id"))
        name = re.split(r"<br\s*/?>", str(item.get("name") or ""), maxsplit=1, flags=re.I)[0]
        name = unescape(re.sub(r"<[^>]*>", "", name)).strip()
        if key:
            self.index[hero, key] = {"name": name or "未知威能", "icon": item.get("icon") or ""}

    def resolve(self, hero, choices):
        result = []
        for item in choices:
            key = guid(item["guid"])
            meta = self.index.get((guid(hero), key)) or self.index.get(("", key)) or {"name": "未知威能", "icon": ""}
            result.append({**item, **meta})
        return sorted(result, key=lambda item: (-item.get("count", 0), item["level"] or 3, item["guid"]))


def draw_choices(draw, entries, x, y, width, font, colors, truncate, *, counts=False, canvas=None, icons=None):
    """One bounded line of icon/name chips, matching the inline medal badges."""
    if not entries:
        return
    visible = sorted(entries[:4], key=lambda item: (item["level"] or 3, -item.get("count", 0), item["guid"]))
    gap = 4
    cell = min(132, (width - gap * (len(visible) - 1)) / len(visible))
    if cell < 40:
        return
    for i, item in enumerate(visible):
        left = x + i * (cell + gap)
        accent = colors.PURPLE if item["level"] == 2 else colors.INFO
        draw.rounded_rectangle((left, y, left + cell, y + 24), radius=6, fill=(*accent[:3], 35))
        icon = (icons or {}).get(item.get("icon"))
        if icon is not None and canvas is not None:
            from PIL import Image, ImageOps
            glyph = ImageOps.contain(icon.convert("RGBA"), (18, 18), Image.Resampling.LANCZOS)
            colored = Image.new("RGBA", glyph.size, accent)
            colored.putalpha(glyph.getchannel("A"))
            canvas.paste(colored, (round(left+4+(18-glyph.width)/2), round(y+3+(18-glyph.height)/2)), colored)
        else:
            draw.text((left+13, y+12), "◇", font=font(12), fill=accent, anchor="mm")
        suffix = f'×{item["count"]}' if counts else ""
        face = font(11)
        suffix_w = draw.textlength(suffix, font=face)
        label = truncate(draw, item["name"], face, max(0, cell-30-suffix_w))
        draw.text((left+25, y+12), label+suffix, font=face, fill=accent, anchor="lm")
