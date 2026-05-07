from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT_DIR = REPO_ROOT.parent
for candidate in (PARENT_DIR, REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from overstats.src.modules.auto_route import AutoRouteModule, AutoRouteToolCall, extract_tool_call
    from overstats.src.modules.errors import ModuleError
except ModuleNotFoundError:
    from src.modules.auto_route import AutoRouteModule, AutoRouteToolCall, extract_tool_call
    from src.modules.errors import ModuleError


class ToolCallParsingTests(unittest.TestCase):
    def test_extracts_openai_tool_calls(self) -> None:
        result = extract_tool_call(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "summary_week",
                                        "arguments": '{"target":"Player#12345"}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )

        self.assertEqual(result.name, "summary_week")
        self.assertEqual(result.arguments["target"], "Player#12345")

    def test_extracts_function_call_fallback(self) -> None:
        result = extract_tool_call(
            {
                "choices": [
                    {
                        "message": {
                            "function_call": {
                                "name": "patch_notes",
                                "arguments": '{"patch_kind":"major"}',
                            }
                        }
                    }
                ]
            }
        )

        self.assertEqual(result.name, "patch_notes")
        self.assertEqual(result.arguments["patch_kind"], "major")

    def test_rejects_missing_tool_call(self) -> None:
        with self.assertRaises(ModuleError) as ctx:
            extract_tool_call({"choices": [{"message": {"content": "hello"}}]})

        self.assertEqual(ctx.exception.error, "auto_route_no_tool_call")

    def test_rejects_invalid_tool_arguments(self) -> None:
        with self.assertRaises(ModuleError) as ctx:
            extract_tool_call(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "summary_week",
                                            "arguments": '{"target":',
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            )

        self.assertEqual(ctx.exception.error, "auto_route_invalid_arguments")


class AutoRouteSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_tool_name(self) -> None:
        module = AutoRouteModule(requests=_StubRequests(AutoRouteToolCall(name="unknown_tool", arguments={})))

        with self.assertRaises(ModuleError) as ctx:
            await module.select("test")

        self.assertEqual(ctx.exception.error, "auto_route_invalid_tool")

    async def test_match_detail_converts_index_and_promotes_analyze(self) -> None:
        module = AutoRouteModule(
            requests=_StubRequests(
                AutoRouteToolCall(
                    name="dashen_match",
                    arguments={
                        "target": "Player#12345",
                        "index": 3,
                        "show_all_heroes": False,
                        "analyze": True,
                    },
                )
            )
        )

        result = await module.select("看第3场并锐评")

        self.assertEqual(result.endpoint, "/api/v2/dashen-match/detail/replies")
        self.assertEqual(result.endpoint_mode, "replies")
        self.assertEqual(result.payload["bnet_id"], "Player#12345")
        self.assertEqual(result.payload["index"], 2)
        self.assertTrue(result.payload["show_all_heroes"])
        self.assertTrue(result.payload["analyze"])

    async def test_token_target_maps_to_customer_token(self) -> None:
        module = AutoRouteModule(
            requests=_StubRequests(
                AutoRouteToolCall(
                    name="dashen_profile",
                    arguments={"target": "ctoken:abc123", "mode": "ranked"},
                )
            )
        )

        result = await module.select("看这个token的竞技资料")

        self.assertEqual(result.endpoint, "/api/v2/dashen-profile/image")
        self.assertEqual(result.payload["customer_token"], "abc123")
        self.assertEqual(result.payload["mode"], "competitive")
        self.assertNotIn("bnet_id", result.payload)

    async def test_hero_pick_rate_normalizes_view_mode_and_mmr(self) -> None:
        module = AutoRouteModule(
            requests=_StubRequests(
                AutoRouteToolCall(
                    name="hero_pick_rate",
                    arguments={
                        "view": "history",
                        "game_mode": "ranked",
                        "mmr": "grandmaster",
                        "hero": "Ana",
                        "history_limit": "30",
                    },
                )
            )
        )

        result = await module.select("看安娜竞技宗师历史")

        self.assertEqual(result.endpoint_mode, "image")
        self.assertEqual(result.payload["view"], "history")
        self.assertEqual(result.payload["game_mode"], "competitive")
        self.assertEqual(result.payload["mmr"], "Grandmaster")
        self.assertEqual(result.payload["hero"], "Ana")
        self.assertEqual(result.payload["history_limit"], 30)

    async def test_patch_notes_defaults_and_normalizes_kind(self) -> None:
        module = AutoRouteModule(
            requests=_StubRequests(
                AutoRouteToolCall(
                    name="patch_notes",
                    arguments={"patch_kind": "major"},
                )
            )
        )

        result = await module.select("看大更新补丁")

        self.assertEqual(result.endpoint, "/api/v2/patch-notes/image")
        self.assertEqual(result.payload["patch_kind"], "big")

    async def test_ow_esports_routes_to_image_endpoint(self) -> None:
        module = AutoRouteModule(
            requests=_StubRequests(
                AutoRouteToolCall(
                    name="ow_esports",
                    arguments={},
                )
            )
        )

        result = await module.select("看看OW赛事")

        self.assertEqual(result.endpoint, "/api/v2/ow-esports/image")
        self.assertEqual(result.endpoint_mode, "image")
        self.assertEqual(result.module_name, "ow_esports")
        self.assertEqual(result.payload, {})

    async def test_endpoint_priority_prefers_replies_then_image(self) -> None:
        module = AutoRouteModule(requests=_StubRequests(AutoRouteToolCall(name="dashen_match", arguments={"target": "Player#1"})))
        match_result = await module.select("看近期对局")
        self.assertEqual(match_result.endpoint_mode, "replies")

        module = AutoRouteModule(requests=_StubRequests(AutoRouteToolCall(name="summary_week", arguments={"target": "Player#1"})))
        summary_result = await module.select("看这周总结")
        self.assertEqual(summary_result.endpoint_mode, "image")


class _StubRequests:
    def __init__(self, tool_call: AutoRouteToolCall) -> None:
        self.tool_call = tool_call

    async def select_tool_call(self, **kwargs) -> AutoRouteToolCall:  # noqa: ANN003
        return self.tool_call


if __name__ == "__main__":
    unittest.main()
