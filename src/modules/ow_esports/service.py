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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "generated_at": self.generated_at,
            "realtime": bool(self.realtime),
            "rows": [dict(row) for row in self.rows],
            "sections": [
                {
                    "league_name": str(section.get("league_name") or UNKNOWN_LEAGUE),
                    "status_sections": [
                        {
                            "status": str(status_section.get("status") or STATUS_FINISHED),
                            "rows": [dict(row) for row in list(status_section.get("rows") or [])],
                            "hidden_count": int(status_section.get("hidden_count") or 0),
                        }
                        for status_section in list(section.get("status_sections") or [])
                        if isinstance(status_section, dict)
                    ],
                }
                for section in self.sections
                if isinstance(section, dict)
            ],
        }


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
        self.renderer = renderer or render_ow_esports

    async def query_ow_esports(self, *, render: bool = False) -> OWEsportsOutput:
        configured_api_key = str(getattr(app_config, "OW_ESPORTS_API_KEY", "") or "").strip()
        if not configured_api_key or configured_api_key.lower().startswith("replace-with-your-"):
            raise ModuleError(
                error="ow_esports_not_configured",
                message="OW esports API key is not configured.",
                status_code=503,
                hint="Set OW_ESPORTS_API_KEY in overstats/config/config.py.",
            )

        try:
            rows = await self.requests.fetch_rows()
        except ValueError as exc:
            raise ModuleError(
                error="ow_esports_invalid_payload",
                message=f"OW esports payload is not recognizable: {exc}",
                status_code=502,
            ) from exc
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(
                error="ow_esports_unavailable",
                message=OW_ESPORTS_UNAVAILABLE_MESSAGE,
                status_code=502,
                details={"exception": type(exc).__name__, "message": str(exc)},
            ) from exc

        sections = build_ow_esports_sections(rows)
        generated_at = self._format_generated_at(self.time_provider())
        output = OWEsportsOutput(
            generated_at=generated_at,
            realtime=True,
            rows=tuple(rows),
            sections=tuple(sections),
        )
        if not render:
            return output

        try:
            logo_assets = await self.requests.fetch_logo_assets(rows)
            image = self.renderer(rows, sections=sections, generated_at=generated_at, logo_assets=logo_assets)
        except RuntimeError as exc:
            raise ModuleError(
                error="render_dependency_missing",
                message=str(exc),
                status_code=500,
                hint="Install Pillow in the runtime environment to enable OW esports image rendering.",
            ) from exc
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(
                error="ow_esports_render_failed",
                message=f"OW esports image generation failed: {type(exc).__name__}: {exc}",
                status_code=500,
            ) from exc

        return OWEsportsOutput(
            generated_at=generated_at,
            realtime=True,
            rows=tuple(rows),
            sections=tuple(sections),
            image=image,
        )

    def _format_generated_at(self, value: dt.datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


ow_esports_module = OWEsportsModule()
