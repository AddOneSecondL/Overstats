from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...constants.backgrounds import build_random_map_background

from .requests import OWShopSection


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RES_DIR = PROJECT_ROOT / "res"
WINDOWS_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)
LOCAL_FONT_CANDIDATES = (
    RES_DIR / "en2.ttf",
    RES_DIR / "en.ttf",
    RES_DIR / "GrotaRoundedExtraBold.otf",
    RES_DIR / "BigNoodleToo.ttf",
)
BACKGROUND_RGB = (25, 30, 40)
CARD_BG_RGB = (50, 60, 75)
TEXT_MUTED = (190, 198, 210)
REFRESH_LABEL = "刷新"
GENERATED_AT_LABEL = "生成时间"
HUGE_BUNDLE_KEYWORD = "超级礼包"


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_ow_shop(
    sections: Sequence[OWShopSection],
    *,
    generated_at: str,
    asset_paths: Mapping[str, Path],
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    sections = list(sections or [])
    if not sections:
        raise RuntimeError("OW shop render requires at least one section.")

    font_section = _load_font(50)
    font_title = _load_font(30)
    font_price = _load_font(24)
    font_desc = _load_font(20)
    font_meta = _load_font(20)

    cols = 3
    card_w = 380
    gap = 20
    padding = 40
    canvas_w = padding * 2 + cols * card_w + (cols - 1) * gap
    current_y = 60
    text_entries = []
    layout_entries = []

    for section in sections:
        text_entries.append(
            {
                "text": section.title,
                "font": font_section,
                "color": "white",
                "x": padding,
                "y": current_y,
            }
        )
        if section.expires_text:
            text_entries.append(
                {
                    "text": f"{REFRESH_LABEL}: {section.expires_text}",
                    "font": font_meta,
                    "color": TEXT_MUTED,
                    "x": canvas_w - padding - 320,
                    "y": current_y + 20,
                }
            )

        current_y += 80
        col_idx = 0
        for item in section.items:
            is_huge = len(item.product_ids) > 8 or HUGE_BUNDLE_KEYWORD in item.title
            if is_huge:
                if col_idx > 0:
                    current_y += card_w + gap
                    col_idx = 0
                width = canvas_w - padding * 2
                height = int(width * 0.5)
                layout_entries.append({"item": item, "x": padding, "y": current_y, "w": width, "h": height})
                current_y += height + gap
                continue

            layout_entries.append(
                {
                    "item": item,
                    "x": padding + col_idx * (card_w + gap),
                    "y": current_y,
                    "w": card_w,
                    "h": card_w,
                }
            )
            col_idx += 1
            if col_idx >= cols:
                current_y += card_w + gap
                col_idx = 0

        if col_idx > 0:
            current_y += card_w + gap
        current_y += 40

    final_img = build_random_map_background(
        (canvas_w, current_y + padding),
        blur_radius=14,
        overlay=(18, 22, 31, 126),
        brightness=0.8,
        color=0.9,
    )
    if final_img is None:
        final_img = Image.new("RGBA", (canvas_w, current_y + padding), BACKGROUND_RGB + (255,))
    draw = ImageDraw.Draw(final_img, "RGBA")
    draw.text(
        (canvas_w - padding - 320, 20),
        f"{GENERATED_AT_LABEL}: {generated_at}",
        font=font_meta,
        fill=(150, 150, 150),
    )

    for text_entry in text_entries:
        draw.text(
            (text_entry["x"], text_entry["y"]),
            text_entry["text"],
            font=text_entry["font"],
            fill=text_entry["color"],
        )

    for layout in layout_entries:
        item = layout["item"]
        x = int(layout["x"])
        y = int(layout["y"])
        width = int(layout["w"])
        height = int(layout["h"])
        asset_path = asset_paths.get(item.image_url)
        card_img = _create_card_image(asset_path, width, height, CARD_BG_RGB)
        final_img.alpha_composite(card_img, (x, y))
        overlay = _render_text_overlay(
            item=item,
            width=width,
            height=height,
            font_title=font_title,
            font_desc=font_desc,
            font_price=font_price,
        )
        final_img.alpha_composite(overlay, (x, y))

    output = BytesIO()
    final_img.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _render_text_overlay(
    *,
    item: Any,
    width: int,
    height: int,
    font_title: Any,
    font_desc: Any,
    font_price: Any,
) -> Any:
    from PIL import Image, ImageDraw

    title_lines = _wrap_text(item.title, font_title, width - 30)
    desc_lines = _wrap_text(item.description, font_desc, width - 30) if item.description else []
    content_height = len(desc_lines) * 25 + len(title_lines) * 35 + 25
    bar_height = max(content_height, 80)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rounded_rectangle((0, height - bar_height, width, height), radius=20, fill=(0, 0, 0, 180))

    text_y = height - bar_height + 10
    for line in desc_lines:
        draw.text((15, text_y), line, font=font_desc, fill=(180, 180, 180))
        text_y += 25
    if desc_lines:
        text_y += 2
    for line in title_lines:
        draw.text((15, text_y), line, font=font_title, fill="white")
        text_y += 35

    label_text, badge_color = _price_label(item.price_raw, item.price_currency)
    _draw_badge(draw, width - 10, 10, label_text, font_price, badge_color, "black")
    if int(item.price_discount_percentage or 0) > 0:
        _draw_badge(draw, width - 10, 50, f"-{int(item.price_discount_percentage)}%", font_desc, (46, 204, 113), "white")
    return overlay


def _create_card_image(image_path: Path | None, target_w: int, target_h: int, bg_color: tuple[int, int, int]) -> Any:
    from PIL import Image, ImageDraw

    card = Image.new("RGBA", (target_w, target_h), bg_color + (255,))
    if image_path is not None and image_path.exists():
        try:
            with Image.open(image_path) as source_image:
                source = source_image.convert("RGB")
                src_w, src_h = source.size
                ratio = max(target_w / float(src_w), target_h / float(src_h))
                resized = source.resize((max(1, int(src_w * ratio)), max(1, int(src_h * ratio))), _resampling_lanczos())
                left = max(0, (resized.width - target_w) // 2)
                top = max(0, (resized.height - target_h) // 2)
                cropped = resized.crop((left, top, left + target_w, top + target_h))
                card.paste(cropped, (0, 0))
        except Exception:
            pass

    mask = Image.new("L", (target_w, target_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, target_w, target_h), radius=20, fill=255)
    card.putalpha(mask)
    return card


def _price_label(price_raw: int | float, currency: str) -> tuple[str, tuple[int, int, int]]:
    currency = str(currency or "").upper()
    if currency == "XWC":
        return f"{price_raw} 金币", (230, 170, 20)
    if currency == "CPT":
        return f"{price_raw} 战网点", (180, 20, 20)
    if currency == "XVT":
        return f"{price_raw} 光子水晶", (120, 200, 255)
    return f"{price_raw} 代币", (200, 200, 200)


def _draw_badge(draw: Any, right_x: int, top_y: int, text: str, font: Any, bg_color: Any, text_color: Any) -> None:
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    width = text_w + 32
    height = text_h + 16
    x = right_x - width
    y = top_y
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height / 2, fill=bg_color)
    draw.text((x + width / 2, y + height / 2 - 2), text, font=font, fill=text_color, anchor="mm")


def _wrap_text(text: str, font: Any, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current_line = ""
    for char in str(text):
        test_line = current_line + char
        if _text_width(test_line, font) <= max_width:
            current_line = test_line
            continue
        if current_line:
            lines.append(current_line)
        current_line = char
    if current_line:
        lines.append(current_line)
    return lines


def _text_width(text: str, font: Any) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(text))
    bbox = font.getbbox(text)
    return float((bbox[2] - bbox[0]) if bbox else 0)


def _load_font(size: int) -> Any:
    from PIL import ImageFont

    candidates = list(WINDOWS_FONT_CANDIDATES) + [str(path) for path in LOCAL_FONT_CANDIDATES]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")
