from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
from typing import Any, Callable, Dict, Optional, Sequence

try:
    from overstats.config import config as app_config
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from config import config as app_config
    from src.modules.errors import ModuleError

from .render import RenderedImage, render_ow_esports
from .requests import OWEsportsRequests, build_ow_esports_sections


OW_ESPORTS_UNAVAILABLE_MESSAGE = "OW esports data is temporarily unavailable."
UNKNOWN_LEAGUE = "未分类赛事"
STATUS_FINISHED = "已结束"


@dataclass(frozen=True)
class OWEsportsOutput:
    generated_at: str
    realtime: bool
    rows: Sequence[Dict[str, Any]]
    sections: Sequence[Dict[str, Any]]
    image: Optional[RenderedImage] = None

    requested_region: str = "china"
    region: str = "china"

    def to_dict(self):
        return {"ok": True, "generated_at": self.generated_at, "realtime": self.realtime,
                "requested_region": self.requested_region, "region": self.region,
                "fallback": self.requested_region != self.region,
                "rows": list(self.rows), "sections": list(self.sections)}


class OWEsportsModule:
    def __init__(
        self,
        requests: Optional[OWEsportsRequests] = None,
        *,
        time_provider: Optional[Callable[[], dt.datetime]] = None,
        renderer: Optional[Callable[..., RenderedImage]] = None,
    ) -> None:
        self.requests = requests or OWEsportsRequests()
        self.time_provider = time_provider or dt.datetime.now
        from .schedule_render import render_schedule
        self.renderer = renderer or render_schedule

    async def query_ow_esports(self, *, render=False, region="china"):
        from .schedule import fetch_schedule, normalize_region
        region = normalize_region(region)
        key = str(getattr(app_config, "OW_ESPORTS_API_KEY", "") or "").strip()
        if not key or key.lower().startswith("replace-with-your-"):
            raise ModuleError(error="ow_esports_not_configured", message="尚未配置赛事 API Key。", status_code=503)
        requested, effective, sections = await fetch_schedule(key, region)
        rows = [row for section in sections for row in section["rows"]]
        now = self.time_provider()
        if now.tzinfo is None:
            now = now.astimezone()
        generated_at = now.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        image = None
        if render:
            assets = await self.requests.fetch_logo_assets(rows)
            image = self.renderer(sections, requested_region=requested, region=effective,
                                  generated_at=generated_at, logo_assets=assets)
        return OWEsportsOutput(generated_at=generated_at, realtime=True, rows=tuple(rows),
                               sections=tuple(sections), image=image, requested_region=requested, region=effective)

    def _format_generated_at(self, value: dt.datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


ow_esports_module = OWEsportsModule()
