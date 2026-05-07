from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.dashen_competitive_strength.engine import (
        _build_player_competitive_meta,
        convert_rank_score,
        DashenCompetitiveStrengthEngine,
        normalize_limit,
        score_to_rank,
    )
    from overstats.src.modules.dashen_competitive_strength.requests import DashenCompetitiveStrengthRequests
    from overstats.src.modules.dashen_competitive_strength.requests import DashenCompetitiveStrengthQuery
    from overstats.src.modules.dashen_competitive_strength.service import DashenCompetitiveStrengthModule
    from overstats.src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        render_quick_strength,
    )
except ModuleNotFoundError:
    from src.modules.errors import ModuleError
    from src.modules.dashen_competitive_strength.engine import (
        _build_player_competitive_meta,
        convert_rank_score,
        DashenCompetitiveStrengthEngine,
        normalize_limit,
        score_to_rank,
    )
    from src.modules.dashen_competitive_strength.requests import DashenCompetitiveStrengthRequests
    from src.modules.dashen_competitive_strength.requests import DashenCompetitiveStrengthQuery
    from src.modules.dashen_competitive_strength.service import DashenCompetitiveStrengthModule
    from src.modules.dashen_quick_strength.render import (
        COMPETITIVE_STRENGTH_THEME,
        render_quick_strength,
    )


class EngineFunctionTests(unittest.TestCase):
    def test_normalize_limit_clamps(self) -> None:
        self.assertEqual(normalize_limit(None), 12)
        self.assertEqual(normalize_limit(2), 3)
        self.assertEqual(normalize_limit(50), 12)

    def test_convert_rank_score(self) -> None:
        self.assertEqual(convert_rank_score(395), 2500)
        self.assertEqual(convert_rank_score(255), 2000)
        self.assertEqual(convert_rank_score(459), 3400)
        self.assertIsNone(convert_rank_score(0))

    def test_score_to_rank(self) -> None:
        self.assertEqual(score_to_rank(3000), "Diamond 5")
        self.assertEqual(score_to_rank(4500), "Champion 5")
        self.assertEqual(score_to_rank(0), "Unranked")

    def test_build_player_competitive_meta_uses_previous_season_fallback(self) -> None:
        payloads = [
            (22, []),
            (
                21,
                [
                    {"roleType": "tank", "lastRankInfo": {"rankScore": 355}},
                    {"roleType": "dps", "lastRankInfo": {"rankScore": 295}},
                ],
            ),
        ]
        meta = _build_player_competitive_meta(payloads, live_season=22)
        self.assertEqual(meta["latest_role_scores"]["tank"], convert_rank_score(355))
        self.assertEqual(meta["latest_role_seasons"]["tank"], 21)
        self.assertEqual(meta["current_role_scores"], {})


class CompetitiveStrengthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_uses_match_rank_info_for_role_range(self) -> None:
        requests = _StubCompetitiveRequests()
        engine = DashenCompetitiveStrengthEngine(requests)

        result = await engine.build(
            customer_token="token-1",
            limit=12,
            include_previous_season=True,
            config={},
        )

        self.assertEqual(len(result["matches"]), 1)
        match = result["matches"][0]
        self.assertEqual(match["role_range"], {"min": 2500, "max": 3500})
        self.assertEqual(match["current_role_range"], {"min": 2500, "max": 3500})
        self.assertEqual(match["all_role_range"], {"min": 2500, "max": 3500})
        self.assertEqual(match["team_scores"], [2500, 3000])
        self.assertEqual(match["enemy_scores"], [3500])
        self.assertEqual(match["avg_score"], 3000.0)

    async def test_customer_token_direct_query(self) -> None:
        engine = _RecordingEngine(_sample_engine_payload())
        module = DashenCompetitiveStrengthModule(api_client=SimpleNamespace(), search_module=_ExplodingSearchModule())
        module.engine = engine
        module._load_ow_config = lambda: {"heroList": [], "mapList": []}

        result = await module.query_competitive_strength(
            DashenCompetitiveStrengthQuery(customer_token="token-1", limit=99),
            render=False,
        )

        self.assertEqual(result.customer_token, "token-1")
        self.assertEqual(engine.calls[0]["limit"], 12)
        self.assertEqual(result.summary.match_count, 3)
        self.assertEqual(len(result.matches), 3)

    async def test_bnet_query_resolves_customer_token(self) -> None:
        engine = _RecordingEngine(_sample_engine_payload())
        search_module = _StubSearchModule()
        module = DashenCompetitiveStrengthModule(api_client=SimpleNamespace(), search_module=search_module)
        module.engine = engine
        module._load_ow_config = lambda: {"heroList": [], "mapList": []}

        result = await module.query_competitive_strength(
            DashenCompetitiveStrengthQuery(bnet_id="Player#12345", limit=5),
            render=False,
        )

        self.assertEqual(search_module.calls, [("Player#12345", False)])
        self.assertEqual(engine.calls[0]["customer_token"], "resolved-token")
        self.assertEqual(engine.calls[0]["limit"], 5)
        self.assertEqual(result.full_id, "Player#12345")

    async def test_empty_match_payload_raises_module_error(self) -> None:
        engine = _RecordingEngine({"summary": {"match_count": 0}, "matches": []})
        module = DashenCompetitiveStrengthModule(api_client=SimpleNamespace(), search_module=_ExplodingSearchModule())
        module.engine = engine
        module._load_ow_config = lambda: {"heroList": [], "mapList": []}

        with self.assertRaises(ModuleError) as ctx:
            await module.query_competitive_strength(
                DashenCompetitiveStrengthQuery(customer_token="token-1"),
                render=False,
            )
        self.assertEqual(ctx.exception.error, "competitive_strength_empty")


