from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import time
from typing import Any, Mapping, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ always provides zoneinfo.
    ZoneInfo = None  # type: ignore[assignment]


try:
    DASHEN_TIMEZONE = ZoneInfo("Asia/Hong_Kong") if ZoneInfo is not None else dt.timezone(dt.timedelta(hours=8))
except Exception:  # pragma: no cover - fallback for systems without timezone data.
    DASHEN_TIMEZONE = dt.timezone(dt.timedelta(hours=8), name="UTC+8")


@dataclass(frozen=True)
class RiskStatus:
    """Normalized player restriction returned by Dashen ``queryCard``."""

    expire_time_ms: Optional[int] = None
    upstream_status: str = ""

    def is_active(self, *, now_ms: Optional[int] = None) -> bool:
        if not self.expire_time_ms:
            return True
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return self.expire_time_ms > current_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "expireTime": self.expire_time_ms,
            "status": self.upstream_status,
        }


def parse_risk_status(value: Any) -> Optional[RiskStatus]:
    """Return a restriction only when the upstream ``riskStatus`` entry exists.

    The upstream ``status`` value is intentionally not interpreted yet. Presence of
    ``riskStatus`` means the player is suspended, as specified by the API contract.
    ``value`` may be a full queryCard payload, its ``data`` object, or the entry itself.
    """

    if isinstance(value, RiskStatus):
        return value
    if not isinstance(value, Mapping):
        return None

    raw: Any = None
    has_entry = False
    if "riskStatus" in value:
        raw = value.get("riskStatus")
        has_entry = True
    else:
        data = value.get("data")
        if isinstance(data, Mapping) and "riskStatus" in data:
            raw = data.get("riskStatus")
            has_entry = True
        elif "expireTime" in value or "status" in value:
            raw = value
            has_entry = True

    if not has_entry or not isinstance(raw, Mapping) or not raw:
        return None

    expire_time_ms: Optional[int]
    try:
        parsed_expire_time = int(float(raw.get("expireTime")))
        expire_time_ms = parsed_expire_time if parsed_expire_time > 0 else None
    except (TypeError, ValueError, OverflowError):
        expire_time_ms = None

    return RiskStatus(
        expire_time_ms=expire_time_ms,
        upstream_status=str(raw.get("status") or "").strip(),
    )


def format_risk_status(value: Any, *, compact: bool = False, now_ms: Optional[int] = None) -> str:
    risk_status = parse_risk_status(value)
    if risk_status is None or not risk_status.is_active(now_ms=now_ms):
        return ""

    expire_text = format_expire_time(risk_status.expire_time_ms, compact=compact)
    return f"禁赛中 · 解封 {expire_text}" if expire_text else "禁赛中"


def format_expire_time(expire_time_ms: Optional[int], *, compact: bool = False) -> str:
    if not expire_time_ms:
        return ""
    try:
        expires_at = dt.datetime.fromtimestamp(expire_time_ms / 1000, tz=DASHEN_TIMEZONE)
    except (OSError, OverflowError, TypeError, ValueError):
        return ""
    return expires_at.strftime("%m-%d %H:%M" if compact else "%Y-%m-%d %H:%M")


def measure_risk_status_badge(
    draw: Any,
    value: Any,
    *,
    font: Any,
    compact: bool = False,
    padding_x: int = 10,
    padding_y: int = 5,
    max_width: Optional[int] = None,
) -> tuple[int, int, str]:
    text = format_risk_status(value, compact=compact)
    if not text:
        return 0, 0, ""

    if max_width is not None and max_width > 0:
        candidates = [text]
        compact_text = format_risk_status(value, compact=True)
        if compact_text and compact_text not in candidates:
            candidates.append(compact_text)
        candidates.append("禁赛中")
        text = candidates[-1]
        for candidate in candidates:
            candidate_width, _ = _measure_text(draw, candidate, font)
            if candidate_width + padding_x * 2 <= max_width:
                text = candidate
                break

    text_width, text_height = _measure_text(draw, text, font)
    return text_width + padding_x * 2, text_height + padding_y * 2, text


def draw_risk_status_badge(
    draw: Any,
    x: int | float,
    y: int | float,
    value: Any,
    *,
    font: Any,
    compact: bool = False,
    padding_x: int = 10,
    padding_y: int = 5,
    max_width: Optional[int] = None,
) -> tuple[int, int]:
    """Draw a high-contrast red restriction label on a subtle white bevel."""

    width, height, text = measure_risk_status_badge(
        draw,
        value,
        font=font,
        compact=compact,
        padding_x=padding_x,
        padding_y=padding_y,
        max_width=max_width,
    )
    if not text:
        return 0, 0

    left = int(round(x))
    top = int(round(y))
    chamfer = max(3, min(8, height // 4))
    shadow_offset = max(1, height // 12)

    def polygon_at(offset_x: int, offset_y: int) -> list[tuple[int, int]]:
        x1 = left + offset_x
        y1 = top + offset_y
        x2 = x1 + width
        y2 = y1 + height
        return [
            (x1 + chamfer, y1),
            (x2 - chamfer, y1),
            (x2, y1 + chamfer),
            (x2, y2 - chamfer),
            (x2 - chamfer, y2),
            (x1 + chamfer, y2),
            (x1, y2 - chamfer),
            (x1, y1 + chamfer),
        ]

    draw.polygon(polygon_at(shadow_offset, shadow_offset + 1), fill=(8, 12, 18, 92))
    points = polygon_at(0, 0)
    draw.polygon(points, fill=(248, 248, 250, 238))
    draw.line(points[:4], fill=(255, 255, 255, 252), width=max(1, height // 18), joint="curve")
    draw.line(points[3:] + [points[0]], fill=(190, 194, 202, 225), width=max(1, height // 20), joint="curve")

    text_width, text_height = _measure_text(draw, text, font)
    text_x = left + (width - text_width) / 2
    text_y = top + (height - text_height) / 2
    draw.text(
        (text_x, text_y),
        text,
        font=font,
        fill=(210, 20, 36, 255),
        stroke_width=0,
    )
    return width, height


def _measure_text(draw: Any, text: str, font: Any) -> tuple[int, int]:
    try:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[2] - box[0]), int(box[3] - box[1])
    except Exception:
        try:
            return int(draw.textlength(str(text or ""), font=font)), int(getattr(font, "size", 16))
        except Exception:
            return len(str(text or "")) * 8, int(getattr(font, "size", 16))


__all__ = [
    "DASHEN_TIMEZONE",
    "RiskStatus",
    "draw_risk_status_badge",
    "format_expire_time",
    "format_risk_status",
    "measure_risk_status_badge",
    "parse_risk_status",
]
