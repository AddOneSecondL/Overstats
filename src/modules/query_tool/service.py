from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

import httpx

try:
    from overstats.src.modules.season_config import normalize_query_tool_config
except ModuleNotFoundError:
    from src.modules.season_config import normalize_query_tool_config

from .requests import MANUAL_KEYS, REMOTE_HEADERS, QueryToolRequests


PROJECT_ROOT = Path(__file__).resolve().parents[4]
QUERY_TOOL_PATH = PROJECT_ROOT / "overstats" / "res" / "query_tool.json"
QUERY_TOOL_ASSET_DIR = PROJECT_ROOT / "overstats" / "res" / "query_tool_assets"
QUERY_TOOL_ASSET_MANIFEST_PATH = QUERY_TOOL_ASSET_DIR / "assets_manifest.json"
IMAGE_URL_KEYS = ("icon", "image", "avatar", "portrait", "background", "smallIconUrl", "ddHeroIcon")
ASSET_SECTION_DIRS = {
    "mapList": "maps",
    "heroList": "heroes",
    "heroPerkList": "perk",
    "modTrait": "perk",
}
DEFAULT_ASSET_DOWNLOAD_WORKERS = 12

_CONFIG_LOCK = threading.Lock()
_CONFIG_UPDATED = False
_CONFIG_CACHE: Dict[str, Any] | None = None


def _run_async_sync(awaitable_factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable_factory())

    result: Dict[str, Any] = {}
    error: Dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable_factory())
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=runner, name="query-tool-refresh", daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def get_query_tool_path() -> Path:
    return QUERY_TOOL_PATH


def get_query_tool_asset_dir() -> Path:
    return QUERY_TOOL_ASSET_DIR


def get_asset_download_workers() -> int:
    raw_value = os.getenv("OVERSTATS_QUERY_TOOL_ASSET_WORKERS", str(DEFAULT_ASSET_DOWNLOAD_WORKERS))
    try:
        return max(1, int(raw_value))
    except ValueError:
        print(
            "[overstats] invalid OVERSTATS_QUERY_TOOL_ASSET_WORKERS="
            f"{raw_value!r}, fallback to {DEFAULT_ASSET_DOWNLOAD_WORKERS}"
        )
        return DEFAULT_ASSET_DOWNLOAD_WORKERS


