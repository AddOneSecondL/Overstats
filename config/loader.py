from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Optional, Tuple

from . import config


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    return int(raw)


def _as_non_empty_string(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _as_positive_int(value: Any, field_name: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return normalized


def _as_positive_float(value: Any, field_name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return normalized


def _normalize_proxy_pool(raw_value: Any) -> Tuple[Optional[str], ...]:
    if raw_value is None:
        return (None,)
    if not isinstance(raw_value, (list, tuple)):
        raise ValueError("DASHEN_NETEASE_PROXIES must be a list or tuple.")

    normalized = []
    for item in raw_value:
        proxy = str(item or "").strip()
        normalized.append(proxy or None)
    return tuple(normalized or [None])


@dataclass(frozen=True)
class APIConfig:
    host: str
    port: int
    use_stream_response: bool
    dashen_max_concurrent_requests: int
    dashen_max_accepted_requests: int = 4


@dataclass(frozen=True)
class DashenCredentialConfig:
    name: str
    role_id: int
    token: str
    dts: int
    server: int


@dataclass(frozen=True)
class DashenClientConfig:
    accounts: Tuple[DashenCredentialConfig, ...]
    bigdata_dts: int
    account_max_requests_per_second: int
    account_rate_limit_window_seconds: float
    client_type: str
    origin: str
    referer: str
    user_agent: str
    account_failure_cooldown_seconds: int
    international_proxy: str
    netease_proxies: Tuple[Optional[str], ...]
    ow_esports_api_key: str


def _normalize_accounts() -> Tuple[DashenCredentialConfig, ...]:
    raw_accounts = getattr(config, "DASHEN_ACCOUNTS", [])
    normalized_accounts = []
    used_names = set()
    default_dts = _as_positive_int(getattr(config, "DASHEN_DTS", 2026), "DASHEN_DTS")
    default_server = _as_positive_int(getattr(config, "DASHEN_SERVER", 1), "DASHEN_SERVER")

    if not isinstance(raw_accounts, (list, tuple)):
        raise ValueError("DASHEN_ACCOUNTS must be a list or tuple.")
    if not raw_accounts:
        raise ValueError("DASHEN_ACCOUNTS must contain at least one account.")

    for index, raw_account in enumerate(raw_accounts, start=1):
        if not isinstance(raw_account, dict):
            raise ValueError(f"DASHEN_ACCOUNTS[{index - 1}] must be a dict.")

        name = str(raw_account.get("name") or f"account-{index}").strip()
        if not name:
            name = f"account-{index}"
        if name in used_names:
            raise ValueError(f"DASHEN_ACCOUNTS contains duplicate account name: {name}")
        used_names.add(name)

        normalized_accounts.append(
            DashenCredentialConfig(
                name=name,
                role_id=_as_positive_int(raw_account.get("role_id"), f"DASHEN_ACCOUNTS[{index - 1}].role_id"),
                token=_as_non_empty_string(raw_account.get("token"), f"DASHEN_ACCOUNTS[{index - 1}].token"),
                dts=default_dts,
                server=default_server,
            )
        )

    return tuple(normalized_accounts)


def _default_dashen_max_accepted_requests() -> int:
    raw_accounts = getattr(config, "DASHEN_ACCOUNTS", [])
    if not isinstance(raw_accounts, (list, tuple)):
        return 4
    return max(1, len(raw_accounts) * 4)


def get_api_config() -> APIConfig:
    return APIConfig(
        host=os.getenv("OVERSTATS_API_HOST", config.API_HOST),
        port=int(os.getenv("OVERSTATS_API_PORT", str(config.API_PORT))),
        use_stream_response=_read_bool_env(
            "OVERSTATS_USE_STREAM_RESPONSE",
            config.USE_STREAM_RESPONSE,
        ),
        dashen_max_concurrent_requests=_read_int_env(
            "OVERSTATS_DASHEN_MAX_CONCURRENT_REQUESTS",
            getattr(config, "DASHEN_MAX_CONCURRENT_REQUESTS", 2),
        ),
        dashen_max_accepted_requests=max(
            1,
            _read_int_env(
                "OVERSTATS_DASHEN_MAX_ACCEPTED_REQUESTS",
                getattr(
                    config,
                    "DASHEN_MAX_ACCEPTED_REQUESTS",
                    _default_dashen_max_accepted_requests(),
                ),
            ),
        ),
    )


def get_dashen_client_config() -> DashenClientConfig:
    accounts = _normalize_accounts()
    cooldown_seconds = _as_positive_int(
        getattr(config, "DASHEN_ACCOUNT_FAILURE_COOLDOWN_SECONDS", 60),
        "DASHEN_ACCOUNT_FAILURE_COOLDOWN_SECONDS",
    )
    return DashenClientConfig(
        accounts=accounts,
        bigdata_dts=_as_positive_int(
            getattr(config, "DASHEN_BIGDATA_DTS", getattr(config, "DASHEN_DTS", accounts[0].dts)),
            "DASHEN_BIGDATA_DTS",
        ),
        account_max_requests_per_second=_as_positive_int(
            getattr(config, "DASHEN_ACCOUNT_MAX_REQUESTS_PER_SECOND", 5),
            "DASHEN_ACCOUNT_MAX_REQUESTS_PER_SECOND",
        ),
        account_rate_limit_window_seconds=_as_positive_float(
            getattr(config, "DASHEN_ACCOUNT_RATE_LIMIT_WINDOW_SECONDS", 1.0),
            "DASHEN_ACCOUNT_RATE_LIMIT_WINDOW_SECONDS",
        ),
        client_type=_as_non_empty_string(
            getattr(config, "DASHEN_CLIENT_TYPE", "60"),
            "DASHEN_CLIENT_TYPE",
        ),
        origin=_as_non_empty_string(
            getattr(config, "DASHEN_ORIGIN", "https://act.ds.163.com"),
            "DASHEN_ORIGIN",
        ),
        referer=_as_non_empty_string(
            getattr(config, "DASHEN_REFERER", "https://act.ds.163.com/"),
            "DASHEN_REFERER",
        ),
        user_agent=_as_non_empty_string(
            getattr(config, "DASHEN_USER_AGENT", ""),
            "DASHEN_USER_AGENT",
        ),
        account_failure_cooldown_seconds=cooldown_seconds,
        international_proxy=str(getattr(config, "DASHEN_INTERNATIONAL_PROXY", "") or "").strip(),
        netease_proxies=_normalize_proxy_pool(getattr(config, "DASHEN_NETEASE_PROXIES", [None])),
        ow_esports_api_key=str(getattr(config, "OW_ESPORTS_API_KEY", "") or "").strip(),
    )
