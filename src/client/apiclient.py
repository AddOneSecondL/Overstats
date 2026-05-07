from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import random
import tempfile
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

import httpx

try:
    from overstats.config import DashenClientConfig, DashenCredentialConfig, get_dashen_client_config
    from overstats.config import config as overstats_config
    from overstats.src.db.player_identity import record_identity_payload
    from overstats.src.db.request_metrics import normalize_request_metric_url
except ModuleNotFoundError:
    try:
        from config import config as overstats_config
        from config.loader import DashenClientConfig, DashenCredentialConfig, get_dashen_client_config
        from src.db.player_identity import record_identity_payload
        from src.db.request_metrics import normalize_request_metric_url
    except ModuleNotFoundError:
        overstats_config = None
        DashenClientConfig = Any  # type: ignore[misc,assignment]
        DashenCredentialConfig = Any  # type: ignore[misc,assignment]
        async def record_identity_payload(payload: Any, *, db: Any = None) -> int:
            return 0
        normalize_request_metric_url = lambda url: str(url or "").strip()  # type: ignore[assignment]

        def get_dashen_client_config() -> Any:
            raise RuntimeError("Dashen client config loader is unavailable.")

if TYPE_CHECKING:
    try:
        from overstats.src.db.request_metrics import RequestMetricsRecorder
    except ModuleNotFoundError:
        from src.db.request_metrics import RequestMetricsRecorder


def _getenv(primary: str, fallback: str, default: str) -> str:
    return os.getenv(primary, os.getenv(fallback, default))


def _config_value(name: str, default: Any) -> Any:
    if overstats_config is None:
        return default
    return getattr(overstats_config, name, default)


DASHEN_API_ROOT = "https://datamsapi.ds.163.com/v1/a19ld5tool"
DASHEN_CUSTOMER_API_BASE = f"{DASHEN_API_ROOT}/customer"
DASHEN_BILLBOARD_API_BASE = f"{DASHEN_API_ROOT}/billboard"
DATAMSAPI_HOST = httpx.URL(DASHEN_API_ROOT).host or "datamsapi.ds.163.com"

SEARCH_BNET_ACCOUNT_URL = "https://datamsapi.ds.163.com/v1/a19ld5tool/searchBnetAccount"
SEARCH_BNET_ACCOUNT_TIMEOUT = httpx.Timeout(6.0, connect=2.5, read=4.0, write=4.0, pool=2.0)

JD_HERO_OFFICIAL_URL = (
    "https://appapi.cc.163.com/v1/amandbop/bigdata/"
    "ads_ld5_play_stadium_recommend_lineup_data"
)
JD_EQ_OFFICIAL_URL = (
    "https://appapi.cc.163.com/v1/amandbop/bigdata/"
    "ads_ld5_play_staduim_recommend_mods_data"
)
JD_EQ_COMMUNITY_URL = (
    "https://appapi.cc.163.com/v1/amandbop/bigdata/"
    "community_play_staduim_recommend_mods_data"
)
OVERFAST_PLAYERS_URL = "https://overfast-api.tekrop.fr/players"
PANDASCORE_OW_MATCHES_URL = "https://api.pandascore.co/ow/matches"
REMOTE_IMAGE_CACHE_DIR = Path(__file__).resolve().parents[2] / "res" / "cache_img"


def _build_ow_esports_headers(api_key: Optional[str]) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    normalized = str(api_key or "").strip()
    if not normalized or normalized.lower().startswith("replace-with-your-"):
        return headers
    if normalized.lower().startswith("bearer "):
        headers["Authorization"] = normalized
    else:
        headers["Authorization"] = f"Bearer {normalized}"
    return headers


CLIENT_CONFIG = get_dashen_client_config()
OW_ESPORTS_API_KEY = CLIENT_CONFIG.ow_esports_api_key
OW_ESPORTS_HEADERS = _build_ow_esports_headers(OW_ESPORTS_API_KEY)

DASHEN_BIGDATA_DTS = int(CLIENT_CONFIG.bigdata_dts)
DASHEN_CLIENT_TYPE = CLIENT_CONFIG.client_type
DASHEN_ORIGIN = CLIENT_CONFIG.origin
DASHEN_REFERER = CLIENT_CONFIG.referer
DASHEN_USER_AGENT = CLIENT_CONFIG.user_agent
DASHEN_ACCOUNT_FAILURE_COOLDOWN_SECONDS = float(CLIENT_CONFIG.account_failure_cooldown_seconds)

