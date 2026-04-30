from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.request import ProxyHandler, Request, build_opener, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from overstats.src.http_server import get_http_ui_bootstrap_payload, get_http_ui_module_specs, resolve_http_ui_asset
    import overstats.src.server as server_module
except ModuleNotFoundError:
    from src.http_server import get_http_ui_bootstrap_payload, get_http_ui_module_specs, resolve_http_ui_asset
    import src.server as server_module


class RegistryTests(unittest.TestCase):
    def test_common_modules_are_registered(self) -> None:
        modules = get_http_ui_module_specs()
        module_map = {item.id: item for item in modules}

        self.assertIn("dashen-profile", module_map)
        self.assertIn("dashen-match", module_map)
        self.assertIn("dashen-match-detail", module_map)
        self.assertIn("dashen-summary-week", module_map)
        self.assertIn("ow-hero-pick-rate", module_map)
        self.assertIn("ow-shop", module_map)
        self.assertIn("patch-notes", module_map)
        self.assertFalse(module_map["ow-hero-pick-rate"].requires_target)
        self.assertFalse(module_map["ow-shop"].requires_target)
        self.assertFalse(module_map["patch-notes"].requires_target)
        self.assertTrue(module_map["dashen-profile"].requires_target)
        self.assertNotIn("player-identity-search", module_map)
        self.assertEqual(module_map["dashen-summary-week"].json_endpoint, "/api/v2/dashen-summary/week")
        self.assertEqual(module_map["dashen-summary-week"].image_endpoint, "/api/v2/dashen-summary/week/image")
        self.assertEqual(module_map["dashen-match-detail"].json_endpoint, "/api/v2/dashen-match/detail/replies")

    def test_module_field_specs_match_expected_payload_keys(self) -> None:
        modules = {item.id: item for item in get_http_ui_module_specs()}

        dashen_profile_fields = {field.id: field for field in modules["dashen-profile"].fields}
        patch_notes_fields = {field.id: field for field in modules["patch-notes"].fields}
        match_detail_fields = {field.id: field for field in modules["dashen-match-detail"].fields}
        hero_pick_rate_fields = {field.id: field for field in modules["ow-hero-pick-rate"].fields}

        self.assertEqual(dashen_profile_fields["profile_mode"].payload_key, "mode")
        self.assertEqual(patch_notes_fields["patch_kind"].payload_key, "patch_kind")
        self.assertEqual(patch_notes_fields["patch_kind"].default, "latest")
        self.assertEqual(match_detail_fields["analyze"].payload_key, "analyze")
        self.assertEqual(match_detail_fields["show_all_heroes"].payload_key, "show_all_heroes")
        self.assertEqual(hero_pick_rate_fields["view"].payload_key, "view")
        self.assertEqual(hero_pick_rate_fields["game_mode"].payload_key, "game_mode")
        self.assertEqual(hero_pick_rate_fields["mmr"].payload_key, "mmr")
        self.assertEqual(hero_pick_rate_fields["hero"].payload_key, "hero")
        self.assertEqual(hero_pick_rate_fields["history_limit"].payload_key, "history_limit")

    def test_bootstrap_payload_matches_registry(self) -> None:
        payload = get_http_ui_bootstrap_payload()

        self.assertIn("modules", payload)
        self.assertEqual(payload["default_module_id"], "dashen-profile")
        self.assertGreaterEqual(len(payload["modules"]), 11)