class RenderSmokeTests(unittest.TestCase):
    def test_render_competitive_strength_returns_png_bytes(self) -> None:
        try:
            image = render_quick_strength(
                player_name="Player#12345",
                bnet_id="12345",
                summary=_sample_engine_payload()["summary"],
                matches=_sample_engine_payload()["matches"],
                avatar_bytes=None,
                theme=COMPETITIVE_STRENGTH_THEME,
                title_text="竞技强度指数",
                chart_title_text="竞技强度趋势",
                match_scope_text="竞技",
            )
        except RuntimeError as exc:
            self.skipTest(str(exc))
            return

        self.assertTrue(image.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(image.media_type, "image/png")


class _RecordingEngine:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def build(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class _StubSearchModule:
    def __init__(self) -> None:
        self.calls = []

    async def search(self, query, render=False):
        self.calls.append((query, render))
        result = SimpleNamespace(
            query=query,
            customer_token="resolved-token",
            bnet_id="12345",
            full_id="Player#12345",
            icon_url="",
            payload={"code": 0, "data": {}},
        )
        return SimpleNamespace(result=result)


class _ExplodingSearchModule:
    async def search(self, query, render=False):
        raise AssertionError("search() should not be called for direct customer_token queries")


class _StubCompetitiveRequests(DashenCompetitiveStrengthRequests):
    def __init__(self) -> None:
        self.api_client = SimpleNamespace()

    async def list_recent_competitive_matches(self, customer_token, *, limit, include_previous_season, pages_per_batch=1):
        return [
            {
                "matchId": "m1",
                "beginTs": 1777098388787,
                "matchRet": 1,
                "mapGuid": "map-1",
                "_dashenSeason": 22,
            }
        ]

    async def get_match_detail(self, customer_token, match_id):
        return {
            "code": 0,
            "data": {
                "matchRet": 1,
                "mapGuid": "map-1",
                "teammateList": [
                    {"customerToken": "t1", "rankInfo": {"rankScore": 395}},
                    {"customerToken": "t2", "rankInfo": {"rankScore": 495}},
                ],
                "enemyList": [
                    {"customerToken": "e1", "rankInfo": {"rankScore": 595}},
                ],
            },
        }

    async def list_recent_competitive_payloads(self, customer_token, *, current_season=None, max_lookback=1):
        payload_map = {
            "t1": [(22, [{"roleType": "tank", "lastRankInfo": {"rankScore": 395}}])],
            "t2": [(22, [{"roleType": "dps", "lastRankInfo": {"rankScore": 495}}])],
            "e1": [(21, [{"roleType": "healer", "lastRankInfo": {"rankScore": 595}}])],
        }
        return payload_map.get(customer_token, [(22, [])])


def _sample_engine_payload():
    return {
        "summary": {
            "match_count": 3,
            "overall_avg_score": 3322.9,
            "overall_avg_rank": "Diamond 2",
            "score_range": {"min": 3138, "max": 3657},
            "used_previous_season_fallback": False,
        },
        "matches": [
            {
                "match_id": "m1",
                "begin_ts": 1777098388787,
                "result": 1,
                "map_guid": "map-1",
                "avg_score": 3410.0,
                "avg_rank": "Diamond 1",
                "role_range": {"min": 3250, "max": 3550},
                "all_role_range": {"min": 3180, "max": 3680},
                "current_role_range": {"min": 3250, "max": 3550},
                "current_all_role_range": {"min": 3180, "max": 3680},
                "team_scores": [3450, 3380, 3320],
                "enemy_scores": [3550, 3410, 3250],
                "team_streak_avg": 0.0,
                "enemy_streak_avg": 0.0,
            },
            {
                "match_id": "m2",
                "begin_ts": 1777098389799,
                "result": -1,
                "map_guid": "map-2",
                "avg_score": 3290.0,
                "avg_rank": "Diamond 3",
                "role_range": {"min": 3120, "max": 3470},
                "all_role_range": {"min": 3050, "max": 3590},
                "current_role_range": {"min": 3120, "max": 3470},
                "current_all_role_range": {"min": 3050, "max": 3590},
                "team_scores": [3290, 3240, 3180],
                "enemy_scores": [3470, 3330, 3120],
                "team_streak_avg": 0.0,
                "enemy_streak_avg": 0.0,
            },
            {
                "match_id": "m3",
                "begin_ts": 1777098390800,
                "result": 1,
                "map_guid": "map-3",
                "avg_score": 3268.7,
                "avg_rank": "Diamond 3",
                "role_range": {"min": 3138, "max": 3410},
                "all_role_range": {"min": 3080, "max": 3657},
                "current_role_range": {"min": 3138, "max": 3410},
                "current_all_role_range": {"min": 3080, "max": 3657},
                "team_scores": [3410, 3320, 3260],
                "enemy_scores": [3330, 3230, 3138],
                "team_streak_avg": 0.0,
                "enemy_streak_avg": 0.0,
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
