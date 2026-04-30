from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from overstats.src.db import HERO_LEADERBOARD_CN_TABLE, OWHeroLeaderboardDB
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.ow_hero_pick_rate import (
        COMPETITIVE_STRENGTH_THEME,
        OWHeroPickRateModule,
        OWHeroPickRateQuery,
        QUICK_STRENGTH_THEME,
        render_pick_rate_history,
        render_pick_rate_ranking,
    )
except ModuleNotFoundError:
    from src.db import HERO_LEADERBOARD_CN_TABLE, OWHeroLeaderboardDB
    from src.modules.errors import ModuleError
    from src.modules.ow_hero_pick_rate import (
        COMPETITIVE_STRENGTH_THEME,
        OWHeroPickRateModule,
        OWHeroPickRateQuery,
        QUICK_STRENGTH_THEME,
        render_pick_rate_history,
        render_pick_rate_ranking,
    )


try:
    import PIL  # noqa: F401
except ModuleNotFoundError:
    PIL_AVAILABLE = False
else:
    PIL_AVAILABLE = True


def _sample_row(
    *,
    season: int = 2,
    ds: str = "2026-04-29",
    game_mode: str = "kuaisu",
    mmr: str = "-127",
    hero_id: str = "ana",
    hero_type: str = "support",
    selection_ratio: float = 6.79,
    ban_ratio: float = 0.0,
    win_ratio: float = 48.82,
    kda: float = 3.87,
) -> dict[str, object]:
    return {
        "season": season,
        "ds": ds,
        "game_mode": game_mode,
        "mmr": mmr,
        "hero_id": hero_id,
        "hero_type": hero_type,
        "selection_ratio": selection_ratio,
        "ban_ratio": ban_ratio,
        "win_ratio": win_ratio,
        "kda": kda,
    }


def _query_tool_payload() -> dict[str, object]:
    return {
        "heroList": [
            {
                "heroGuid": "ana",
                "name": "安娜",
                "roleType": "support",
                "smallIconUrl": "",
            },
            {
                "heroGuid": "mercy",
                "name": "天使",
                "roleType": "support",
                "smallIconUrl": "",
            },
            {
                "heroGuid": "reinhardt",
                "name": "莱因哈特",
                "roleType": "tank",
                "smallIconUrl": "",
            },
        ]
    }


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranking_selects_latest_snapshot_and_desc_sort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3")
            db.upsert_rows(
                HERO_LEADERBOARD_CN_TABLE,
                [
                    _sample_row(season=1, ds="2026-04-27", hero_id="ana", selection_ratio=9.9),
                    _sample_row(season=2, ds="2026-04-28", hero_id="ana", selection_ratio=7.2),
                    _sample_row(season=2, ds="2026-04-29", hero_id="ana", selection_ratio=4.1, kda=3.2),
                    _sample_row(season=2, ds="2026-04-29", hero_id="mercy", selection_ratio=8.8, kda=5.4),
                ],
            )
            module = OWHeroPickRateModule(db=db, config_loader=_query_tool_payload)

            result = await module.query_pick_rate(
                OWHeroPickRateQuery(view="ranking", game_mode="quick", mmr="all")
            )

        self.assertEqual(result.view, "ranking")
        self.assertEqual(result.snapshot.season, 2)
        self.assertEqual(result.snapshot.ds, "2026-04-29")
        self.assertEqual(result.snapshot.hero_count, 2)
        self.assertEqual([item.hero_guid for item in result.heroes], ["mercy", "ana"])
        self.assertEqual([item.hero_name for item in result.heroes], ["天使", "安娜"])
        self.assertEqual(result.to_dict()["heroes"][0]["selection_ratio"], 8.8)

    async def test_history_uses_default_limit_and_keeps_time_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3")
            rows = []
            for index in range(25):
                season = 1 if index < 12 else 2
                day = index + 1
                rows.append(
                    _sample_row(
                        season=season,
                        ds=f"2026-04-{day:02d}",
                        hero_id="ana",
                        selection_ratio=2.0 + index,
                        win_ratio=40.0 + index,
                    )
                )
            db.upsert_rows(HERO_LEADERBOARD_CN_TABLE, rows)
            module = OWHeroPickRateModule(db=db, config_loader=_query_tool_payload)

            result = await module.query_pick_rate(
                OWHeroPickRateQuery(view="history", game_mode="quick", mmr="all", hero="安娜")
            )

        self.assertEqual(result.view, "history")
        self.assertEqual(result.hero.hero_guid, "ana")
        self.assertEqual(result.history_total, 25)
        self.assertEqual(result.history_limit, 20)
        self.assertEqual(len(result.series), 20)
        self.assertEqual(result.series[0].ds, "2026-04-06")
        self.assertEqual(result.series[-1].ds, "2026-04-25")
        self.assertEqual(result.series[0].selection_ratio, 7.0)
        self.assertEqual(result.latest.selection_ratio, 26.0)

    async def test_history_accepts_hero_guid_and_custom_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3")
            db.upsert_rows(
                HERO_LEADERBOARD_CN_TABLE,
                [
                    _sample_row(ds="2026-04-28", hero_id="ana", selection_ratio=4.5),
                    _sample_row(ds="2026-04-29", hero_id="ana", selection_ratio=5.5),
                    _sample_row(ds="2026-04-30", hero_id="ana", selection_ratio=6.5),
                ],
            )
            module = OWHeroPickRateModule(db=db, config_loader=_query_tool_payload)

            result = await module.query_pick_rate(
                OWHeroPickRateQuery(
                    view="history",
                    game_mode="quick",
                    mmr="all",
                    hero="ana",
                    history_limit=2,
                )
            )

        self.assertEqual(result.hero.hero_name, "安娜")
        self.assertEqual(len(result.series), 2)
        self.assertEqual([item.ds for item in result.series], ["2026-04-29", "2026-04-30"])

    async def test_missing_hero_raises_expected_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            module = OWHeroPickRateModule(
                db=OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3"),
                config_loader=_query_tool_payload,
            )

            with self.assertRaises(ModuleError) as context:
                await module.query_pick_rate(
                    OWHeroPickRateQuery(view="history", game_mode="quick", mmr="all")
                )

        self.assertEqual(context.exception.error, "hero_pick_rate_missing_hero")
        self.assertEqual(context.exception.status_code, 400)

    async def test_unknown_hero_raises_expected_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            module = OWHeroPickRateModule(
                db=OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3"),
                config_loader=_query_tool_payload,
            )

            with self.assertRaises(ModuleError) as context:
                await module.query_pick_rate(
                    OWHeroPickRateQuery(view="history", game_mode="quick", mmr="all", hero="不存在英雄")
                )

        self.assertEqual(context.exception.error, "hero_pick_rate_hero_not_found")
        self.assertEqual(context.exception.status_code, 404)

    async def test_invalid_mmr_raises_expected_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            module = OWHeroPickRateModule(
                db=OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3"),
                config_loader=_query_tool_payload,
            )

            with self.assertRaises(ModuleError) as context:
                await module.query_pick_rate(
                    OWHeroPickRateQuery(view="ranking", game_mode="quick", mmr="Top500")
                )

        self.assertEqual(context.exception.error, "invalid_pick_rate_query")
        self.assertEqual(context.exception.status_code, 400)

    async def test_history_without_rows_raises_expected_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            module = OWHeroPickRateModule(
                db=OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3"),
                config_loader=_query_tool_payload,
            )

            with self.assertRaises(ModuleError) as context:
                await module.query_pick_rate(
                    OWHeroPickRateQuery(view="history", game_mode="quick", mmr="all", hero="安娜")
                )

        self.assertEqual(context.exception.error, "hero_pick_rate_history_empty")
        self.assertEqual(context.exception.status_code, 404)

    async def test_empty_snapshot_raises_expected_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = OWHeroLeaderboardDB(db_path=Path(temp_dir) / "leaderboard.sqlite3")
            module = OWHeroPickRateModule(db=db, config_loader=_query_tool_payload)

            with self.assertRaises(ModuleError) as context:
                await module.query_pick_rate(
                    OWHeroPickRateQuery(view="ranking", game_mode="quick", mmr="all")
                )

        self.assertEqual(context.exception.error, "hero_pick_rate_empty")
        self.assertEqual(context.exception.status_code, 404)