class AssetResponseTests(unittest.TestCase):
    def test_root_asset_contains_bootstrap_and_preview_layout(self) -> None:
        response = resolve_http_ui_asset("/")

        self.assertIsNotNone(response)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        html = response.body.decode("utf-8")
        self.assertIn("Overstats 控制面板", html)
        self.assertIn('id="moduleNav"', html)
        self.assertIn('id="requestForm"', html)
        self.assertIn('id="jsonPreview"', html)
        self.assertIn('id="imagePreview"', html)
        self.assertIn('id="replyPreview"', html)
        self.assertIn("JSON 预览", html)
        self.assertIn("图片预览", html)
        self.assertIn("回复预览", html)
        self.assertIn("window.__OVERSTATS_UI_BOOTSTRAP__", html)
        self.assertIn("dashen-profile", html)
        self.assertIn("dashen-match-detail", html)

    def test_static_assets_and_ui_health_exist(self) -> None:
        css_response = resolve_http_ui_asset("/ui/app.css")
        js_response = resolve_http_ui_asset("/ui/app.js")
        health_response = resolve_http_ui_asset("/ui/healthz")

        self.assertIsNotNone(css_response)
        self.assertIsNotNone(js_response)
        self.assertIsNotNone(health_response)
        self.assertIn("text/css", css_response.content_type)
        self.assertIn("application/javascript", js_response.content_type)
        self.assertIn("application/json", health_response.content_type)
        self.assertIsNone(resolve_http_ui_asset("/healthz"))

    def test_js_asset_contains_match_detail_reply_bundle_logic(self) -> None:
        response = resolve_http_ui_asset("/ui/app.js")

        self.assertIsNotNone(response)
        js_text = response.body.decode("utf-8")
        self.assertIn("MATCH_DETAIL_MODULE_ID", js_text)
        self.assertIn("getEffectiveEndpoint", js_text)
        self.assertIn("renderReplyPreview", js_text)
        self.assertIn("extractFirstImageReply", js_text)


