from __future__ import annotations

from ..dashen_promo import append_dashen_promo

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import random
from typing import Any, Mapping


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_guess_image(
    selection: Mapping[str, Any],
    media_path: Path,
    *,
    rng: random.Random | None = None,
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pillow is required for OW guess image rendering.") from exc

    random_source = rng or random.Random()
    question_type = str(selection.get("question_type") or "")
    with Image.open(media_path) as opened:
        base = opened.convert("RGBA")

    if question_type == "hero_icon":
        rendered = _render_hero_icon_crop(base, random_source)
    elif question_type == "map_image":
        rendered = _render_map_image_crop(base, random_source)
    elif question_type == "hero_silhouette":
        background_path = Path(str(selection.get("background_path") or "")).resolve()
        rendered = _render_hero_silhouette(base, background_path)
    elif question_type in {"skill_icon_hero", "perk_icon_hero", "skill_icon_name"}:
        rendered = _render_icon_card(base)
    else:
        rendered = base

    if question_type in {"hero_icon", "map_image", "hero_silhouette"}:
        rendered = append_dashen_promo(rendered)
    return _encode_image(rendered)


def _render_hero_icon_crop(image: Any, random_source: random.Random) -> Any:
    crop_size = (40, 40)
    return _random_crop(image, crop_size, margin=(40, 40), random_source=random_source)


def _render_map_image_crop(image: Any, random_source: random.Random) -> Any:
    crop_size = (150, 150)
    return _random_crop(image, crop_size, margin=(100, 150), random_source=random_source)


def _render_icon_card(image: Any) -> Any:
    from PIL import Image, ImageDraw

    canvas_size = 220
    corner_radius = 26
    icon = image.convert("RGBA")
    icon.thumbnail((canvas_size - 44, canvas_size - 44), Image.LANCZOS)

    card = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw_bg = ImageDraw.Draw(card)
    draw_bg.rounded_rectangle(
        (0, 0, canvas_size - 1, canvas_size - 1),
        radius=corner_radius,
        fill=(34, 39, 52, 255),
        outline=(106, 123, 153, 255),
        width=3,
    )

    inner = Image.new("RGBA", (canvas_size - 28, canvas_size - 28), (245, 247, 250, 235))
    inner_mask = Image.new("L", inner.size, 0)
    inner_draw = ImageDraw.Draw(inner_mask)
    inner_draw.rounded_rectangle(
        (0, 0, inner.size[0] - 1, inner.size[1] - 1),
        radius=max(14, corner_radius - 8),
        fill=255,
    )
    card.paste(inner, (14, 14), inner_mask)

    paste_x = (canvas_size - icon.width) // 2
    paste_y = (canvas_size - icon.height) // 2
    card.paste(icon, (paste_x, paste_y), icon)
    return card


def _render_hero_silhouette(image: Any, background_path: Path) -> Any:
    from PIL import Image

    background = Image.open(background_path).convert("RGBA")
    icon = image.convert("RGBA").resize((200, 200), Image.LANCZOS)
    silhouette = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    alpha = icon.getchannel("A")
    silhouette.paste((0, 0, 0, 255), (0, 0, icon.size[0], icon.size[1]), alpha)
    background.paste(silhouette, (60, 60), silhouette)
    return background


def _random_crop(image: Any, crop_size: tuple[int, int], *, margin: tuple[int, int], random_source: random.Random) -> Any:
    crop_width, crop_height = crop_size
    margin_x, margin_y = margin
    width, height = image.size
    if width <= crop_width or height <= crop_height:
        return _center_crop(image, crop_size)

    min_x = min(max(0, margin_x), max(0, width - crop_width))
    min_y = min(max(0, margin_y), max(0, height - crop_height))
    max_x = max(min_x, width - crop_width - margin_x)
    max_y = max(min_y, height - crop_height - margin_y)

    if max_x <= min_x:
        crop_x = max(0, (width - crop_width) // 2)
    else:
        crop_x = random_source.randint(min_x, max_x)
    if max_y <= min_y:
        crop_y = max(0, (height - crop_height) // 2)
    else:
        crop_y = random_source.randint(min_y, max_y)

    return image.crop((crop_x, crop_y, crop_x + crop_width, crop_y + crop_height))


def _center_crop(image: Any, crop_size: tuple[int, int]) -> Any:
    crop_width, crop_height = crop_size
    width, height = image.size
    left = max(0, (width - crop_width) // 2)
    top = max(0, (height - crop_height) // 2)
    right = min(width, left + crop_width)
    bottom = min(height, top + crop_height)
    return image.crop((left, top, right, bottom))


def _encode_image(image: Any) -> RenderedImage:
    output = BytesIO()
    image.save(output, format="PNG")
    return RenderedImage(content=output.getvalue())
