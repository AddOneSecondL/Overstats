from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Dict, Optional, Sequence

try:
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.modules.errors import ModuleError

from .render import RenderedImage, render_ow_shop
from .requests import OWShopRequests, OWShopSection, SHOP_SECTION_SOURCES


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "cache" / "ow_shop"
CACHE_TTL_SECONDS = 15 * 60
OW_SHOP_UNAVAILABLE_MESSAGE = "OW 商店数据暂时不可用。"


@dataclass(frozen=True)
class OWShopOutput:
    generated_at: str
    cache_ttl_seconds: int
    sections: Sequence[OWShopSection]
    image: Optional[RenderedImage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "generated_at": self.generated_at,
            "cache_ttl_seconds": int(self.cache_ttl_seconds),
            "sections": [section.to_dict() for section in self.sections],
        }


class OWShopModule:
    def __init__(
        self,
        requests: Optional[OWShopRequests] = None,
        *,
        cache_root: Path | str | None = None,
        time_provider: Optional[Callable[[], float]] = None,
        renderer: Optional[Callable[..., RenderedImage]] = None,
    ) -> None:
        self.requests = requests or OWShopRequests()
        self.cache_root = Path(cache_root or DEFAULT_CACHE_ROOT)
        self.time_provider = time_provider or time.time
        self.renderer = renderer or render_ow_shop
        self.data_cache_path = self.cache_root / "shop_data.json"
        self.image_cache_path = self.cache_root / "shop_image.png"
        self.image_asset_dir = self.cache_root / "images"

    async def query_shop(self, *, render: bool = False) -> OWShopOutput:
        snapshot = self._load_cached_snapshot()
        if snapshot is None:
            snapshot = await self._refresh_snapshot()
            self._write_json_atomic(self.data_cache_path, snapshot)
            self._delete_stale_render_cache()

        output = OWShopOutput(
            generated_at=str(snapshot.get("generated_at") or self._format_generated_at(self.time_provider())),
            cache_ttl_seconds=int(snapshot.get("cache_ttl_seconds") or CACHE_TTL_SECONDS),
            sections=tuple(
                OWShopSection.from_dict(payload)
                for payload in list(snapshot.get("sections") or [])
                if isinstance(payload, dict)
            ),
        )

        if not render:
            return output

        cached_image = self._load_cached_render()
        if cached_image is not None:
            return OWShopOutput(
                generated_at=output.generated_at,
                cache_ttl_seconds=output.cache_ttl_seconds,
                sections=output.sections,
                image=cached_image,
            )

        rendered = await self._render_sections(output.sections, output.generated_at)
        self._write_bytes_atomic(self.image_cache_path, rendered.content)
        return OWShopOutput(
            generated_at=output.generated_at,
            cache_ttl_seconds=output.cache_ttl_seconds,
            sections=output.sections,
            image=rendered,
        )

    async def _refresh_snapshot(self) -> Dict[str, Any]:
        results = await asyncio.gather(
            *(self.requests.fetch_section(source) for source in SHOP_SECTION_SOURCES),
            return_exceptions=True,
        )
        sections = []
        failures = {}
        for source, result in zip(SHOP_SECTION_SOURCES, results):
            if isinstance(result, Exception):
                failures[source.title] = f"{type(result).__name__}: {result}"
                print(f"[overstats] ow_shop fetch failed: section={source.title} error={type(result).__name__}: {result}")
                continue
            if result.items:
                sections.append(result)

        if not sections:
            raise ModuleError(
                error="ow_shop_unavailable",
                message=OW_SHOP_UNAVAILABLE_MESSAGE,
                status_code=502,
                details={"failures": failures},
            )

        timestamp = float(self.time_provider())
        return {
            "generated_at": self._format_generated_at(timestamp),
            "cached_at": timestamp,
            "cache_ttl_seconds": CACHE_TTL_SECONDS,
            "sections": [section.to_dict() for section in sections],
        }

    async def _render_sections(self, sections: Sequence[OWShopSection], generated_at: str) -> RenderedImage:
        image_urls = [
            item.image_url
            for section in sections
            for item in section.items
            if str(item.image_url or "").strip()
        ]
        asset_paths = await self.requests.cache_images(image_urls, self.image_asset_dir)
        try:
            return self.renderer(sections=sections, generated_at=generated_at, asset_paths=asset_paths)
        except RuntimeError as exc:
            raise ModuleError(
                error="render_dependency_missing",
                message=str(exc),
                status_code=500,
                hint="Install Pillow in the runtime environment to enable image rendering.",
            ) from exc

    def _load_cached_snapshot(self) -> Optional[Dict[str, Any]]:
        if not self.data_cache_path.exists():
            return None
        try:
            payload = json.loads(self.data_cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[overstats] failed to read ow_shop cache {self.data_cache_path}: {exc}")
            return None
        if not isinstance(payload, dict):
            return None
        cached_at = float(payload.get("cached_at") or 0)
        ttl = max(1, int(payload.get("cache_ttl_seconds") or CACHE_TTL_SECONDS))
        if float(self.time_provider()) - cached_at >= ttl:
            return None
        return payload

    def _load_cached_render(self) -> Optional[RenderedImage]:
        if not self.image_cache_path.exists():
            return None
        try:
            return RenderedImage(content=self.image_cache_path.read_bytes())
        except Exception as exc:
            print(f"[overstats] failed to read ow_shop image cache {self.image_cache_path}: {exc}")
            return None

    def _delete_stale_render_cache(self) -> None:
        try:
            self.image_cache_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="ow-shop.", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
            Path(temp_path).replace(path)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _write_bytes_atomic(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="ow-shop.", suffix=path.suffix, dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
            Path(temp_path).replace(path)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _format_generated_at(self, timestamp: float) -> str:
        return dt.datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M:%S")


ow_shop_module = OWShopModule()
