from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx


REQUEST_TIMEOUT_SECONDS = 20.0
IMAGE_CACHE_MAX_CONCURRENCY = 6
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://us.shop.battle.net/",
}


@dataclass(frozen=True)
class OWShopSource:
    title: str
    url: str


SHOP_SECTION_SOURCES: tuple[OWShopSource, ...] = (
    OWShopSource(
        title="精选商品",
        url="https://shop.battlenet.com.cn/api/itemshop/pages/blt01ee8af4f4da5e5f?userId=0&locale=zh-CN",
    ),
    OWShopSource(
        title="电竞商品",
        url="https://shop.battlenet.com.cn/api/itemshop/pages/blt2065e08d915d3ff8?userId=0&locale=zh-CN",
    ),
    OWShopSource(
        title="赛季物品",
        url=(
            "https://shop.battlenet.com.cn/api/card-collection?"
            "id=blt9f0779a1ce3674d7&id=bltf6f3754ef9ac5efe&id=bltff44f3db7e349cb3"
            "&id=blt11708b9adcddb5e2&id=blt9463b6e951095627&locale=zh-cn"
        ),
    ),
    OWShopSource(
        title="光子水晶商店",
        url="https://shop.battlenet.com.cn/api/card-collection?id=blt96bb02f90b1c493c&id=blt41c246cabce228fe&locale=zh-cn",
    ),
    OWShopSource(
        title="货币商店",
        url=(
            "https://shop.battlenet.com.cn/api/card-collection?"
            "id=blt33b65689468107fd&id=blte794697a49f1ac23&id=blt965ebe71fa46b9fb&locale=zh-cn"
        ),
    ),
    OWShopSource(
        title="PVE商店",
        url="https://shop.battlenet.com.cn/api/card-collection?id=blt6ba8925b6fb5d816&locale=zh-cn",
    ),
)


