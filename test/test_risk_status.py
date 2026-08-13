from __future__ import annotations

import unittest

from src.modules.risk_status import (
    draw_risk_status_badge,
    format_expire_time,
    format_risk_status,
    parse_risk_status,
)


class RiskStatusTests(unittest.TestCase):
    def test_missing_or_empty_entry_is_not_suspended(self) -> None:
        for value in (None, {}, {"data": {}}, {"riskStatus": None}, {"riskStatus": {}}, "SUSPENDED"):
            with self.subTest(value=value):
                self.assertIsNone(parse_risk_status(value))
                self.assertEqual(format_risk_status(value), "")

    def test_parses_full_payload_and_does_not_interpret_status_value(self) -> None:
        payload = {
            "data": {
                "riskStatus": {
                    "expireTime": "1787127797000",
                    "status": "A_FUTURE_VALUE_WITH_NO_DEFINED_MEANING",
                }
            }
        }

        parsed = parse_risk_status(payload)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.expire_time_ms, 1787127797000)
        self.assertEqual(parsed.upstream_status, "A_FUTURE_VALUE_WITH_NO_DEFINED_MEANING")
        self.assertEqual(
            format_risk_status(payload, now_ms=1787000000000),
            "禁赛中 · 解封 2026-08-19 16:23",
        )

    def test_formats_millisecond_timestamp_in_hong_kong_time(self) -> None:
        self.assertEqual(format_expire_time(1787127797000), "2026-08-19 16:23")
        self.assertEqual(format_expire_time(1787127797000, compact=True), "08-19 16:23")

    def test_expired_cached_entry_is_not_rendered(self) -> None:
        risk = {"expireTime": 1000, "status": "SUSPENDED"}
        self.assertEqual(format_risk_status(risk, now_ms=1000), "")
        self.assertEqual(format_risk_status(risk, now_ms=999), "禁赛中 · 解封 1970-01-01 08:00")

    def test_invalid_expire_time_still_marks_present_entry(self) -> None:
        risk = {"expireTime": "not-a-number", "status": ""}
        parsed = parse_risk_status(risk)
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed.expire_time_ms)
        self.assertEqual(format_risk_status(risk), "禁赛中")

    def test_draws_red_text_on_white_chamfered_backplate(self) -> None:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ModuleNotFoundError:
            self.skipTest("Pillow is not installed")

        image = Image.new("RGBA", (460, 80), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")
        width, height = draw_risk_status_badge(
            draw,
            10,
            10,
            {"expireTime": 4102444800000, "status": "ANY"},
            font=ImageFont.load_default(),
        )

        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        pixels = list(image.crop((10, 10, 10 + width, 10 + height)).getdata())
        self.assertTrue(any(red > 190 and green < 80 and blue < 90 and alpha > 0 for red, green, blue, alpha in pixels))
        self.assertTrue(any(red > 225 and green > 225 and blue > 225 and alpha > 0 for red, green, blue, alpha in pixels))


if __name__ == "__main__":
    unittest.main()
