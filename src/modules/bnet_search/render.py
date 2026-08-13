from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional

try:
    from overstats.src.modules.font_resolver import load_font
    from overstats.src.modules.risk_status import draw_risk_status_badge
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font
    from src.modules.risk_status import draw_risk_status_badge

from .requests import BnetSearchResult


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_bnet_search_result(result: BnetSearchResult, *, risk_status: Optional[dict[str, Any]] = None) -> RenderedImage:
    lines = [
        "BattleTag Search",
        "",
        f"query: {result.query}",
        f"full_id: {result.full_id or '-'}",
        f"bnet_id: {result.bnet_id or '-'}",
        f"has_customer_token: {bool(result.customer_token)}",
        f"code: {result.payload.get('code')}",
    ]
    return _render_text_png(lines, risk_status=risk_status)


def _render_text_png(lines: list[str], *, risk_status: Optional[dict[str, Any]] = None) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    width = 960
    line_height = 34
    padding = 36
    height = max(220, padding * 2 + line_height * len(lines))
    image = Image.new("RGB", (width, height), (18, 22, 30))
    draw = ImageDraw.Draw(image)
    font = load_font(18, name="simhei.ttf", fallback="en.ttf", prefer_cjk=True)
    y = padding
    for idx, line in enumerate(lines):
        fill = (120, 240, 220) if idx == 0 else (230, 235, 245)
        draw.text((padding, y), line, fill=fill, font=font)
        if idx == 3:
            line_width = int(draw.textlength(line, font=font))
            draw_risk_status_badge(
                draw,
                padding + line_width + 16,
                y - 4,
                risk_status,
                font=font,
                padding_x=8,
                padding_y=4,
                max_width=width - padding * 2 - line_width - 16,
            )
        y += line_height

    output = BytesIO()
    image.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())
