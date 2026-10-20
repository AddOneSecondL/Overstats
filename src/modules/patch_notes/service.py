from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Dict, Mapping, Optional

from ..errors import ModuleError
from .render import RenderedImage, RENDER_VERSION, build_reader, page_assets, render_patch_fallback, render_patch_notes
from .requests import (
    PATCH_TRANSLATION_CACHE_VERSION, PatchNotesRequests, build_patch_cache_key,
    build_sources_summary, build_summary_text, choose_source,
    deserialize_patch_candidate, normalize_patch_kind, serialize_patch_candidate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "cache" / "patch_notes"
PATCH_NOTES_UNAVAILABLE_MESSAGE = "OW 补丁说明暂时不可用。"


@dataclass(frozen=True)
class PatchNotesOutput:
    requested_kind: str
    selected_kind: str
    source: str
    source_name: str
    translated: bool
    summary: str
    selected: Dict[str, Any]
    sources: Dict[str, Dict[str, str]]
    image: Optional[RenderedImage] = None
    reader: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "ok": True, "requested_kind": self.requested_kind,
            "selected_kind": self.selected_kind, "source": self.source,
            "source_name": self.source_name, "translated": self.translated,
            "summary": self.summary, "selected": serialize_patch_candidate(self.selected),
            "sources": self.sources, "reader": self.reader,
        }