MAX_CONCURRENT_REQUESTS = int(_getenv("OVERSTATS_DASHEN_MAX_CONCURRENT", "OVERSHOP_DASHEN_MAX_CONCURRENT", "300"))
DATAMSAPI_MAX_CONCURRENT_REQUESTS = int(
    os.getenv(
        "OVERSTATS_DASHEN_MAX_CONCURRENT_REQUESTS",
        str(_config_value("DASHEN_MAX_CONCURRENT_REQUESTS", 2)),
    )
)
MAX_BURST_CONCURRENT_REQUESTS = int(
    _getenv("OVERSTATS_DASHEN_BURST_CONCURRENT", "OVERSHOP_DASHEN_BURST_CONCURRENT", "150")
)
DASHEN_SLOW_REQUEST_SECONDS = float(_getenv("OVERSTATS_DASHEN_SLOW_SECONDS", "OVERSHOP_DASHEN_SLOW_SECONDS", "12"))
DASHEN_BURST_TRIGGER_INFLIGHT = int(
    _getenv(
        "OVERSTATS_DASHEN_BURST_TRIGGER_INFLIGHT",
        "OVERSHOP_DASHEN_BURST_TRIGGER_INFLIGHT",
        str(max(1, MAX_CONCURRENT_REQUESTS - 5)),
    )
)
DASHEN_BURST_TRIGGER_SLOW = int(
    _getenv("OVERSTATS_DASHEN_BURST_TRIGGER_SLOW", "OVERSHOP_DASHEN_BURST_TRIGGER_SLOW", "10")
)
DASHEN_ROUTE_COOLDOWN_SECONDS = float(
    _getenv("OVERSTATS_DASHEN_ROUTE_COOLDOWN_SECONDS", "OVERSHOP_DASHEN_ROUTE_COOLDOWN_SECONDS", "15")
)
DASHEN_RETRY_ON_TIMEOUT = int(_getenv("OVERSTATS_DASHEN_RETRY_ON_TIMEOUT", "OVERSHOP_DASHEN_RETRY_ON_TIMEOUT", "1"))
DASHEN_POOL_TIMEOUT_SECONDS = float(
    _getenv("OVERSTATS_DASHEN_POOL_TIMEOUT", "OVERSHOP_DASHEN_POOL_TIMEOUT", "30")
)
DASHEN_MAX_KEEPALIVE_CONNECTIONS = int(
    _getenv("OVERSTATS_DASHEN_MAX_KEEPALIVE", "OVERSHOP_DASHEN_MAX_KEEPALIVE", "600")
)
DASHEN_MAX_CONNECTIONS = int(_getenv("OVERSTATS_DASHEN_MAX_CONNECTIONS", "OVERSHOP_DASHEN_MAX_CONNECTIONS", "2400"))

HTTP_TIMEOUT = httpx.Timeout(
    55.0,
    connect=12.0,
    read=40.0,
    write=12.0,
    pool=DASHEN_POOL_TIMEOUT_SECONDS,
)
HTTP_LIMITS = httpx.Limits(
    max_keepalive_connections=DASHEN_MAX_KEEPALIVE_CONNECTIONS,
    max_connections=DASHEN_MAX_CONNECTIONS,
)

INTERNATIONAL_PROXY = CLIENT_CONFIG.international_proxy
NETEASE_PROXIES = CLIENT_CONFIG.netease_proxies
REQUEST_LOG_ENABLED = os.getenv("OVERSTATS_DASHEN_LOG_REQUESTS", "1").strip().lower() not in {"0", "false", "no", "off"}
REQUEST_LOG_WINDOW_SECONDS = max(
    0.2,
    float(os.getenv("OVERSTATS_DASHEN_LOG_WINDOW_SECONDS", "1.0") or "1.0"),
)
_request_started_timestamps: deque[float] = deque()
_request_finished_timestamps: deque[float] = deque()
ACCOUNT_RATE_LIMIT_WINDOW_SECONDS = max(0.2, float(CLIENT_CONFIG.account_rate_limit_window_seconds))
ACCOUNT_MAX_REQUESTS_PER_SECOND = max(1, int(CLIENT_CONFIG.account_max_requests_per_second))


def _default_client_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": DASHEN_USER_AGENT,
    }


@dataclass(frozen=True)
class DashenCredential:
    name: str
    role_id: int
    token: str
    dts: int
    server: int


