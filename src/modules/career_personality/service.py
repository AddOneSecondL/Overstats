"""Authenticated, read-only lifetime personality reports for the mini-program API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import httpx

from ..career_compare.service import CareerCompareModule
from ..dashen_hero_treemap.mini_program import MODE_TYPES, validate_xcxtoken
from ..dashen_hero_treemap.requests import normalize_treemap_mode
from ..errors import ModuleError


@dataclass(frozen=True)
class CareerPersonalityQuery:
    player: str
    xcxtoken: str = field(default="", repr=False)
    mode: str = "quick"


@dataclass(frozen=True)
class CareerPersonalityOutput:
    data: dict
    image: Any = None

    def to_dict(self):
        return self.data


class CareerPersonalityModule:
    def __init__(self, *, search_module=None, transport=None, reader=None, catalog=None):
        self.transport = transport
        self.reader = reader or CareerCompareModule(search_module=search_module, transport=transport)
        self.catalog = catalog

    async def query_personality(self, query: CareerPersonalityQuery, *, render=False):
        token = validate_xcxtoken(query.xcxtoken)
        target = str(query.player or "").strip()
        if not target:
            raise ModuleError(error="missing_target", message="生涯人格测试需要完整战网名称或九位数字 ID。", status_code=400)
        try:
            mode = normalize_treemap_mode(query.mode, allow_stadium=True)
        except ValueError:
            raise ModuleError(error="invalid_career_personality_mode", message="未知生涯人格模式。", status_code=400) from None
        if mode not in MODE_TYPES:
            raise ModuleError(error="unsupported_career_personality_mode", message="生涯人格支持快速、竞技、角斗快速和角斗竞技。", status_code=400)
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                     transport=self.transport, headers={"Accept-Encoding": "gzip, deflate"}) as client:
            # Shared reader validates identity and only supplements details from the same scope.
            # Do not use query_compare(), whose final output selects only the top three heroes.
            side = await self.reader.fetch_player(client, target, token, mode)
        from .engine import analyze_career
        data = analyze_career(side["heroes_raw"], side["player"], mode,
                              catalog=self.catalog, notes=side.get("notes"))
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()
        data["source_scope"] = {"mode": mode, "season_id": "total", "time_precision": "rounded_hours"}
        image = None
        if render:
            from .render import render_career_personality
            from ..dashen_hero_treemap.render import RenderedImage
            canvas = render_career_personality(data)
            buffer = BytesIO()
            canvas.save(buffer, format="PNG")
            image = RenderedImage(buffer.getvalue())
        return CareerPersonalityOutput(data, image)


career_personality_module = CareerPersonalityModule()
