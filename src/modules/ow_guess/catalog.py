from __future__ import annotations

import html
import hashlib
from pathlib import Path
import random
import re
import tempfile

import httpx

from ..query_tool import read_query_tool
from ..errors import ModuleError
from ...constants import iter_hero_alias_pairs


EXCLUDED_MAP_MARKERS = (
    "地图工坊", "英雄精通", "vppgreenroom", "怪鼠复仇", "教学模式", "高架车站",
    "workshop", "heromastery", "junkenstein", "tutorial",
)


def is_excluded_map(item):
    values = (str(item.get(key) or "") for key in ("name", "mode"))
    return any(marker in re.sub(r"[\s_-]+", "", value).casefold()
               for value in values for marker in EXCLUDED_MAP_MARKERS)


def simplify_map_name(name):
    return re.sub(r"\s*[-‐‑–—－]\s*", "", str(name or "")).strip()


class OWGuessCatalog:
    """Internal questions are derived directly from the resource configuration."""

    def __init__(self, *, random_source=None):
        self.random = random_source or random.Random()

    def pick_question(self):
        payload = read_query_tool(default={})
        entries = {}
        control_names = {
            simplify_map_name(item.get("name"))
            for item in payload.get("mapList", [])
            if isinstance(item, dict) and item.get("mode") == "占领要点"
            and not is_excluded_map(item) and item.get("name")
        }
        for item in payload.get("mapList", []):
            if not isinstance(item, dict) or is_excluded_map(item):
                continue
            original_name = str(item.get("name") or "").strip()
            name = simplify_map_name(original_name)
            url = str(item.get("icon") or "").strip()
            if name and url.startswith("https://"):
                entries[(name, url)] = {**item, "name": name, "answer_aliases": list(dict.fromkeys((name, original_name))),
                    "requires_submap": item.get("mode") == "占领要点" and any(
                        parent != name and parent in name for parent in control_names
                    )}
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="地图题库暂无可用图片，请更新资源配置。", status_code=503)
        return self.random.choice(list(entries.values()))

    def pick_perk_question(self):
        payload = read_query_tool(default={})
        heroes = {str(h.get("id")): h.get("name") for h in payload.get("heroList", []) if h.get("name")}
        by_icon = {}
        for hero_id, perks in payload.get("heroPerkList", {}).items():
            hero = heroes.get(str(hero_id))
            if not hero:
                continue
            for perk in perks:
                url = str(perk.get("icon") or "").strip()
                title = html.unescape(re.split(r"<br\s*/?>", str(perk.get("name") or ""), flags=re.I)[0]).strip()
                if not url.startswith("https://") or not title or "[PH]" in title:
                    continue
                by_icon.setdefault(url, []).append((hero, title, perk.get("id")))
        entries = []
        aliases = iter_hero_alias_pairs()
        for url, owners in by_icon.items():
            if len({row[0] for row in owners}) != 1:
                continue
            hero, title, perk_id = owners[0]
            entries.append({"name": hero, "icon": url, "id": perk_id,
                            "perk_name": title,
                            "answer_aliases": list(dict.fromkeys([hero] + [a for a, canonical in aliases if canonical == hero]))})
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="威能题库暂无可用图标，请更新资源配置。", status_code=503)
        return self.random.choice(entries)

    async def resolve_media_path(self, entry):
        url = entry["icon"]
        directory = Path(tempfile.gettempdir()) / "overstats-map-guess"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (hashlib.sha256(url.encode()).hexdigest() + ".img")
        if target.exists():
            return target
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(response.content)
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