class DashenCredentialPool:
    def __init__(
        self,
        credentials: Sequence[DashenCredential],
        cooldown_seconds: float = DASHEN_ACCOUNT_FAILURE_COOLDOWN_SECONDS,
    ) -> None:
        normalized = tuple(credentials)
        if not normalized:
            raise ValueError("DashenCredentialPool requires at least one credential.")
        self._credentials = normalized
        self._cooldown_seconds = max(1.0, float(cooldown_seconds or 1))
        self._cooldowns: Dict[str, float] = {credential.name: 0.0 for credential in normalized}
        self._next_index = 0
        self._lock = threading.Lock()
        self._by_token = {credential.token: credential for credential in normalized}

    @classmethod
    def from_config(cls, client_config: DashenClientConfig) -> "DashenCredentialPool":
        credentials = [
            DashenCredential(
                name=account.name,
                role_id=int(account.role_id),
                token=str(account.token),
                dts=int(account.dts),
                server=int(account.server),
            )
            for account in client_config.accounts
        ]
        return cls(credentials, cooldown_seconds=client_config.account_failure_cooldown_seconds)

    @property
    def credentials(self) -> Tuple[DashenCredential, ...]:
        return self._credentials

    def get_by_token(self, token: str) -> Optional[DashenCredential]:
        return self._by_token.get(str(token or "").strip())

    def next_credential(self, *, now: Optional[float] = None) -> DashenCredential:
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            total = len(self._credentials)
            start_index = self._next_index % total
            for offset in range(total):
                index = (start_index + offset) % total
                credential = self._credentials[index]
                if self._cooldowns.get(credential.name, 0.0) <= now:
                    self._next_index = (index + 1) % total
                    return credential

            earliest_index = min(
                range(total),
                key=lambda idx: (self._cooldowns.get(self._credentials[idx].name, 0.0), idx),
            )
            credential = self._credentials[earliest_index]
            self._next_index = (earliest_index + 1) % total
            return credential

    def mark_success(self, credential: DashenCredential, *, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self._cooldowns.get(credential.name, 0.0) > now:
                self._cooldowns[credential.name] = 0.0

    def mark_failure(
        self,
        credential: DashenCredential,
        *,
        reason: str,
        now: Optional[float] = None,
    ) -> None:
        now = time.monotonic() if now is None else float(now)
        cooldown_until = now + self._cooldown_seconds
        with self._lock:
            self._cooldowns[credential.name] = cooldown_until
        print(
            "[overstats] dashen credential cooled down "
            f"account={credential.name} role_id={credential.role_id} "
            f"cooldown_seconds={int(self._cooldown_seconds)} reason={reason}"
        )


def _authenticated_headers(
    credential: DashenCredential,
    *,
    dts_override: Optional[int] = None,
) -> Dict[str, str]:
    header_dts = int(credential.dts if dts_override is None else dts_override)
    return {
        "Accept": "application/json, text/plain, */*",
        "GL-Bigdata-Auth-Token": credential.token,
        "GL-Bigdata-Dts": str(header_dts),
        "GL-Bigdata-Role-Id": str(credential.role_id),
        "GL-Bigdata-Server": str(credential.server),
        "GL-ClientType": DASHEN_CLIENT_TYPE,
        "Origin": DASHEN_ORIGIN,
        "Referer": DASHEN_REFERER,
        "User-Agent": DASHEN_USER_AGENT,
    }


_semaphore_cache: Dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}
_burst_semaphore_cache: Dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}
_domain_semaphore_cache: Dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Semaphore] = {}
_account_rate_limiter_cache: Dict[tuple[asyncio.AbstractEventLoop, str], "_SlidingWindowRateLimiter"] = {}


class _SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = max(1, int(limit))
        self._window_seconds = max(0.01, float(window_seconds))
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            wait_seconds = 0.0
            async with self._lock:
                now = time.monotonic()
                cutoff = now - self._window_seconds
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                wait_seconds = max(0.01, self._window_seconds - (now - self._timestamps[0]))
            await asyncio.sleep(wait_seconds)


def _record_request_window_sample(bucket: deque[float], now: Optional[float] = None) -> int:
    now = time.monotonic() if now is None else now
    bucket.append(now)
    cutoff = now - REQUEST_LOG_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket)


def _current_request_window_count(bucket: deque[float], now: Optional[float] = None) -> int:
    now = time.monotonic() if now is None else now
    cutoff = now - REQUEST_LOG_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return len(bucket)


def _season_params(season: Optional[int]) -> Dict[str, int]:
    return {} if season is None else {"season": int(season)}


def _is_success_status(status_code: int) -> bool:
    return 200 <= int(status_code) < 300


def _is_successful_upstream_payload(status_code: int, payload: Any) -> bool:
    if not _is_success_status(status_code):
        return False
    if isinstance(payload, dict):
        if "ok" in payload:
            return payload.get("ok") is True
        if "success" in payload:
            return payload.get("success") is True
        if "code" in payload:
            return payload.get("code") == 0
    return True


def _metric_url_for_request(url: str, params: Any = None) -> str:
    try:
        normalized = httpx.URL(url)
        if params:
            normalized = normalized.copy_merge_params(params)
        return normalize_request_metric_url(str(normalized))
    except Exception:
        return normalize_request_metric_url(str(url))


def _normalize_remote_image_url(url: str) -> str:
    return str(url or "").strip()


def _remote_image_cache_stem(url: str) -> str:
    return hashlib.sha256(_normalize_remote_image_url(url).encode("utf-8")).hexdigest()


def _remote_image_cache_suffix(url: str) -> str:
    try:
        suffix = Path(httpx.URL(url).path or "").suffix.lower()
    except Exception:
        suffix = Path(str(url or "")).suffix.lower()
    if suffix and len(suffix) <= 10:
        return suffix
    return ".img"


def _find_cached_remote_image_path(url: str) -> Optional[Path]:
    normalized = _normalize_remote_image_url(url)
    if not normalized or not REMOTE_IMAGE_CACHE_DIR.exists():
        return None
    stem = _remote_image_cache_stem(normalized)
    for path in REMOTE_IMAGE_CACHE_DIR.glob(f"{stem}.*"):
        if path.is_file():
            return path
    return None


