from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from overstats.src.modules.errors import ModuleError
    from overstats.src.modules.ow_esports.render import RenderedImage, render_ow_esports
    from overstats.src.modules.ow_esports.requests import (
        OWEsportsRequests,
        STATUS_FINISHED,
        STATUS_LIVE,
        STATUS_UPCOMING,
        build_ow_esports_sections,
        normalize_ow_esports_rows,
    )
    from overstats.src.modules.ow_esports.service import OWEsportsModule, OWEsportsOutput
    import overstats.src.modules.ow_esports.service as ow_esports_service_module
    import overstats.src.server as server_module
except ModuleNotFoundError:
    from src.modules.errors import ModuleError
    from src.modules.ow_esports.render import RenderedImage, render_ow_esports
    from src.modules.ow_esports.requests import (
        OWEsportsRequests,
        STATUS_FINISHED,
        STATUS_LIVE,
        STATUS_UPCOMING,
        build_ow_esports_sections,
        normalize_ow_esports_rows,
    )
    from src.modules.ow_esports.service import OWEsportsModule, OWEsportsOutput
    import src.modules.ow_esports.service as ow_esports_service_module
    import src.server as server_module


def _sample_raw_payload() -> list[dict]:
    return [
        {
            "name": "Alpha vs Beta",
            "status": "running",
            "begin_at": "2026-05-07T10:00:00Z",
            "league": {"name": "OWCS Asia"},
            "tournament": {"region": "CN"},
            "opponents": [
                {
                    "opponent": {
                        "id": 1,
                        "name": "Team Alpha",
                        "acronym": "ALP",
                        "image_url": "https://example.com/a.png",
                        "location": "CN",
                    }
                },
                {
                    "opponent": {
                        "id": 2,
                        "name": "Team Beta",
                        "acronym": "BET",
                        "image_url": "https://example.com/b.png",
                        "location": "KR",
                    }
                },
            ],
            "results": [
                {"team_id": 1, "score": 2},
                {"team_id": 2, "score": 1},
            ],
        },
        {
            "name": "Gamma vs Delta",
            "status": "not_started",
            "scheduled_at": "2026-05-08T12:30:00Z",
            "league": {"name": "OWCS Asia"},
            "tournament": {"region": "TW"},
            "opponents": [
                {"opponent": {"id": 3, "name": "Team Gamma", "acronym": "GAM", "location": "TW"}},
                {"opponent": {"id": 4, "name": "Team Delta", "acronym": "DEL", "location": "HK"}},
            ],
            "results": [],
        },
        {
            "name": "Epsilon vs Zeta",
            "status": "finished",
            "begin_at": "2026-05-06T15:00:00Z",
            "league": {"name": "OWCS NA"},
            "tournament": {"region": "US"},
            "opponents": [
                {"opponent": {"id": 5, "name": "Team Epsilon", "acronym": "EPS", "location": "US"}},
                {"opponent": {"id": 6, "name": "Team Zeta", "acronym": "ZET", "location": "CA"}},
            ],
            "results": [
                {"team_id": 5, "score": 0},
                {"team_id": 6, "score": 3},
            ],
        },
    ]


class RequestNormalizationTests(unittest.TestCase):
    def test_normalizes_raw_pandascore_payload(self) -> None:
        rows = normalize_ow_esports_rows(_sample_raw_payload())

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["league_name"], "OWCS Asia")
        self.assertEqual(rows[0]["status"], STATUS_LIVE)
        self.assertEqual(rows[0]["score"], "2:1")
        self.assertEqual(rows[0]["team1"]["name"], "Team Alpha")
        self.assertEqual(rows[0]["team2"]["region"], "KR")
        self.assertIsInstance(rows[0]["start_timestamp"], int)

        upcoming = next(row for row in rows if row["match_name"] == "Gamma vs Delta")
        self.assertEqual(upcoming["status"], STATUS_UPCOMING)
        self.assertEqual(upcoming["score"], STATUS_UPCOMING)
        self.assertEqual(upcoming["team1"]["region"], "CN(TW)")
        self.assertEqual(upcoming["team2"]["region"], "CN(HK)")

    def test_normalizes_wrapped_payload(self) -> None:
        payload = {"data": {"matches": _sample_raw_payload()}}
        rows = normalize_ow_esports_rows(payload)

        self.assertEqual(len(rows), 3)
        self.assertEqual({row["league_name"] for row in rows}, {"OWCS Asia", "OWCS NA"})

    def test_build_sections_limits_recent_ended_matches(self) -> None:
        rows = []
        for index in range(12):
            rows.append(
                {
                    "league_name": "OWCS Asia",
                    "status": STATUS_FINISHED,
                    "raw_status": "finished",
                    "match_name": f"Ended {index}",
                    "start_time": "2026-05-01 00:00",
                    "start_timestamp": 1_700_000_000 + index,
                    "score": "3:2",
                    "score1": 3,
                    "score2": 2,
                    "team1": {"id": 1, "name": "A", "short_name": "A", "logo": "", "region": "CN"},
                    "team2": {"id": 2, "name": "B", "short_name": "B", "logo": "", "region": "KR"},
                }
            )

        sections = build_ow_esports_sections(rows)

        self.assertEqual(len(sections), 1)
        ended_section = sections[0]["status_sections"][0]
        self.assertEqual(ended_section["status"], STATUS_FINISHED)
        self.assertEqual(len(ended_section["rows"]), 10)
        self.assertEqual(ended_section["hidden_count"], 2)
        self.assertEqual(ended_section["rows"][0]["match_name"], "Ended 11")


class ModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_returns_rows_sections_and_image(self) -> None:
        original_api_key = getattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", "")
        setattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", "test-api-key")
        try:
            rows = normalize_ow_esports_rows(_sample_raw_payload())
            module = OWEsportsModule(
                requests=_StubRequests(rows=rows),
                time_provider=lambda: dt.datetime(2026, 5, 7, 18, 30, 0),
                renderer=_stub_renderer,
            )
            result = await module.query_ow_esports(render=True)
        finally:
            setattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", original_api_key)

        self.assertTrue(result.to_dict()["ok"])
        self.assertTrue(result.realtime)
        self.assertEqual(result.generated_at, "2026-05-07 18:30:00")
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(len(result.sections), 2)
        self.assertEqual(result.image.content, b"ow-esports-image")

    async def test_service_errors_when_api_key_not_configured(self) -> None:
        original_api_key = getattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", "")
        setattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", "")
        try:
            module = OWEsportsModule(requests=_StubRequests(rows=[]))
            with self.assertRaises(ModuleError) as ctx:
                await module.query_ow_esports(render=False)
        finally:
            setattr(ow_esports_service_module.app_config, "OW_ESPORTS_API_KEY", original_api_key)

        self.assertEqual(ctx.exception.error, "ow_esports_not_configured")


class RenderSmokeTests(unittest.TestCase):
    def test_render_empty_state_outputs_png(self) -> None:
        try:
            from PIL import Image  # noqa: F401
        except ModuleNotFoundError as exc:
            self.skipTest(str(exc))
            return

        rendered = render_ow_esports([], sections=[], generated_at="2026-05-07 12:00:00", logo_assets={})

        self.assertTrue(rendered.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(rendered.media_type, "image/png")

    def test_render_mixed_status_outputs_png(self) -> None:
        try:
            from PIL import Image
        except ModuleNotFoundError as exc:
            self.skipTest(str(exc))
            return

        rows = normalize_ow_esports_rows(_sample_raw_payload())
        sections = build_ow_esports_sections(rows)
        buffer = BytesIO()
        Image.new("RGBA", (128, 96), (80, 150, 220, 255)).save(buffer, format="PNG")
        rendered = render_ow_esports(
            rows,
            sections=sections,
            generated_at="2026-05-07 12:00:00",
            logo_assets={"https://example.com/a.png": buffer.getvalue()},
        )

        self.assertTrue(rendered.content.startswith(b"\x89PNG\r\n\x1a\n"))


class ServerBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_bridge_returns_json_and_image(self) -> None:
        original_module = server_module.ow_esports_module
        server_module.ow_esports_module = _StubOWEsportsModule()
        try:
            service = server_module.OverstatsCoreService()
            payload = await service.handle_ow_esports({})
            image = await service.handle_ow_esports_image({})
        finally:
            server_module.ow_esports_module = original_module

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rows"][0]["league_name"], "OWCS Asia")
        self.assertEqual(image, b"stub-ow-esports-image")


class _StubRequests(OWEsportsRequests):
    def __init__(self, *, rows) -> None:
        self._rows = list(rows)

    async def fetch_rows(self):
        return list(self._rows)

    async def fetch_logo_assets(self, rows, *, max_concurrency=8):  # noqa: ANN001
        return {}


class _StubOWEsportsModule:
    async def query_ow_esports(self, *, render=False):
        rows = normalize_ow_esports_rows(_sample_raw_payload())
        sections = build_ow_esports_sections(rows)
        return OWEsportsOutput(
            generated_at="2026-05-07 12:00:00",
            realtime=True,
            rows=tuple(rows),
            sections=tuple(sections),
            image=RenderedImage(content=b"stub-ow-esports-image") if render else None,
        )


def _stub_renderer(rows, *, sections, generated_at, logo_assets):  # noqa: ANN001
    return RenderedImage(content=b"ow-esports-image")


if __name__ == "__main__":
    unittest.main()
