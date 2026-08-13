import asyncio
import base64
import datetime
import hashlib
import json
import os
import random
import re
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from functools import partial
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ....constants.backgrounds import build_random_map_background
from ....constants.ranks import get_rank_score, normalize_raw_rank_bucket, raw_rank_score_to_strength

from .dashen import (
    dashen_api_client,
    ds_get_single_fight_match,
    ds_get_single_match,
    get_icon,
    get_fight_match_list,
    match_rating_recent,
    ranking_dist2,
    season,
)
from .db import IDPoolDB
from .ow_config import load_ow_config
from .perf_log import append_perf_log
from .render_gate import get_global_render_limit, get_global_render_semaphore
from .stat_reference import get_cached_statmap_summary as _shared_get_cached_statmap_summary

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.risk_status import (
        draw_risk_status_badge,
        measure_risk_status_badge,
        parse_risk_status,
    )
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.risk_status import (
        draw_risk_status_badge,
        measure_risk_status_badge,
        parse_risk_status,
    )


def _read_env_int(name, default):
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return int(default)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESOURCE_DIR = PROJECT_ROOT / "res"
QUERY_TOOL_ASSET_DIR = RESOURCE_DIR / "query_tool_assets"
SUMMARY_EXTRA_ASSET_DIR = QUERY_TOOL_ASSET_DIR / "extra"
CONFIG_PATH = os.path.join(PROJECT_ROOT, "res", "query_tool.json")
RANK_DISTRIBUTION_CACHE_DIR = os.path.join(MODULE_DIR, "cache", "rank_distribution_daily")
SEASON_SUMMARY_URL_LIMIT = 6
SEASON_SUMMARY_RENDER_CONCURRENCY = get_global_render_limit()
SEASON_SUMMARY_RENDER_LOG_WAIT_MS = 200
_SEASON_SUMMARY_URL_SEMAPHORES = {}
_SEASON_SUMMARY_COMMAND_BUSY = False
_SUMMARY_IMAGE_CACHE = OrderedDict()
_SUMMARY_IMAGE_CACHE_BYTES_BY_URL = {}
_SUMMARY_COVER_CACHE = OrderedDict()
_SUMMARY_COVER_CACHE_BYTES_BY_KEY = {}
_SUMMARY_FONT_CACHE = {}
_SUMMARY_MASK_CACHE = {}
_SUMMARY_STATMAP_REFERENCE_CACHE = OrderedDict()
_SUMMARY_DETAIL_CACHE = OrderedDict()
SUMMARY_PRELOAD_IMAGES_ENABLED = os.getenv("OVERSTATS_PRELOAD_IMAGES", "1").strip().lower() not in {"0", "false", "no", "off"}
SUMMARY_PRELOAD_IMAGE_BUDGET_MB = max(64, _read_env_int("OVERSTATS_SUMMARY_PRELOAD_IMAGE_MB", 128))
SUMMARY_PRELOAD_IMAGE_BUDGET_BYTES = SUMMARY_PRELOAD_IMAGE_BUDGET_MB * 1024 * 1024
SUMMARY_IMAGE_CACHE_MAX_BYTES = SUMMARY_PRELOAD_IMAGE_BUDGET_BYTES
SUMMARY_COVER_CACHE_BUDGET_MB = max(32, _read_env_int("OVERSTATS_SUMMARY_COVER_CACHE_MB", 256))
SUMMARY_COVER_CACHE_MAX_BYTES = SUMMARY_COVER_CACHE_BUDGET_MB * 1024 * 1024
SUMMARY_STATMAP_REFERENCE_CACHE_MAX = max(128, _read_env_int("OVERSTATS_SUMMARY_STATMAP_REF_CACHE_MAX", 2048))
SUMMARY_DETAIL_CACHE_TTL = max(60, _read_env_int("OVERSTATS_SUMMARY_DETAIL_CACHE_TTL", 1800))
SUMMARY_DETAIL_CACHE_MAX = max(128, _read_env_int("OVERSTATS_SUMMARY_DETAIL_CACHE_MAX", 2048))
SUMMARY_IMAGE_JPEG_QUALITY = max(65, min(95, _read_env_int("OVERSTATS_SUMMARY_JPEG_QUALITY", 82)))
_SUMMARY_PRELOAD_IMAGE_BYTES = 0
_SUMMARY_COVER_CACHE_BYTES = 0
_SUMMARY_PRELOAD_IMAGE_COUNT = 0
_SUMMARY_PRELOAD_THREAD_STARTED = False
_SUMMARY_PRELOAD_LOCK = threading.Lock()
_GROUP_TITLE_DB = IDPoolDB()
MAX_GROUP_TITLES_PER_PLAYER = 3
GROUP_TITLE_COLOR_RE = re.compile(r"^(?:背景颜色)?#([0-9A-Fa-f]{6})$")

OW_CONFIG = load_ow_config()


async def _ensure_resolved_target_risk_status(resolved_target):
    if not isinstance(resolved_target, dict):
        return resolved_target

    existing = parse_risk_status(resolved_target.get("risk_status"))
    if existing is None and "riskStatus" in resolved_target:
        existing = parse_risk_status({"riskStatus": resolved_target.get("riskStatus")})
    if existing is not None:
        resolved_target["risk_status"] = existing.to_dict()
        return resolved_target

    customer_token = str(resolved_target.get("customer_token") or "").strip()
    if not customer_token:
        return resolved_target
    try:
        payload = await dashen_api_client.query_card(customer_token)
    except Exception:
        return resolved_target

    risk_status = parse_risk_status(payload)
    resolved_target["risk_status"] = risk_status.to_dict() if risk_status else None
    return resolved_target


def _summary_png_b64(image):
    out = BytesIO()
    try:
        image.convert("RGB").save(
            out,
            format="JPEG",
            quality=SUMMARY_IMAGE_JPEG_QUALITY,
            optimize=False,
            progressive=False,
            subsampling=1,
        )
    except OSError:
        image.convert("RGB").save(
            out,
            format="JPEG",
            quality=max(65, SUMMARY_IMAGE_JPEG_QUALITY - 6),
            optimize=False,
            progressive=False,
            subsampling=1,
        )
    return "base64://" + base64.b64encode(out.getvalue()).decode("utf-8")


def _base64_payload_kb(image_b64):
    try:
        payload = str(image_b64 or "").replace("base64://", "", 1)
        return int(len(payload) * 3 / 4 / 1024)
    except Exception:
        return 0


def _get_summary_render_semaphore():
    return get_global_render_semaphore()


async def _run_summary_render_async(label, awaitable_factory):
    loop = asyncio.get_running_loop()
    queued_at = loop.time()
    async with _get_summary_render_semaphore():
        wait_ms = int((loop.time() - queued_at) * 1000)
        if wait_ms >= SEASON_SUMMARY_RENDER_LOG_WAIT_MS:
            print(
                f"[season-summary-render] step={label} wait_ms={wait_ms} "
                f"limit={SEASON_SUMMARY_RENDER_CONCURRENCY}"
            )
        return await awaitable_factory()


async def _run_summary_render_sync(label, func, *args):
    loop = asyncio.get_running_loop()
    queued_at = loop.time()
    async with _get_summary_render_semaphore():
        wait_ms = int((loop.time() - queued_at) * 1000)
        if wait_ms >= SEASON_SUMMARY_RENDER_LOG_WAIT_MS:
            print(
                f"[season-summary-render] step={label} wait_ms={wait_ms} "
                f"limit={SEASON_SUMMARY_RENDER_CONCURRENCY}"
            )
        return await loop.run_in_executor(None, partial(func, *args))


async def _summary_png_b64_async(image, label):
    return await _run_summary_render_sync(f"{label}:encode", _summary_png_b64, image)


def _format_summary_image_message(image_b64, image_message_formatter=None):
    if callable(image_message_formatter):
        return image_message_formatter(image_b64)
    return image_b64


async def _send_summary_image(bot, ev, image_b64, image_message_formatter=None):
    await bot.send(
        ev,
        _format_summary_image_message(
            image_b64,
            image_message_formatter=image_message_formatter,
        ),
    )

HERO_BY_GUID = {
    str(item.get("heroGuid")): item
    for item in OW_CONFIG.get("heroList", [])
    if item.get("heroGuid")
}
HERO_LOOKUP = {}
HERO_ALIASES_BY_GUID = defaultdict(list)
for item in OW_CONFIG.get("heroList", []):
    alias_keys = []
    for key in ("heroGuid", "id", "guid"):
        value = item.get(key)
        if not value:
            continue
        value = str(value)
        HERO_LOOKUP[value] = item
        alias_keys.append(value)
    canonical_guid = str(item.get("heroGuid") or (alias_keys[0] if alias_keys else ""))
    if canonical_guid:
        deduped_aliases = []
        for alias in [canonical_guid, *alias_keys]:
            if alias and alias not in deduped_aliases:
                deduped_aliases.append(alias)
        HERO_ALIASES_BY_GUID[canonical_guid] = deduped_aliases
MAP_BY_GUID = {
    str(item.get("guid")): item
    for item in OW_CONFIG.get("mapList", [])
    if item.get("guid")
}
HERO_ATTRS_BY_HERO = defaultdict(dict)
for item in OW_CONFIG.get("heroAttrList", []):
    hero_guid = str(item.get("heroGuid") or "")
    value_guid = str(item.get("valueGuid") or "")
    if hero_guid and value_guid:
        HERO_ATTRS_BY_HERO[hero_guid][value_guid] = item

HERO_AVG_PERCENT_KEYWORDS = ("率", "效率", "占比")
HERO_AVG_PERCENT_TEXTS = {"英雄获胜"}
HERO_AVG_RAW_VALUE_TEXTS = {"英雄获胜", "累计游戏时间", "累积游戏时间"}
HERO_AVG_RAW_VALUE_GUIDS = {"603482350067646497", "603482350067648623"}
HERO_AVG_SKIP_VALUE_GUIDS = {"603482350067646497"}
PERIOD_HIGHLIGHT_EXCLUDED_TEXTS = {"击杀", "助攻", "阵亡", "英雄获胜", "累计游戏时间", "累积游戏时间", "游戏时间"}
PERIOD_HIGHLIGHT_EXCLUDED_GUIDS = {"603482350067646495", "603482350067648392", "603482350067646506", "603482350067646497", "603482350067648623"}
PERIOD_HIGHLIGHT_BAND_COLORS = {
    "above_median": (96, 216, 135),
    "top20": (90, 169, 255),
    "top10": (177, 135, 255),
    "top5": (255, 176, 74),
    "top2": (255, 220, 120),
}
GAME_TIME_GUID = "603482350067646497"
ATTR_TEXT_BY_GUID = {
    str(item.get("valueGuid")): item.get("valueText", str(item.get("valueGuid")))
    for item in OW_CONFIG.get("heroAttrList", [])
    if item.get("valueGuid")
}
QUICK_DIST_BUCKET_START = 500
QUICK_DIST_BUCKET_END = 4900
QUICK_DIST_BUCKET_STEP = 100
QUICK_DIST_SNAPSHOT_VERSION = 3
QUICK_DIST_RANK_SPANS = (
    (500, 1000, "青铜"),
    (1000, 1500, "白银"),
    (1500, 2000, "黄金"),
    (2000, 2500, "白金"),
    (2500, 3000, "翡翠"),
    (3000, 3500, "钻石"),
    (3500, 4000, "大师"),
    (4000, 4500, "宗师"),
    (4500, 5000, "英杰"),
)