def read_query_tool(default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if default is None:
        default = {}
    if not QUERY_TOOL_PATH.exists():
        return normalize_query_tool_config(default)
    try:
        data = json.loads(QUERY_TOOL_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return normalize_query_tool_config(data)
        return normalize_query_tool_config(default)
    except Exception as exc:
        print(f"[overstats] failed to read query tool config {QUERY_TOOL_PATH}: {exc}")
    return normalize_query_tool_config(default)


def write_query_tool(payload: Dict[str, Any]) -> None:
    QUERY_TOOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix="query_tool.",
        suffix=".tmp",
        dir=str(QUERY_TOOL_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        Path(temp_path).replace(QUERY_TOOL_PATH)
    except Exception:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def get_cached_asset_path(url: str, category: str = "misc") -> Optional[Path]:
    url = _normalize_url(url)
    if not url:
        return None
    folder = QUERY_TOOL_ASSET_DIR / category
    stem = _asset_hash(url)
    for path in folder.glob(f"{stem}.*"):
        if path.is_file():
            return path
    return None


def cache_query_tool_asset_bytes(url: str, data: bytes, category: str = "misc") -> Optional[Path]:
    normalized = _normalize_url(url)
    if not normalized or not data:
        return None

    existing_path = get_cached_asset_path(normalized, category)
    if existing_path is not None and existing_path.exists():
        return existing_path

    folder = QUERY_TOOL_ASSET_DIR / (category or "misc")
    folder.mkdir(parents=True, exist_ok=True)
    extension = _guess_asset_extension(normalized, "")
    target_path = folder / f"{_asset_hash(normalized)}{extension}"
    fd, temp_path = tempfile.mkstemp(prefix=f"{target_path.stem}.", suffix=".tmp", dir=str(folder))
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        Path(temp_path).replace(target_path)
        return target_path
    except Exception:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
        return None


def ensure_query_tool_assets(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if os.environ.get("OVERSTATS_SCF_FROZEN_QUERY_TOOL") == "1":
        return {"checked": 0, "cached": 0, "downloaded": 0, "failed": 0,
                "asset_dir": str(QUERY_TOOL_ASSET_DIR), "skipped": True}
    config = config or read_query_tool(default={})
    assets = list(_iter_unique_asset_urls(config))
    QUERY_TOOL_ASSET_DIR.mkdir(parents=True, exist_ok=True)

    configured_workers = get_asset_download_workers()
    manifest = _read_asset_manifest()
    checked = 0
    cached = 0
    downloaded = 0
    failed = 0
    total = len(assets)
    if total:
        print(f"[overstats] query_tool asset check started: total={total} workers={configured_workers}")
        _print_asset_progress(0, total, cached, downloaded, failed, "start")

    pending = []
    for item in assets:
        url = item["url"]
        category = item["category"]
        local_path = get_cached_asset_path(url, category)
        if local_path and local_path.exists():
            checked += 1
            cached += 1
            manifest[url] = {
                "category": category,
                "path": str(local_path.relative_to(QUERY_TOOL_ASSET_DIR)),
            }
            _print_asset_progress(checked, total, cached, downloaded, failed, "cached")
            continue
        pending.append(item)

    if pending:
        workers = max(1, min(configured_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="query-tool-asset") as executor:
            future_map = {
                executor.submit(_download_asset_job, item["url"], item["category"]): item
                for item in pending
            }
            for future in as_completed(future_map):
                item = future_map[future]
                url = item["url"]
                category = item["category"]
                checked += 1
                try:
                    local_path = future.result()
                    downloaded += 1
                    status = "downloaded"
                    manifest[url] = {
                        "category": category,
                        "path": str(local_path.relative_to(QUERY_TOOL_ASSET_DIR)),
                    }
                except Exception as exc:
                    failed += 1
                    status = "failed"
                    manifest[url] = {
                        "category": category,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    print()
                    print(f"[overstats] failed to download query_tool asset {url}: {exc}")
                _print_asset_progress(checked, total, cached, downloaded, failed, status)

    _write_asset_manifest(manifest)
    if total:
        print()
        print(
            "[overstats] query_tool asset check finished: "
            f"checked={checked} cached={cached} downloaded={downloaded} failed={failed}"
        )
    return {
        "checked": checked,
        "cached": cached,
        "downloaded": downloaded,
        "failed": failed,
        "asset_dir": str(QUERY_TOOL_ASSET_DIR),
    }


def _download_asset_job(url: str, category: str) -> Path:
    with httpx.Client(headers=REMOTE_HEADERS, timeout=20.0, follow_redirects=True) as client:
        return _download_asset(client, url, category)


class QueryToolModule:
    def __init__(self, requests: QueryToolRequests | None = None) -> None:
        self.requests = requests or QueryToolRequests()

    def load(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        global _CONFIG_CACHE
        if force_refresh:
            return self.refresh(force=True)
        if _CONFIG_CACHE is not None:
            return _CONFIG_CACHE
        return self.refresh(force=False)

    def refresh(self, *, force: bool = False) -> Dict[str, Any]:
        global _CONFIG_CACHE, _CONFIG_UPDATED
        if os.environ.get("OVERSTATS_SCF_FROZEN_QUERY_TOOL") == "1":
            with _CONFIG_LOCK:
                if _CONFIG_CACHE is None:
                    local_config = read_query_tool(default={})
                    if not local_config:
                        raise RuntimeError("SCF image is missing packaged query_tool.json; rebuild image")
                    _CONFIG_CACHE = normalize_query_tool_config(local_config)
                    _CONFIG_UPDATED = True
                return _CONFIG_CACHE
        if _CONFIG_UPDATED and not force and _CONFIG_CACHE is not None:
            return _CONFIG_CACHE

        with _CONFIG_LOCK:
            if _CONFIG_UPDATED and not force and _CONFIG_CACHE is not None:
                return _CONFIG_CACHE

            local_config = read_query_tool(default={})
            remote_config = _run_async_sync(self.requests.fetch_remote_query_tool)
            merged_config = dict(remote_config)

            for key in MANUAL_KEYS:
                if key in local_config:
                    merged_config[key] = local_config[key]

            merged_config = normalize_query_tool_config(merged_config)

            try:
                write_query_tool(merged_config)
            except Exception as exc:
                print(f"[overstats] failed to write {QUERY_TOOL_PATH}: {exc}")

            _CONFIG_CACHE = merged_config
            _CONFIG_UPDATED = True
            return merged_config

    def ensure_assets(self) -> Dict[str, Any]:
        return ensure_query_tool_assets(self.load(force_refresh=False))


query_tool_module = QueryToolModule()


def load_query_tool(force_refresh: bool = False) -> Dict[str, Any]:
    return query_tool_module.load(force_refresh=force_refresh)


def _iter_asset_urls(config: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    for section, value in (config or {}).items():
        category = ASSET_SECTION_DIRS.get(section, _category_from_section(section))
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield from _iter_item_urls(item, category)
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, dict):
                    yield from _iter_item_urls(item, category)
                elif isinstance(item, list):
                    for nested_item in item:
                        if isinstance(nested_item, dict):
                            yield from _iter_item_urls(nested_item, category)


def _iter_unique_asset_urls(config: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    seen = set()
    for item in _iter_asset_urls(config):
        key = (item["url"], item["category"])
        if key in seen:
            continue
        seen.add(key)
        yield item


def _iter_item_urls(item: Dict[str, Any], category: str) -> Iterable[Dict[str, str]]:
    for key in IMAGE_URL_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            url = _normalize_url(value)
            if url.startswith(("http://", "https://")):
                yield {"url": url, "category": category}


def _download_asset(client: httpx.Client, url: str, category: str) -> Path:
    response = client.get(url)
    response.raise_for_status()
    content = response.content
    extension = _guess_asset_extension(url, response.headers.get("Content-Type", ""))
    folder = QUERY_TOOL_ASSET_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_asset_hash(url)}{extension}"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_bytes(content)
    temp_path.replace(path)
    return path


def _asset_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _normalize_url(url: str) -> str:
    return str(url or "").strip()


def _category_from_section(section: str) -> str:
    name = str(section or "misc")
    if name.endswith("List"):
        name = name[:-4]
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "misc"


def _guess_asset_extension(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return ext
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if guessed in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return guessed
    return ".img"


def _read_asset_manifest() -> Dict[str, Any]:
    if not QUERY_TOOL_ASSET_MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(QUERY_TOOL_ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_asset_manifest(manifest: Dict[str, Any]) -> None:
    QUERY_TOOL_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    QUERY_TOOL_ASSET_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _print_asset_progress(
    current: int,
    total: int,
    cached: int,
    downloaded: int,
    failed: int,
    status: str,
) -> None:
    if total <= 0:
        return
    width = 28
    ratio = min(max(current / total, 0), 1)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    percent = ratio * 100
    print(
        "\r"
        f"[overstats] assets [{bar}] {current}/{total} {percent:5.1f}% "
        f"cached={cached} downloaded={downloaded} failed={failed} last={status}",
        end="",
        flush=True,
    )
