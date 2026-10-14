from __future__ import annotations

import hashlib
from pathlib import Path
import random
import re
import tempfile

import httpx

from ..query_tool import read_query_tool
from ..errors import ModuleError


EXCLUDED_MAP_MARKERS = (
    "地图工坊", "英雄精通", "vppgreenroom", "怪鼠复仇", "教学模式",
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
        for item in payload.get("mapList", []):
            if not isinstance(item, dict) or is_excluded_map(item):
                continue
            original_name = str(item.get("name") or "").strip()
            name = simplify_map_name(original_name)
            url = str(item.get("icon") or "").strip()
            if name and url.startswith("https://"):
                entries[(name, url)] = {**item, "name": name, "answer_aliases": list(dict.fromkeys((name, original_name)))}
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="地图题库暂无可用图片，请更新资源配置。", status_code=503)
        return self.random.choice(list(entries.values()))

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