@unittest.skipUnless(PIL_AVAILABLE, "Pillow required for render smoke tests")
class RenderSmokeTests(unittest.TestCase):
    def test_render_pick_rate_ranking_returns_png(self) -> None:
        result = render_pick_rate_ranking(
            game_mode="quick",
            mmr="all",
            snapshot={"season": 2, "ds": "2026-04-29", "hero_count": 2},
            heroes=[
                {
                    "rank": 1,
                    "hero_guid": "ana",
                    "hero_name": "安娜",
                    "hero_role": "support",
                    "selection_ratio": 8.8,
                    "ban_ratio": 0.0,
                    "win_ratio": 51.2,
                    "kda": 4.1,
                    "icon_url": "",
                },
                {
                    "rank": 2,
                    "hero_guid": "mercy",
                    "hero_name": "天使",
                    "hero_role": "support",
                    "selection_ratio": 7.1,
                    "ban_ratio": 0.0,
                    "win_ratio": 53.0,
                    "kda": 4.9,
                    "icon_url": "",
                },
            ],
            theme=dict(QUICK_STRENGTH_THEME),
        )

        self.assertEqual(result.media_type, "image/png")
        self.assertTrue(result.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_render_pick_rate_history_returns_png(self) -> None:
        result = render_pick_rate_history(
            game_mode="competitive",
            mmr="Master",
            hero={
                "hero_guid": "ana",
                "hero_name": "安娜",
                "hero_role": "support",
                "icon_url": "",
            },
            latest={
                "season": 2,
                "ds": "2026-04-29",
                "selection_ratio": 7.2,
                "ban_ratio": 0.0,
                "win_ratio": 51.4,
                "kda": 4.2,
            },
            history_total=3,
            history_limit=3,
            series=[
                {
                    "season": 1,
                    "ds": "2026-04-27",
                    "selection_ratio": 5.1,
                    "ban_ratio": 0.0,
                    "win_ratio": 49.1,
                    "kda": 3.8,
                },
                {
                    "season": 2,
                    "ds": "2026-04-28",
                    "selection_ratio": 6.0,
                    "ban_ratio": 0.0,
                    "win_ratio": 50.7,
                    "kda": 4.0,
                },
                {
                    "season": 2,
                    "ds": "2026-04-29",
                    "selection_ratio": 7.2,
                    "ban_ratio": 0.0,
                    "win_ratio": 51.4,
                    "kda": 4.2,
                },
            ],
            theme=dict(COMPETITIVE_STRENGTH_THEME),
        )

        self.assertEqual(result.media_type, "image/png")
        self.assertTrue(result.content.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