def _extract_match_entries(payload, *preferred_keys):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in preferred_keys or ("matchList", "recentMatchList"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _num(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    return int(_num(value, default))


def _fmt_int(value):
    return f"{int(value):,}"


def _fmt_pct(wins, total):
    if not total:
        return "-"
    return f"{wins / total * 100:.1f}%"


def _fmt_time(seconds):
    seconds = int(seconds or 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _is_hero_avg_percent_stat(value_text):
    value_text = str(value_text or "")
    return value_text in HERO_AVG_PERCENT_TEXTS or any(keyword in value_text for keyword in HERO_AVG_PERCENT_KEYWORDS)


def _is_hero_avg_raw_stat(value_text, value_guid=None):
    return str(value_guid or "") in HERO_AVG_RAW_VALUE_GUIDS or str(value_text or "") in HERO_AVG_RAW_VALUE_TEXTS


def _clamp_percent_value(value):
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _normalize_hero_rank_score(rank_score):
    return normalize_raw_rank_bucket(rank_score)


def _get_hero_avg_percent_guids(stat_guids=None):
    stat_guid_set = {str(guid) for guid in stat_guids} if stat_guids else None
    percent_guids = []
    for hero_attrs in HERO_ATTRS_BY_HERO.values():
        for value_guid, item in hero_attrs.items():
            if stat_guid_set is not None and value_guid not in stat_guid_set:
                continue
            if _is_hero_avg_percent_stat(item.get("valueText")):
                percent_guids.append(value_guid)
    return sorted(set(percent_guids))


def _format_hero_avg_value(value, value_text):
    if value is None:
        return "无数据"
    if _is_hero_avg_percent_stat(value_text):
        return f"{_clamp_percent_value(value):.1%}"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(value) >= 100:
        return _fmt_int(round(value))
    return f"{value:.1f}"


def normalize_dashen_hero_stat_value(value, user_time_sec, value_text=None, value_guid=None):
    if value is None:
        return None
    try:
        value = float(value)
        user_time_sec = float(user_time_sec or 0)
    except (TypeError, ValueError):
        return None
    if _is_hero_avg_percent_stat(value_text):
        return _clamp_percent_value(value)
    if _is_hero_avg_raw_stat(value_text, value_guid):
        return value
    time_coef = user_time_sec / 600
    if time_coef <= 0:
        return None
    return value / time_coef


def _classify_hero_average_band(current_value, ref):
    if current_value is None or not ref:
        return "unknown"
    if ref.get("top2") is not None and current_value >= ref["top2"]:
        return "top2"
    if ref.get("top5") is not None and current_value >= ref["top5"]:
        return "top5"
    if ref.get("top10") is not None and current_value >= ref["top10"]:
        return "top10"
    if ref.get("top20") is not None and current_value >= ref["top20"]:
        return "top20"
    if ref.get("avg") is not None and current_value > ref["avg"]:
        return "above_median"
    return "below_median"


def _mode_label(match):
    raw = str(match.get("gameMode") or match.get("_seasonSummaryMode") or "").lower()
    if "sportfight" in raw:
        return "Comp Fight"
    if "quickfight" in raw or "leisurefight" in raw:
        return "Quick Fight"
    if "sport" in raw:
        return "Competitive"
    return "Quick Play"


def _is_comp(match):
    return "sport" in str(match.get("gameMode") or match.get("_seasonSummaryMode") or "").lower()


def _is_fight(match):
    return "fight" in str(match.get("gameMode") or match.get("_seasonSummaryMode") or "").lower()


def _detail_root(detail):
    if not isinstance(detail, dict):
        return {}
    total_count = detail.get("totalCount")
    if isinstance(total_count, dict):
        root = dict(total_count)
        if "nameMap" in detail and "nameMap" not in root:
            root["nameMap"] = detail.get("nameMap")
        return root
    return detail


def _short_name(name, max_len=12):
    name = str(name or "Unknown")
    if len(name) <= max_len:
        return name
    return name[: max_len - 3] + "..."


def _hero_name(guid):
    hero = HERO_LOOKUP.get(str(guid), {}) or HERO_BY_GUID.get(str(guid), {})
    return hero.get("name") or "Unknown Hero"


def _map_name(guid):
    return MAP_BY_GUID.get(str(guid), {}).get("name") or "Unknown Map"


def _role_label(hero_guid):
    hero = HERO_LOOKUP.get(str(hero_guid), {}) or HERO_BY_GUID.get(str(hero_guid), {})
    role = str(hero.get("roleType") or "").lower()
    if role == "tank":
        return "Tank"
    if role in ("dps", "damage", "offense"):
        return "Damage"
    if role in ("healer", "support"):
        return "Support"
    return "Unknown"


def _estimate_summary_image_bytes(image):
    try:
        channels = max(1, len(image.getbands()))
    except Exception:
        channels = 4
    return max(1, int(image.width) * int(image.height) * channels)


def _get_cached_summary_image_copy(url):
    cached = _SUMMARY_IMAGE_CACHE.get(url)
    if cached is None:
        return None
    try:
        _SUMMARY_IMAGE_CACHE.move_to_end(url)
    except Exception:
        pass
    return cached.copy()


def _has_cached_summary_image(url):
    return str(url or "").strip() in _SUMMARY_IMAGE_CACHE


def _put_summary_image_cache(url, image):
    global _SUMMARY_PRELOAD_IMAGE_BYTES
    if not url or image is None:
        return False
    estimated_bytes = _estimate_summary_image_bytes(image)
    if estimated_bytes > SUMMARY_IMAGE_CACHE_MAX_BYTES:
        return False

    with _SUMMARY_PRELOAD_LOCK:
        old_image = _SUMMARY_IMAGE_CACHE.pop(url, None)
        if old_image is not None:
            _SUMMARY_PRELOAD_IMAGE_BYTES -= int(_SUMMARY_IMAGE_CACHE_BYTES_BY_URL.pop(url, 0))
        _SUMMARY_IMAGE_CACHE[url] = image.copy()
        _SUMMARY_IMAGE_CACHE_BYTES_BY_URL[url] = estimated_bytes
        _SUMMARY_PRELOAD_IMAGE_BYTES += estimated_bytes

        while (
            _SUMMARY_PRELOAD_IMAGE_BYTES > SUMMARY_IMAGE_CACHE_MAX_BYTES
            and len(_SUMMARY_IMAGE_CACHE) > 1
        ):
            old_url, _ = _SUMMARY_IMAGE_CACHE.popitem(last=False)
            _SUMMARY_PRELOAD_IMAGE_BYTES -= int(_SUMMARY_IMAGE_CACHE_BYTES_BY_URL.pop(old_url, 0))
    return True


def _get_cached_summary_cover_copy(cache_key):
    cached = _SUMMARY_COVER_CACHE.get(cache_key)
    if cached is None:
        return None
    try:
        _SUMMARY_COVER_CACHE.move_to_end(cache_key)
    except Exception:
        pass
    return cached.copy()


def _put_summary_cover_cache(cache_key, image):
    global _SUMMARY_COVER_CACHE_BYTES
    if image is None:
        return False
    estimated_bytes = _estimate_summary_image_bytes(image)
    if estimated_bytes > SUMMARY_COVER_CACHE_MAX_BYTES:
        return False

    with _SUMMARY_PRELOAD_LOCK:
        old_image = _SUMMARY_COVER_CACHE.pop(cache_key, None)
        if old_image is not None:
            _SUMMARY_COVER_CACHE_BYTES -= int(_SUMMARY_COVER_CACHE_BYTES_BY_KEY.pop(cache_key, 0))
        _SUMMARY_COVER_CACHE[cache_key] = image.copy()
        _SUMMARY_COVER_CACHE_BYTES_BY_KEY[cache_key] = estimated_bytes
        _SUMMARY_COVER_CACHE_BYTES += estimated_bytes

        while (
            _SUMMARY_COVER_CACHE_BYTES > SUMMARY_COVER_CACHE_MAX_BYTES
            and len(_SUMMARY_COVER_CACHE) > 1
        ):
            old_key, _ = _SUMMARY_COVER_CACHE.popitem(last=False)
            _SUMMARY_COVER_CACHE_BYTES -= int(_SUMMARY_COVER_CACHE_BYTES_BY_KEY.pop(old_key, 0))
    return True


async def _prefetch_summary_images(urls):
    deduped_urls = []
    seen = set()
    for url in urls or []:
        url = str(url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if _has_cached_summary_image(url):
            continue
        deduped_urls.append(url)
    if not deduped_urls:
        return
    await asyncio.gather(*(_load_summary_image(url) for url in deduped_urls), return_exceptions=True)


def _iter_summary_preload_urls():
    seen = set()
    for item in OW_CONFIG.get("heroList", []):
        for key in ("smallIconUrl", "ddHeroIcon", "circleIcon", "icon"):
            value = str(item.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                yield value
    for item in OW_CONFIG.get("mapList", []):
        value = str(item.get("icon") or "").strip()
        if value and value not in seen:
                seen.add(value)
                yield value


def _summary_extra_asset_path_for_url(url):
    raw_url = str(url or "").strip()
    if not raw_url:
        return None
    icon_name = raw_url.split("/")[-1].split("?")[0]
    suffix = Path(icon_name).suffix or ".png"
    digest = hashlib.sha256(raw_url.encode("utf-8")).hexdigest()
    SUMMARY_EXTRA_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    return str(SUMMARY_EXTRA_ASSET_DIR / f"{digest}{suffix}")


def _summary_local_candidates_for_url(url):
    icon_name = str(url or "").split("/")[-1].split("?")[0]
    if not icon_name:
        return []
    candidates = []
    extra_path = _summary_extra_asset_path_for_url(url)
    if extra_path:
        candidates.append(extra_path)
    candidates.extend(
        [
            os.path.join(MODULE_DIR, "res", icon_name),
            os.path.join(MODULE_DIR, "cache", icon_name),
        ]
    )
    deduped = []
    for path in candidates:
        if path and path not in deduped:
            deduped.append(path)
    return deduped


def _preload_summary_local_images():
    global _SUMMARY_PRELOAD_IMAGE_COUNT
    loaded_any = False
    for url in _iter_summary_preload_urls():
        if _has_cached_summary_image(url):
            continue
        local_path = next((path for path in _summary_local_candidates_for_url(url) if os.path.exists(path)), None)
        if not local_path:
            continue
        try:
            with Image.open(local_path) as raw_img:
                image = raw_img.convert("RGBA")
        except Exception:
            continue
        if _put_summary_image_cache(url, image):
            _SUMMARY_PRELOAD_IMAGE_COUNT += 1
            loaded_any = True
    if loaded_any:
        print(
            f"[season-summary-preload] warmed_images={_SUMMARY_PRELOAD_IMAGE_COUNT} "
            f"used_mb={_SUMMARY_PRELOAD_IMAGE_BYTES / (1024 * 1024):.1f}/{SUMMARY_PRELOAD_IMAGE_BUDGET_MB}"
        )


def _summary_preload_worker():
    started_at = datetime.datetime.now()
    try:
        _preload_summary_local_images()
    except Exception as exc:
        print(f"[season-summary-preload] worker_failed={type(exc).__name__}: {exc}")
    finally:
        cost_ms = int((datetime.datetime.now() - started_at).total_seconds() * 1000)
        print(f"[season-summary-preload] finished cost_ms={cost_ms}")


def _start_summary_preload():
    global _SUMMARY_PRELOAD_THREAD_STARTED
    if not SUMMARY_PRELOAD_IMAGES_ENABLED or _SUMMARY_PRELOAD_THREAD_STARTED:
        return
    _SUMMARY_PRELOAD_THREAD_STARTED = True
    thread = threading.Thread(
        target=_summary_preload_worker,
        name="season-summary-preload",
        daemon=True,
    )
    thread.start()


_start_summary_preload()


def _get_url_semaphore():
    loop = asyncio.get_running_loop()
    loop_key = id(loop)
    semaphore = _SEASON_SUMMARY_URL_SEMAPHORES.get(loop_key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(SEASON_SUMMARY_URL_LIMIT)
        _SEASON_SUMMARY_URL_SEMAPHORES[loop_key] = semaphore
    return semaphore


async def _limited_call(awaitable_factory):
    async with _get_url_semaphore():
        return await awaitable_factory()


async def _fetch_normal_match_page(customer_token, game_mode, page):
    try:
        payload = await _limited_call(
            lambda: dashen_api_client.query_match_list(
                customer_token,
                game_mode,
                page=page,
                season=int(season),
            )
        )
    except Exception as e:
        print(
            "[season_conclusion] request failed: "
            f"queryMatchList mode={game_mode} page={page} {type(e).__name__}: {e}"
        )
        return []
    if not payload or payload.get("code") != 0:
        return []
    return _extract_match_entries(payload, "matchList", "recentMatchList")


async def _fetch_normal_match_list(customer_token, game_mode):
    match_list = []
    page = 1
    batch_size = SEASON_SUMMARY_URL_LIMIT
    while True:
        pages = range(page, page + batch_size)
        results = await asyncio.gather(
            *[_fetch_normal_match_page(customer_token, game_mode, current_page) for current_page in pages]
        )
        batch_has_data = False
        for entries in results:
            if not entries:
                continue
            batch_has_data = True
            for item in entries:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item["_seasonSummaryMode"] = game_mode
                item.setdefault("gameMode", game_mode)
                match_list.append(item)
        if not batch_has_data:
            break
        page += batch_size
    return match_list


async def _fetch_fight_match_list(customer_token):
    all_matches = []
    for game_mode in ("QuickFight", "LeisureFight", "SportFight"):
        page = 1
        while True:
            payloads = await asyncio.gather(
                *[
                    _limited_call(
                        lambda game_mode=game_mode, current_page=page + offset: get_fight_match_list(
                            customer_token,
                            game_mode,
                            current_page,
                            season,
                        )
                    )
                    for offset in range(SEASON_SUMMARY_URL_LIMIT)
                ]
            )
            batch_has_data = False
            for payload in payloads:
                entries = _extract_match_entries(payload, "matchList", "recentMatchList")
                if not entries:
                    continue
                batch_has_data = True
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    item = dict(item)
                    item["gameMode"] = game_mode
                    item["_seasonSummaryFight"] = True
                    all_matches.append(item)
            if not batch_has_data:
                break
            page += SEASON_SUMMARY_URL_LIMIT
    return all_matches


async def _fetch_season_match_lists(customer_token):
    quick, comp, fight = await asyncio.gather(
        _fetch_normal_match_list(customer_token, "leisure"),
        _fetch_normal_match_list(customer_token, "sport"),
        _fetch_fight_match_list(customer_token),
    )

    matches = []
    for source, mode in ((quick or [], "leisure"), (comp or [], "sport")):
        for item in source:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["_seasonSummaryMode"] = mode
            item.setdefault("gameMode", mode)
            matches.append(item)
    matches.extend(fight or [])

    deduped = []
    seen = set()
    for item in matches:
        match_id = item.get("matchId")
        if match_id and match_id in seen:
            continue
        if match_id:
            seen.add(match_id)
        deduped.append(item)
    deduped.sort(key=lambda item: item.get("beginTs") or 0, reverse=True)
    return deduped


async def _fetch_details(customer_token, matches):
    async def fetch_one(match):
        match_id = match.get("matchId")
        if not match_id:
            return match, None
        is_fight_match = _is_fight(match)
        now_ts = time.time()
        cache_key = (str(customer_token), str(match_id), "fight" if is_fight_match else "normal")
        cached = _SUMMARY_DETAIL_CACHE.get(cache_key)
        if cached and cached.get("expiry", 0) > now_ts:
            try:
                _SUMMARY_DETAIL_CACHE.move_to_end(cache_key)
            except Exception:
                pass
            return match, cached.get("data")

        if is_fight_match:
            payload = await _limited_call(lambda: ds_get_single_fight_match(customer_token, match_id))
        else:
            payload = await _limited_call(lambda: ds_get_single_match(customer_token, match_id))
        if payload and payload.get("code") == 0:
            data = payload.get("data") or {}
            _SUMMARY_DETAIL_CACHE[cache_key] = {
                "expiry": now_ts + SUMMARY_DETAIL_CACHE_TTL,
                "data": data,
            }
            while len(_SUMMARY_DETAIL_CACHE) > SUMMARY_DETAIL_CACHE_MAX:
                _SUMMARY_DETAIL_CACHE.popitem(last=False)
            return match, data
        return match, None

    return await asyncio.gather(*(fetch_one(match) for match in matches))


def _find_me(detail, resolved_target):
    detail = _detail_root(detail)
    if not detail:
        return None, None, {}

    full_id = str(resolved_target.get("full_id") or "")
    bnet_id = str(resolved_target.get("bnet_id") or "")
    name_map = {str(k): v for k, v in (detail.get("nameMap") or {}).items()}

    players = []
    for side in ("teammateList", "enemyList"):
        for player in detail.get(side) or []:
            player = dict(player)
            if not player.get("name") and player.get("bnetId") is not None:
                player["name"] = name_map.get(str(player.get("bnetId")), "")
            players.append((side, player))

    for side, player in players:
        if bnet_id and str(player.get("bnetId")) == bnet_id:
            return side, player, name_map
        if full_id and player.get("name") == full_id:
            return side, player, name_map
    return None, None, name_map


def _resolve_me_player_detail(detail, resolved_target):
    raw_detail = detail if isinstance(detail, dict) else {}
    root = _detail_root(raw_detail)
    _, me, _ = _find_me(root, resolved_target)

    top_level_hero_list = raw_detail.get("heroList")
    if isinstance(top_level_hero_list, list) and top_level_hero_list:
        merged = dict(me or {})
        merged["heroList"] = top_level_hero_list
        if not merged.get("bnetId") and raw_detail.get("bnetId") is not None:
            merged["bnetId"] = raw_detail.get("bnetId")
        return merged

    return me


def _player_name(player, name_map):
    if not player:
        return "Unknown"
    return player.get("name") or name_map.get(str(player.get("bnetId"))) or str(player.get("bnetId") or "Unknown")


def _party_size(me):
    return min(5, max(1, len(me.get("friendBnetIds") or []) + 1))


def _update_counter(counter, key, amount=1):
    if key:
        counter[str(key)] += amount


def _calculate_period_carry_score(
    damage=0,
    healing=0,
    blocked=0,
    kill=0,
    final_blows=0,
    solo_kills=0,
    assist=0,
    healing_taken=0,
    damage_taken=0,
    death=0,
):
    return (
        (damage + healing + (blocked / 10))
        + (kill * 200)
        + (final_blows * 200)
        + (solo_kills * 300)
        + (assist * 50)
        + (healing_taken * -0.3)
        + (damage_taken * 0.3)
        - (death * 200)
    )


def _build_stats(matches, detail_pairs, resolved_target):
    stats = {
        "total": len(matches),
        "wins": 0,
        "ties": 0,
        "losses": 0,
        "total_time": 0,
        "total_kill": 0,
        "total_assist": 0,
        "total_death": 0,
        "total_damage": 0,
        "total_healing": 0,
        "total_blocked": 0,
        "total_final_hit": 0,
        "total_solo_kills": 0,
        "total_damage_taken": 0,
        "total_healing_taken": 0,
        "total_objective_time": 0,
        "maps": defaultdict(lambda: {"total": 0, "wins": 0}),
        "friends": defaultdict(lambda: {"games": 0, "wins": 0, "time": 0, "score": 0, "bnet_id": "", "risk_status": None, "objective_time": 0, "deaths": 0, "damage_taken": 0, "endorse_received": 0, "heroes": set()}),
        "strangers": Counter(),
        "stranger_details": defaultdict(lambda: {"games": 0, "wins": 0, "time": 0, "score": 0, "bnet_id": "", "risk_status": None, "objective_time": 0, "deaths": 0, "damage_taken": 0, "endorse_received": 0, "heroes": set()}),
        "party": Counter(),
        "party_wins": Counter(),
        "heroes": Counter(),
        "hero_medals": defaultdict(lambda: {"K": 0, "H": 0, "D": 0, "M": 0, "wins": 0}),
        "roles": Counter(),
        "perks": Counter(),
        "mods": Counter(),
        "hours": Counter(),
        "comp_hour_total": Counter(),
        "comp_hour_wins": Counter(),
        "endorse_received": Counter(),
        "endorse_given": Counter(),
        "endorse_received_team": 0,
        "endorse_received_enemy": 0,
        "mode_total": Counter(),
        "mode_wins": Counter(),
        "detail_count": 0,
        "top3_strongest": [],
        "top3_worst": [],
    }

    for match in matches:
        ret = _int(match.get("matchRet"))
        if ret == 1:
            stats["wins"] += 1
        elif ret == 0:
            stats["ties"] += 1
        else:
            stats["losses"] += 1

        map_guid = match.get("mapGuid")
        if map_guid:
            stats["maps"][str(map_guid)]["total"] += 1
            if ret == 1:
                stats["maps"][str(map_guid)]["wins"] += 1

        hero_guid = match.get("heroGuid")
        _update_counter(stats["heroes"], hero_guid)
        _update_counter(stats["roles"], _role_label(hero_guid))

        ts = match.get("beginTs")
        if ts:
            hour = datetime.datetime.fromtimestamp(_num(ts) / 1000).hour
            stats["hours"][hour] += 1
            if _is_comp(match):
                stats["comp_hour_total"][hour] += 1
                if ret == 1:
                    stats["comp_hour_wins"][hour] += 1

        mode = _mode_label(match)
        stats["mode_total"][mode] += 1
        if ret == 1:
            stats["mode_wins"][mode] += 1

        stats["total_kill"] += _int(match.get("kill"))
        stats["total_assist"] += _int(match.get("assist"))
        stats["total_death"] += _int(match.get("death"))
        stats["total_damage"] += _int(match.get("heroDamage"))
        stats["total_healing"] += _int(match.get("cure"))
        stats["total_blocked"] += _int(match.get("resistDamage"))

    for match, detail in detail_pairs:
        detail = _detail_root(detail)
        if not detail:
            continue
        side, me, name_map = _find_me(detail, resolved_target)
        if not me:
            continue
        stats["detail_count"] += 1
        ret = _int(match.get("matchRet"))
        game_time = _int(detail.get("gameTimeSec"))
        stats["total_time"] += game_time

        stats["total_kill"] += max(0, _int(me.get("kill")) - _int(match.get("kill")))
        stats["total_assist"] += max(0, _int(me.get("assist")) - _int(match.get("assist")))
        stats["total_death"] += max(0, _int(me.get("death")) - _int(match.get("death")))
        stats["total_damage"] += max(0, _int(me.get("heroDamage")) - _int(match.get("heroDamage")))
        stats["total_healing"] += max(0, _int(me.get("cure")) - _int(match.get("cure")))
        stats["total_blocked"] += max(0, _int(me.get("resistDamage")) - _int(match.get("resistDamage")))
        stats["total_final_hit"] += _int(me.get("finalHit") or me.get("finalBlows"))
        stats["total_solo_kills"] += _int(me.get("soloKills"))
        stats["total_damage_taken"] += _int(me.get("damageTaken"))
        stats["total_healing_taken"] += _int(me.get("healingTaken"))
        stats["total_objective_time"] += _num(me.get("targetCompetingTime"))

        if me.get("heroGuid") and not match.get("heroGuid"):
            _update_counter(stats["heroes"], me.get("heroGuid"))
            _update_counter(stats["roles"], _role_label(me.get("heroGuid")))

        current_hero_guid = me.get("heroGuid") or match.get("heroGuid")
        if current_hero_guid and (detail.get("teammateList") or []):
            teammates_for_medals = detail.get("teammateList") or []
            max_kill = max((_int(player.get("kill")) for player in teammates_for_medals), default=0)
            max_healing = max((_int(player.get("cure")) for player in teammates_for_medals), default=0)
            max_damage = max((_int(player.get("heroDamage")) for player in teammates_for_medals), default=0)
            max_blocked = max((_int(player.get("resistDamage")) for player in teammates_for_medals), default=0)
            medal_data = stats["hero_medals"][str(current_hero_guid)]
            if ret == 1:
                medal_data["wins"] += 1
            if _int(me.get("kill")) >= max_kill and max_kill > 0:
                medal_data["K"] += 1
            if _int(me.get("cure")) >= max_healing and max_healing > 0:
                medal_data["H"] += 1
            if _int(me.get("heroDamage")) >= max_damage and max_damage > 0:
                medal_data["D"] += 1
            if _int(me.get("resistDamage")) >= max_blocked and max_blocked > 0:
                medal_data["M"] += 1

        for perk_guid in me.get("traitGuids") or []:
            _update_counter(stats["perks"], perk_guid)
        for mod_guid in me.get("modGuids") or []:
            _update_counter(stats["mods"], mod_guid)

        party_size = _party_size(me)
        stats["party"][party_size] += 1
        if ret == 1:
            stats["party_wins"][party_size] += 1

        friends = {str(item) for item in (me.get("friendBnetIds") or [])}
        for player in detail.get("teammateList") or []:
            if str(player.get("bnetId")) == str(me.get("bnetId")):
                continue
            name = _player_name(player, name_map)
            teammate_kda = (_int(player.get("kill")) + _int(player.get("assist"))) / max(1, _int(player.get("death")))
            teammate_hero_guid = player.get("heroGuid")
            if not teammate_hero_guid and player.get("heroList"):
                hero_item = (player.get("heroList") or [{}])[0] or {}
                teammate_hero_guid = hero_item.get("heroGuid") or hero_item.get("heroId")
            teammate_risk_status = None
            if "riskStatus" in player:
                parsed_teammate_risk = parse_risk_status({"riskStatus": player.get("riskStatus")})
                teammate_risk_status = parsed_teammate_risk.to_dict() if parsed_teammate_risk else None
            teammate_entry = {
                "kda": teammate_kda,
                "name": name,
                "heroGuid": teammate_hero_guid,
                "mapGuid": match.get("mapGuid") or detail.get("mapGuid"),
                "risk_status": teammate_risk_status,
            }
            existing_best = next((item for item in stats["top3_strongest"] if item["name"] == name), None)
            if existing_best is None:
                stats["top3_strongest"].append(teammate_entry)
            elif teammate_kda > existing_best["kda"]:
                stats["top3_strongest"].remove(existing_best)
                stats["top3_strongest"].append(teammate_entry)
            stats["top3_strongest"].sort(key=lambda item: item["kda"], reverse=True)
            stats["top3_strongest"] = stats["top3_strongest"][:3]

            existing_worst = next((item for item in stats["top3_worst"] if item["name"] == name), None)
            if existing_worst is None:
                stats["top3_worst"].append(teammate_entry)
            elif teammate_kda < existing_worst["kda"]:
                stats["top3_worst"].remove(existing_worst)
                stats["top3_worst"].append(teammate_entry)
            stats["top3_worst"].sort(key=lambda item: item["kda"])
            stats["top3_worst"] = stats["top3_worst"][:3]

            if str(player.get("bnetId")) in friends:
                if player.get("bnetId") is not None:
                    stats["friends"][name]["bnet_id"] = str(player.get("bnetId"))
                if teammate_risk_status:
                    stats["friends"][name]["risk_status"] = teammate_risk_status
                stats["friends"][name]["games"] += 1
                stats["friends"][name]["time"] += game_time
                stats["friends"][name]["objective_time"] += _num(player.get("targetCompetingTime"))
                stats["friends"][name]["deaths"] += _int(player.get("death"))
                stats["friends"][name]["damage_taken"] += _int(player.get("damageTaken"))
                stats["friends"][name]["endorse_received"] += len(player.get("endorserBnetIds") or [])
                if teammate_hero_guid:
                    stats["friends"][name]["heroes"].add(str(teammate_hero_guid))
                if ret == 1:
                    stats["friends"][name]["wins"] += 1
                stats["friends"][name]["score"] += _calculate_period_carry_score(
                    damage=_int(player.get("heroDamage")),
                    healing=_int(player.get("cure")),
                    blocked=_int(player.get("resistDamage")),
                    kill=_int(player.get("kill")),
                    final_blows=_int(player.get("finalHit") or player.get("finalBlows")),
                    solo_kills=_int(player.get("soloKills")),
                    assist=_int(player.get("assist")),
                    healing_taken=_int(player.get("healingTaken")),
                    damage_taken=_int(player.get("damageTaken")),
                    death=_int(player.get("death")),
                )
            else:
                stats["strangers"][name] += 1
                if player.get("bnetId") is not None:
                    stats["stranger_details"][name]["bnet_id"] = str(player.get("bnetId"))
                if teammate_risk_status:
                    stats["stranger_details"][name]["risk_status"] = teammate_risk_status
                stats["stranger_details"][name]["games"] += 1
                stats["stranger_details"][name]["time"] += game_time
                stats["stranger_details"][name]["objective_time"] += _num(player.get("targetCompetingTime"))
                stats["stranger_details"][name]["deaths"] += _int(player.get("death"))
                stats["stranger_details"][name]["damage_taken"] += _int(player.get("damageTaken"))
                stats["stranger_details"][name]["endorse_received"] += len(player.get("endorserBnetIds") or [])
                if teammate_hero_guid:
                    stats["stranger_details"][name]["heroes"].add(str(teammate_hero_guid))
                if ret == 1:
                    stats["stranger_details"][name]["wins"] += 1
                stats["stranger_details"][name]["score"] += _calculate_period_carry_score(
                    damage=_int(player.get("heroDamage")),
                    healing=_int(player.get("cure")),
                    blocked=_int(player.get("resistDamage")),
                    kill=_int(player.get("kill")),
                    final_blows=_int(player.get("finalHit") or player.get("finalBlows")),
                    solo_kills=_int(player.get("soloKills")),
                    assist=_int(player.get("assist")),
                    healing_taken=_int(player.get("healingTaken")),
                    damage_taken=_int(player.get("damageTaken")),
                    death=_int(player.get("death")),
                )

        all_players = (detail.get("teammateList") or []) + (detail.get("enemyList") or [])
        id_to_name = {
            str(player.get("bnetId")): _player_name(player, name_map)
            for player in all_players
            if player.get("bnetId") is not None
        }
        teammate_ids = {str(player.get("bnetId")) for player in detail.get("teammateList") or []}

        for endorser_id in me.get("endorserBnetIds") or []:
            endorser_id = str(endorser_id)
            stats["endorse_received"][id_to_name.get(endorser_id, endorser_id)] += 1
            if endorser_id in teammate_ids:
                stats["endorse_received_team"] += 1
            else:
                stats["endorse_received_enemy"] += 1

        my_bnet_id = str(me.get("bnetId"))
        for player in all_players:
            if str(player.get("bnetId")) == my_bnet_id:
                continue
            if my_bnet_id in {str(item) for item in (player.get("endorserBnetIds") or [])}:
                stats["endorse_given"][_player_name(player, name_map)] += 1

    return stats


def _rank_distribution_cache_file(target_day):
    os.makedirs(RANK_DISTRIBUTION_CACHE_DIR, exist_ok=True)
    return os.path.join(RANK_DISTRIBUTION_CACHE_DIR, f"{target_day.isoformat()}.json")


def _read_rank_distribution_snapshot(target_day):
    cache_file = _rank_distribution_cache_file(target_day)
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _score_bucket_key(score):
    try:
        score = int(float(score))
    except (TypeError, ValueError):
        return None
    if score <= 0:
        return None
    score = max(QUICK_DIST_BUCKET_START, min(QUICK_DIST_BUCKET_END, score))
    return ((score - QUICK_DIST_BUCKET_START) // QUICK_DIST_BUCKET_STEP) * QUICK_DIST_BUCKET_STEP + QUICK_DIST_BUCKET_START


def _all_rank_bucket_keys():
    return list(range(QUICK_DIST_BUCKET_START, QUICK_DIST_BUCKET_END + QUICK_DIST_BUCKET_STEP, QUICK_DIST_BUCKET_STEP))


def _major_rank_breakpoints():
    return [
        ("青铜", 700),
        ("白银", 1200),
        ("黄金", 1700),
        ("白金", 2200),
        ("翡翠", 2700),
        ("钻石", 3200),
        ("大师", 3700),
        ("宗师", 4200),
        ("英杰", 4700),
    ]


def _quick_dist_rank_label(score):
    bucket = _score_bucket_key(score)
    if bucket is None:
        return "未定级"
    for lower, upper, label in QUICK_DIST_RANK_SPANS:
        if lower <= bucket < upper:
            tier_idx = max(0, min(4, int((bucket - lower) // QUICK_DIST_BUCKET_STEP)))
            return f"{label}{5 - tier_idx}"
    return "英杰1"


def _is_rank_distribution_snapshot_compatible(snapshot):
    if not isinstance(snapshot, dict):
        return False
    if int(snapshot.get("version") or 0) != QUICK_DIST_SNAPSHOT_VERSION:
        return False
    bucket_counts = snapshot.get("bucket_counts")
    if not isinstance(bucket_counts, dict) or not bucket_counts:
        return False
    expected_keys = {str(bucket) for bucket in _all_rank_bucket_keys()}
    actual_keys = {str(key) for key in bucket_counts.keys()}
    return bool(expected_keys & actual_keys)


def _build_rank_distribution_snapshot(target_day):
    bucket_counts = {str(bucket): 0 for bucket in _all_rank_bucket_keys()}
    total_samples = 0
    try:
        rank_rows = _GROUP_TITLE_DB.get_all_rank() or []
    except Exception:
        rank_rows = []
    for row in rank_rows:
        if not isinstance(row, dict):
            continue
        for key in ("tank", "dps", "healer"):
            strength = raw_rank_score_to_strength(row.get(key))
            bucket = _score_bucket_key(strength)
            if bucket is None:
                continue
            bucket_counts[str(bucket)] = bucket_counts.get(str(bucket), 0) + 1
            total_samples += 1
    peak_bucket = None
    peak_count = 0
    for bucket in _all_rank_bucket_keys():
        count = int(bucket_counts.get(str(bucket), 0))
        if count > peak_count:
            peak_count = count
            peak_bucket = bucket
    payload = {
        "version": QUICK_DIST_SNAPSHOT_VERSION,
        "date": target_day.isoformat(),
        "bucket_counts": bucket_counts,
        "total_samples": total_samples,
        "peak_bucket": peak_bucket,
        "peak_count": peak_count,
        "cached_at": int(datetime.datetime.now().timestamp()),
    }
    cache_file = _rank_distribution_cache_file(target_day)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass
    return payload


async def _build_rank_distribution_snapshot_from_ranking_dist(target_day):
    bucket_counts = {str(bucket): 0 for bucket in _all_rank_bucket_keys()}
    total_samples = 0
    try:
        ranking_result = await ranking_dist2(0)
    except Exception:
        ranking_result = None

    if not isinstance(ranking_result, tuple) or len(ranking_result) < 2:
        return None

    _, rank_scores = ranking_result
    raw_scores = [int(float(score)) for score in (rank_scores or []) if score]
    print(
        "[quick_dist_raw]",
        {
            "count": len(raw_scores),
            "min": min(raw_scores) if raw_scores else None,
            "max": max(raw_scores) if raw_scores else None,
            "sample": raw_scores[:12],
        },
    )
    for score in rank_scores or []:
        strength = raw_rank_score_to_strength(score)
        bucket = _score_bucket_key(strength)
        if bucket is None:
            continue
        bucket_counts[str(bucket)] = bucket_counts.get(str(bucket), 0) + 1
        total_samples += 1

    if total_samples <= 0:
        return None

    peak_bucket = None
    peak_count = 0
    for bucket in _all_rank_bucket_keys():
        count = int(bucket_counts.get(str(bucket), 0))
        if count > peak_count:
            peak_count = count
            peak_bucket = bucket

    payload = {
        "version": QUICK_DIST_SNAPSHOT_VERSION,
        "date": target_day.isoformat(),
        "bucket_counts": bucket_counts,
        "total_samples": total_samples,
        "peak_bucket": peak_bucket,
        "peak_count": peak_count,
        "cached_at": int(datetime.datetime.now().timestamp()),
    }
    cache_file = _rank_distribution_cache_file(target_day)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass
    return payload


def _get_rank_distribution_snapshot(target_day=None):
    if target_day is None:
        target_day = datetime.datetime.now().date()
    snapshot = _read_rank_distribution_snapshot(target_day)
    if snapshot and int(snapshot.get("total_samples") or 0) > 0 and _is_rank_distribution_snapshot_compatible(snapshot):
        return snapshot
    built_snapshot = _build_rank_distribution_snapshot(target_day)
    return built_snapshot if int(built_snapshot.get("total_samples") or 0) > 0 else (snapshot or built_snapshot)


def _sample_period_quick_matches(matches, max_samples=12):
    quick_matches = [
        dict(match)
        for match in (matches or [])
        if isinstance(match, dict)
        and match.get("matchId")
        and not _is_comp(match)
        and not _is_fight(match)
    ]
    quick_matches.sort(key=lambda item: item.get("beginTs") or 0)
    if len(quick_matches) <= max_samples:
        return quick_matches
    sample_count = min(max_samples, len(quick_matches))
    picked = []
    used = set()
    for idx in range(sample_count):
        mapped_idx = round(idx * (len(quick_matches) - 1) / max(sample_count - 1, 1))
        if mapped_idx in used:
            continue
        used.add(mapped_idx)
        picked.append(quick_matches[mapped_idx])
    return picked


async def _build_quick_strength_distribution_data(customer_token, matches):
    sampled_matches = _sample_period_quick_matches(matches, max_samples=12)
    latest_ts = max(
        (_num(match.get("beginTs")) for match in (sampled_matches or matches or [])),
        default=0,
    )
    target_day = (
        datetime.datetime.fromtimestamp(latest_ts / 1000).date()
        if latest_ts
        else datetime.datetime.now().date()
    )
    snapshot = _get_rank_distribution_snapshot(target_day)
    if int(snapshot.get("total_samples") or 0) <= 0:
        fallback_snapshot = await _build_rank_distribution_snapshot_from_ranking_dist(target_day)
        if fallback_snapshot:
            snapshot = fallback_snapshot
    bucket_counts = snapshot.get("bucket_counts") or {}
    peak_count = max([int(bucket_counts.get(str(bucket), 0)) for bucket in _all_rank_bucket_keys()] or [0])
    non_zero_debug = [
        (int(bucket), int(bucket_counts.get(str(bucket), 0)))
        for bucket in _all_rank_bucket_keys()
        if int(bucket_counts.get(str(bucket), 0)) > 0
    ]
    print(
        "[quick_dist]",
        {
            "snapshot_date": snapshot.get("date"),
            "total_samples": int(snapshot.get("total_samples") or 0),
            "peak_count": peak_count,
            "non_zero_bucket_count": len(non_zero_debug),
            "top_buckets": non_zero_debug[:8],
            "source_match_count": len(sampled_matches),
        },
    )
    if not sampled_matches:
        return {
            "snapshot_date": snapshot.get("date"),
            "bucket_counts": bucket_counts,
            "peak_bucket": snapshot.get("peak_bucket"),
            "peak_count": peak_count,
            "total_samples": int(snapshot.get("total_samples") or 0),
            "sampled_matches": [],
            "sampled_count": 0,
            "source_match_count": 0,
        }

    results = await asyncio.gather(
        *(match_rating_recent(match.get("matchId"), customer_token, OW_CONFIG) for match in sampled_matches),
        return_exceptions=True,
    )

    sample_points = []
    for match, result in zip(sampled_matches, results):
        if isinstance(result, Exception) or not isinstance(result, tuple) or len(result) < 4:
            continue
        avg_score = _num(result[3])
        if avg_score <= 0:
            continue
        bucket = _score_bucket_key(avg_score)
        if bucket is None:
            continue
        sample_points.append(
            {
                "match_id": match.get("matchId"),
                "bucket": bucket,
                "avg_score": avg_score,
                "rank_label": _quick_dist_rank_label(avg_score),
                "count": int(bucket_counts.get(str(bucket), 0)),
                "begin_ts": _num(match.get("beginTs")),
                "map_guid": match.get("mapGuid"),
                "result": _int(match.get("matchRet")),
            }
        )

    return {
        "snapshot_date": snapshot.get("date"),
        "bucket_counts": bucket_counts,
        "peak_bucket": snapshot.get("peak_bucket"),
        "peak_count": peak_count,
        "total_samples": int(snapshot.get("total_samples") or 0),
        "sampled_matches": sample_points,
        "sampled_count": len(sample_points),
        "source_match_count": len(sampled_matches),
    }


def _load_font(size, bold=False):
    cache_key = (int(size), bool(bold))
    cached = _SUMMARY_FONT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    adjusted_size = int(size)
    if adjusted_size <= 11:
        adjusted_size += 1
    elif adjusted_size <= 14:
        adjusted_size += 2
    elif adjusted_size <= 18:
        adjusted_size += 1
    size = adjusted_size
    font = load_font(
        size,
        name="simhei.ttf",
        fallback="en.ttf",
        prefer_cjk=True,
        bold=bold,
    )
    _SUMMARY_FONT_CACHE[cache_key] = font
    return font


def _text_size(draw, text, font):
    box = draw.textbbox((0, 0), str(text), font=font)
    return box[2] - box[0], box[3] - box[1]


def _text_box(draw, text, font):
    return draw.textbbox((0, 0), str(text or ""), font=font)


def _normalize_group_title_color(raw_color):
    color_text = str(raw_color or "").strip()
    match = GROUP_TITLE_COLOR_RE.fullmatch(color_text)
    if not match:
        return None
    return f"#{match.group(1).upper()}"


def _pick_contrast_text_color(bg_hex):
    normalized = _normalize_group_title_color(bg_hex) or "#4B5563"
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return (24, 28, 38) if luminance >= 186 else (255, 255, 255)


def _get_group_titles_safe(bnet_id):
    cache_key = str(bnet_id or "").strip()
    if not cache_key or cache_key.lower() == "none":
        return []
    try:
        return _GROUP_TITLE_DB.get_group_titles(cache_key) or []
    except Exception:
        return []


def _truncate_to_width(draw, text, font, max_width, suffix="..."):
    content = str(text or "")
    if max_width <= 0:
        return ""
    if _text_size(draw, content, font)[0] <= max_width:
        return content
    suffix_width = _text_size(draw, suffix, font)[0]
    if suffix_width >= max_width:
        return content[:1]
    truncated = ""
    for char in content:
        candidate = truncated + char
        if _text_size(draw, candidate, font)[0] + suffix_width > max_width:
            break
        truncated = candidate
    return (truncated or content[:1]) + suffix


def _fit_group_title_font(draw, text, max_text_width, max_font_size, min_font_size):
    for size in range(max_font_size, min_font_size - 1, -1):
        font = _load_font(size, bold=True)
        if _text_size(draw, text, font)[0] <= max_text_width:
            return font
    return _load_font(min_font_size, bold=True)


def _fit_text_font(draw, text, max_text_width, max_font_size, min_font_size, bold=False):
    for size in range(max_font_size, min_font_size - 1, -1):
        font = _load_font(size, bold=bold)
        if _text_size(draw, text, font)[0] <= max_text_width:
            return font
    return _load_font(min_font_size, bold=bold)


def _draw_group_title_badges(
    draw,
    title_list,
    start_x,
    center_y,
    max_x,
    badge_height=24,
    badge_gap=8,
    max_badge_width=118,
    min_badge_width=44,
    padding_x=10,
    max_font_size=14,
    min_font_size=10,
    allow_wrap=False,
    wrap_start_x=None,
    row_gap=6,
):
    curr_x = int(start_x)
    row_start_x = int(wrap_start_x if wrap_start_x is not None else start_x)
    row_top = int(center_y - badge_height / 2)
    drawn = 0
    max_bottom = row_top + badge_height
    for title_item in (title_list or [])[:MAX_GROUP_TITLES_PER_PLAYER]:
        badge_text = str((title_item or {}).get("title") or "").strip()
        if not badge_text:
            continue

        if allow_wrap and curr_x > row_start_x and curr_x + min_badge_width > int(max_x):
            curr_x = row_start_x
            row_top += badge_height + row_gap

        available_width = min(max_badge_width, int(max_x) - curr_x)
        if available_width < min_badge_width:
            if allow_wrap and curr_x != row_start_x:
                curr_x = row_start_x
                row_top += badge_height + row_gap
                available_width = min(max_badge_width, int(max_x) - curr_x)
            if available_width < min_badge_width:
                break

        badge_color = _normalize_group_title_color((title_item or {}).get("color")) or "#4B5563"
        font = _fit_group_title_font(
            draw,
            badge_text,
            max(8, available_width - padding_x * 2),
            max_font_size,
            min_font_size,
        )
        display_text = _truncate_to_width(draw, badge_text, font, max(8, available_width - padding_x * 2))
        text_width = _text_size(draw, display_text, font)[0]
        badge_width = min(available_width, max(min_badge_width, int(text_width + padding_x * 2)))
        top = row_top
        box = (curr_x, top, curr_x + badge_width, top + badge_height)

        draw.rounded_rectangle(box, radius=min(8, badge_height // 2), fill=badge_color)
        text_box = _text_box(draw, display_text, font)
        text_height = text_box[3] - text_box[1]
        text_x = curr_x + (badge_width - text_width) / 2
        text_y = top + (badge_height - text_height) / 2 - text_box[1]
        draw.text((text_x, text_y), display_text, font=font, fill=_pick_contrast_text_color(badge_color))

        curr_x += badge_width + badge_gap
        drawn += 1
        max_bottom = max(max_bottom, top + badge_height)
    return curr_x, drawn, max_bottom


def _card(draw, box, title):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=8, fill=(18, 24, 34, 198), outline=(81, 103, 130, 180), width=1)
    draw.text((x1 + 18, y1 + 12), title, font=_load_font(26, bold=True), fill=(244, 248, 255))
    draw.line((x1 + 18, y1 + 50, x2 - 18, y1 + 50), fill=(93, 112, 140, 145), width=1)


def _draw_metric(draw, x, y, label, value, color=(255, 210, 105)):
    draw.text((x, y), str(value), font=_load_font(40, bold=True), fill=color)
    draw.text((x, y + 48), label, font=_load_font(19), fill=(180, 190, 205))


def _draw_small_metric(draw, x, y, label, value, color=(246, 248, 255)):
    draw.text((x, y), str(value), font=_load_font(25, bold=True), fill=color)
    draw.text((x, y + 30), label, font=_load_font(15), fill=(180, 190, 205))


def _draw_bar(draw, x, y, w, h, ratio, fill, bg=(54, 62, 76, 210)):
    ratio = max(0.0, min(float(ratio or 0), 1.0))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=4, fill=bg)
    if ratio > 0:
        draw.rounded_rectangle((x, y, x + max(h, int(w * ratio)), y + h), radius=4, fill=fill)


def _smooth_polyline(points, steps=14):
    if len(points) <= 2:
        return points
    smoothed = []
    for idx in range(len(points) - 1):
        p0 = points[idx - 1] if idx > 0 else points[idx]
        p1 = points[idx]
        p2 = points[idx + 1]
        p3 = points[idx + 2] if idx + 2 < len(points) else points[idx + 1]
        for step in range(steps):
            t = step / float(steps)
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            smoothed.append((x, y))
    smoothed.append(points[-1])
    return smoothed


def _draw_quick_strength_distribution(draw, box, dist_data):
    x1, y1, x2, y2 = box
    inner_x1 = x1 + 28
    inner_x2 = x2 - 28
    axis_y = y2 - 44
    label_y = y2 - 24

    if not dist_data:
        draw.text((inner_x1, y1 + 48), "暂无可用的快速强度分布数据", font=_load_font(18), fill=(145, 155, 170))
        return

    sampled_matches = sorted(
        dist_data.get("sampled_matches") or [],
        key=lambda item: item.get("begin_ts") or 0,
    )
    grouped_samples = OrderedDict()
    for sample in sampled_matches:
        bucket = _score_bucket_key(sample.get("bucket") or sample.get("avg_score"))
        if bucket is None:
            continue
        group = grouped_samples.setdefault(
            bucket,
            {
                "bucket": bucket,
                "rank_label": str(sample.get("rank_label") or _quick_dist_rank_label(bucket)),
                "sample_count": 0,
                "wins": 0,
                "losses": 0,
            },
        )
        group["sample_count"] += 1
        result = _int(sample.get("result"))
        if result == 1:
            group["wins"] += 1
        elif result == -1:
            group["losses"] += 1

    if not grouped_samples:
        draw.text((inner_x1, y1 + 48), "暂无可用的快速对局强度样本", font=_load_font(18), fill=(145, 155, 170))
        return

    bucket_keys = _all_rank_bucket_keys()
    visible_buckets = sorted(grouped_samples.keys())
    first_idx = max(0, bucket_keys.index(min(visible_buckets)) - 1)
    last_idx = min(len(bucket_keys) - 1, bucket_keys.index(max(visible_buckets)) + 1)
    visible_bucket_keys = bucket_keys[first_idx : last_idx + 1]
    bucket_x_map = {}
    if len(visible_bucket_keys) == 1:
        bucket_x_map[visible_bucket_keys[0]] = (inner_x1 + inner_x2) / 2
    else:
        step_x = (inner_x2 - inner_x1) / max(len(visible_bucket_keys) - 1, 1)
        for idx, bucket in enumerate(visible_bucket_keys):
            bucket_x_map[bucket] = inner_x1 + idx * step_x

    sample_total = sum(int(group.get("sample_count") or 0) for group in grouped_samples.values())
    summary_text = f"抽样 {sample_total} 场 / 覆盖 {len(grouped_samples)} 个强度段位"
    summary_w = _text_size(draw, summary_text, _load_font(12))[0]
    draw.text((inner_x2 - summary_w, y1 + 4), summary_text, font=_load_font(12), fill=(158, 170, 188))

    draw.line((inner_x1, axis_y, inner_x2, axis_y), fill=(72, 94, 122, 140), width=2)

    for lower, upper, label in QUICK_DIST_RANK_SPANS:
        rank_buckets = [bucket for bucket in visible_bucket_keys if lower <= bucket < upper]
        if not rank_buckets:
            continue
        center_bucket = rank_buckets[len(rank_buckets) // 2]
        text = _truncate_to_width(draw, label, _load_font(12), 48)
        text_w = _text_size(draw, text, _load_font(12))[0]
        draw.text((bucket_x_map[center_bucket] - text_w / 2, label_y), text, font=_load_font(12), fill=(158, 170, 188))

    chip_rows = [y1 + 26, y1 + 58]
    for idx, group in enumerate(sorted(grouped_samples.values(), key=lambda item: item.get("bucket") or 0)):
        bucket = int(group["bucket"])
        center_x = bucket_x_map.get(bucket)
        if center_x is None:
            continue

        row_y = chip_rows[idx % len(chip_rows)]
        sample_count = max(1, int(group.get("sample_count") or 0))
        wins = int(group.get("wins") or 0)
        losses = int(group.get("losses") or 0)
        if wins and not losses:
            fill = (100, 206, 255, 232)
            outline = (160, 228, 255, 250)
        elif losses and not wins:
            fill = (63, 106, 148, 228)
            outline = (118, 162, 204, 245)
        else:
            fill = (86, 152, 201, 230)
            outline = (150, 207, 236, 248)

        label_text = str(group.get("rank_label") or _quick_dist_rank_label(bucket))
        if sample_count > 1:
            label_text = f"{label_text} x{sample_count}"
        label_text = _truncate_to_width(draw, label_text, _load_font(14, bold=True), 96)
        text_w, _ = _text_size(draw, label_text, _load_font(14, bold=True))
        chip_w = max(54, min(104, int(text_w + 24)))
        chip_h = 24
        chip_x1 = int(center_x - chip_w / 2)
        chip_x1 = max(inner_x1, min(chip_x1, inner_x2 - chip_w))
        chip_y1 = int(row_y)
        chip_x2 = chip_x1 + chip_w
        chip_y2 = chip_y1 + chip_h

        draw.line((int(center_x), chip_y2 + 4, int(center_x), axis_y - 8), fill=(86, 126, 164, 130), width=2)
        draw.ellipse((int(center_x - 4), axis_y - 4, int(center_x + 4), axis_y + 4), fill=outline)
        draw.rounded_rectangle((chip_x1, chip_y1, chip_x2, chip_y2), radius=12, fill=fill, outline=outline, width=1)

        text_box = _text_box(draw, label_text, _load_font(14, bold=True))
        text_h = text_box[3] - text_box[1]
        text_x = chip_x1 + (chip_w - text_w) / 2
        text_y = chip_y1 + (chip_h - text_h) / 2 - text_box[1]
        draw.text((text_x, text_y), label_text, font=_load_font(14, bold=True), fill=(245, 249, 255))



def _winrate_color(wins, total):
    return (100, 255, 120) if wins / max(total, 1) >= 0.5 else (255, 100, 100)


def _carry_color(ratio):
    if ratio >= 100:
        return (255, 215, 0)
    if ratio > 80:
        return (238, 242, 248)
    return (180, 180, 190)


def _carry_baseline(stats):
    my_score = _calculate_period_carry_score(
        damage=stats["total_damage"],
        healing=stats["total_healing"],
        blocked=stats["total_blocked"],
        kill=stats["total_kill"],
        final_blows=stats["total_final_hit"],
        solo_kills=stats.get("total_solo_kills", 0),
        assist=stats["total_assist"],
        healing_taken=stats.get("total_healing_taken", 0),
        damage_taken=stats.get("total_damage_taken", 0),
        death=stats["total_death"],
    )
    return max(1, my_score / (max(1, stats["total_time"]) / 600))


def _carry_ratio(data, baseline):
    avg_score = _num(data.get("score")) / (max(1, data.get("time", 0)) / 600)
    return max(0, avg_score / max(1, baseline) * 100)


def _period_contact_rows(stats):
    rows = []
    for name, data in stats["friends"].items():
        rows.append(("好友", name, data))
    for name, data in stats["stranger_details"].items():
        if data.get("games", 0) > 1:
            rows.append(("路人", name, data))
    rows.sort(key=lambda item: (item[2].get("games", 0), item[2].get("wins", 0) / max(1, item[2].get("games", 0))), reverse=True)
    return rows


def _teammate_fun_awards(stats):
    teammate_pool = []
    for kind, source in (("好友", stats.get("friends") or {}), ("路人", stats.get("stranger_details") or {})):
        for name, data in source.items():
            if not data.get("games", 0):
                continue
            teammate_pool.append((kind, name, data))

    def _pick(title, metric_key, value_func, formatter, positive_only=True):
        if not teammate_pool:
            return None
        ranked = sorted(
            teammate_pool,
            key=lambda item: (value_func(item[2]), item[2].get("games", 0), item[2].get("wins", 0)),
            reverse=True,
        )
        winner_kind, winner_name, winner_data = ranked[0]
        winner_value = value_func(winner_data)
        if positive_only and winner_value <= 0:
            return None
        return {
            "title": title,
            "kind": winner_kind,
            "name": winner_name,
            "value": formatter(winner_value),
        }

    awards = [
        _pick("推车金", "objective_time", lambda data: _num(data.get("objective_time")), _fmt_time),
        _pick("返场金", "deaths", lambda data: _int(data.get("deaths")), lambda value: f"死亡 {int(value)}"),
        _pick("挨打金", "damage_taken", lambda data: _int(data.get("damage_taken")), lambda value: f"承伤 {_fmt_int(value)}"),
        _pick("礼貌金", "endorse_received", lambda data: _int(data.get("endorse_received")), lambda value: f"被赞 {int(value)}"),
        _pick("花活金", "heroes", lambda data: len(data.get("heroes") or set()), lambda value: f"英雄 {int(value)}"),
    ]
    return [award for award in awards if award]


def _teammate_spotlight_height(stats):
    if stats.get("top3_strongest") or stats.get("top3_worst"):
        strong_count = len(stats.get("top3_strongest") or [])
        worst_entries = stats.get("top3_worst") or []
        worst_count = 1 if (worst_entries and all(_num(entry.get("kda")) > 1.0 for entry in worst_entries)) else len(worst_entries)
        strong_h = 46 + max(1, strong_count) * 38
        worst_h = 46 + max(1, worst_count) * 38
        return strong_h + worst_h + 20
    return 0


def _party_summary_height(stats):
    return 66 if stats.get("party") else 0


def _teammate_awards_height(stats):
    award_count = len(_teammate_fun_awards(stats))
    if not award_count:
        return 0
    award_rows = (award_count + 1) // 2
    return 36 + award_rows * 72


def _hero_ring_color(role_label):
    return {
        "Tank": (92, 178, 255, 255),
        "Damage": (255, 118, 92, 255),
        "Support": (117, 223, 174, 255),
    }.get(role_label, (180, 190, 205, 255))


def _draw_top_rows(draw, rows, x, y, w, row_h, label_func, value_func, ratio_func, fill):
    if not rows:
        draw.text((x, y), "No data", font=_load_font(18), fill=(145, 155, 170))
        return
    for idx, row in enumerate(rows):
        yy = y + idx * row_h
        draw.text((x, yy), label_func(row), font=_load_font(18), fill=(232, 238, 247))
        value = value_func(row)
        vw = _text_size(draw, value, _load_font(17))[0]
        draw.text((x + w - vw, yy + 1), value, font=_load_font(17), fill=(190, 204, 222))
        _draw_bar(draw, x, yy + 27, w, 10, ratio_func(row), fill)


def _make_background(size):
    w, h = size
    bg = build_random_map_background(
        size,
        blur_radius=24,
        overlay=(5, 8, 14, 158),
        brightness=0.78,
        color=0.88,
    )
    if bg is not None:
        return bg
    bg = Image.new("RGBA", size, (9, 13, 19, 255))
    bg_path = os.path.join(MODULE_DIR, "bg.png")
    if os.path.exists(bg_path):
        try:
            raw = Image.open(bg_path).convert("RGBA")
            bg = _make_blurred_summary_background(raw, size, blur_radius=24)
        except Exception:
            pass
    return bg


def _make_blurred_summary_background(source_image, size, blur_radius=50, overlay=(5, 8, 14, 158)):
    bg = _cover_fit(source_image.convert("RGBA"), size)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    bg = Image.alpha_composite(bg, Image.new("RGBA", size, overlay))
    return bg


async def _make_period_background(size, matches):
    background = build_random_map_background(
        size,
        blur_radius=50,
        overlay=(5, 8, 14, 166),
        brightness=0.78,
        color=0.86,
    )
    if background is not None:
        return background
    return _make_background(size)


async def _load_summary_image(url):
    url = str(url or "").strip()
    if not url:
        return None
    cached = _get_cached_summary_image_copy(url)
    if cached is not None:
        return cached
    icon_name = url.split("/")[-1].split("?")[0]
    local_candidates = []
    if icon_name:
        local_candidates.extend(
            [
                os.path.join(MODULE_DIR, "res", icon_name),
                os.path.join(MODULE_DIR, "cache", icon_name),
            ]
        )
    try:
        image = None
        for local_path in local_candidates:
            if not os.path.exists(local_path):
                continue
            try:
                with Image.open(local_path) as raw_img:
                    image = raw_img.convert("RGBA")
                break
            except Exception:
                image = None
        if image is None:
            raw = await _limited_call(lambda: get_icon(url))
            image = Image.open(BytesIO(raw)).convert("RGBA")
            if local_candidates:
                try:
                    image.save(local_candidates[0])
                except Exception:
                    pass
    except Exception:
        return None
    _put_summary_image_cache(url, image)
    return image


def _cover_fit(image, size):
    target_w, target_h = size
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGBA", size, (24, 31, 42, 255))
    scale = max(target_w / src_w, target_h / src_h)
    resized = image.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))), Image.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _rounded_mask(size, radius=8):
    cache_key = (int(size[0]), int(size[1]), int(radius))
    mask = _SUMMARY_MASK_CACHE.get(cache_key)
    if mask is None:
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
        _SUMMARY_MASK_CACHE[cache_key] = mask
    return mask


def _period_range_text(matches):
    stamps = sorted(_num(item.get("beginTs")) for item in matches if item.get("beginTs"))
    if not stamps:
        return "无时间记录"
    start = datetime.datetime.fromtimestamp(stamps[0] / 1000)
    end = datetime.datetime.fromtimestamp(stamps[-1] / 1000)
    if start.date() == end.date():
        return f"{start:%m-%d} {start:%H:%M}-{end:%H:%M}"
    return f"{start:%m-%d %H:%M} - {end:%m-%d %H:%M}"


def _result_color(ret):
    ret = _int(ret)
    if ret == 1:
        return "胜利", (115, 225, 162, 255)
    if ret == 0:
        return "平局", (255, 218, 117, 255)
    return "战败", (255, 112, 112, 255)


def _hero_icon_url(hero_guid):
    hero = HERO_LOOKUP.get(str(hero_guid), {}) or HERO_BY_GUID.get(str(hero_guid), {})
    return hero.get("smallIconUrl") or ""


def _canonical_hero_guid(hero_ref):
    hero = HERO_LOOKUP.get(str(hero_ref), {}) or HERO_BY_GUID.get(str(hero_ref), {})
    return str(hero.get("heroGuid") or hero_ref or "")


def _hero_aliases(hero_ref):
    canonical_guid = _canonical_hero_guid(hero_ref)
    aliases = list(HERO_ALIASES_BY_GUID.get(canonical_guid, []))
    raw_key = str(hero_ref or "")
    if raw_key and raw_key not in aliases:
        aliases.insert(0, raw_key)
    if canonical_guid and canonical_guid not in aliases:
        aliases.insert(0, canonical_guid)
    return [alias for alias in aliases if alias]


def _map_icon_url(map_guid):
    return MAP_BY_GUID.get(str(map_guid), {}).get("icon") or ""


def _role_cn(hero_guid):
    return {
        "Tank": "重装",
        "Damage": "输出",
        "Support": "支援",
    }.get(_role_label(hero_guid), "未知")


def _counter_wins_by_guid(matches, guid_key):
    data = defaultdict(lambda: {"total": 0, "wins": 0})
    for match in matches:
        guid = match.get(guid_key)
        if not guid:
            continue
        key = str(guid)
        data[key]["total"] += 1
        if _int(match.get("matchRet")) == 1:
            data[key]["wins"] += 1
    return data


def _period_title_line(stats):
    total = max(stats["total"], 1)
    wr = stats["wins"] / total

    if wr >= 0.7:
        state = "手感很热"
    elif wr >= 0.5:
        state = "节奏在线"
    elif wr >= 0.35:
        state = "有点拉扯"
    else:
        state = "被赛博雨淋了一会儿"
    return f"今日状态：{state}。"


def _streak_segments(matches):
    segments = []
    current = None
    count = 0
    for match in sorted(matches or [], key=lambda item: item.get("beginTs") or 0):
        ret = _int(match.get("matchRet"))
        state = 1 if ret == 1 else (-1 if ret == -1 else 0)
        if state == 0:
            if count:
                segments.append((current, count))
                current, count = None, 0
            continue
        if current is None or state != current:
            if count:
                segments.append((current, count))
            current, count = state, 1
        else:
            count += 1
    if count:
        segments.append((current, count))
    return segments


def _build_period_story(matches, stats):
    sorted_matches = sorted(matches or [], key=lambda item: item.get("beginTs") or 0)
    total = len(sorted_matches)
    if total <= 2:
        return "今日剧本：浅尝几局，很快收工。"

    first_half = sorted_matches[: max(1, total // 2)]
    second_half = sorted_matches[max(1, total // 2):]
    first_wr = sum(1 for match in first_half if _int(match.get("matchRet")) == 1) / max(1, len(first_half))
    second_wr = sum(1 for match in second_half if _int(match.get("matchRet")) == 1) / max(1, len(second_half))
    segments = _streak_segments(sorted_matches)
    longest_win = max([count for state, count in segments if state == 1] or [0])
    longest_loss = max([count for state, count in segments if state == -1] or [0])

    if second_wr - first_wr >= 0.3 and stats["wins"] >= stats["losses"]:
        return "今日剧本：前段慢热，中段回暖，收尾顺风。"
    if first_wr - second_wr >= 0.3 and stats["losses"] > stats["wins"]:
        return "今日剧本：开局有声有色，后半段逐渐坐牢。"
    if longest_win >= 4 and longest_win > longest_loss:
        return f"今日剧本：中途打出一波 {longest_win} 连胜，节奏直接拉满。"
    if longest_loss >= 4 and longest_loss >= longest_win:
        return f"今日剧本：中段吃了 {longest_loss} 连败，今天主打硬扛。"
    if abs(second_wr - first_wr) < 0.15:
        return "今日剧本：整天都在拉扯，输赢交替起伏。"
    if stats["wins"] > stats["losses"]:
        return "今日剧本：波动不小，但总体还是赚分的一天。"
    if stats["wins"] < stats["losses"]:
        return "今日剧本：偶有高光，可惜整体还是逆风。"
    return "今日剧本：从头到尾五五开，谁也不肯让。"


def _build_streak_summary(matches):
    segments = _streak_segments(matches)
    longest_win = max([count for state, count in segments if state == 1] or [0])
    longest_loss = max([count for state, count in segments if state == -1] or [0])
    return f"连胜连败：最长连胜 {longest_win} 场，最长连败 {longest_loss} 场"


def _build_data_king(detail_pairs, resolved_target):
    best_by_rule = {}
    metric_rules = [
        ("伤害王", "heroDamage", 12000, "单场最高伤害"),
        ("治疗王", "cure", 10000, "单场最高治疗"),
        ("承伤王", "resistDamage", 9000, "单场最高阻挡"),
        ("收割王", "finalHit", 15, "单场最后一击"),
        ("单挑王", "soloKills", 5, "单场单杀"),
        ("推车王", "targetCompetingTime", 90, "单场夺点时间"),
    ]

    for match, detail in detail_pairs:
        root = _detail_root(detail)
        if not root:
            continue
        _, me, _ = _find_me(root, resolved_target)
        if not me:
            continue
        for title, key, divisor, label in metric_rules:
            raw_value = _num(me.get(key))
            if key == "finalHit":
                raw_value = _num(me.get("finalHit") or me.get("finalBlows"))
            if raw_value <= 0:
                continue
            score = raw_value / max(divisor, 1)
            candidate = {
                "score": score,
                "title": title,
                "label": label,
                "value": raw_value,
                "map_guid": match.get("mapGuid") or root.get("mapGuid"),
                "hero_guid": me.get("heroGuid") or match.get("heroGuid"),
            }
            current_best = best_by_rule.get(title)
            if current_best is None or candidate["score"] > current_best["score"]:
                best_by_rule[title] = candidate

    result = []
    for title, _, _, label in metric_rules:
        best = best_by_rule.get(title)
        if not best:
            continue
        if label == "单场夺点时间":
            best["value_text"] = _fmt_time(best["value"])
        else:
            best["value_text"] = _fmt_int(best["value"])
        result.append(best)
    return result


def _extract_hero_stat_time(stat_map, hero=None):
    if isinstance(hero, dict):
        hero_user_time = _num(hero.get("userTimeSec"))
        if hero_user_time > 0:
            return hero_user_time
    if not isinstance(stat_map, dict):
        return 0
    for key in ("603482350067646497", 603482350067646497):
        if key in stat_map:
            return _num(stat_map.get(key))
    return 0


def _get_stat_value(stat_map, guid, default=0):
    if guid in stat_map:
        return stat_map.get(guid, default)
    try:
        return stat_map.get(int(guid), default)
    except (TypeError, ValueError):
        return default


def _get_cached_statmap_summary(lookup_key, stat_guids, rank_buckets, ratio_stat_guids, prefer_rank):
    result = _shared_get_cached_statmap_summary(
        _GROUP_TITLE_DB,
        lookup_key,
        stat_guids,
        rank_buckets,
        ratio_stat_guids,
        prefer_rank,
        cache_max=SUMMARY_STATMAP_REFERENCE_CACHE_MAX,
    )
    cache_key = (
        str(lookup_key),
        tuple(sorted(str(item) for item in (stat_guids or []))),
        tuple(sorted(str(item) for item in (rank_buckets or []))) if rank_buckets is not None else None,
        tuple(sorted(str(item) for item in (ratio_stat_guids or []))),
        bool(prefer_rank),
    )
    _SUMMARY_STATMAP_REFERENCE_CACHE[cache_key] = result
    while len(_SUMMARY_STATMAP_REFERENCE_CACHE) > SUMMARY_STATMAP_REFERENCE_CACHE_MAX:
        _SUMMARY_STATMAP_REFERENCE_CACHE.popitem(last=False)
    return result


def _build_period_stat_highlights(detail_pairs, resolved_target):
    band_priority = {"above_median": 1, "top20": 2, "top10": 3, "top5": 4, "top2": 5}
    hero_instances = []
    hero_stat_guids = defaultdict(set)
    hero_lookup_keys = defaultdict(set)

    for match, detail in detail_pairs:
        me = _resolve_me_player_detail(detail, resolved_target)
        if not me:
            continue
        rank_bucket = _normalize_hero_rank_score(get_rank_score(me.get("rankInfo") or me.get("rank_info") or {}))
        match_map_guid = match.get("mapGuid") or _detail_root(detail).get("mapGuid")
        for hero in me.get("heroList", []) or []:
            hero_id = str(hero.get("heroGuid") or hero.get("heroId") or "")
            stat_map = hero.get("statMap", {}) or {}
            if not hero_id or not stat_map:
                continue
            canonical_guid = _canonical_hero_guid(hero_id)
            lookup_keys = _hero_aliases(hero_id)
            user_time_sec = _num(hero.get("userTimeSec")) or _get_stat_value(stat_map, GAME_TIME_GUID, 0)
            if user_time_sec < 100:
                continue
            hero_instances.append((canonical_guid, lookup_keys, rank_bucket, stat_map, user_time_sec, match_map_guid))
            hero_lookup_keys[canonical_guid].update(lookup_keys)
            for guid in stat_map.keys():
                guid = str(guid)
                stat_name = str(ATTR_TEXT_BY_GUID.get(guid) or guid)
                if guid in HERO_AVG_SKIP_VALUE_GUIDS or guid in PERIOD_HIGHLIGHT_EXCLUDED_GUIDS:
                    continue
                if stat_name in PERIOD_HIGHLIGHT_EXCLUDED_TEXTS:
                    continue
                hero_stat_guids[canonical_guid].add(guid)

    avg_reference_cache = {}
    rank_buckets_by_hero = defaultdict(set)
    for canonical_guid, _, rank_bucket, _, _, _ in hero_instances:
        if rank_bucket is not None:
            rank_buckets_by_hero[canonical_guid].add(rank_bucket)

    for canonical_guid, stat_guids in hero_stat_guids.items():
        stat_guids = sorted(stat_guids)
        if not stat_guids:
            continue
        ratio_stat_guids = _get_hero_avg_percent_guids(stat_guids)
        lookup_keys = list(hero_lookup_keys.get(canonical_guid) or [canonical_guid])
        for lookup_key in lookup_keys:
            refs_all = _get_cached_statmap_summary(
                lookup_key,
                stat_guids,
                None,
                ratio_stat_guids,
                False,
            ) or {}
            for (stat_guid, rank_key), stat in refs_all.items():
                avg_reference_cache[(str(lookup_key), str(stat_guid), rank_key)] = stat
            ranked_buckets = sorted(rank_buckets_by_hero.get(canonical_guid, set()))
            if not ranked_buckets:
                continue
            refs_ranked = _get_cached_statmap_summary(
                lookup_key,
                stat_guids,
                ranked_buckets,
                ratio_stat_guids,
                True,
            ) or {}
            for (stat_guid, rank_key), stat in refs_ranked.items():
                avg_reference_cache[(str(lookup_key), str(stat_guid), rank_key)] = stat

    candidates = []
    for canonical_guid, lookup_keys, rank_bucket, stat_map, user_time_sec, match_map_guid in hero_instances:
        for guid, raw_value in stat_map.items():
            guid = str(guid)
            stat_name = str(ATTR_TEXT_BY_GUID.get(guid) or guid)
            if guid in HERO_AVG_SKIP_VALUE_GUIDS or guid in PERIOD_HIGHLIGHT_EXCLUDED_GUIDS:
                continue
            if stat_name in PERIOD_HIGHLIGHT_EXCLUDED_TEXTS:
                continue

            ref = None
            for lookup_key in lookup_keys:
                ref = avg_reference_cache.get((str(lookup_key), guid, rank_bucket))
                if ref:
                    break
            if not ref:
                for lookup_key in lookup_keys:
                    ref = avg_reference_cache.get((str(lookup_key), guid, None))
                    if ref:
                        break
            if not ref or not ref.get("count"):
                continue

            current_value = normalize_dashen_hero_stat_value(raw_value, user_time_sec, stat_name, guid)
            if current_value is None:
                continue

            band = _classify_hero_average_band(current_value, ref)
            if band not in band_priority:
                continue

            avg_value = ref.get("avg") or 0
            if avg_value and current_value <= avg_value:
                continue
            avg_ratio = (current_value / avg_value) if avg_value else 0
            candidates.append({
                "hero_guid": canonical_guid,
                "hero_name": _hero_name(canonical_guid),
                "value_guid": guid,
                "value_text": stat_name,
                "value_display": _format_hero_avg_value(current_value, stat_name),
                "raw_value_display": _format_hero_avg_value(raw_value, stat_name),
                "map_guid": match_map_guid,
                "band": band,
                "color": PERIOD_HIGHLIGHT_BAND_COLORS.get(band, (246, 248, 255)),
                "avg_ratio": avg_ratio,
                "current": current_value,
            })

    deduped = {}
    for item in candidates:
        key = (item["hero_guid"], item["value_guid"])
        best = deduped.get(key)
        score = (band_priority.get(item["band"], 0), item["avg_ratio"], item["current"])
        if best is None or score > (
            band_priority.get(best["band"], 0),
            best["avg_ratio"],
            best["current"],
        ):
            deduped[key] = item

    return sorted(
        deduped.values(),
        key=lambda item: (band_priority.get(item["band"], 0), item["avg_ratio"], item["current"]),
        reverse=True,
    )[:9]


def _summary_winrate_color(total, wins):
    return (100, 255, 120) if wins / max(total, 1) >= 0.5 else (255, 100, 100)


def _build_period_profile_tag(stats, matches, highlights):
    detail_total_games = max(1, stats.get("detail_count") or len(matches or []) or stats.get("total") or 1)
    total_games = max(1, stats.get("total") or len(matches or []) or 1)
    hours = [
        datetime.datetime.fromtimestamp(_num(match.get("beginTs")) / 1000).hour
        for match in matches or []
        if isinstance(match, dict) and match.get("beginTs")
    ]
    avg_hour = sum(hours) / len(hours) if hours else 15
    is_group = bool(stats.get("friends"))
    wr_val = stats.get("wins", 0) / total_games
    top_h_guid = stats["heroes"].most_common(1)[0][0] if stats.get("heroes") else None
    top_h_name = _hero_name(top_h_guid) if top_h_guid else "未知"

    prefixes = []

    if 0 <= avg_hour < 5:
        prefixes.extend(["深夜", "修仙", "不见太阳", "绝不睡觉", "月下"])
    elif 5 <= avg_hour < 9:
        prefixes.extend(["早起", "晨练", "养生", "自律"])
    elif 9 <= avg_hour < 12:
        prefixes.extend(["上午", "元气", "摸鱼", "早班"])
    elif 12 <= avg_hour < 14:
        prefixes.extend(["午休", "干饭", "忙里偷闲"])
    elif 14 <= avg_hour < 18:
        prefixes.extend(["白日", "阳光", "下午茶", "慵懒"])
    else:
        prefixes.extend(["黄金档", "下班后", "高强度", "夜间", "热血"])

    if is_group:
        prefixes.extend(["组排", "开黑", "抱大腿", "带妹", "社交牛逼症", "欢声笑语"])
    else:
        prefixes.extend(["孤狼", "单排", "自闭", "寂寞", "独来独往", "不想说话", "高冷"])

    if wr_val < 0.3:
        prefixes.extend(["深受ELO伤害", "被系统制裁", "心态崩了", "含泪", "一直在输", "做慈善", "破防"])
    elif wr_val < 0.45:
        prefixes.extend(["手感冰凉", "运气不佳", "尽力局", "带不动"])
    elif wr_val > 0.7:
        prefixes.extend(["手感火热", "不可阻挡", "重拳出击", "狂虐对手", "带飞全场", "天神下凡"])
    elif wr_val > 0.55:
        prefixes.extend(["顺风顺水", "稳扎稳打", "上分", "状态在线"])

    if stats["total_time"] > 6 * 3600:
        prefixes.extend(["肝疼", "住在守望", "不知疲倦", "除了OW没事做", "守望先锋启动"])
    elif stats["total_time"] > 3 * 3600:
        prefixes.extend(["高强度", "沉迷", "热爱"])
    elif stats["total_time"] < 1800:
        prefixes.extend(["随便玩玩", "光速下播", "试水", "摸一把就走"])

    avg_kda = (stats["total_kill"] + stats["total_assist"]) / max(1, stats["total_death"])
    best_kda = (highlights.get("best") or {}).get("kda")
    worst_kda = (highlights.get("worst") or {}).get("kda")
    kda_gap = (best_kda - worst_kda) if best_kda is not None and worst_kda is not None else 0

    if avg_kda > 5.5:
        prefixes.extend(["KDA怪物", "保命专家", "不死", "存活大师", "惜命"])
    if avg_kda < 1.2:
        prefixes.extend(["敢死队", "复活赛常客", "送能量", "勇往直前", "头铁"])
    if kda_gap > 6:
        prefixes.extend(["发挥不稳定", "神鬼二象性", "看天吃饭", "看状态", "上下限极大"])
    elif kda_gap < 0.8 and detail_total_games > 4:
        prefixes.extend(["发挥稳定", "坚若磐石", "稳如老狗", "莫得感情", "机器人"])

    endorse_get = sum(stats["endorse_received"].values())
    avg_endorse = endorse_get / detail_total_games
    if endorse_get >= 6 or avg_endorse >= 0.8:
        prefixes.extend(["受人爱戴", "社交达人", "人缘好", "好队友", "大家都爱", "文明"])

    if stats.get("total_solo_kills", 0) > detail_total_games * 2:
        prefixes.extend(["独行侠", "刺客信条", "单挑王"])
    fleta_idx = stats.get("total_final_hit", 0) / max(1, stats.get("total_kill", 0))
    if fleta_idx > 0.6:
        prefixes.extend(["人头狗", "收割机", "K头怪", "补刀大神"])

    if not prefixes:
        prefixes.append("普普通通")

    suffixes = []
    h_hitscan = ["士兵：76", "卡西迪", "艾什", "黑百合", "索杰恩", "巴蒂斯特", "安娜", "伊拉锐", "毛加", "D.Va", "破坏球", "猎空", "黑影", "堡垒", "死神", "路霸", "渣客女王"]
    h_proj = ["法老之鹰", "源氏", "狂鼠", "半藏", "美", "托比昂", "禅雅塔", "拉玛刹", "奥丽莎", "回声", "西格玛", "卢西奥", "雾子", "生命之梭", "朱诺", "弗蕾娅", "无漾", "骇灾", "探奇", "斩仇"]
    h_beam = ["查莉娅", "莱因哈特", "温斯顿", "莫伊拉", "秩序之光", "回声", "美", "布丽吉塔"]
    h_mobile = ["猎空", "源氏", "黑影", "卢西奥", "破坏球", "末日铁拳", "温斯顿", "D.Va", "回声", "法老之鹰", "朱诺", "探奇", "斩仇"]

    if top_h_name in h_hitscan and top_h_name not in ["D.Va", "毛加"]:
        suffixes.extend(["描边大师", "神射手", "点名机器", "瞄准人", "长枪位", "外挂(误)"])
    if top_h_name in h_proj and top_h_name not in ["奥丽莎", "西格玛"]:
        suffixes.extend(["随缘射手", "几何学家", "摸奖专家", "弹道玩家", "抽奖人"])
    if top_h_name in h_beam:
        suffixes.extend(["跟枪怪", "滋崩人", "光波使用者", "不瞄准玩家"])
    if top_h_name in h_mobile:
        suffixes.extend(["多动症患者", "后排噩梦", "跑酷选手", "狗位"])

    hero_titles = {
        "天使": ["守护天使", "挂件", "全职保姆", "急救包"],
        "织飞": ["救护车"],
        "无漾": ["小天才"],
        "末日铁拳": ["上勾拳", "卤蛋", "小黑子", "蓝拳"],
        "源氏": ["幼儿源", "拔刀", "只有我看得到", "小金人"],
        "骇灾": ["三体人", "数值怪", "紫薯精"],
        "探奇": ["地鼠", "钻头", "考古学家"],
        "朱诺": ["火星人", "外星来客"],
        "斩仇": ["狼女", "大剑", "狂战士"],
        "莱因哈特": ["大锤", "举盾侠", "冲锋战神"],
        "路霸": ["充电宝", "钩子"],
        "温斯顿": ["电疗师", "猩猩"],
        "D.Va": ["核爆"],
        "黑百合": ["望远镜"],
        "半藏": ["随缘箭"],
        "狂鼠": ["轮胎"],
        "托比昂": ["炮台架设者", "小矮人"],
        "堡垒": ["推土机"],
        "卢西奥": ["滑墙", "DJ"],
        "禅雅塔": ["武僧", "易伤怪"],
    }
    for hero_name, titles in hero_titles.items():
        if hero_name in top_h_name:
            suffixes.extend(titles)

    h_tank = ["D.Va", "末日铁拳", "渣客女王", "毛加", "奥丽莎", "拉玛刹", "莱因哈特", "路霸", "西格玛", "温斯顿", "破坏球", "查莉娅", "骇灾", "弗蕾娅"]
    h_dps = ["艾什", "堡垒", "卡西迪", "回声", "源氏", "半藏", "狂鼠", "美", "法老之鹰", "死神", "索杰恩", "士兵：76", "黑影", "秩序之光", "托比昂", "猎空", "探奇", "黑百合", "斩仇"]
    h_support = ["安娜", "巴蒂斯特", "布丽吉塔", "伊拉锐", "朱诺", "雾子", "生命之梭", "卢西奥", "天使", "莫伊拉", "禅雅塔", "无漾"]

    if top_h_name in h_tank:
        suffixes.extend(["重装驾驶员", "肉盾", "挨揍位", "泥头车司机", "主T"])
    if top_h_name in h_dps:
        suffixes.extend(["输出位", "C位", "杀手", "破坏者"])
    if top_h_name in h_support:
        suffixes.extend(["奶妈", "辅助", "医务兵", "后勤保障", "奶爸"])

    if wr_val < 0.25:
        suffixes.extend(["小天使", "倒霉蛋", "慈善家", "分母", "红地毯铺设者", "受害者", "背锅位"])
    elif wr_val > 0.75:
        suffixes.extend(["通天代", "炸鱼佬", "上分机器", "大魔王", "不是人"])
    else:
        suffixes.extend(["特工", "玩家", "英雄", "老司机", "混子", "路人", "打工人"])

    avg_dmg = stats["total_damage"] / detail_total_games
    avg_heal = stats["total_healing"] / detail_total_games
    avg_block = stats["total_blocked"] / detail_total_games

    if avg_dmg > 13000:
        suffixes.extend(["输出机器", "伤害制造者", "火力全开", "重炮手", "核能C位"])
    elif avg_dmg < 4000 and top_h_name in h_dps:
        suffixes.extend(["描边师傅", "人体描边", "滋水枪", "无效输出"])

    if avg_heal > 11000:
        suffixes.extend(["神医", "移动血包", "活菩萨", "众星之子", "大奶"])
    if avg_block > 9000:
        suffixes.extend(["叹息之墙", "坚盾", "守护者", "城墙"])
    if endorse_get >= 5:
        suffixes.extend(["明星", "人气王", "团队之光", "吉祥物"])
    if total_games > 15:
        suffixes.extend(["卷王", "劳模"])
    if len(stats["maps"]) > 8:
        suffixes.extend(["探险家", "环球旅行者"])

    if not suffixes:
        suffixes.append("特工")

    return f"{random.choice(prefixes)}的{random.choice(suffixes)}"


def _daily_win_stats(matches):
    daily_stats = {}
    for match in matches or []:
        if not isinstance(match, dict) or not match.get("beginTs"):
            continue
        day_key = datetime.datetime.fromtimestamp(_num(match.get("beginTs")) / 1000).date()
        if day_key not in daily_stats:
            daily_stats[day_key] = {"wins": 0, "total": 0}
        daily_stats[day_key]["total"] += 1
        if _int(match.get("matchRet")) == 1:
            daily_stats[day_key]["wins"] += 1
    return daily_stats


def _weather_win_color(day_stats):
    if not day_stats or not day_stats.get("total"):
        return (40, 46, 58, 170), (120, 132, 150), "-"
    ratio = day_stats["wins"] / max(day_stats["total"], 1)
    if ratio > 0.65:
        return (255, 140, 0, 230), (255, 255, 255), "晴"
    if ratio >= 0.50:
        return (135, 206, 235, 225), (20, 30, 42), "云"
    if ratio >= 0.35:
        return (105, 112, 124, 220), (255, 255, 255), "阴"
    return (70, 130, 180, 230), (255, 255, 255), "雨"


def _summary_rainbow_colors():
    return [
        (255, 110, 110),
        (255, 176, 74),
        (255, 218, 117),
        (117, 223, 174),
        (139, 216, 255),
        (177, 135, 255),
    ]


def _draw_rainbow_text(draw, x, y, text, font):
    cursor_x = x
    colors = _summary_rainbow_colors()
    for idx, char in enumerate(str(text or "")):
        draw.text((cursor_x, y), char, font=font, fill=colors[idx % len(colors)])
        cursor_x += _text_size(draw, char, font)[0]
    return cursor_x


def _draw_rainbow_segments(draw, box, radius=8):
    x1, y1, x2, y2 = [int(v) for v in box]
    colors = _summary_rainbow_colors()
    total_w = max(1, x2 - x1)
    seg_w = max(1, total_w // len(colors))
    for idx, color in enumerate(colors):
        seg_x1 = x1 + idx * seg_w
        seg_x2 = x2 if idx == len(colors) - 1 else min(x2, seg_x1 + seg_w)
        draw.rounded_rectangle((seg_x1, y1, seg_x2, y2), radius=radius, fill=color)


def _draw_period_weather_calendar(draw, matches, x, y, w, h):
    daily_stats = _daily_win_stats(matches)
    if not daily_stats:
        draw.text((x, y), "暂无足够日期数据。", font=_load_font(18), fill=(145, 155, 170))
        return 120

    end_day = max(daily_stats)
    start_day = end_day - datetime.timedelta(days=41)
    while start_day.weekday() != 0:
        start_day -= datetime.timedelta(days=1)
    total_days = (end_day - start_day).days + 1
    total_weeks = max(1, (total_days + 6) // 7)

    draw.text((x, y), "最近胜率晴雨表", font=_load_font(18, bold=True), fill=(238, 242, 248))
    draw.text((x + 166, y + 2), f"{start_day:%m-%d} 至 {end_day:%m-%d}", font=_load_font(14), fill=(160, 174, 194))

    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    cell_w, cell_h, gap = 42, 30, 6
    grid_x, grid_y = x, y + 54
    for idx, label in enumerate(weekdays):
        draw.text((grid_x + idx * (cell_w + gap) + 14, y + 29), label, font=_load_font(12), fill=(150, 164, 184))

    for day_idx in range(total_weeks * 7):
        day = start_day + datetime.timedelta(days=day_idx)
        col = day_idx % 7
        row = day_idx // 7
        cx = grid_x + col * (cell_w + gap)
        cy = grid_y + row * (cell_h + gap)
        day_stats = daily_stats.get(day)
        fill, text_fill, weather_label = _weather_win_color(day_stats)
        outline = (255, 218, 117, 210) if day == end_day else (74, 88, 112, 140)
        draw.rounded_rectangle((cx, cy, cx + cell_w, cy + cell_h), radius=6, fill=fill, outline=outline, width=1)
        draw.text((cx + 6, cy + 5), f"{day.day}", font=_load_font(13, bold=True), fill=text_fill)
        if day_stats and day_stats.get("total"):
            draw.text((cx + 24, cy + 6), str(day_stats["total"]), font=_load_font(10), fill=text_fill)
        elif weather_label == "-":
            draw.text((cx + 27, cy + 6), "-", font=_load_font(10), fill=(120, 132, 150))

    legend_x = x + 370
    legend_y = y + 54
    legend_items = [
        ("晴 >65%", (255, 140, 0, 230)),
        ("多云 50-65%", (135, 206, 235, 225)),
        ("阴 35-50%", (105, 112, 124, 220)),
        ("雨 <35%", (70, 130, 180, 230)),
    ]
    for idx, (label, color) in enumerate(legend_items):
        yy = legend_y + idx * 28
        draw.rounded_rectangle((legend_x, yy + 3, legend_x + 18, yy + 21), radius=4, fill=color)
        draw.text((legend_x + 28, yy), label, font=_load_font(14), fill=(218, 228, 242))

    ranked_days = sorted(
        ((day, data["wins"], data["total"]) for day, data in daily_stats.items() if data.get("total")),
        key=lambda item: (item[1] / item[2], item[2]),
        reverse=True,
    )
    if ranked_days:
        best_day, best_wins, best_total = ranked_days[0]
        low_day, low_wins, low_total = sorted(
            ranked_days,
            key=lambda item: (item[1] / item[2], -item[2]),
        )[0]
        draw.text((legend_x, legend_y + 134), "最佳天气", font=_load_font(15, bold=True), fill=(255, 218, 117))
        draw.text((legend_x, legend_y + 160), f"{best_day:%m-%d}  {best_wins}/{best_total}  {_fmt_pct(best_wins, best_total)}", font=_load_font(14), fill=(218, 228, 242))
        draw.text((legend_x, legend_y + 190), "低迷天气", font=_load_font(15, bold=True), fill=(139, 216, 255))
        draw.text((legend_x, legend_y + 216), f"{low_day:%m-%d}  {low_wins}/{low_total}  {_fmt_pct(low_wins, low_total)}", font=_load_font(14), fill=(218, 228, 242))
    return 54 + total_weeks * (cell_h + gap)


def _build_period_highlights(detail_pairs, resolved_target):
    highlights = {"best": None, "worst": None, "shortest": None, "longest": None, "best_fleta": None}

    def better_kda(entry, current):
        return current is None or entry["kda"] > current["kda"]

    def worse_kda(entry, current):
        return current is None or entry["kda"] < current["kda"]

    def better_fleta(entry, current):
        return current is None or entry["fleta"] > current["fleta"]

    for match, detail in detail_pairs:
        root = _detail_root(detail)
        if not root:
            continue
        _, me, _ = _find_me(root, resolved_target)
        if not me:
            continue
        hero_guid = me.get("heroGuid") or match.get("heroGuid")
        if not hero_guid and me.get("heroList"):
            hero_item = me.get("heroList")[0] or {}
            hero_guid = hero_item.get("heroGuid") or hero_item.get("heroId")
        game_time = _int(root.get("gameTimeSec"))
        kills = _int(me.get("kill"))
        assists = _int(me.get("assist"))
        deaths = max(1, _int(me.get("death")))
        my_final_hit = _int(me.get("finalHit") or me.get("finalBlows"))
        teammate_list = root.get("teammateList") or []
        team_final_hit = sum(_int(player.get("finalHit") or player.get("finalBlows")) for player in teammate_list)
        fleta = (my_final_hit / (team_final_hit * 0.5) * 100) if team_final_hit > 0 else 0
        entry = {
            "match": match,
            "map_guid": match.get("mapGuid") or root.get("mapGuid"),
            "hero_guid": hero_guid,
            "kda": (kills + assists) / deaths,
            "fleta": fleta,
            "game_time": game_time,
            "result": _int(match.get("matchRet")),
        }
        if better_kda(entry, highlights["best"]):
            highlights["best"] = entry
        if worse_kda(entry, highlights["worst"]):
            highlights["worst"] = entry
        if better_fleta(entry, highlights["best_fleta"]):
            highlights["best_fleta"] = entry
        if game_time and (highlights["shortest"] is None or game_time < highlights["shortest"]["game_time"]):
            highlights["shortest"] = entry
        if game_time and (highlights["longest"] is None or game_time > highlights["longest"]["game_time"]):
            highlights["longest"] = entry
    return highlights


async def _paste_remote_cover(canvas, box, url, radius=8, tint=(8, 12, 20, 125)):
    x1, y1, x2, y2 = box
    width = int(x2 - x1)
    height = int(y2 - y1)
    cache_key = (str(url or "").strip(), width, height, int(radius), tuple(tint or ()))
    cached_cover = _get_cached_summary_cover_copy(cache_key)
    if cached_cover is not None:
        canvas.paste(cached_cover, (x1, y1), _rounded_mask(cached_cover.size, radius))
        return True

    image = await _load_summary_image(url)
    if not image:
        return False
    image = _cover_fit(image, (width, height))
    if tint:
        image = Image.alpha_composite(image, Image.new("RGBA", image.size, tint))
    _put_summary_cover_cache(cache_key, image)
    canvas.paste(image, (x1, y1), _rounded_mask(image.size, radius))
    return True


async def _draw_teammate_spotlight(draw, canvas, box, title, entries, color, is_worst=False):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=8, fill=(28, 36, 50, 185), outline=color, width=1)
    draw.text((x1 + 14, y1 + 10), title, font=_load_font(16, bold=True), fill=color)
    draw.line((x1 + 12, y1 + 34, x2 - 12, y1 + 34), fill=(55, 60, 75), width=1)

    if is_worst and entries and all(_num(entry.get("kda")) > 1.0 for entry in entries):
        draw.text((x1 + 16, y1 + 52), "队友都挺能打", font=_load_font(15, bold=True), fill=(100, 255, 180))
        return
    if not entries:
        draw.text((x1 + 16, y1 + 52), "暂无记录", font=_load_font(14), fill=(145, 155, 170))
        return

    for idx, entry in enumerate(entries[:3]):
        row_y = y1 + 42 + idx * 34
        hero_icon = await _load_summary_image(_hero_icon_url(entry.get("heroGuid")))
        if hero_icon:
            hero_icon = _cover_fit(hero_icon, (24, 24))
            canvas.paste(hero_icon, (x1 + 14, row_y + 3), _rounded_mask((24, 24), 12))
        else:
            draw.ellipse((x1 + 14, row_y + 3, x1 + 38, row_y + 27), fill=(55, 65, 82, 210))

        name_font = _load_font(14, bold=True)
        risk_font = _load_font(8, bold=True)
        risk_width, risk_height, _ = measure_risk_status_badge(
            draw,
            entry.get("risk_status"),
            font=risk_font,
            compact=True,
            padding_x=4,
            padding_y=2,
            max_width=90,
        )
        name_max_width = max(92, 210 - risk_width - (6 if risk_width else 0))
        name_text = _truncate_to_width(draw, entry.get("name"), name_font, name_max_width)
        draw.text((x1 + 46, row_y + 1), name_text, font=name_font, fill=(246, 248, 255))
        if risk_width:
            name_width = _text_size(draw, name_text, name_font)[0]
            draw_risk_status_badge(
                draw,
                x1 + 46 + name_width + 6,
                row_y + max(1, int((28 - risk_height) / 2)),
                entry.get("risk_status"),
                font=risk_font,
                compact=True,
                padding_x=4,
                padding_y=2,
                max_width=90,
            )

        kda_text = f"KDA {_num(entry.get('kda')):.2f}"
        map_text = _truncate_to_width(draw, _map_name(entry.get("mapGuid")), _load_font(12), max(80, x2 - x1 - 300))
        kda_w = _text_size(draw, kda_text, _load_font(12, bold=True))[0]
        draw.text((x2 - 16 - kda_w, row_y + 2), kda_text, font=_load_font(12, bold=True), fill=(255, 218, 117))
        draw.text((x1 + 46, row_y + 18), map_text, font=_load_font(12), fill=(160, 174, 194))

        if idx < min(len(entries[:3]), 3) - 1:
            draw.line((x1 + 12, row_y + 32, x2 - 12, row_y + 32), fill=(48, 52, 65), width=1)


def _draw_party_summary(draw, stats, x, y, w):
    party_names = {1: "单排", 2: "双排", 3: "三排", 4: "四排", 5: "五排"}
    draw.text((x, y), "队伍人数", font=_load_font(14, bold=True), fill=(255, 218, 117))
    max_party = max(stats["party"].values() or [1])
    cell_w = w / 5
    for idx, size in enumerate(range(1, 6)):
        total = stats["party"][size]
        wins = stats["party_wins"][size]
        cell_x = x + idx * cell_w
        draw.text((cell_x, y + 24), party_names[size], font=_load_font(12), fill=(170, 182, 200))
        _draw_bar(draw, cell_x, y + 43, cell_w - 16, 7, total / max_party if total else 0, (255, 198, 92, 230))
        value = f"{total}场"
        if total:
            value += f" {_fmt_pct(wins, total)}"
        draw.text((cell_x + 42, y + 24), value, font=_load_font(12), fill=_summary_winrate_color(total, wins) if total else (120, 132, 150))


def _draw_teammate_fun_awards(draw, stats, x, y, w):
    awards = _teammate_fun_awards(stats)
    if not awards:
        return
    draw.text((x, y), "一些奇怪的金牌", font=_load_font(14, bold=True), fill=(255, 218, 117))

    cell_gap = 8
    cell_w = int((w - cell_gap) / 2)
    cell_h = 58
    start_y = y + 24
    kind_fill = {"好友": (117, 223, 174, 220), "路人": (139, 216, 255, 210)}

    for idx, award in enumerate(awards):
        col = idx % 2
        row = idx // 2
        x1 = int(x + col * (cell_w + cell_gap))
        y1 = int(start_y + row * 66)
        x2 = x1 + cell_w
        y2 = y1 + cell_h
        draw.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=(33, 35, 46, 215), outline=(65, 70, 90), width=1)
        draw.text((x1 + 10, y1 + 7), award["title"], font=_load_font(14, bold=True), fill=(246, 248, 255))
        kind_w = _text_size(draw, award["kind"], _load_font(10, bold=True))[0]
        badge_x2 = x2 - 10
        badge_x1 = badge_x2 - kind_w - 12
        draw.rounded_rectangle((badge_x1, y1 + 7, badge_x2, y1 + 23), radius=4, fill=kind_fill.get(award["kind"], (139, 216, 255, 210)))
        draw.text((badge_x1 + 6, y1 + 8), award["kind"], font=_load_font(10, bold=True), fill=(18, 24, 34))
        draw.text((x1 + 10, y1 + 28), _truncate_to_width(draw, award["name"], _load_font(13, bold=True), cell_w - 20), font=_load_font(13, bold=True), fill=(218, 228, 242))
        draw.text((x1 + 10, y1 + 46), award["value"], font=_load_font(11), fill=(170, 182, 200))


async def _render_period_image(
    stats,
    resolved_target,
    matches,
    detail_pairs,
    title_text,
    all_matches=None,
    quick_dist_data=None,
    render_stage_log=None,
):
    def _render_step(stage, extra=None):
        if not render_stage_log:
            return
        try:
            render_stage_log(stage, extra)
        except Exception:
            pass

    _render_step(
        "START",
        extra=(
            f"match_count={len(matches or [])}; "
            f"detail_count={len(detail_pairs or [])}; "
            f"all_match_count={len(all_matches or []) if isinstance(all_matches, list) else 0}"
        ),
    )
    contact_rows = _period_contact_rows(stats)
    party_summary_height = _party_summary_height(stats)
    teammate_spotlight_height = _teammate_spotlight_height(stats)
    teammate_awards_height = _teammate_awards_height(stats)
    full_id = str(resolved_target.get("full_id") or "Unknown Player")
    display_name = full_id
    display_suffix = ""
    if "#" in full_id:
        display_name, suffix = full_id.split("#", 1)
        display_suffix = f"#{suffix}"
    visual_title_text = {
        "今日测试": "今日总结",
        "本周测试": "本周总结",
    }.get(title_text, title_text)
    period_scope_text = visual_title_text[:2]
    period_text = _period_range_text(matches)
    kda = (stats["total_kill"] + stats["total_assist"]) / max(stats["total_death"], 1)
    hero_win_rows = _counter_wins_by_guid(matches, "heroGuid")
    map_win_rows = stats["maps"]
    highlights = _build_period_highlights(detail_pairs, resolved_target)
    profile_tag = _build_period_profile_tag(stats, matches, highlights)
    carry_baseline = _carry_baseline(stats)
    state_text = _period_title_line(stats).replace("今日状态：", "", 1).strip()
    if state_text.endswith("。"):
        state_text = state_text[:-1]
    story_text = _build_period_story(matches, stats).replace("今日剧本：", "", 1).strip()
    if story_text.endswith("。"):
        story_text = story_text[:-1]
    streak_text = _build_streak_summary(matches).replace("连胜连败：", "", 1).strip()
    data_king_text = _build_data_king(detail_pairs, resolved_target)
    stat_highlights = _build_period_stat_highlights(detail_pairs, resolved_target)
    header_line = f"{state_text}，{story_text}。".strip("，")

    hero_rows_all = stats["heroes"].most_common()
    hero_top_rows = hero_rows_all[:5]
    other_heroes = hero_rows_all[5:]
    other_hero_rows = (len(other_heroes) + 2) // 3 if other_heroes else 0
    hero_other_height = 48 + other_hero_rows * 62 if other_heroes else 0

    width = 1400
    measure_draw = ImageDraw.Draw(Image.new("RGBA", (width, 320), (0, 0, 0, 0)))
    name_font = _load_font(44, bold=True)
    title_font = _load_font(22, bold=True)
    risk_badge_font = _load_font(16, bold=True)
    display_name = _truncate_to_width(measure_draw, display_name, name_font, 420)
    name_x = 190
    name_y = 70
    name_w, name_h = _text_size(measure_draw, display_name, name_font)
    risk_badge_x = name_x + name_w + 16
    risk_badge_max_width = max(96, min(250, 802 - risk_badge_x))
    risk_badge_width, risk_badge_height, _ = measure_risk_status_badge(
        measure_draw,
        resolved_target.get("risk_status"),
        font=risk_badge_font,
        compact=True,
        padding_x=9,
        padding_y=4,
        max_width=risk_badge_max_width,
    )
    risk_badge_y = name_y + max(0, int((name_h - risk_badge_height) / 2))
    identity_end_x = name_x + name_w
    if risk_badge_width:
        identity_end_x = risk_badge_x + risk_badge_width
    player_titles = _get_group_titles_safe(resolved_target.get("bnet_id"))
    badges_bottom = max(name_y + name_h, risk_badge_y + risk_badge_height)
    if player_titles:
        badge_center_y = 92 if identity_end_x <= 450 else 178
        badge_start_x = identity_end_x + 16 if badge_center_y == 92 else name_x
        _, _, title_badges_bottom = _draw_group_title_badges(
            measure_draw,
            player_titles,
            badge_start_x,
            badge_center_y,
            width - 30,
            badge_height=34,
            badge_gap=10,
            max_badge_width=140,
            min_badge_width=64,
            padding_x=12,
            max_font_size=18,
            min_font_size=12,
            allow_wrap=True,
            wrap_start_x=name_x,
            row_gap=8,
        )
        badges_bottom = max(badges_bottom, title_badges_bottom)
    subtitle_y = max(128, int(badges_bottom) + 12)
    profile_y = subtitle_y + 38
    period_y = profile_y + 38
    header_line_y = period_y + 32
    top_y1 = max(340, header_line_y + 64)
    hero_card_h = max(308, 78 + len(hero_top_rows) * 64 + hero_other_height + 24)
    stats_highlight_rows = (len(stat_highlights) + 2) // 3 if stat_highlights else 0
    stats_highlight_h = 38 + stats_highlight_rows * 94 if stat_highlights else 0
    stats_card_h = max(290, 250 + stats_highlight_h)
    top_section_h = max(hero_card_h, stats_card_h)

    mid_y1 = top_y1 + top_section_h + 30
    map_rows = sorted(map_win_rows.items(), key=lambda item: (item[1]["total"], item[1]["wins"]), reverse=True)
    map_card_h = max(310, 78 + len(map_rows) * 58 + 20)
    team_rows_h = 78 + (len(contact_rows) * 28 if contact_rows else 40)
    team_card_h = max(
        295,
        team_rows_h
        + (party_summary_height + 12 if party_summary_height else 0)
        + (teammate_spotlight_height + 12 if teammate_spotlight_height else 0)
        + (teammate_awards_height + 12 if teammate_awards_height else 0)
        + 20,
    )
    mid_section_h = max(map_card_h, team_card_h)

    timeline_y1 = mid_y1 + mid_section_h + 30
    sorted_matches = sorted(matches, key=lambda item: item.get("beginTs") or 0)
    timeline_rows = max(1, (len(sorted_matches) + 14) // 15) if sorted_matches else 1
    timeline_h = 126 + timeline_rows * 88
    quick_dist_y1 = timeline_y1 + timeline_h + 30
    quick_dist_h = 220
    bottom_y1 = quick_dist_y1 + quick_dist_h + 30
    highlight_rows_total = 5 + max(1, len(data_king_text))
    weather_source_matches = all_matches if all_matches else matches
    weather_daily_stats = _daily_win_stats(weather_source_matches)
    if weather_daily_stats:
        weather_end_day = max(weather_daily_stats)
        weather_start_day = weather_end_day - datetime.timedelta(days=41)
        while weather_start_day.weekday() != 0:
            weather_start_day -= datetime.timedelta(days=1)
        weather_total_days = (weather_end_day - weather_start_day).days + 1
        weather_total_weeks = max(1, (weather_total_days + 6) // 7)
    else:
        weather_total_weeks = 6
    weather_panel_h = 120 + weather_total_weeks * 36
    bottom_h = max(428, 96 + highlight_rows_total * 52, weather_panel_h + 54)
    footer_y = bottom_y1 + bottom_h + 18

    height = footer_y + 30
    _render_step(
        "LAYOUT_READY",
        extra=(
            f"size={width}x{height}; heroes={len(hero_rows_all)}; maps={len(map_rows)}; "
            f"contacts={len(contact_rows)}; timeline_rows={timeline_rows}; "
            f"data_king={len(data_king_text)}; stat_highlights={len(stat_highlights)}"
        ),
    )
    prefetch_urls = [resolved_target.get("icon_url")]
    prefetch_urls.extend(_map_icon_url(match.get("mapGuid")) for match in (matches or []) if match.get("mapGuid"))
    prefetch_urls.extend(_hero_icon_url(hero_guid) for hero_guid, _ in hero_rows_all)
    prefetch_urls.extend(_hero_icon_url(item.get("hero_guid")) for item in stat_highlights)
    for entry in highlights.values():
        if entry:
            prefetch_urls.append(_hero_icon_url(entry.get("hero_guid")))
            prefetch_urls.append(_map_icon_url(entry.get("map_guid")))
    for entry in data_king_text:
        prefetch_urls.append(_hero_icon_url(entry.get("hero_guid")))
        prefetch_urls.append(_map_icon_url(entry.get("map_guid")))
    for entry in (stats.get("top3_strongest") or []) + (stats.get("top3_worst") or []):
        prefetch_urls.append(_hero_icon_url(entry.get("heroGuid")))
    await _prefetch_summary_images(prefetch_urls)
    _render_step("ASSET_PREFETCH_DONE", extra=f"url_candidates={len(prefetch_urls)}")

    canvas = await _make_period_background((width, height), matches)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _render_step("BACKGROUND_DONE")

    avatar = await _load_summary_image(resolved_target.get("icon_url"))
    if avatar:
        avatar = _cover_fit(avatar, (110, 110))
        canvas.paste(avatar, (55, 55), _rounded_mask((110, 110), 55))
    else:
        draw.ellipse((55, 55, 165, 165), fill=(28, 36, 50, 220), outline=(96, 126, 160, 180), width=2)

    draw.text((name_x, name_y), display_name, font=name_font, fill=(255, 255, 255))
    if risk_badge_width:
        draw_risk_status_badge(
            draw,
            risk_badge_x,
            risk_badge_y,
            resolved_target.get("risk_status"),
            font=risk_badge_font,
            compact=True,
            padding_x=9,
            padding_y=4,
            max_width=risk_badge_max_width,
        )
    if player_titles:
        _draw_group_title_badges(
            draw,
            player_titles,
            badge_start_x,
            badge_center_y,
            width - 30,
            badge_height=34,
            badge_gap=10,
            max_badge_width=140,
            min_badge_width=64,
            padding_x=12,
            max_font_size=18,
            min_font_size=12,
            allow_wrap=True,
            wrap_start_x=name_x,
            row_gap=8,
        )
    subtitle_text = f"{display_suffix} · {visual_title_text}" if display_suffix else visual_title_text
    draw.text((name_x, subtitle_y), subtitle_text, font=title_font, fill=(180, 180, 200))
    profile_label = f"{period_scope_text}画像："
    draw.text((name_x, profile_y), profile_label, font=_load_font(24), fill=(220, 220, 220))
    label_w = _text_size(draw, profile_label, _load_font(24))[0]
    draw.text((name_x + label_w, profile_y), profile_tag, font=_load_font(24), fill=(255, 215, 0))
    draw.text((name_x, period_y), period_text, font=_load_font(20), fill=(165, 178, 198))
    header_line = _truncate_to_width(draw, header_line, _load_font(18), 1110)
    draw.text((name_x, header_line_y), header_line, font=_load_font(18), fill=(165, 178, 198))

    metric_y = 72
    _draw_metric(draw, 820, metric_y, "总场次", stats["total"], (139, 216, 255))
    _draw_metric(draw, 980, metric_y, "胜率", _fmt_pct(stats["wins"], stats["total"]), _summary_winrate_color(stats["total"], stats["wins"]))
    _draw_metric(draw, 1150, metric_y, "KDA", f"{kda:.2f}", (165, 235, 185))
    _render_step("HEADER_DONE")

    _card(draw, (50, top_y1, 665, top_y1 + top_section_h), f"{visual_title_text[:2]}常用英雄排行")
    if not hero_top_rows:
        draw.text((75, top_y1 + 72), "暂无英雄数据", font=_load_font(18), fill=(145, 155, 170))
    hero_start_y = top_y1 + 76
    max_hero = max([count for _, count in hero_top_rows] or [1])
    for idx, (hero_guid, count) in enumerate(hero_top_rows):
        row_y = hero_start_y + idx * 64
        hero_icon = await _load_summary_image(_hero_icon_url(hero_guid))
        ring_color = _hero_ring_color(_role_label(hero_guid))
        draw.ellipse((75, row_y, 123, row_y + 48), fill=ring_color, outline=(255, 255, 255, 120), width=1)
        if hero_icon:
            hero_icon = _cover_fit(hero_icon, (44, 44))
            canvas.paste(hero_icon, (77, row_y + 2), _rounded_mask((44, 44), 22))
        draw.text((135, row_y + 1), _hero_name(hero_guid), font=_load_font(20, bold=True), fill=(238, 242, 248))
        medal_x = 135 + _text_size(draw, _hero_name(hero_guid), _load_font(20, bold=True))[0] + 10
        medal_data = stats["hero_medals"].get(str(hero_guid), {})
        for medal_text, medal_value, medal_color in (
            ("K", medal_data.get("K", 0), (255, 50, 50)),
            ("H", medal_data.get("H", 0), (255, 215, 0)),
            ("D", medal_data.get("D", 0), (180, 80, 255)),
            ("M", medal_data.get("M", 0), (200, 200, 200)),
        ):
            if medal_value <= 0:
                continue
            label = f"{medal_text}×{medal_value}"
            medal_font = _load_font(13, bold=True)
            label_w = _text_size(draw, label, medal_font)[0]
            draw.rounded_rectangle((medal_x, row_y + 2, medal_x + label_w + 14, row_y + 22), radius=4, fill=medal_color)
            luminance = 0.299 * medal_color[0] + 0.587 * medal_color[1] + 0.114 * medal_color[2]
            draw.text((medal_x + 7, row_y + 4), label, font=medal_font, fill=(20, 20, 20) if luminance > 140 else (255, 255, 255))
            medal_x += label_w + 19
        wins = hero_win_rows.get(str(hero_guid), {}).get("wins", 0)
        total = hero_win_rows.get(str(hero_guid), {}).get("total", count)
        _draw_bar(draw, 135, row_y + 32, 480, 6, count / max_hero, (0, 160, 255, 230), bg=(50, 52, 65, 210))
        draw.text((medal_x + 4, row_y + 3), f"{count}场", font=_load_font(16), fill=(180, 180, 190))
        draw.text((542, row_y + 3), f"胜率 {int(round((wins / max(total, 1)) * 100))}%", font=_load_font(16), fill=_summary_winrate_color(total, wins))

    if other_heroes:
        compact_title_y = hero_start_y + len(hero_top_rows) * 64 + 8
        draw.text((75, compact_title_y), "其他上场英雄", font=_load_font(18), fill=(180, 180, 200))
        compact_y = compact_title_y + 38
        box_x1, box_x2 = 75, 640
        box_h = other_hero_rows * 62 + 16
        draw.rounded_rectangle((box_x1, compact_y, box_x2, compact_y + box_h), radius=8, fill=(33, 35, 46), outline=(65, 70, 90), width=1)
        cell_w = (box_x2 - box_x1) // 3
        for idx, (hero_guid, count) in enumerate(other_heroes):
            col = idx % 3
            row = idx // 3
            cell_x = box_x1 + col * cell_w
            cell_y = compact_y + row * 62 + 8
            hero_icon = await _load_summary_image(_hero_icon_url(hero_guid))
            if hero_icon:
                hero_icon = _cover_fit(hero_icon, (42, 42))
                canvas.paste(hero_icon, (cell_x + 8, cell_y + 4), _rounded_mask((42, 42), 21))
            draw.text((cell_x + 58, cell_y + 4), f"{count}场", font=_load_font(14), fill=(200, 205, 220))
            oh_wins = hero_win_rows.get(str(hero_guid), {}).get("wins", 0)
            oh_total = hero_win_rows.get(str(hero_guid), {}).get("total", count)
            draw.text((cell_x + 58, cell_y + 25), _fmt_pct(oh_wins, oh_total), font=_load_font(14), fill=_summary_winrate_color(oh_total, oh_wins))
            if col < 2 and idx < len(other_heroes) - 1:
                split_x = cell_x + cell_w
                draw.line((split_x, compact_y + 4, split_x, compact_y + box_h - 4), fill=(65, 70, 90), width=1)
    _render_step("HERO_CARD_DONE", extra=f"top={len(hero_top_rows)}; other={len(other_heroes)}")

    _card(draw, (705, top_y1, 1350, top_y1 + top_section_h), "总体数据")
    metrics = [
        ("击杀", _fmt_int(stats["total_kill"])),
        ("助攻", _fmt_int(stats["total_assist"])),
        ("死亡", _fmt_int(stats["total_death"])),
        ("伤害", _fmt_int(stats["total_damage"])),
        ("治疗", _fmt_int(stats["total_healing"])),
        ("阻挡", _fmt_int(stats["total_blocked"])),
        ("夺点时间", _fmt_time(stats["total_objective_time"])),
        ("被赞", sum(stats["endorse_received"].values())),
        ("点赞", sum(stats["endorse_given"].values())),
        ("游玩时间", _fmt_time(stats["total_time"])),
    ]
    for idx, (label, value) in enumerate(metrics):
        x = 735 + (idx % 5) * 118
        y = top_y1 + 76 + (idx // 5) * 76
        _draw_small_metric(draw, x, y, label, value)
    stats_highlight_y = top_y1 + 238
    if stat_highlights:
        draw.text((735, stats_highlight_y), "亮眼表现", font=_load_font(15, bold=True), fill=(255, 218, 117))
        cell_w = 188
        cell_h = 84
        cell_gap_x = 10
        cell_gap_y = 10
        for idx, item in enumerate(stat_highlights):
            col = idx % 3
            row = idx // 3
            cell_x = int(735 + col * (cell_w + cell_gap_x))
            cell_y = int(stats_highlight_y + 26 + row * (cell_h + cell_gap_y))
            cell_box = (cell_x, cell_y, cell_x + cell_w, cell_y + cell_h)
            accent = item.get("color", (246, 248, 255))
            draw.rounded_rectangle(cell_box, radius=8, fill=(30, 33, 45, 220), outline=accent, width=1)
            if item.get("band") == "top2":
                _draw_rainbow_segments(draw, (cell_x + 2, cell_y + 2, cell_x + cell_w - 2, cell_y + 8), radius=6)
            hero_icon = await _load_summary_image(_hero_icon_url(item.get("hero_guid")))
            if hero_icon:
                hero_icon = _cover_fit(hero_icon, (30, 30))
                canvas.paste(hero_icon, (cell_x + 10, cell_y + 10), _rounded_mask((30, 30), 15))
            else:
                draw.ellipse((cell_x + 10, cell_y + 10, cell_x + 40, cell_y + 40), fill=(55, 65, 82, 210))
            draw.text((cell_x + 48, cell_y + 8), _truncate_to_width(draw, item.get("hero_name"), _load_font(14, bold=True), 86), font=_load_font(14, bold=True), fill=(246, 248, 255))
            draw.text((cell_x + 48, cell_y + 28), _truncate_to_width(draw, item.get("value_text"), _load_font(11), 90), font=_load_font(11), fill=(170, 182, 200))
            raw_value_text = item.get("raw_value_display", item.get("value_display", "-"))
            value_text = item.get("value_display", "-")
            raw_value_font = _fit_text_font(draw, raw_value_text, 78, 19, 12, bold=True)
            raw_value_w = _text_size(draw, raw_value_text, raw_value_font)[0]
            value_x = cell_x + cell_w - 10 - raw_value_w
            value_y = cell_y + 12
            if item.get("band") == "top2":
                _draw_rainbow_text(draw, value_x, value_y, raw_value_text, raw_value_font)
            else:
                draw.text((value_x, value_y), raw_value_text, font=raw_value_font, fill=accent)
            rate_line = f"{value_text}/10min"
            rate_font = _fit_text_font(draw, rate_line, 112, 10, 8, bold=False)
            rate_w = _text_size(draw, rate_line, rate_font)[0]
            draw.text((cell_x + cell_w - 10 - rate_w, cell_y + 39), rate_line, font=rate_font, fill=(170, 182, 200))
            map_name = _map_name(item.get("map_guid"))
            draw.text((cell_x + 10, cell_y + 55), _truncate_to_width(draw, map_name, _load_font(10), cell_w - 20), font=_load_font(10), fill=(145, 155, 170))
    else:
        draw.text((735, stats_highlight_y), "暂无亮眼表现数据", font=_load_font(15), fill=(190, 204, 222))
    _render_step("SUMMARY_STATS_DONE", extra=f"stat_highlights={len(stat_highlights)}")

    _card(draw, (50, mid_y1, 665, mid_y1 + mid_section_h), "地图足迹")
    if not map_rows:
        draw.text((75, mid_y1 + 72), "暂无地图数据", font=_load_font(18), fill=(145, 155, 170))
    for idx, (map_guid, data) in enumerate(map_rows):
        row_y = mid_y1 + 76 + idx * 58
        row_box = (75, row_y, 640, row_y + 50)
        if not await _paste_remote_cover(canvas, row_box, _map_icon_url(map_guid), radius=8, tint=(8, 12, 20, 145)):
            draw.rounded_rectangle(row_box, radius=8, fill=(28, 36, 50, 210))
        map_name = _map_name(map_guid)
        map_font = _fit_text_font(draw, map_name, 300, 18, 12, bold=True)
        draw.text((92, row_y + 12), map_name, font=map_font, fill=(246, 248, 255))
        draw.text((402, row_y + 13), f'{data["total"]}场', font=_load_font(16), fill=(218, 228, 242))
        draw.text((515, row_y + 13), _fmt_pct(data["wins"], data["total"]), font=_load_font(16), fill=_summary_winrate_color(data["total"], data["wins"]))
    _render_step("MAP_CARD_DONE", extra=f"map_rows={len(map_rows)}")

    _card(draw, (705, mid_y1, 1350, mid_y1 + mid_section_h), "组队")
    draw.text((735, mid_y1 + 72), "同玩ID", font=_load_font(15, bold=True), fill=(145, 155, 170))
    draw.text((1032, mid_y1 + 72), "局数", font=_load_font(15, bold=True), fill=(145, 155, 170))
    draw.text((1105, mid_y1 + 72), "胜率", font=_load_font(15, bold=True), fill=(145, 155, 170))
    draw.text((1195, mid_y1 + 72), "带飞指数", font=_load_font(15, bold=True), fill=(145, 155, 170))
    team_table_y = mid_y1 + 108
    if contact_rows:
        for idx, (kind, name, data) in enumerate(contact_rows):
            row_y = team_table_y + idx * 28
            is_friend = kind == "好友"
            badge_color = (117, 223, 174, 230) if is_friend else (139, 216, 255, 220)
            draw.rounded_rectangle((735, row_y + 3, 775, row_y + 21), radius=4, fill=badge_color)
            draw.text((743, row_y + 3), kind, font=_load_font(11, bold=True), fill=(18, 24, 34))
            name_font = _load_font(17, bold=True)
            risk_font = _load_font(8, bold=True)
            risk_width, risk_height, _ = measure_risk_status_badge(
                draw,
                data.get("risk_status"),
                font=risk_font,
                compact=True,
                padding_x=4,
                padding_y=2,
                max_width=84,
            )
            friend_name_max_width = max(90, 210 - risk_width - (6 if risk_width else 0))
            friend_name = _truncate_to_width(draw, name, name_font, friend_name_max_width)
            draw.text((784, row_y), friend_name, font=name_font, fill=(218, 228, 242))
            friend_name_w = _text_size(draw, friend_name, name_font)[0]
            title_badge_start_x = 784 + friend_name_w + 8
            if risk_width:
                risk_x = 784 + friend_name_w + 6
                draw_risk_status_badge(
                    draw,
                    risk_x,
                    row_y + max(1, int((24 - risk_height) / 2)),
                    data.get("risk_status"),
                    font=risk_font,
                    compact=True,
                    padding_x=4,
                    padding_y=2,
                    max_width=84,
                )
                title_badge_start_x = risk_x + risk_width + 4
            _draw_group_title_badges(
                draw,
                _get_group_titles_safe(data.get("bnet_id")),
                title_badge_start_x,
                row_y + 12,
                1018,
                badge_height=18,
                badge_gap=4,
                max_badge_width=62,
                min_badge_width=34,
                padding_x=6,
                max_font_size=10,
                min_font_size=8,
            )
            games = data.get("games", 0)
            wins = data.get("wins", 0)
            carry_ratio = _carry_ratio(data, carry_baseline)
            value_font = _load_font(16, bold=True)
            draw.text((1035, row_y + 1), str(games), font=value_font, fill=(246, 248, 255))
            draw.text((1105, row_y + 1), _fmt_pct(wins, games), font=value_font, fill=_summary_winrate_color(games, wins))
            draw.text((1202, row_y + 1), f"{carry_ratio:.0f}%", font=value_font, fill=_carry_color(carry_ratio))
    else:
        draw.text((735, team_table_y), "这段时间像个孤狼。", font=_load_font(16), fill=(160, 170, 185))

    current_team_y = team_table_y + (len(contact_rows) * 28 if contact_rows else 40)
    if party_summary_height:
        _draw_party_summary(draw, stats, 735, current_team_y + 10, 585)
        current_team_y += party_summary_height + 14
    if teammate_spotlight_height:
        strong_entries = stats.get("top3_strongest") or []
        worst_entries = stats.get("top3_worst") or []
        strong_h = 46 + max(1, len(strong_entries)) * 38
        worst_rows = 1 if (worst_entries and all(_num(entry.get("kda")) > 1.0 for entry in worst_entries)) else max(1, len(worst_entries))
        worst_h = 46 + worst_rows * 38
        await _draw_teammate_spotlight(
            draw,
            canvas,
            (735, current_team_y + 8, 1328, current_team_y + 8 + strong_h),
            "最强队友",
            strong_entries,
            (100, 255, 120),
            is_worst=False,
        )
        worst_y = current_team_y + 8 + strong_h + 10
        await _draw_teammate_spotlight(
            draw,
            canvas,
            (735, worst_y, 1328, worst_y + worst_h),
            "最差队友",
            worst_entries,
            (255, 100, 100),
            is_worst=True,
        )
        current_team_y = worst_y + worst_h
    if teammate_awards_height:
        _draw_teammate_fun_awards(draw, stats, 735, current_team_y + 18, 585)
    _render_step(
        "TEAM_CARD_DONE",
        extra=(
            f"contacts={len(contact_rows)}; party={bool(party_summary_height)}; "
            f"spotlight={bool(teammate_spotlight_height)}; awards={bool(teammate_awards_height)}"
        ),
    )

    _card(draw, (50, timeline_y1, 1350, timeline_y1 + timeline_h), "对局时间线")
    if sorted_matches:
        start_x, end_x = 90, 1310
        row_gap = 88
        for row_idx in range(timeline_rows):
            row_matches = sorted_matches[row_idx * 15:(row_idx + 1) * 15]
            line_y = timeline_y1 + 98 + row_idx * row_gap
            draw.line((start_x, line_y, end_x, line_y), fill=(93, 112, 140, 145), width=2)
            step = (end_x - start_x) / (len(row_matches) + 1)
            for idx, match in enumerate(row_matches):
                x = start_x + (idx + 1) * step
                _, color = _result_color(match.get("matchRet"))
                draw.ellipse((x - 7, line_y - 7, x + 7, line_y + 7), fill=color)
                dt = datetime.datetime.fromtimestamp(_num(match.get("beginTs")) / 1000)
                map_label = _short_name(_map_name(match.get("mapGuid")), 6)
                time_label = dt.strftime("%m-%d %H:%M") if period_scope_text == "本周" else dt.strftime("%H:%M")
                map_w = _text_size(draw, map_label, _load_font(13))[0]
                time_w = _text_size(draw, time_label, _load_font(12))[0]
                draw.text((x - map_w / 2, line_y - 36), map_label, font=_load_font(13), fill=(218, 228, 242))
                draw.text((x - time_w / 2, line_y + 20), time_label, font=_load_font(12), fill=(165, 178, 198))
        streak_y = timeline_y1 + 98 + (timeline_rows - 1) * row_gap + 38
        draw.text((75, streak_y), streak_text, font=_load_font(13), fill=(190, 204, 222))
    else:
        draw.text((75, timeline_y1 + 72), "暂无时间线数据", font=_load_font(18), fill=(145, 155, 170))
    _render_step("TIMELINE_DONE", extra=f"matches={len(sorted_matches)}; rows={timeline_rows}")

    _card(draw, (50, quick_dist_y1, 1350, quick_dist_y1 + quick_dist_h), "快速强度分布图")
    _draw_quick_strength_distribution(draw, (50, quick_dist_y1 + 52, 1350, quick_dist_y1 + quick_dist_h - 10), quick_dist_data)
    _render_step(
        "QUICK_DIST_DONE",
        extra=f"points={len((quick_dist_data or {}).get('sampled_matches') or [])}",
    )

    _card(draw, (50, bottom_y1, 665, bottom_y1 + bottom_h), "高光数据")
    highlight_rows = [
        ("最高KDA", highlights.get("best"), "kda"),
        ("最低KDA", highlights.get("worst"), "kda"),
        ("最高fleta指数", highlights.get("best_fleta"), "fleta"),
        ("最快结束", highlights.get("shortest"), "time"),
        ("最久拉扯", highlights.get("longest"), "time"),
    ]
    for entry in data_king_text:
        highlight_rows.append((entry.get("title") or "高光数据王", entry, "data_king"))
    for idx, (label, entry, value_type) in enumerate(highlight_rows):
        row_y = bottom_y1 + 72 + idx * 52
        if value_type == "text":
            draw.rounded_rectangle((75, row_y, 640, row_y + 38), radius=8, fill=(28, 36, 50, 210))
            draw.text((90, row_y + 9), f"{label}：{entry}", font=_load_font(15), fill=(218, 228, 242))
            continue
        if value_type == "data_king":
            if not entry:
                draw.text((75, row_y + 8), f"{label}：暂无有效详情", font=_load_font(16), fill=(145, 155, 170))
                continue
            row_box = (75, row_y, 640, row_y + 42)
            if not await _paste_remote_cover(canvas, row_box, _map_icon_url(entry.get("map_guid")), radius=8, tint=(8, 12, 20, 165)):
                draw.rounded_rectangle(row_box, radius=8, fill=(28, 36, 50, 210))
            hero_icon = await _load_summary_image(_hero_icon_url(entry.get("hero_guid")))
            if hero_icon:
                hero_icon = _cover_fit(hero_icon, (30, 30))
                canvas.paste(hero_icon, (90, row_y + 6), _rounded_mask((30, 30), 15))
            draw.text((132, row_y + 10), label, font=_load_font(16, bold=True), fill=(246, 248, 255))
            draw.text((260, row_y + 11), _short_name(_map_name(entry.get("map_guid")), 12), font=_load_font(15), fill=(218, 228, 242))
            value_line = f"{entry.get('label')} {entry.get('value_text')}"
            value_line = _truncate_to_width(draw, value_line, _load_font(15), 180)
            draw.text((450, row_y + 11), value_line, font=_load_font(15), fill=(255, 218, 117))
            continue
        if not entry:
            draw.text((75, row_y + 8), f"{label}：暂无详情", font=_load_font(16), fill=(145, 155, 170))
            continue
        row_box = (75, row_y, 640, row_y + 42)
        if not await _paste_remote_cover(canvas, row_box, _map_icon_url(entry.get("map_guid")), radius=8, tint=(8, 12, 20, 165)):
            draw.rounded_rectangle(row_box, radius=8, fill=(28, 36, 50, 210))
        hero_icon = await _load_summary_image(_hero_icon_url(entry.get("hero_guid")))
        if hero_icon:
            hero_icon = _cover_fit(hero_icon, (30, 30))
            canvas.paste(hero_icon, (90, row_y + 6), _rounded_mask((30, 30), 15))
        result_text, color = _result_color(entry.get("result"))
        if value_type == "kda":
            value = f'KDA {entry["kda"]:.2f}'
        elif value_type == "fleta":
            value = f'Fleta {entry["fleta"]:.2f}%'
        else:
            value = _fmt_time(entry["game_time"])
        draw.text((132, row_y + 10), label, font=_load_font(16, bold=True), fill=(246, 248, 255))
        draw.text((260, row_y + 11), _short_name(_map_name(entry.get("map_guid")), 12), font=_load_font(15), fill=(218, 228, 242))
        draw.text((450, row_y + 11), value, font=_load_font(15), fill=(255, 218, 117))
        draw.text((565, row_y + 11), result_text, font=_load_font(15), fill=color)
    _render_step("HIGHLIGHT_CARD_DONE", extra=f"rows={len(highlight_rows)}")

    _card(draw, (705, bottom_y1, 1350, bottom_y1 + bottom_h), "胜率晴雨表")
    _draw_period_weather_calendar(draw, weather_source_matches, 735, bottom_y1 + 67, 585, weather_panel_h)
    _render_step(
        "WEATHER_DONE",
        extra=f"source_matches={len(weather_source_matches or [])}; weeks={weather_total_weeks}",
    )

    footer = f"生成时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    draw.text((50, footer_y), footer, font=_load_font(14), fill=(130, 145, 166))
    result_image = canvas.convert("RGB")
    _render_step("CONVERT_DONE")
    return result_image


def _render_calendar(draw, stats, x, y, w):
    totals = stats["comp_hour_total"]
    wins = stats["comp_hour_wins"]
    max_total = max(totals.values() or [1])
    col_w = w / 6
    best = sorted(
        [(hour, wins[hour], totals[hour]) for hour in range(24) if totals[hour]],
        key=lambda item: (item[1] / item[2], item[2]),
        reverse=True,
    )[:3]
    for idx, (hour, win, total) in enumerate(best):
        yy = y + idx * 48
        ratio = win / total if total else 0
        draw.text((x, yy), f"{hour:02d}:00", font=_load_font(20, bold=True), fill=(255, 225, 120))
        draw.text((x + 82, yy + 3), f"{win}/{total}  {_fmt_pct(win, total)}", font=_load_font(17), fill=(224, 232, 242))
        _draw_bar(draw, x, yy + 27, w, 10, ratio, (255, 191, 77, 230))

    grid_y = y + 160
    for hour in range(24):
        gx = x + (hour % 6) * col_w
        gy = grid_y + (hour // 6) * 30
        total = totals[hour]
        ratio = wins[hour] / total if total else 0
        alpha = 65 + int(155 * (total / max_total)) if total else 42
        color = (75, 142, 226, alpha) if ratio < 0.5 else (255, 178, 72, alpha)
        draw.rounded_rectangle((gx, gy, gx + col_w - 8, gy + 22), radius=4, fill=color)
        draw.text((gx + 6, gy + 3), f"{hour:02d}", font=_load_font(12), fill=(238, 242, 248))


def _render_season_image(stats, resolved_target):
    width = height = 1400
    canvas = _make_background((width, height))
    draw = ImageDraw.Draw(canvas, "RGBA")

    display_name = str(resolved_target.get("full_id") or "Unknown Player")
    season_info = OW_CONFIG.get("seasonList", {}).get(str(season), {})
    season_text = f"S{season}"
    if season_info:
        season_text += f" | {season_info.get('startTime', '')}-{season_info.get('endTime', '')}"

    draw.text((54, 42), "赛季总结", font=_load_font(54, bold=True), fill=(255, 255, 255))
    name_font = _load_font(28, bold=True)
    risk_badge_font = _load_font(13, bold=True)
    display_name = _truncate_to_width(draw, display_name, name_font, 560)
    draw.text((58, 112), display_name, font=name_font, fill=(218, 228, 242))
    name_width, name_height = _text_size(draw, display_name, name_font)
    risk_badge_x = 58 + name_width + 12
    risk_badge_width, risk_badge_height, _ = measure_risk_status_badge(
        draw,
        resolved_target.get("risk_status"),
        font=risk_badge_font,
        compact=True,
        padding_x=8,
        padding_y=3,
        max_width=max(90, 850 - risk_badge_x),
    )
    if risk_badge_width:
        draw_risk_status_badge(
            draw,
            risk_badge_x,
            112 + max(0, int((name_height - risk_badge_height) / 2)),
            resolved_target.get("risk_status"),
            font=risk_badge_font,
            compact=True,
            padding_x=8,
            padding_y=3,
            max_width=max(90, 850 - risk_badge_x),
        )
    draw.text((58, 150), season_text, font=_load_font(20), fill=(165, 178, 198))

    _draw_metric(draw, 880, 54, "总场次", stats["total"], (139, 216, 255))
    _draw_metric(draw, 1040, 54, "胜率", _fmt_pct(stats["wins"], stats["total"]), (255, 218, 117))
    _draw_metric(draw, 1210, 54, "游玩时间", _fmt_time(stats["total_time"]), (165, 235, 185))

    _card(draw, (50, 210, 665, 500), "地图游玩")
    map_rows = sorted(
        stats["maps"].items(),
        key=lambda item: (item[1]["total"], item[1]["wins"]),
        reverse=True,
    )[:6]
    max_map_total = max([row[1]["total"] for row in map_rows] or [1])
    _draw_top_rows(
        draw,
        map_rows,
        75,
        282,
        550,
        35,
        lambda row: _short_name(_map_name(row[0]), 16),
        lambda row: f'{row[1]["total"]}场  {_fmt_pct(row[1]["wins"], row[1]["total"])}',
        lambda row: row[1]["total"] / max_map_total,
        (103, 191, 255, 230),
    )
    draw.text((75, 468), "地图距离趣味统计：暂时搁置", font=_load_font(14), fill=(135, 146, 165))

    _card(draw, (705, 210, 1350, 500), "总体数据")
    metrics = [
        ("总击杀", _fmt_int(stats["total_kill"])),
        ("助攻", _fmt_int(stats["total_assist"])),
        ("死亡", _fmt_int(stats["total_death"])),
        ("总伤害", _fmt_int(stats["total_damage"])),
        ("总治疗", _fmt_int(stats["total_healing"])),
        ("阻挡", _fmt_int(stats["total_blocked"])),
        ("收到伤害", _fmt_int(stats["total_damage_taken"])),
        ("收到治疗", _fmt_int(stats["total_healing_taken"])),
        ("占点时间", _fmt_time(stats["total_objective_time"])),
        ("最后一击", _fmt_int(stats["total_final_hit"])),
    ]
    for idx, (label, value) in enumerate(metrics):
        x = 735 + (idx % 5) * 120
        y = 280 + (idx // 5) * 62
        _draw_small_metric(draw, x, y, label, value, (246, 248, 255))

    kda = (stats["total_kill"] + stats["total_assist"]) / max(stats["total_death"], 1)
    damage_per_kill = stats["total_damage"] / max(stats["total_kill"], 1)
    damage_taken_per_death = stats["total_damage_taken"] / max(stats["total_death"], 1)
    fun_lines = [
        f"KDA {kda:.2f}",
        f"平均消灭一名玩家需要 {damage_per_kill:.0f} 伤害",
        f"平均死亡一次承受 {damage_taken_per_death:.0f} 伤害",
    ]
    draw.text((735, 424), "趣味数据", font=_load_font(16, bold=True), fill=(255, 218, 117))
    for idx, line in enumerate(fun_lines):
        draw.text((735, 450 + idx * 18), line, font=_load_font(14), fill=(190, 204, 222))

    _card(draw, (50, 530, 665, 825), "好友 / 路人 / 组排")
    friend_rows = sorted(stats["friends"].items(), key=lambda item: item[1]["games"], reverse=True)[:4]
    if friend_rows:
        max_friend = max(row[1]["games"] for row in friend_rows)
        _draw_top_rows(
            draw,
            friend_rows,
            75,
            602,
            300,
            42,
            lambda row: _short_name(row[0], 12),
            lambda row: f'{row[1]["games"]}场 {_fmt_pct(row[1]["wins"], row[1]["games"])}',
            lambda row: row[1]["games"] / max_friend,
            (117, 223, 174, 230),
        )
    else:
        draw.text((75, 602), "本季没识别到好友组队", font=_load_font(18), fill=(160, 170, 185))

    draw.text((415, 600), "常见路人", font=_load_font(18, bold=True), fill=(238, 242, 248))
    for idx, (name, count) in enumerate(stats["strangers"].most_common(3)):
        draw.text((415, 636 + idx * 31), f"{_short_name(name, 10)}  x{count}", font=_load_font(16), fill=(185, 199, 216))

    party_names = {1: "单排", 2: "双排", 3: "三排", 4: "四排", 5: "五排"}
    max_party = max(stats["party"].values() or [1])
    for idx, size in enumerate(range(1, 6)):
        total = stats["party"][size]
        x = 75 + idx * 112
        draw.text((x, 745), party_names[size], font=_load_font(15), fill=(170, 182, 200))
        _draw_bar(draw, x, 770, 82, 12, total / max_party if total else 0, (255, 198, 92, 230))
        draw.text((x, 790), f"{total}场", font=_load_font(13), fill=(190, 200, 215))

    _card(draw, (705, 530, 1350, 825), "威能选择")
    hero_rows = stats["heroes"].most_common(5)
    max_hero = max([row[1] for row in hero_rows] or [1])
    _draw_top_rows(
        draw,
        hero_rows,
        735,
        602,
        260,
        35,
        lambda row: _short_name(_hero_name(row[0]), 10),
        lambda row: f"{row[1]}场",
        lambda row: row[1] / max_hero,
        (255, 209, 102, 230),
    )
    draw.text((1040, 600), "威能ID", font=_load_font(18, bold=True), fill=(238, 242, 248))
    perk_rows = stats["perks"].most_common(5)
    if perk_rows:
        for idx, (guid, count) in enumerate(perk_rows):
            draw.text((1040, 636 + idx * 30), f"{str(guid)[-6:]}  x{count}", font=_load_font(16), fill=(190, 204, 222))
    else:
        draw.text((1040, 636), "暂无详情数据", font=_load_font(16), fill=(150, 162, 180))

    _card(draw, (50, 855, 665, 1210), "竞技比赛数据")
    comp_total = sum(v for k, v in stats["mode_total"].items() if "Comp" in k or "Competitive" in k)
    comp_wins = sum(stats["mode_wins"][k] for k in stats["mode_total"] if "Comp" in k or "Competitive" in k)
    _draw_metric(draw, 75, 930, "竞技场次", comp_total, (139, 216, 255))
    _draw_metric(draw, 270, 930, "竞技胜率", _fmt_pct(comp_wins, comp_total), (255, 218, 117))
    _draw_metric(draw, 465, 930, "有效详情", stats["detail_count"], (165, 235, 185))
    draw.text((75, 1030), "上分胜率时段表", font=_load_font(21, bold=True), fill=(238, 242, 248))
    _render_calendar(draw, stats, 75, 1070, 540)

    _card(draw, (705, 855, 1350, 1210), "游玩时间")
    hour_rows = [(h, stats["hours"][h]) for h in range(24) if stats["hours"][h]]
    max_hour = max([count for _, count in hour_rows] or [1])
    for hour in range(24):
        col = hour % 12
        row = hour // 12
        x = 735 + col * 47
        y = 930 + row * 95
        count = stats["hours"][hour]
        try:
            bar_h = int(58 * (float(count) / max(float(max_hour), 1.0))) if count else 0
        except (TypeError, ValueError, ZeroDivisionError):
            bar_h = 0
        bar_h = max(0, min(58, bar_h))
        fill = (113, 196, 255, 210) if count else (54, 62, 76, 150)
        bar_h = max(2, bar_h)
        top_y = int(y + 60 - bar_h)
        bottom_y = int(y + 60)
        if bottom_y < top_y:
            top_y, bottom_y = bottom_y, top_y
        draw.rounded_rectangle((x, top_y, x + 28, bottom_y), radius=4, fill=fill)
        draw.text((x, y + 68), f"{hour:02d}", font=_load_font(12), fill=(168, 180, 198))
    draw.text((735, 1148), "强度抽样：暂时搁置", font=_load_font(15), fill=(135, 146, 165))

    _card(draw, (50, 1240, 665, 1360), "点赞 / 被赞")
    received = sum(stats["endorse_received"].values())
    given = sum(stats["endorse_given"].values())
    _draw_metric(draw, 75, 1290, "被赞", received, (255, 218, 117))
    _draw_metric(draw, 220, 1290, "点赞", given, (139, 216, 255))
    draw.text((380, 1294), f"队友 {stats['endorse_received_team']} / 对手 {stats['endorse_received_enemy']}", font=_load_font(18), fill=(210, 222, 236))
    top_endorse = stats["endorse_received"].most_common(1)
    if top_endorse:
        draw.text((380, 1326), f"最常点赞你：{_short_name(top_endorse[0][0], 13)} x{top_endorse[0][1]}", font=_load_font(15), fill=(170, 184, 202))

    _card(draw, (705, 1240, 1350, 1360), "AI点评")
    draw.text((735, 1295), "暂时搁置。数据管线和方形版式已就绪。", font=_load_font(19), fill=(218, 228, 242))
    draw.text((735, 1328), f"生成时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", font=_load_font(14), fill=(140, 152, 170))

    return canvas.convert("RGB")


async def render_period_conclusion(
    bot,
    ev,
    resolved_target,
    matches,
    title_text,
    all_matches=None,
    image_message_formatter=None,
):
    perf_trace_id = f"{int(time.time())}-{getattr(ev, 'user_id', 'unknown')}"
    perf_started_at = time.perf_counter()
    perf_last_at = perf_started_at
    render_started_at = None
    render_last_at = None

    def _period_stage_log(stage, extra=None):
        nonlocal perf_last_at
        now_perf = time.perf_counter()
        delta_ms = int((now_perf - perf_last_at) * 1000)
        total_ms = int((now_perf - perf_started_at) * 1000)
        append_perf_log(title_text or "周期总结", perf_trace_id, stage, delta_ms, total_ms, extra)
        perf_last_at = now_perf

    def _period_render_stage_log(stage, extra=None):
        nonlocal render_started_at, render_last_at
        now_perf = time.perf_counter()
        if render_started_at is None or render_last_at is None:
            render_started_at = now_perf
            render_last_at = now_perf
        delta_ms = int((now_perf - render_last_at) * 1000)
        total_ms = int((now_perf - render_started_at) * 1000)
        append_perf_log(title_text or "周期总结", perf_trace_id, f"RENDER_{stage}", delta_ms, total_ms, extra)
        render_last_at = now_perf

    customer_token = resolved_target.get("customer_token")
    if not customer_token:
        await bot.finish(ev, "没有找到该玩家的大神 token，无法生成总结图。")
    resolved_target = await _ensure_resolved_target_risk_status(resolved_target)

    matches = [dict(match) for match in (matches or []) if isinstance(match, dict)]
    matches.sort(key=lambda item: item.get("beginTs") or 0, reverse=True)
    if not matches:
        await bot.finish(ev, f"{title_text}没有可用于生成的对局。")
    _period_stage_log(
        "REQUEST_READY",
        extra=(
            f"title={title_text}; match_count={len(matches)}; "
            f"all_match_count={len(all_matches or []) if isinstance(all_matches, list) else 0}"
        ),
    )

    detail_task = asyncio.create_task(_fetch_details(customer_token, matches))
    quick_dist_task = asyncio.create_task(_build_quick_strength_distribution_data(customer_token, matches))
    detail_pairs, quick_dist_data = await asyncio.gather(detail_task, quick_dist_task)
    _period_stage_log(
        "DETAIL_AND_QUICK_DIST_DONE",
        extra=(
            f"detail_count={len(detail_pairs)}; "
            f"quick_dist_points={len((quick_dist_data or {}).get('sampled_matches') or [])}"
        ),
    )
    stats = _build_stats(matches, detail_pairs, resolved_target)
    _period_stage_log("STATS_DONE")
    _period_stage_log("RENDER_QUEUE_START")
    image = await _run_summary_render_async(
        "period-image",
        lambda: _render_period_image(
            stats,
            resolved_target,
            matches,
            detail_pairs,
            title_text,
            all_matches=all_matches,
            quick_dist_data=quick_dist_data,
            render_stage_log=_period_render_stage_log,
        ),
    )
    _period_stage_log("RENDER_DONE")
    image_b64 = await _summary_png_b64_async(image, "period-image")
    _period_stage_log(
        "ENCODE_DONE",
        extra=f"payload_kb={_base64_payload_kb(image_b64)}; quality={SUMMARY_IMAGE_JPEG_QUALITY}",
    )
    await _send_summary_image(
        bot,
        ev,
        image_b64,
        image_message_formatter=image_message_formatter,
    )
    _period_stage_log("IMAGE_SENT")


async def render_season_conclusion(bot, ev, resolved_target, image_message_formatter=None):
    global _SEASON_SUMMARY_COMMAND_BUSY

    if _SEASON_SUMMARY_COMMAND_BUSY:
        await bot.finish(ev, "赛季总结正在生成中，请稍后再试。")

    _SEASON_SUMMARY_COMMAND_BUSY = True
    try:
        await _render_season_conclusion_locked(
            bot,
            ev,
            resolved_target,
            image_message_formatter=image_message_formatter,
        )
    finally:
        _SEASON_SUMMARY_COMMAND_BUSY = False


async def _render_season_conclusion_locked(
    bot,
    ev,
    resolved_target,
    image_message_formatter=None,
):
    full_id = resolved_target.get("full_id") or "Unknown Player"
    await bot.send(ev, f"正在生成 {full_id} 的赛季总结图，开始抓取本赛季对局...")

    customer_token = resolved_target.get("customer_token")
    if not customer_token:
        await bot.finish(ev, "没有找到该玩家的大神 token，无法生成赛季总结。")
    resolved_target = await _ensure_resolved_target_risk_status(resolved_target)

    matches = await _fetch_season_match_lists(customer_token)
    if not matches:
        await bot.finish(ev, "本赛季没有查到可用于总结的对局。")

    await bot.send(ev, f"已抓到 {len(matches)} 场本赛季对局，正在补充单场详情...")
    detail_pairs = await _fetch_details(customer_token, matches)
    stats = _build_stats(matches, detail_pairs, resolved_target)
    image = await _run_summary_render_sync(
        "season-image",
        _render_season_image,
        stats,
        resolved_target,
    )
    await _send_summary_image(
        bot,
        ev,
        await _summary_png_b64_async(image, "season-image"),
        image_message_formatter=image_message_formatter,
    )


async def render_season_conclusion_placeholder(
    bot,
    ev,
    resolved_target,
    image_message_formatter=None,
):
    await render_season_conclusion(
        bot,
        ev,
        resolved_target,
        image_message_formatter=image_message_formatter,
    )
