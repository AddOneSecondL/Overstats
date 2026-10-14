from __future__ import annotations

import hashlib
from pathlib import Path
import random
import tempfile

import httpx

from ..query_tool import read_query_tool
from ..errors import ModuleError


class OWGuessCatalog:
    """Internal questions are derived directly from the resource configuration."""

    def __init__(self, *, random_source=None):
        self.random = random_source or random.Random()

    def pick_question(self):
        payload = read_query_tool(default={})
        entries = {}
        for item in payload.get("mapList", []):
            name = str(item.get("name") or "").strip()
            url = str(item.get("icon") or "").strip()
            if name and url.startswith("https://"):
                entries[(name, url)] = item
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
