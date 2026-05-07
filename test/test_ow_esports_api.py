from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    import overstats.src.server as server_module
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    import src.server as server_module
    from src.modules.errors import ModuleError


class OWEsportsRouteTests(unittest.TestCase):
    def test_routes_return_json_and_png(self) -> None:
        original_load_query_tool = server_module.load_query_tool
        original_ensure_query_tool_assets = server_module.ensure_query_tool_assets
        original_request_metrics_recorder = server_module.RequestMetricsRecorder
        original_sync_service = server_module.OWHeroLeaderboardSyncService
        original_ow_esports_module = server_module.ow_esports_module
        original_client_recorder = server_module.dashen_api_client.request_metrics_recorder

        server_module.load_query_tool = lambda: {}
        server_module.ensure_query_tool_assets = lambda _config: {
            "checked": 0,
            "cached": 0,
            "downloaded": 0,
            "failed": 0,
            "asset_dir": ".",
        }
        server_module.RequestMetricsRecorder = _StubRequestMetricsRecorder
        server_module.OWHeroLeaderboardSyncService = _StubSyncService
        server_module.ow_esports_module = _StubOWEsportsModule()

        server = None
        thread = None
        try:
            config = server_module.APIConfig(
                host="127.0.0.1",
                port=0,
                use_stream_response=False,
                dashen_max_concurrent_requests=1,
                dashen_max_accepted_requests=4,
            )
            server = server_module.create_server(config)
            thread = threading.Thread(target=server.serve_forever, name="test-ow-esports-server", daemon=True)
            thread.start()
            time.sleep(0.1)

            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            opener = build_opener(ProxyHandler({}))
            body = json.dumps({}).encode("utf-8")

            json_request = Request(
                base_url + "/api/v2/ow-esports",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(json_request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["realtime"])
                self.assertEqual(payload["rows"][0]["league_name"], "OWCS Asia")

            image_request = Request(
                base_url + "/api/v2/ow-esports/image",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(image_request, timeout=10) as response:
                image_body = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn("image/png", response.headers.get("Content-Type", ""))
                self.assertEqual(image_body, b"ow-esports-image")
        finally:
            if server is not None:
                try:
                    server.shutdown()
                except Exception:
                    pass
                try:
                    server.server_close()
                except Exception:
                    pass
            if thread is not None:
                thread.join(timeout=2)
            server_module.load_query_tool = original_load_query_tool
            server_module.ensure_query_tool_assets = original_ensure_query_tool_assets
            server_module.RequestMetricsRecorder = original_request_metrics_recorder
            server_module.OWHeroLeaderboardSyncService = original_sync_service
            server_module.ow_esports_module = original_ow_esports_module
            server_module.dashen_api_client.request_metrics_recorder = original_client_recorder

    def test_route_returns_clear_error_when_not_configured(self) -> None:
        original_load_query_tool = server_module.load_query_tool
        original_ensure_query_tool_assets = server_module.ensure_query_tool_assets
        original_request_metrics_recorder = server_module.RequestMetricsRecorder
        original_sync_service = server_module.OWHeroLeaderboardSyncService
        original_ow_esports_module = server_module.ow_esports_module
        original_client_recorder = server_module.dashen_api_client.request_metrics_recorder

        server_module.load_query_tool = lambda: {}
        server_module.ensure_query_tool_assets = lambda _config: {
            "checked": 0,
            "cached": 0,
            "downloaded": 0,
            "failed": 0,
            "asset_dir": ".",
        }
        server_module.RequestMetricsRecorder = _StubRequestMetricsRecorder
        server_module.OWHeroLeaderboardSyncService = _StubSyncService
        server_module.ow_esports_module = _FailingOWEsportsModule()

        server = None
        thread = None
        try:
            config = server_module.APIConfig(
                host="127.0.0.1",
                port=0,
                use_stream_response=False,
                dashen_max_concurrent_requests=1,
                dashen_max_accepted_requests=4,
            )
            server = server_module.create_server(config)
            thread = threading.Thread(target=server.serve_forever, name="test-ow-esports-server-fail", daemon=True)
            thread.start()
            time.sleep(0.1)

            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            opener = build_opener(ProxyHandler({}))
            body = json.dumps({}).encode("utf-8")
            json_request = Request(
                base_url + "/api/v2/ow-esports",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                opener.open(json_request, timeout=10)

            error_payload = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(ctx.exception.code, 503)
            self.assertEqual(error_payload["error"], "ow_esports_not_configured")
        finally:
            if server is not None:
                try:
                    server.shutdown()
                except Exception:
                    pass
                try:
                    server.server_close()
                except Exception:
                    pass
            if thread is not None:
                thread.join(timeout=2)
            server_module.load_query_tool = original_load_query_tool
            server_module.ensure_query_tool_assets = original_ensure_query_tool_assets
            server_module.RequestMetricsRecorder = original_request_metrics_recorder
            server_module.OWHeroLeaderboardSyncService = original_sync_service
            server_module.ow_esports_module = original_ow_esports_module
            server_module.dashen_api_client.request_metrics_recorder = original_client_recorder


class _StubRequestMetricsRecorder:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def enqueue(self, url, source_type, success):  # noqa: ANN001
        return None


class _StubSyncService:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _StubOWEsportsImage:
    content = b"ow-esports-image"


class _StubOWEsportsOutput:
    def __init__(self, *, with_image: bool) -> None:
        self.image = _StubOWEsportsImage() if with_image else None

    def to_dict(self):
        return {
            "ok": True,
            "generated_at": "2026-05-07 12:00:00",
            "realtime": True,
            "rows": [
                {
                    "league_name": "OWCS Asia",
                    "status": "正在进行",
                    "raw_status": "running",
                    "match_name": "Alpha vs Beta",
                    "start_time": "2026-05-07 18:00",
                    "start_timestamp": 1778176800,
                    "score": "2:1",
                    "score1": 2,
                    "score2": 1,
                    "team1": {"id": 1, "name": "Alpha", "short_name": "ALP", "logo": "", "region": "CN"},
                    "team2": {"id": 2, "name": "Beta", "short_name": "BET", "logo": "", "region": "KR"},
                }
            ],
            "sections": [
                {
                    "league_name": "OWCS Asia",
                    "status_sections": [
                        {
                            "status": "正在进行",
                            "rows": [],
                            "hidden_count": 0,
                        }
                    ],
                }
            ],
        }


class _StubOWEsportsModule:
    async def query_ow_esports(self, *, render=False):
        return _StubOWEsportsOutput(with_image=render)


class _FailingOWEsportsModule:
    async def query_ow_esports(self, *, render=False):
        raise ModuleError(
            error="ow_esports_not_configured",
            message="OW esports API key is not configured.",
            status_code=503,
            hint="Set OW_ESPORTS_API_KEY in overstats/config/config.py.",
        )


if __name__ == "__main__":
    unittest.main()