@dataclass(frozen=True)
class OWShopItem:
    title: str
    description: str
    product_ids: tuple[int, ...]
    price_raw: int | float
    price_currency: str
    price_discount_percentage: int
    image_url: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OWShopItem":
        product_ids = payload.get("product_ids")
        if product_ids is None:
            product_ids = payload.get("productIds")
        return cls(
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            product_ids=tuple(_coerce_product_ids(product_ids)),
            price_raw=_coerce_price_raw(payload.get("price_raw", payload.get("priceRaw"))),
            price_currency=str(payload.get("price_currency", payload.get("priceCurrency")) or "UNK").strip() or "UNK",
            price_discount_percentage=max(0, int(payload.get("price_discount_percentage", payload.get("priceDiscountPercentage")) or 0)),
            image_url=normalize_image_url(str(payload.get("image_url", payload.get("imageUrl")) or "").strip()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "product_ids": list(self.product_ids),
            "price_raw": self.price_raw,
            "price_currency": self.price_currency,
            "price_discount_percentage": self.price_discount_percentage,
            "image_url": self.image_url,
        }


@dataclass(frozen=True)
class OWShopSection:
    title: str
    expires_text: str
    items: tuple[OWShopItem, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OWShopSection":
        raw_items = payload.get("items")
        return cls(
            title=str(payload.get("title") or "").strip(),
            expires_text=str(payload.get("expires_text", payload.get("expiresText")) or "").strip(),
            items=tuple(OWShopItem.from_dict(item) for item in list(raw_items or []) if isinstance(item, Mapping)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "expires_text": self.expires_text,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }


class OWShopRequests:
    def __init__(
        self,
        *,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        headers: Optional[Mapping[str, str]] = None,
        now_ms_factory: Optional[Callable[[], int]] = None,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.headers = dict(headers or REQUEST_HEADERS)
        self.now_ms_factory = now_ms_factory or (lambda: int(time.time() * 1000))

    async def fetch_section(self, source: OWShopSource) -> OWShopSection:
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            payload = await self._fetch_json_with_client(client, source.url)
        return self.normalize_section_payload(source, payload)

    def normalize_section_payload(self, source: OWShopSource, payload: Any) -> OWShopSection:
        expires_text = ""
        raw_items: Sequence[Mapping[str, Any]] = []

        if isinstance(payload, list):
            raw_items = [item for item in payload if isinstance(item, Mapping)]
        elif isinstance(payload, Mapping):
            collections = payload.get("mtxCollections")
            if isinstance(collections, list) and collections:
                first_collection = collections[0]
                if isinstance(first_collection, Mapping):
                    items = first_collection.get("items")
                    if isinstance(items, list):
                        raw_items = [item for item in items if isinstance(item, Mapping)]
            expires_text = format_expiry_text(payload.get("expiresAtMs"), now_ms=self.now_ms_factory())

        items = tuple(self.normalize_item_payload(item) for item in raw_items)
        return OWShopSection(
            title=source.title,
            expires_text=expires_text,
            items=tuple(item for item in items if item.title or item.image_url),
        )

    def normalize_item_payload(self, payload: Mapping[str, Any]) -> OWShopItem:
        price_payload = payload.get("price") if isinstance(payload.get("price"), Mapping) else {}
        image_payload = payload.get("image") if isinstance(payload.get("image"), Mapping) else {}
        return OWShopItem(
            title=clean_shop_text(str(payload.get("title") or "未知商品")) or "未知商品",
            description=clean_shop_text(str(payload.get("description") or "")),
            product_ids=tuple(_coerce_product_ids(payload.get("productIds"))),
            price_raw=_coerce_price_raw(price_payload.get("raw")),
            price_currency=str(price_payload.get("currency") or "UNK").strip() or "UNK",
            price_discount_percentage=max(0, int(price_payload.get("discountPercentage") or 0)),
            image_url=normalize_image_url(str(image_payload.get("url") or "")),
        )

    async def cache_images(
        self,
        image_urls: Sequence[str],
        asset_dir: Path,
        *,
        max_concurrency: int = IMAGE_CACHE_MAX_CONCURRENCY,
    ) -> Dict[str, Path]:
        normalized_urls = []
        seen = set()
        for image_url in image_urls:
            normalized = normalize_image_url(image_url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_urls.append(normalized)

        asset_dir.mkdir(parents=True, exist_ok=True)
        if not normalized_urls:
            return {}

        results: Dict[str, Path] = {}
        semaphore = asyncio.Semaphore(max(1, int(max_concurrency or 1)))
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:

            async def run(image_url: str) -> None:
                async with semaphore:
                    path = await self._cache_single_image(client, image_url, asset_dir)
                    if path is not None:
                        results[image_url] = path

            failures = await asyncio.gather(*(run(image_url) for image_url in normalized_urls), return_exceptions=True)
            for image_url, failure in zip(normalized_urls, failures):
                if isinstance(failure, Exception):
                    print(f"[overstats] ow_shop image cache failed: url={image_url} error={type(failure).__name__}: {failure}")

        return results

    async def _fetch_json_with_client(self, client: httpx.AsyncClient, url: str) -> Any:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def _cache_single_image(
        self,
        client: httpx.AsyncClient,
        image_url: str,
        asset_dir: Path,
    ) -> Optional[Path]:
        normalized = normalize_image_url(image_url)
        if not normalized:
            return None

        parsed = urlparse(normalized)
        suffix = Path(parsed.path or "").suffix.lower() or ".png"
        filename = f"{stable_url_hash(normalized)}{suffix}"
        target_path = asset_dir / filename
        if target_path.exists() and is_valid_image_file(target_path):
            return target_path

        response = await client.get(normalized)
        response.raise_for_status()
        content = response.content
        if not content:
            return None

        fd, temp_path = tempfile.mkstemp(prefix="ow-shop-image.", suffix=suffix, dir=str(asset_dir))
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
            Path(temp_path).replace(target_path)
        finally:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        return target_path


def clean_shop_text(value: str) -> str:
    cleaned = str(value or "").replace("®", "").replace("™", "")
    return " ".join(cleaned.split()).strip()


def normalize_image_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    return text


def format_expiry_text(value: Any, *, now_ms: Optional[int] = None) -> str:
    expires_at_ms = _safe_int(value)
    if expires_at_ms is None or expires_at_ms <= 0:
        return ""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    remaining_ms = max(0, expires_at_ms - now_ms)
    total_minutes = remaining_ms // 60000
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if days > 0 or hours > 0:
        parts.append(f"{hours}小时")
    parts.append(f"{minutes}分")
    return "".join(parts)


def stable_url_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def is_valid_image_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return True

    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _coerce_price_raw(value: Any) -> int | float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _coerce_product_ids(value: Any) -> tuple[int, ...]:
    return tuple(
        item
        for item in (_safe_int(entry) for entry in list(value or []))
        if item is not None
    )


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