class ServerRouteIntegrationTests(unittest.TestCase):
    def test_root_ui_routes_and_existing_api_route_work_together(self) -> None:
        original_load_query_tool = server_module.load_query_tool
        original_ensure_query_tool_assets = server_module.ensure_query_tool_assets
        original_request_metrics_recorder = server_module.RequestMetricsRecorder
        original_sync_service = server_module.OWHeroLeaderboardSyncService
        original_pick_rate_module = server_module.ow_hero_pick_rate_module
        original_ow_shop_module = server_module.ow_shop_module
        original_player_identity_search_module = server_module.player_identity_search_module
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
        server_module.ow_hero_pick_rate_module = _StubOWHeroPickRateModule()
        server_module.ow_shop_module = _StubOWShopModule()
        server_module.player_identity_search_module = _StubPlayerIdentitySearchModule()

        server = None
        thread = None
        try:
            config = server_module.APIConfig(
                host="127.0.0.1",
                port=0,
                use_stream_response=False,
                dashen_max_concurrent_requests=1,
            )
            server = server_module.create_server(config)
            thread = threading.Thread(target=server.serve_forever, name="test-http-ui-server", daemon=True)
            thread.start()
            time.sleep(0.1)

            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            opener = build_opener(ProxyHandler({}))

            with opener.open(base_url + "/", timeout=10) as response:
                html_text = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
                self.assertIn("Overstats 控制面板", html_text)

            with opener.open(base_url + "/ui/app.js", timeout=10) as response:
                js_text = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("application/javascript", response.headers.get("Content-Type", ""))
                self.assertIn("MATCH_DETAIL_MODULE_ID", js_text)

            with opener.open(base_url + "/ui/app.css", timeout=10) as response:
                css_text = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("text/css", response.headers.get("Content-Type", ""))
                self.assertIn(".app-shell", css_text)

            with opener.open(base_url + "/ui/healthz", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["service"], "overstats-http-ui")

            with opener.open(base_url + "/healthz", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["service"], "overstats-core")

            body = json.dumps({}).encode("utf-8")
            request = Request(
                base_url + "/api/v2/ow-shop",
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["sections"][0]["title"], "Test Shop")

            pick_rate_body = json.dumps({"view": "ranking", "game_mode": "quick", "mmr": "all"}).encode("utf-8")
            pick_rate_request = Request(
                base_url + "/api/v2/ow-hero-pick-rate",
                data=pick_rate_body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(pick_rate_request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["view"], "ranking")
                self.assertEqual(payload["heroes"][0]["hero_name"], "安娜")

            pick_rate_image_request = Request(
                base_url + "/api/v2/ow-hero-pick-rate/image",
                data=pick_rate_body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(pick_rate_image_request, timeout=10) as response:
                image_body = response.read()
                self.assertEqual(response.status, 200)
                self.assertIn("image/png", response.headers.get("Content-Type", ""))
                self.assertEqual(image_body, b"pick-rate-image")

            identity_body = json.dumps({"bnet_id": "12345"}).encode("utf-8")
            identity_request = Request(
                base_url + "/api/v2/internal/player-identity/search",
                data=identity_body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with opener.open(identity_request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["query"]["bnet_id"], "12345")
                self.assertEqual(payload["candidates"], ["GrowlR#5632", "GrowlRAlt#9001"])
                self.assertEqual(payload["matches"][0]["match_type"], "exact")
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
            server_module.ow_hero_pick_rate_module = original_pick_rate_module
            server_module.ow_shop_module = original_ow_shop_module
            server_module.player_identity_search_module = original_player_identity_search_module
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


class _StubOWShopOutput:
    def to_dict(self):
        return {
            "ok": True,
            "generated_at": "2026-04-29 12:34:56",
            "cache_ttl_seconds": 900,
            "sections": [
                {
                    "title": "Test Shop",
                    "expires_text": "",
                    "item_count": 0,
                    "items": [],
                }
            ],
        }


class _StubOWShopImage:
    content = b"stub-image"


class _StubOWShopModule:
    async def query_shop(self, *, render=False):
        if render:
            output = _StubOWShopOutput()
            output.image = _StubOWShopImage()
            return output
        return _StubOWShopOutput()


class _StubOWHeroPickRateOutput:
    def __init__(self, *, with_image: bool = False) -> None:
        self.image = _StubOWHeroPickRateImage() if with_image else None

    def to_dict(self):
        return {
            "ok": True,
            "view": "ranking",
            "region": "cn",
            "game_mode": "quick",
            "mmr": "all",
            "snapshot": {
                "season": 2,
                "ds": "2026-04-29",
                "hero_count": 1,
            },
            "heroes": [
                {
                    "rank": 1,
                    "hero_guid": "ana",
                    "hero_name": "安娜",
                    "hero_role": "support",
                    "selection_ratio": 7.1,
                    "ban_ratio": 0.0,
                    "win_ratio": 51.2,
                    "kda": 4.2,
                    "icon_url": "",
                }
            ],
        }


class _StubOWHeroPickRateImage:
    content = b"pick-rate-image"


class _StubOWHeroPickRateModule:
    async def query_pick_rate(self, query, *, render=False):  # noqa: ANN001
        return _StubOWHeroPickRateOutput(with_image=render)


class _StubPlayerIdentityMatch:
    def __init__(self, bnet_id, battletag, battlename, battlenum, update_time, match_type):  # noqa: ANN001
        self.bnet_id = bnet_id
        self.battletag = battletag
        self.battlename = battlename
        self.battlenum = battlenum
        self.update_time = update_time
        self.match_type = match_type

    def to_dict(self):
        return {
            "bnet_id": self.bnet_id,
            "battletag": self.battletag,
            "battlename": self.battlename,
            "battlenum": self.battlenum,
            "update_time": self.update_time,
            "match_type": self.match_type,
        }


class _StubPlayerIdentitySearchOutput:
    def __init__(self, query, matches):  # noqa: ANN001
        self.query = query
        self.matches = tuple(matches)


class _StubPlayerIdentitySearchModule:
    async def search(self, query):  # noqa: ANN001
        return _StubPlayerIdentitySearchOutput(
            query=query,
            matches=(
                _StubPlayerIdentityMatch("12345", "GrowlR#5632", "GrowlR", "5632", 1714464000, "exact"),
                _StubPlayerIdentityMatch("123456", "GrowlRAlt#9001", "GrowlRAlt", "9001", 1714463000, "prefix"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
