from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import httpx

try:
    from overstats.config import config as app_config
except ModuleNotFoundError:
    from config import config as app_config


OW_HERO_LEADERBOARD_CN_URL = "https://webapi.blizzard.cn/ow-armory-server/hero_leaderboard"
REQUEST_TIMEOUT_SECONDS = 20.0
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Referer": "https://ow.blizzard.cn/",
}
CN_GAME_MODES: tuple[str, ...] = ("kuaisu", "jingji")
CN_MMRS: tuple[str, ...] = (
    "-127",
    "Bronze",
    "Silver",
    "Gold",
    "Platinum",
    "Emerald",
    "Diamond",
    "Master",
    "Grandmaster",
    "Champion",
)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class OWHeroLeaderboardTarget:
    season: int
    game_mode: str
    mmr: str


@dataclass(frozen=True)
class OWHeroLeaderboardRow:
    season: int
    ds: str
    game_mode: str
    mmr: str
    hero_id: str
    hero_type: str
    selection_ratio: float
    ban_ratio: float
    win_ratio: float
    kda: float


class OWHeroLeaderboardRequests:
    def __init__(
        self,
        *,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.headers = dict(headers or REQUEST_HEADERS)

    def get_cn_season(self) -> int:
        raw_value = getattr(app_config, "OW_HERO_LEADERBOARD_CN_SEASON", 2)
        return int(raw_value or 2)

    def build_cn_targets(self, season: Optional[int] = None) -> tuple[OWHeroLeaderboardTarget, ...]:
        resolved_season = int(season or self.get_cn_season())
        return tuple(
            OWHeroLeaderboardTarget(season=resolved_season, game_mode=game_mode, mmr=mmr)
            for game_mode in CN_GAME_MODES
            for mmr in CN_MMRS
        )

    def build_cn_params(self, target: OWHeroLeaderboardTarget) -> dict[str, Any]:
        return {
            "game_mode": str(target.game_mode),
            "season": int(target.season),
            "mmr": str(target.mmr),
        }

    def normalize_payload(
        self,
        payload: Any,
        target: OWHeroLeaderboardTarget,
    ) -> tuple[OWHeroLeaderboardRow, ...]:
        if not isinstance(payload, Mapping):
            raise TypeError("OW hero leaderboard payload must be a mapping.")

        code = int(payload.get("code") or 0)
        message = str(payload.get("message") or "").strip()
        if code != 0:
            raise RuntimeError(
                "OW hero leaderboard request failed: "
                f"game_mode={target.game_mode} mmr={target.mmr} code={code} message={message}"
            )

        data = payload.get("data") or []
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes, bytearray)):
            raise TypeError("OW hero leaderboard data must be a list.")

        rows = []
        for item in data:
            if not isinstance(item, Mapping):
                continue

            hero_id = str(item.get("hero_id") or "").strip()
            ds = str(item.get("ds") or "").strip()
            if not hero_id or not ds:
                continue

            rows.append(
                OWHeroLeaderboardRow(
                    season=int(target.season),
                    ds=ds,
                    game_mode=str(target.game_mode),
                    mmr=str(target.mmr),
                    hero_id=hero_id,
                    hero_type=str(item.get("hero_type") or "").strip(),
                    selection_ratio=_safe_float(item.get("selection_ratio")),
                    ban_ratio=_safe_float(item.get("ban_ratio")),
                    win_ratio=_safe_float(item.get("win_ratio")),
                    kda=_safe_float(item.get("kda")),
                )
            )
        return tuple(rows)

    async def fetch_cn_target(
        self,
        target: OWHeroLeaderboardTarget,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ) -> tuple[OWHeroLeaderboardRow, ...]:
        if client is not None:
            return await self._fetch_cn_target_with_client(client, target)

        async with self.create_async_client() as owned_client:
            return await self._fetch_cn_target_with_client(owned_client, target)

    def create_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    async def _fetch_cn_target_with_client(
        self,
        client: httpx.AsyncClient,
        target: OWHeroLeaderboardTarget,
    ) -> tuple[OWHeroLeaderboardRow, ...]:
        response = await client.get(OW_HERO_LEADERBOARD_CN_URL, params=self.build_cn_params(target))
        response.raise_for_status()
        return self.normalize_payload(response.json(), target)