def _read_cached_remote_image_bytes(url: str) -> Optional[bytes]:
    cached_path = _find_cached_remote_image_path(url)
    if cached_path is None:
        return None
    try:
        data = cached_path.read_bytes()
    except Exception:
        return None
    return data or None


def _write_cached_remote_image_bytes(url: str, data: bytes) -> Optional[Path]:
    normalized = _normalize_remote_image_url(url)
    if not normalized or not data:
        return None
    REMOTE_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = _find_cached_remote_image_path(normalized)
    if cached_path is not None and cached_path.exists():
        return cached_path
    target_path = REMOTE_IMAGE_CACHE_DIR / f"{_remote_image_cache_stem(normalized)}{_remote_image_cache_suffix(normalized)}"
    fd, temp_path = tempfile.mkstemp(prefix=f"{target_path.stem}.", suffix=".tmp", dir=str(REMOTE_IMAGE_CACHE_DIR))
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


def get_global_semaphore(limit: Optional[int] = None) -> asyncio.Semaphore:
    if limit is None:
        limit = MAX_CONCURRENT_REQUESTS
    loop = asyncio.get_running_loop()
    if loop not in _semaphore_cache:
        _semaphore_cache[loop] = asyncio.Semaphore(limit)
    return _semaphore_cache[loop]


def get_global_burst_semaphore(limit: Optional[int] = None) -> asyncio.Semaphore:
    if limit is None:
        limit = MAX_BURST_CONCURRENT_REQUESTS
    loop = asyncio.get_running_loop()
    if loop not in _burst_semaphore_cache:
        _burst_semaphore_cache[loop] = asyncio.Semaphore(limit)
    return _burst_semaphore_cache[loop]