class PatchNotesModule:
    def __init__(self, requests=None, *, cache_root=None, time_provider=None,
                 date_provider=None, renderer=None, fallback_renderer=None):
        self.requests = requests or PatchNotesRequests()
        self.cache_root = Path(cache_root or DEFAULT_CACHE_ROOT)
        self.time_provider = time_provider or time.time
        self.date_provider = date_provider or dt.date.today
        self.renderer = renderer or render_patch_notes
        self.fallback_renderer = fallback_renderer or render_patch_fallback
        self.asset_dir = self.cache_root / "images"
        self._latest = {}
        self._inflight = {}
        self._render_tasks = {}
        self._render_limit = asyncio.Semaphore(2)

    def _snapshot_path(self, patch_id):
        if not isinstance(patch_id, str) or not re.fullmatch(r"[0-9a-f]{64}", patch_id):
            raise ModuleError(error="invalid_patch_id", message="patch_id 格式不正确。", status_code=400)
        return self.cache_root / "snapshots" / f"{patch_id}.json"

    def _read_snapshot(self, patch_id):
        path = self._snapshot_path(patch_id)
        try:
            value = json.loads(path.read_text("utf-8"))
            if value.get("cache_version") != PATCH_TRANSLATION_CACHE_VERSION:
                return None
            value["candidate"] = deserialize_patch_candidate(value["candidate"])
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def _fetch_snapshot(self, kind):
        cn, en = await self.requests.scan_sources(now_date=self.date_provider(), requested_kind=kind)
        source = choose_source(cn, en, slot_key=kind)
        if source is None:
            raise ModuleError(error="patch_notes_unavailable", message=PATCH_NOTES_UNAVAILABLE_MESSAGE, status_code=502)
        original = dict((cn if source == "cn" else en)[kind])
        patch_id = build_patch_cache_key(original)
        saved = self._read_snapshot(patch_id)
        if saved and (source != "en" or saved.get("translated") or self.time_provider() - saved.get("saved_at", 0) < 120):
            snapshot = saved
        else:
            candidate, translated = original, False
            if source == "en":
                try:
                    candidate, translated = await self.requests.translate_patch_candidate(original)
                except Exception as exc:
                    print(f"[overstats] patch_notes translation failed: {type(exc).__name__}")
            snapshot = {
                "cache_version": PATCH_TRANSLATION_CACHE_VERSION,
                "candidate": serialize_patch_candidate(candidate), "translated": translated,
                "patch_id": patch_id, "saved_at": self.time_provider(),
            }
        snapshot = dict(snapshot, sources=build_sources_summary(cn, en),
                        summary=build_summary_text(cn, en, original), selected_kind=kind)
        self._write_json_atomic(self._snapshot_path(patch_id), dict(snapshot, candidate=serialize_patch_candidate(snapshot["candidate"])))
        self._latest[kind] = (self.time_provider(), patch_id)
        return snapshot

    async def _resolve_snapshot(self, kind, patch_id):
        if patch_id:
            snapshot = self._read_snapshot(patch_id)
            if snapshot is None:
                raise ModuleError(error="patch_snapshot_not_found", message="此补丁快照不存在，请重新查询总览。", status_code=404)
            return snapshot
        cached = self._latest.get(kind)
        if cached and self.time_provider() - cached[0] < 120:
            snapshot = self._read_snapshot(cached[1])
            if snapshot:
                return snapshot
        task = self._inflight.get(kind)
        if task is None:
            task = asyncio.create_task(self._fetch_snapshot(kind))
            self._inflight[kind] = task
            task.add_done_callback(lambda done: self._inflight.pop(kind, None))
        return await asyncio.shield(task)

    async def query_patch_notes(self, *, patch_kind=None, render=False, view="auto", section="", hero="", page=1, patch_id=""):
        try:
            kind = normalize_patch_kind(patch_kind)
            if isinstance(page, bool) or not re.fullmatch(r"[1-9][0-9]{0,4}", str(page)):
                raise ValueError("page 必须是大于零的整数。")
            page = int(page)
            if view not in {"auto", "overview", "detail"}:
                raise ValueError("view 必须为 auto、overview 或 detail。")
            for value in (section, hero):
                if not isinstance(value, str) or len(value) > 200:
                    raise ValueError("章节和英雄名称必须为不超过 200 字的文本。")
            if patch_id and not isinstance(patch_id, str):
                raise ValueError("patch_id 必须为文本。")
        except (TypeError, ValueError) as exc:
            raise ModuleError(error="invalid_patch_query", message=str(exc), status_code=400) from exc
        start = time.perf_counter()
        snapshot = await self._resolve_snapshot(kind, patch_id)
        candidate = deserialize_patch_candidate(snapshot["candidate"])
        try:
            # Layout is CPU work; it must not block other API requests.
            async with self._render_limit:
                reader = await asyncio.to_thread(build_reader, candidate, view=view, section=section, hero=hero)
        except LookupError as exc:
            raise ModuleError(error="patch_filter_not_found", message=str(exc), status_code=404) from exc
        except ValueError as exc:
            raise ModuleError(error="patch_layout_failed", message=str(exc), status_code=400) from exc
        if page > reader["page_count"]:
            raise ModuleError(error="patch_page_out_of_range", message=f"此视图共 {reader['page_count']} 页。", status_code=400,
                              details={"page_count": reader["page_count"]})
        stable_id = snapshot["patch_id"]
        base = {"patch_id": stable_id, "view": reader["view"], "section": section, "hero": hero}
        meta = {key: value for key, value in reader.items() if key != "pages"}
        meta.update(patch_id=stable_id, page=page, source_url=candidate.get("url", ""),
                    next_request=dict(base, page=page + 1) if page < reader["page_count"] else None,
                    previous_request=dict(base, page=page - 1) if page > 1 else None,
                    detail_request={"patch_id": stable_id, "view": "detail", "page": 1},
                    overview_request={"patch_id": stable_id, "view": "overview", "page": 1})
        for part in meta["sections"]:
            part["request"] = {"patch_id": stable_id, "view": "detail", "section": part["id"], "page": 1}
        image = None
        if render:
            selected_page = reader["pages"][page - 1]
            payload = dict(candidate, _reader_page=selected_page, _reader_meta=meta)
            image = await self._render_cached(payload, stable_id)
        print(f"[overstats] patch_reader total={time.perf_counter() - start:.3f}s view={reader['view']} page={page}")
        return PatchNotesOutput(
            requested_kind=kind, selected_kind=snapshot.get("selected_kind", kind),
            source=candidate.get("source", ""), source_name=candidate.get("source_name", ""),
            translated=bool(snapshot.get("translated")), summary=snapshot.get("summary", ""),
            selected=candidate, sources=snapshot.get("sources", {}), image=image, reader=meta,
        )

    async def _render_cached(self, candidate, patch_id):
        encoded = json.dumps({"version": RENDER_VERSION, "patch": patch_id, "candidate": serialize_patch_candidate(candidate)}, ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        path = self.cache_root / "pages" / f"{key}.png"
        try:
            content = path.read_bytes()
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                return RenderedImage(content)
        except OSError:
            pass
        task = self._render_tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._produce_page(candidate, path))
            self._render_tasks[key] = task
            task.add_done_callback(lambda done: self._render_tasks.pop(key, None))
        return await asyncio.shield(task)

    async def _produce_page(self, candidate, path):
        async with self._render_limit:
            t = time.perf_counter()
            assets = await self.requests.cache_images(page_assets(candidate["_reader_page"]), self.asset_dir,
                                                       use_proxy=candidate.get("source") == "en")
            asset_seconds = time.perf_counter() - t
            t = time.perf_counter()
            try:
                image = await asyncio.to_thread(self.renderer, candidate, summary_text="", asset_paths=assets)
            except Exception as exc:
                print(f"[overstats] patch_reader render fallback: {type(exc).__name__}")
                image = await asyncio.to_thread(self.fallback_renderer, candidate, summary_text="")
            # Missing remote images should be retried on the next request, not frozen forever.
            if all(url in assets for url in page_assets(candidate["_reader_page"])):
                self._write_bytes_atomic(path, image.content)
            print(f"[overstats] patch_reader assets={asset_seconds:.3f}s draw_encode={time.perf_counter() - t:.3f}s")
            return image

    def _write_json_atomic(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="patch-notes.", suffix=".json", dir=str(path.parent))
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
        fd, temp_path = tempfile.mkstemp(prefix="patch-notes.", suffix=path.suffix, dir=str(path.parent))
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


patch_notes_module = PatchNotesModule()