def get_domain_semaphore(host: str, limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = (loop, str(host or "").lower())
    if key not in _domain_semaphore_cache:
        _domain_semaphore_cache[key] = asyncio.Semaphore(max(1, int(limit or 1)))
    return _domain_semaphore_cache[key]


def get_account_rate_limiter(identity: str, limit: int, window_seconds: float) -> _SlidingWindowRateLimiter:
    loop = asyncio.get_running_loop()
    key = (loop, str(identity or "").strip().lower())
    limiter = _account_rate_limiter_cache.get(key)
    if limiter is None:
        limiter = _SlidingWindowRateLimiter(limit=limit, window_seconds=window_seconds)
        _account_rate_limiter_cache[key] = limiter
    return limiter


def _domain_limit_for_url(url: str) -> tuple[Optional[str], Optional[int]]:
    try:
        host = (httpx.URL(url).host or "").lower()
    except Exception:
        return None, None
    if host == DATAMSAPI_HOST:
        return host, DATAMSAPI_MAX_CONCURRENT_REQUESTS
    return host, None


class _SafeRoute:
    def __init__(self, client: httpx.AsyncClient, label: str, group: Optional[str] = None) -> None:
        self.client = client
        self.label = label
        self.group = group or label
        self.fail_count = 0
        self.cooldown_until = 0.0

    def is_available(self, now: Optional[float] = None) -> bool:
        return self.cooldown_until <= (now if now is not None else time.monotonic())


class SafeClient:
    _request_seq = 0

    def __init__(
        self,
        raw_clients: httpx.AsyncClient | Sequence[httpx.AsyncClient],
        labels: Optional[Sequence[str]] = None,
        groups: Optional[Sequence[str]] = None,
    ) -> None:
        clients = list(raw_clients) if isinstance(raw_clients, (list, tuple)) else [raw_clients]
        route_labels = list(labels or [f"route-{idx}" for idx in range(len(clients))])
        route_groups = list(groups or route_labels)
        if len(route_labels) < len(clients):
            route_labels.extend(f"route-{idx}" for idx in range(len(route_labels), len(clients)))
        if len(route_groups) < len(clients):
            route_groups.extend(route_labels[len(route_groups):])
        self._routes = [_SafeRoute(client, route_labels[idx], route_groups[idx]) for idx, client in enumerate(clients)]
        self._active_requests: Dict[int, float] = {}

    def _active_count(self) -> int:
        return len(self._active_requests)

    def _slow_count(self) -> int:
        now = time.monotonic()
        return sum(1 for started_at in self._active_requests.values() if now - started_at >= DASHEN_SLOW_REQUEST_SECONDS)

    def _should_allow_burst(self) -> bool:
        if MAX_BURST_CONCURRENT_REQUESTS <= 0:
            return False
        return (
            self._active_count() >= DASHEN_BURST_TRIGGER_INFLIGHT
            and self._slow_count() >= DASHEN_BURST_TRIGGER_SLOW
        )

    async def _acquire_slot(self) -> Tuple[asyncio.Semaphore, str]:
        base_sem = get_global_semaphore()
        burst_sem = get_global_burst_semaphore()
        while True:
            if getattr(base_sem, "_value", 0) > 0:
                await base_sem.acquire()
                return base_sem, "base"
            if self._should_allow_burst() and getattr(burst_sem, "_value", 0) > 0:
                await burst_sem.acquire()
                return burst_sem, "burst"
            await asyncio.sleep(0.02)

    def _mark_request_start(self) -> int:
        SafeClient._request_seq += 1
        request_id = SafeClient._request_seq
        self._active_requests[request_id] = time.monotonic()
        return request_id

    def _mark_request_done(self, request_id: int) -> None:
        self._active_requests.pop(request_id, None)

    def _choose_route(self, excluded: Optional[set[int]] = None) -> _SafeRoute:
        excluded = excluded or set()
        now = time.monotonic()
        available = [route for route in self._routes if id(route) not in excluded and route.is_available(now)]
        if not available:
            available = [route for route in self._routes if id(route) not in excluded]
        if not available:
            available = self._routes
        return random.choice(available)

    def _is_retryable(self, exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.PoolTimeout,
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
            ),
        )

    def _record_route_success(self, route: _SafeRoute) -> None:
        for item in self._routes:
            if item.group == route.group:
                item.fail_count = 0
                item.cooldown_until = 0.0

    def _record_route_failure(self, route: _SafeRoute, exc: Exception) -> None:
        if not self._is_retryable(exc):
            return
        cooldown_until = time.monotonic() + DASHEN_ROUTE_COOLDOWN_SECONDS
        for item in self._routes:
            if item.group == route.group:
                item.fail_count += 1
                item.cooldown_until = cooldown_until

    def _log_route_error(
        self,
        method: str,
        url: str,
        route: _SafeRoute,
        exc: Exception,
        cost_ms: int,
        attempt: int,
        will_retry: bool,
        slot_kind: str,
        log_context: Optional[str],
    ) -> None:
        cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        context_suffix = f" {log_context}" if log_context else ""
        print(
            f"[{cur_time}] [SafeClient {method} Error] "
            f"route={route.label} slot={slot_kind} attempt={attempt} cost_ms={cost_ms} "
            f"retry={will_retry} active={self._active_count()} slow={self._slow_count()}"
            f"{context_suffix} URL: {url} | Error: {type(exc).__name__}({exc})"
        )

    def _log_slow_success(
        self,
        method: str,
        url: str,
        route: _SafeRoute,
        cost_ms: int,
        slot_kind: str,
        log_context: Optional[str],
    ) -> None:
        if cost_ms < int(DASHEN_SLOW_REQUEST_SECONDS * 1000):
            return
        cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        context_suffix = f" {log_context}" if log_context else ""
        print(
            f"[{cur_time}] [SafeClient {method} Slow] "
            f"route={route.label} slot={slot_kind} cost_ms={cost_ms} "
            f"active={self._active_count()} slow={self._slow_count()}{context_suffix} URL: {url}"
        )

    def _log_request_start(
        self,
        request_id: int,
        method: str,
        url: str,
        route: _SafeRoute,
        attempt: int,
        slot_kind: str,
        log_context: Optional[str],
    ) -> None:
        if not REQUEST_LOG_ENABLED:
            return
        now = time.monotonic()
        start_rps = _record_request_window_sample(_request_started_timestamps, now)
        cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        context_suffix = f" {log_context}" if log_context else ""
        print(
            f"[{cur_time}] [SafeClient {method} Start] "
            f"id={request_id} route={route.label} slot={slot_kind} attempt={attempt} "
            f"active={self._active_count()} slow={self._slow_count()} start_rps={start_rps}/{REQUEST_LOG_WINDOW_SECONDS:.1f}s"
            f"{context_suffix} URL: {url}"
        )

    def _log_request_success(
        self,
        request_id: int,
        method: str,
        url: str,
        route: _SafeRoute,
        response: httpx.Response,
        cost_ms: int,
        attempt: int,
        slot_kind: str,
        log_context: Optional[str],
    ) -> None:
        if not REQUEST_LOG_ENABLED:
            return
        now = time.monotonic()
        done_rps = _record_request_window_sample(_request_finished_timestamps, now)
        start_rps = _current_request_window_count(_request_started_timestamps, now)
        cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        context_suffix = f" {log_context}" if log_context else ""
        print(
            f"[{cur_time}] [SafeClient {method} Done] "
            f"id={request_id} route={route.label} slot={slot_kind} attempt={attempt} status={response.status_code} "
            f"cost_ms={cost_ms} active={self._active_count()} slow={self._slow_count()} "
            f"start_rps={start_rps}/{REQUEST_LOG_WINDOW_SECONDS:.1f}s done_rps={done_rps}/{REQUEST_LOG_WINDOW_SECONDS:.1f}s"
            f"{context_suffix} URL: {url}"
        )

    async def _request_with_retry(
        self,
        request_id: int,
        method: str,
        url: str,
        slot_kind: str,
        *,
        log_context: Optional[str] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        attempts = max(1, 1 + DASHEN_RETRY_ON_TIMEOUT)
        excluded_routes: set[int] = set()
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            route = self._choose_route(excluded_routes)
            excluded_routes.add(id(route))
            started_at = time.monotonic()
            self._log_request_start(request_id, method, url, route, attempt, slot_kind, log_context)
            try:
                response = await route.client.request(method, url, **kwargs)
                cost_ms = int((time.monotonic() - started_at) * 1000)
                self._record_route_success(route)
                self._log_request_success(request_id, method, url, route, response, cost_ms, attempt, slot_kind, log_context)
                self._log_slow_success(method, url, route, cost_ms, slot_kind, log_context)
                return response
            except Exception as exc:
                cost_ms = int((time.monotonic() - started_at) * 1000)
                last_exc = exc
                self._record_route_failure(route, exc)
                will_retry = self._is_retryable(exc) and attempt < attempts and len(self._routes) > 1
                self._log_route_error(method, url, route, exc, cost_ms, attempt, will_retry, slot_kind, log_context)
                if not will_retry:
                    raise
        raise RuntimeError("request retry loop exited without a response") from last_exc

    async def request(
        self,
        method: str,
        url: str,
        *,
        log_context: Optional[str] = None,
        rate_limit_identity: Optional[str] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        sem, slot_kind = await self._acquire_slot()
        domain_host, domain_limit = _domain_limit_for_url(url)
        domain_sem = get_domain_semaphore(domain_host, domain_limit) if domain_host and domain_limit else None
        rate_limiter = (
            get_account_rate_limiter(
                rate_limit_identity,
                ACCOUNT_MAX_REQUESTS_PER_SECOND,
                ACCOUNT_RATE_LIMIT_WINDOW_SECONDS,
            )
            if rate_limit_identity
            else None
        )
        request_id = self._mark_request_start()
        try:
            if domain_sem is not None:
                await domain_sem.acquire()
            if rate_limiter is not None:
                await rate_limiter.acquire()
            return await self._request_with_retry(
                request_id,
                method.upper(),
                url,
                slot_kind,
                log_context=log_context,
                **kwargs,
            )
        finally:
            if domain_sem is not None:
                domain_sem.release()
            self._mark_request_done(request_id)
            sem.release()

    async def get(self, url: str, *, log_context: Optional[str] = None, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, log_context=log_context, **kwargs)

    async def post(self, url: str, *, log_context: Optional[str] = None, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, log_context=log_context, **kwargs)

    async def aclose(self) -> None:
        seen: set[int] = set()
        for route in self._routes:
            if id(route.client) in seen:
                continue
            seen.add(id(route.client))
            await route.client.aclose()


def _build_async_client(proxy_url: Optional[str] = None) -> httpx.AsyncClient:
    client_kwargs = {
        "timeout": HTTP_TIMEOUT,
        "limits": HTTP_LIMITS,
        "headers": _default_client_headers(),
    }
    if not proxy_url:
        return httpx.AsyncClient(**client_kwargs)
    try:
        return httpx.AsyncClient(
            proxies={"http://": proxy_url, "https://": proxy_url},
            **client_kwargs,
        )
    except TypeError:
        return httpx.AsyncClient(proxy=proxy_url, **client_kwargs)


def _build_default_netease_client() -> SafeClient:
    raw_clients: List[httpx.AsyncClient] = []
    labels: List[str] = []
    groups: List[str] = []
    direct_idx = 0
    proxy_idx = 0
    for proxy in NETEASE_PROXIES:
        raw_clients.append(_build_async_client(proxy))
        if proxy:
            proxy_idx += 1
            labels.append(f"netease-proxy-{proxy_idx}")
            groups.append(f"proxy:{proxy}")
        else:
            direct_idx += 1
            labels.append(f"netease-direct-{direct_idx}")
            groups.append("direct")
    return SafeClient(raw_clients, labels=labels, groups=groups)


class DashenAPIClient:
    """Request-only client for Dashen and adjacent public endpoints."""

    def __init__(
        self,
        netease_client: Optional[SafeClient] = None,
        proxy_client: Optional[SafeClient] = None,
        *,
        client_config: Optional[DashenClientConfig] = None,
        credential_pool: Optional[DashenCredentialPool] = None,
        request_metrics_recorder: Optional["RequestMetricsRecorder"] = None,
        dts: Optional[int] = None,
        role_id: Optional[int] = None,
        server: Optional[int] = None,
        token: Optional[str] = None,
    ) -> None:
        self.client_config = client_config or CLIENT_CONFIG
        self.request_metrics_recorder = request_metrics_recorder
        self.netease_client = netease_client or _build_default_netease_client()
        self.proxy_client = proxy_client or SafeClient(
            _build_async_client(INTERNATIONAL_PROXY),
            labels=["intl-proxy"],
            groups=["intl-proxy"],
        )
        if credential_pool is not None:
            self.credential_pool = credential_pool
        elif token is not None or role_id is not None or dts is not None or server is not None:
            manual_credential = DashenCredential(
                name="manual-1",
                role_id=int(role_id if role_id is not None else self.client_config.accounts[0].role_id),
                token=str(token if token is not None else self.client_config.accounts[0].token),
                dts=int(dts if dts is not None else self.client_config.accounts[0].dts),
                server=int(server if server is not None else self.client_config.accounts[0].server),
            )
            self.credential_pool = DashenCredentialPool(
                [manual_credential],
                cooldown_seconds=self.client_config.account_failure_cooldown_seconds,
            )
        else:
            self.credential_pool = DashenCredentialPool.from_config(self.client_config)

    def _select_credential(self, preferred_token: Optional[str] = None) -> DashenCredential:
        if preferred_token:
            matched = self.credential_pool.get_by_token(preferred_token)
            if matched is not None:
                return matched
        return self.credential_pool.next_credential()

    async def _record_upstream_metric(self, url: str, success: bool) -> None:
        recorder = self.request_metrics_recorder
        if recorder is None:
            return
        try:
            await recorder.enqueue(url, "upstream", success)
        except Exception as exc:
            print(f"[overstats] failed to record upstream request metric url={url}: {exc}")

    async def _record_player_identity_payload(self, url: str, payload: Any) -> None:
        try:
            host = (httpx.URL(url).host or "").lower()
        except Exception:
            host = ""
        if host != DATAMSAPI_HOST:
            return
        try:
            await record_identity_payload(payload)
        except Exception as exc:
            print(f"[overstats] failed to record player identity url={url}: {exc}")

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        use_proxy: bool = False,
        credential: Optional[DashenCredential] = None,
        auth_dts_override: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        client = self.proxy_client if use_proxy else self.netease_client
        request_kwargs = dict(kwargs)
        metric_url = _metric_url_for_request(url, request_kwargs.get("params"))
        headers = dict(request_kwargs.pop("headers", {}) or {})
        log_context = None
        if credential is not None:
            merged_headers = _authenticated_headers(credential, dts_override=auth_dts_override)
            merged_headers.update(headers)
            request_kwargs["headers"] = merged_headers
            log_context = f"account={credential.name}"
            request_kwargs["rate_limit_identity"] = credential.name
        elif headers:
            request_kwargs["headers"] = headers

        try:
            response = await client.request(method, url, log_context=log_context, **request_kwargs)
        except Exception as exc:
            await self._record_upstream_metric(metric_url, False)
            if credential is not None:
                self.credential_pool.mark_failure(
                    credential,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            raise

        if credential is not None:
            if response.status_code in {401, 403}:
                self.credential_pool.mark_failure(
                    credential,
                    reason=f"http_{response.status_code}",
                )
            else:
                self.credential_pool.mark_success(credential)
        try:
            payload = response.json()
        except Exception:
            await self._record_upstream_metric(str(response.request.url), False)
            raise
        upstream_success = _is_successful_upstream_payload(response.status_code, payload)
        request_url = str(response.request.url)
        await self._record_upstream_metric(request_url, upstream_success)
        if upstream_success:
            await self._record_player_identity_payload(request_url, payload)
        return payload

    async def request_bytes(self, url: str, *, use_proxy: bool = False, **kwargs: Any) -> bytes:
        client = self.proxy_client if use_proxy else self.netease_client
        metric_url = _metric_url_for_request(url, kwargs.get("params"))
        try:
            response = await client.get(url, **kwargs)
        except Exception:
            await self._record_upstream_metric(metric_url, False)
            raise
        await self._record_upstream_metric(str(response.request.url), _is_success_status(response.status_code))
        return response.content

    async def search_bnet_account(self, bnet: str) -> Dict[str, Any]:
        credential = self._select_credential()
        payload = {
            "token": credential.token,
            "roleId": credential.role_id,
            "dts": credential.dts,
            "server": credential.server,
            "name": str(bnet or "").replace("＃", "#").strip(),
        }
        return await self.request_json(
            "POST",
            SEARCH_BNET_ACCOUNT_URL,
            credential=credential,
            json=payload,
            timeout=SEARCH_BNET_ACCOUNT_TIMEOUT,
        )

    async def query_card(self, customer_token: str) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/queryCard",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params={"token": customer_token},
        )

    async def query_count_info(
        self,
        customer_token: str,
        game_mode: str,
        season: Optional[int] = None,
    ) -> Dict[str, Any]:
        params = {"gameMode": game_mode, "token": customer_token, **_season_params(season)}
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/queryCountInfo",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def query_match_list(
        self,
        customer_token: str,
        game_mode: str,
        page: int = 1,
        season: Optional[int] = None,
    ) -> Dict[str, Any]:
        params = {"token": customer_token, "gameMode": game_mode, "page": page, **_season_params(season)}
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/queryMatchList",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def query_match_info(self, customer_token: str, match_id: str) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/queryMatchInfo",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params={"matchId": match_id, "token": customer_token},
        )

    async def fight_query_match_info(self, customer_token: str, match_id: str) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/fight/queryMatchInfo",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params={"matchId": match_id, "token": customer_token},
        )

    async def fight_query_count(self, customer_token: str, season: Optional[int] = None) -> Dict[str, Any]:
        params = {"token": customer_token, **_season_params(season)}
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/fight/queryCount",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def fight_leisure_role_card(self, customer_token: str, season: Optional[int] = None) -> Dict[str, Any]:
        params = {"token": customer_token, **_season_params(season)}
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/fight/getLeisureFightRoleCard",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def fight_query_match_list(
        self,
        customer_token: str,
        game_mode: str = "SportFight",
        page: int = 1,
        season: Optional[int] = None,
    ) -> Dict[str, Any]:
        params = {"token": customer_token, "gameMode": game_mode, "page": page, **_season_params(season)}
        return await self.request_json(
            "GET",
            f"{DASHEN_CUSTOMER_API_BASE}/fight/queryMatchList",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def query_province_rank(
        self,
        province: str,
        role_type: str,
        *,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        credential = self._select_credential(token)
        params = {
            "server": credential.server,
            "dts": DASHEN_BIGDATA_DTS,
            "roleId": credential.role_id,
            "token": token or credential.token,
            "roleType": role_type,
            "province": province,
        }
        return await self.request_json(
            "GET",
            f"{DASHEN_API_ROOT}/queryProvinceRank",
            credential=credential,
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def get_hero_billboard(
        self,
        province: str,
        game_mode: str,
        hero_guid: str,
        *,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        credential = self._select_credential(token)
        params = {
            "server": credential.server,
            "dts": DASHEN_BIGDATA_DTS,
            "roleId": credential.role_id,
            "token": token or credential.token,
            "gameMode": game_mode,
            "heroGuid": hero_guid,
            "province": province,
        }
        return await self.request_json(
            "GET",
            f"{DASHEN_BILLBOARD_API_BASE}/getHeroBillboard",
            credential=credential,
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params=params,
        )

    async def query_historical_count_info(
        self,
        customer_token: str,
        start_season: int,
        end_season: int,
        *,
        game_mode: str = "sport",
    ) -> Dict[int, Dict[str, Any]]:
        tasks = {
            season: self.query_count_info(customer_token, game_mode=game_mode, season=season)
            for season in range(start_season, end_season + 1)
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            season: result
            for season, result in zip(tasks.keys(), results)
            if not isinstance(result, Exception)
        }

    async def query_historical_fight_count(
        self,
        customer_token: str,
        start_season: int,
        end_season: int,
    ) -> Dict[int, Dict[str, Any]]:
        tasks = {
            season: self.fight_query_count(customer_token, season=season)
            for season in range(start_season, end_season + 1)
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            season: result
            for season, result in zip(tasks.keys(), results)
            if not isinstance(result, Exception)
        }

    async def get_billboard_user(self, customer_token: str) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            f"{DASHEN_BILLBOARD_API_BASE}/customGetUserHeroBillboard",
            credential=self._select_credential(),
            auth_dts_override=DASHEN_BIGDATA_DTS,
            params={"token": customer_token},
        )

    async def fetch_ow_esports_payload(self) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            PANDASCORE_OW_MATCHES_URL,
            headers=OW_ESPORTS_HEADERS,
            timeout=15,
        )

    async def overfast_player_summary(self, player_id: str) -> Dict[str, Any]:
        player_name = str(player_id or "").replace("#", "-")
        return await self.request_json(
            "GET",
            OVERFAST_PLAYERS_URL,
            use_proxy=True,
            params={"name": player_name},
        )

    async def get_jd_hero_official(self, rank: str = "全部") -> Dict[str, Any]:
        return await self.request_json("GET", JD_HERO_OFFICIAL_URL, params={"rank_level": rank})

    async def get_jd_eq_official(self, hero_guid: str, rank: str = "全部") -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            JD_EQ_OFFICIAL_URL,
            params={"rank_level": rank, "hero_guid": hero_guid},
        )

    async def get_jd_eq_community(self, hero_guid: str, rank: str = "全部") -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            JD_EQ_COMMUNITY_URL,
            params={"rank_level": rank, "hero_guid": hero_guid},
        )

    async def get_icon(self, url: str) -> bytes:
        normalized = _normalize_remote_image_url(url)
        if not normalized:
            return b""
        cached = _read_cached_remote_image_bytes(normalized)
        if cached is not None:
            return cached
        data = await self.request_bytes(normalized)
        _write_cached_remote_image_bytes(normalized, data)
        return data

    async def get_icon_proxy(self, url: str) -> bytes:
        normalized = _normalize_remote_image_url(url)
        if not normalized:
            return b""
        cached = _read_cached_remote_image_bytes(normalized)
        if cached is not None:
            return cached
        data = await self.request_bytes(normalized, use_proxy=True)
        _write_cached_remote_image_bytes(normalized, data)
        return data

    async def aclose(self) -> None:
        await self.netease_client.aclose()
        await self.proxy_client.aclose()


dashen_api_client = DashenAPIClient()
http_client = dashen_api_client.netease_client
http_client_with_proxy = dashen_api_client.proxy_client


@asynccontextmanager
async def get_shared_client() -> Iterable[SafeClient]:
    yield http_client


async def request_json(method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
    return await dashen_api_client.request_json(method, url, **kwargs)


async def request_bytes(url: str, **kwargs: Any) -> bytes:
    return await dashen_api_client.request_bytes(url, **kwargs)


async def close_default_clients() -> None:
    await dashen_api_client.aclose()
