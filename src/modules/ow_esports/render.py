from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RES_DIR = PROJECT_ROOT / "res"
OW_ESPORTS_IMAGE_WIDTH = 1600
OW_ESPORTS_RENDER_LOGO_SIZE = (176, 132)

STATUS_LIVE = "正在进行"
STATUS_UPCOMING = "未开始"
STATUS_FINISHED = "已结束"
UNKNOWN_TEXT = "未知"
UNKNOWN_LEAGUE = "未分类赛事"
TITLE_TEXT = "守望先锋赛事"
SUMMARY_TEXT = "PANDASCORE OW MATCHES  |  当前为实时拉取数据"
EMPTY_TEXT = "当前没有可展示的 OW 赛事。"
UNKNOWN_REGION_TEXT = "未公开"
REGION_LABEL = "地区"
SCHEDULED_LABEL = "预计开始时间"
COUNTDOWN_PREFIX = "倒计时"
HIDDEN_TEMPLATE = "已结束赛事较多，当前仅展示最近 {count} 场，另外隐藏 {hidden} 场。"
GENERATED_AT_LABEL = "生成时间"


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def render_ow_esports(
    rows: Sequence[Mapping[str, Any]],
    *,
    sections: Sequence[Mapping[str, Any]],
    generated_at: str,
    logo_assets: Optional[Mapping[str, bytes]] = None,
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    width = OW_ESPORTS_IMAGE_WIDTH
    padding = 36
    header_h = 140
    footer_h = 36
    height = _calc_image_height(sections)

    canvas = Image.new("RGB", (width, height), (15, 19, 28))
    draw = ImageDraw.Draw(canvas, "RGBA")

    title_font = _load_font(46, bold=True)
    sub_font = _load_font(24, bold=False)
    league_font = _load_font(30, bold=True)
    status_font = _load_font(22, bold=True)
    team_name_font = _load_font(40, bold=True)
    meta_font = _load_font(22, bold=False)
    region_font = _load_font(24, bold=False)
    tiny_font = _load_font(20, bold=False)
    status_big_font = _load_font(24, bold=True)
    score_big_font = _load_font(56, bold=True)
    colon_font = _load_font(48, bold=True)
    countdown_font = _load_font(24, bold=True)
    start_font = _load_font(31, bold=True)

    _safe_rounded_rectangle(draw, (padding, 24, width - padding, 30), radius=3, fill=(255, 151, 64, 255))
    draw.text((padding, 44), TITLE_TEXT, font=title_font, fill=(255, 255, 255))
    draw.text((padding, 92), SUMMARY_TEXT, font=sub_font, fill=(175, 183, 198))

    y = header_h
    if not sections:
        empty_font = _load_font(32, bold=True)
        _safe_rounded_rectangle(
            draw,
            (padding, y, width - padding, y + 220),
            radius=28,
            fill=(28, 34, 46, 255),
            outline=(54, 64, 83, 255),
            width=2,
        )
        draw.text((padding + 40, y + 88), EMPTY_TEXT, font=empty_font, fill=(245, 247, 250))
        return _encode_image(canvas)

    card_h = 248
    card_gap = 16
    section_gap = 18
    league_header_h = 54
    status_header_h = 42

    for section in sections:
        league_name = str(section.get("league_name") or UNKNOWN_LEAGUE).strip() or UNKNOWN_LEAGUE
        draw.text((padding, y), league_name, font=league_font, fill=(255, 228, 181))
        y += league_header_h

        status_sections = section.get("status_sections")
        if not isinstance(status_sections, Sequence):
            status_sections = []

        for status_section in status_sections:
            if not isinstance(status_section, Mapping):
                continue
            status_name = str(status_section.get("status") or STATUS_FINISHED).strip() or STATUS_FINISHED
            rows_in_status = list(status_section.get("rows") or [])
            hidden_count = int(status_section.get("hidden_count") or 0)
            status_color = _status_color(status_name)

            _safe_rounded_rectangle(
                draw,
                (padding, y + 4, padding + 148, y + 36),
                radius=16,
                fill=(*status_color, 255),
            )
            draw.text((padding + 18, y + 9), status_name, font=status_font, fill=(20, 24, 30))
            y += status_header_h

            for row in rows_in_status:
                if not isinstance(row, Mapping):
                    continue
                card_x1 = padding
                card_y1 = y
                card_x2 = width - padding
                card_y2 = y + card_h

                has_cn_team = _row_has_cn(row)
                is_live = status_name == STATUS_LIVE
                is_ended = status_name == STATUS_FINISHED
                is_not_started = status_name == STATUS_UPCOMING

                if is_live:
                    card_fill = (22, 66, 44, 255)
                    card_outline = (102, 214, 151, 255)
                elif has_cn_team:
                    card_fill = (46, 35, 22, 255)
                    card_outline = (255, 151, 64, 255)
                elif is_not_started:
                    card_fill = (24, 32, 52, 255)
                    card_outline = (66, 82, 116, 255)
                else:
                    card_fill = (28, 34, 46, 255)
                    card_outline = (54, 64, 83, 255)

                _safe_rounded_rectangle(
                    draw,
                    (card_x1, card_y1, card_x2, card_y2),
                    radius=28,
                    fill=card_fill,
                    outline=card_outline,
                    width=2,
                )
                if has_cn_team:
                    _safe_rounded_rectangle(
                        draw,
                        (card_x1 + 12, card_y1 + 16, card_x1 + 24, card_y2 - 16),
                        radius=6,
                        fill=(255, 151, 64, 255),
                    )

                left_box_x = card_x1 + 24
                logo_box_w = 196
                logo_box_h = 152
                logo_top = card_y1 + 18
                right_box_x = card_x2 - 24 - logo_box_w

                for box_x in (left_box_x, right_box_x):
                    _safe_rounded_rectangle(
                        draw,
                        (box_x, logo_top, box_x + logo_box_w, logo_top + logo_box_h),
                        radius=24,
                        fill=(38, 26, 18, 255) if has_cn_team and not is_live else ((18, 56, 40, 255) if is_live else (20, 24, 34, 255)),
                        outline=(255, 186, 120, 72) if has_cn_team else ((175, 255, 216, 72) if is_live else (255, 255, 255, 18)),
                        width=2,
                    )

                team1 = row.get("team1") if isinstance(row.get("team1"), Mapping) else {}
                team2 = row.get("team2") if isinstance(row.get("team2"), Mapping) else {}
                team1_logo = _load_logo_image(
                    str(team1.get("logo") or ""),
                    OW_ESPORTS_RENDER_LOGO_SIZE,
                    str(team1.get("short_name") or team1.get("name") or "OW"),
                    logo_assets=logo_assets or {},
                )
                team2_logo = _load_logo_image(
                    str(team2.get("logo") or ""),
                    OW_ESPORTS_RENDER_LOGO_SIZE,
                    str(team2.get("short_name") or team2.get("name") or "OW"),
                    logo_assets=logo_assets or {},
                )
                canvas.paste(team1_logo, (left_box_x + 10, logo_top + 10), team1_logo)
                canvas.paste(team2_logo, (right_box_x + 10, logo_top + 10), team2_logo)

                center_x = (card_x1 + card_x2) / 2
                left_text_x = left_box_x + logo_box_w + 18
                left_text_w = max(210, int(center_x - 175 - left_text_x))
                right_text_x = int(center_x + 175)
                right_text_w = max(210, right_box_x - 18 - right_text_x)
                team_name_color = (255, 229, 204) if has_cn_team else ((223, 255, 236) if is_live else (245, 247, 250))
                team_region_color = (230, 201, 168) if has_cn_team else ((190, 239, 210) if is_live else (175, 183, 198))

                _draw_team_block(draw, team1, left_text_x, logo_top + 8, left_text_w, team_name_font, region_font, team_name_color, team_region_color, align="left")
                _draw_team_block(draw, team2, right_text_x, logo_top + 8, right_text_w, team_name_font, region_font, team_name_color, team_region_color, align="right")

                title_lines = _wrap_text(draw, str(row.get("match_name") or ""), meta_font, 420, 2)
                title_y = card_y1 + 22
                for index, line in enumerate(title_lines):
                    line_w, _ = _measure_text(draw, line, meta_font)
                    draw.text((center_x - line_w / 2, title_y + index * 26), line, font=meta_font, fill=(210, 220, 232))

                if is_ended or is_live:
                    center_status = STATUS_FINISHED if is_ended else STATUS_LIVE
                    center_status_color = (170, 180, 194) if is_ended else (120, 255, 182)
                    status_w, _ = _measure_text(draw, center_status, status_big_font)
                    draw.text((center_x - status_w / 2, card_y1 + 86), center_status, font=status_big_font, fill=center_status_color)

                    score1 = row.get("score1")
                    score2 = row.get("score2")
                    score1_text = str(0 if score1 is None else score1)
                    score2_text = str(0 if score2 is None else score2)
                    score_y = card_y1 + 122
                    left_score_x = center_x - 86
                    right_score_x = center_x + 86
                    score1_fill = (255, 215, 90) if score1 is not None and score2 is not None and int(score1) > int(score2) else (245, 247, 250)
                    score2_fill = (255, 215, 90) if score1 is not None and score2 is not None and int(score2) > int(score1) else (245, 247, 250)

                    score1_w, _ = _measure_text(draw, score1_text, score_big_font)
                    score2_w, _ = _measure_text(draw, score2_text, score_big_font)
                    colon_w, _ = _measure_text(draw, ":", colon_font)

                    draw.text((left_score_x - score1_w / 2, score_y), score1_text, font=score_big_font, fill=score1_fill)
                    draw.text((center_x - colon_w / 2, score_y + 4), ":", font=colon_font, fill=(245, 247, 250))
                    draw.text((right_score_x - score2_w / 2, score_y), score2_text, font=score_big_font, fill=score2_fill)

                    time_text = str(row.get("start_time") or UNKNOWN_TEXT)
                    time_w, _ = _measure_text(draw, time_text, tiny_font)
                    draw.text((center_x - time_w / 2, card_y2 - 34), time_text, font=tiny_font, fill=(175, 183, 198))
                else:
                    status_w, _ = _measure_text(draw, STATUS_UPCOMING, status_big_font)
                    draw.text((center_x - status_w / 2, card_y1 + 86), STATUS_UPCOMING, font=status_big_font, fill=(141, 188, 255))

                    start_text = f"{SCHEDULED_LABEL} {row.get('start_time') or UNKNOWN_TEXT}"
                    start_w, _ = _measure_text(draw, start_text, start_font)
                    draw.text((center_x - start_w / 2, card_y1 + 126), start_text, font=start_font, fill=(245, 247, 250))

                    countdown_text = _format_countdown(row.get("start_timestamp"))
                    countdown_w, countdown_h = _measure_text(draw, countdown_text, countdown_font)
                    countdown_pad_x = 24
                    countdown_pad_y = 10
                    countdown_x1 = center_x - (countdown_w + countdown_pad_x * 2) / 2
                    countdown_y1 = card_y1 + 176
                    countdown_x2 = center_x + (countdown_w + countdown_pad_x * 2) / 2
                    countdown_y2 = countdown_y1 + countdown_h + countdown_pad_y * 2
                    _safe_rounded_rectangle(
                        draw,
                        (countdown_x1, countdown_y1, countdown_x2, countdown_y2),
                        radius=18,
                        fill=(38, 51, 82, 255),
                        outline=(92, 158, 255, 90),
                        width=2,
                    )
                    draw.text((center_x - countdown_w / 2, countdown_y1 + countdown_pad_y - 2), countdown_text, font=countdown_font, fill=(210, 229, 255))

                y += card_h + card_gap

            if hidden_count > 0:
                hint_text = HIDDEN_TEMPLATE.format(count=len(rows_in_status), hidden=hidden_count)
                draw.text((padding + 4, y - 4), hint_text, font=tiny_font, fill=(150, 158, 170))
                y += 24

        y += section_gap

    footer_text = f"{GENERATED_AT_LABEL}：{generated_at or dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    footer_w, _ = _measure_text(draw, footer_text, tiny_font)
    draw.text((width - padding - footer_w, height - footer_h), footer_text, font=tiny_font, fill=(100, 108, 118))
    return _encode_image(canvas)


def _encode_image(image: Any) -> RenderedImage:
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _calc_image_height(sections: Sequence[Mapping[str, Any]]) -> int:
    header_h = 140
    footer_h = 36
    league_header_h = 54
    status_header_h = 42
    card_h = 248
    card_gap = 16
    section_gap = 18

    height = header_h + footer_h
    if not sections:
        return height + 240

    for section in sections:
        height += league_header_h
        status_sections = section.get("status_sections")
        if not isinstance(status_sections, Sequence):
            continue
        for status_section in status_sections:
            if not isinstance(status_section, Mapping):
                continue
            row_count = len(list(status_section.get("rows") or []))
            hidden_count = int(status_section.get("hidden_count") or 0)
            height += status_header_h
            height += row_count * card_h
            if row_count > 1:
                height += (row_count - 1) * card_gap
            if hidden_count > 0:
                height += 28
        height += section_gap
    return max(height, header_h + footer_h + 260)


def _load_logo_image(
    source: str,
    size: tuple[int, int],
    label: str,
    *,
    logo_assets: Mapping[str, bytes],
) -> Any:
    raw = logo_assets.get(str(source or "").strip(), b"")
    return _prepare_logo_image(raw, size, label)


def _prepare_logo_image(raw: bytes, size: tuple[int, int], label: str) -> Any:
    from PIL import Image

    if raw:
        try:
            image = Image.open(BytesIO(raw)).convert("RGBA")
            image.thumbnail((size[0] - 18, size[1] - 18), _resampling_lanczos())
            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            x = (size[0] - image.width) // 2
            y = (size[1] - image.height) // 2
            canvas.paste(image, (x, y), image)
            return canvas
        except Exception:
            pass
    return _create_logo_placeholder(size, label)


def _create_logo_placeholder(size: tuple[int, int], label: str) -> Any:
    from PIL import Image, ImageDraw

    seed_text = str(label or "OW").encode("utf-8", errors="ignore")
    seed = int(hashlib.md5(seed_text).hexdigest()[:8], 16)
    r = 54 + (seed & 0x3F)
    g = 78 + ((seed >> 6) & 0x3F)
    b = 104 + ((seed >> 12) & 0x3F)

    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    _safe_rounded_rectangle(draw, (0, 0, size[0] - 1, size[1] - 1), radius=24, fill=(r, g, b, 255), outline=(255, 255, 255, 30), width=2)

    short_text = "".join(ch for ch in str(label or "").upper() if ch.isalnum())[:4] or "OW"
    font = _load_font(max(20, min(size) // 3), bold=True)
    text_w, text_h = _measure_text(draw, short_text, font)
    draw.text(((size[0] - text_w) / 2, (size[1] - text_h) / 2 - 4), short_text, font=font, fill=(255, 255, 255, 255))
    return image


def _draw_team_block(
    draw: Any,
    team: Mapping[str, Any],
    x: int,
    y: int,
    width: int,
    name_font: Any,
    region_font: Any,
    name_fill: Any,
    region_fill: Any,
    *,
    align: str,
) -> None:
    name_lines = _wrap_text(draw, str(team.get("name") or "TBD"), name_font, width, 2)
    current_y = y
    for line in name_lines:
        line_w, _ = _measure_text(draw, line, name_font)
        text_x = x if align == "left" else x + width - line_w
        draw.text((text_x, current_y), line, font=name_font, fill=name_fill)
        current_y += 42

    region = str(team.get("region") or "").strip()
    region_line = f"{REGION_LABEL}：{region}" if region else f"{REGION_LABEL}：{UNKNOWN_REGION_TEXT}"
    region_w, _ = _measure_text(draw, region_line, region_font)
    region_x = x if align == "left" else x + width - region_w
    draw.text((region_x, current_y + 4), region_line, font=region_font, fill=region_fill)


def _row_has_cn(row: Mapping[str, Any]) -> bool:
    for key in ("team1", "team2"):
        team = row.get(key)
        if not isinstance(team, Mapping):
            continue
        region = str(team.get("region") or "").strip().upper()
        if region.startswith("CN"):
            return True
    return False


def _status_color(status_name: str) -> tuple[int, int, int]:
    return {
        STATUS_LIVE: (255, 163, 60),
        STATUS_UPCOMING: (92, 158, 255),
        STATUS_FINISHED: (128, 138, 152),
    }.get(str(status_name or ""), (128, 138, 152))


def _format_countdown(start_timestamp: Any) -> str:
    try:
        if start_timestamp in (None, ""):
            return f"{COUNTDOWN_PREFIX}：{UNKNOWN_TEXT}"
        start_dt = dt.datetime.fromtimestamp(int(start_timestamp)).astimezone()
    except Exception:
        return f"{COUNTDOWN_PREFIX}：{UNKNOWN_TEXT}"

    now = dt.datetime.now(start_dt.tzinfo)
    delta = start_dt - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return f"{COUNTDOWN_PREFIX}：即将开始"

    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days > 0:
        return f"{COUNTDOWN_PREFIX}：{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{COUNTDOWN_PREFIX}：{hours:02d}:{minutes:02d}:{seconds:02d}"


def _load_font(size: int, *, bold: bool) -> Any:
    from PIL import ImageFont

    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                RES_DIR / "GrotaRoundedExtraBold.otf",
                RES_DIR / "BigNoodleToo.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                RES_DIR / "en.ttf",
                RES_DIR / "en2.ttf",
            ]
        )

    candidates.extend(
        [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _measure_text(draw: Any, text: str, font: Any) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), str(text or ""), font=font)
    return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])


def _wrap_text(draw: Any, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
    normalized = str(text or "")
    if not normalized:
        return []

    lines = []
    current = ""
    for char in normalized:
        test = current + char
        width, _ = _measure_text(draw, test, font)
        if width <= max_width or not current:
            current = test
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    overflow = "".join(lines) != normalized
    if overflow and lines:
        tail = lines[-1]
        while tail:
            width, _ = _measure_text(draw, tail + "...", font)
            if width <= max_width:
                lines[-1] = tail + "..."
                break
            tail = tail[:-1]
        if not tail:
            lines[-1] = "..."

    return lines[:max_lines]


def _safe_rounded_rectangle(draw: Any, box: Sequence[float], radius: int, **kwargs: Any) -> None:
    x0, y0, x1, y1 = box
    left = min(x0, x1)
    right = max(x0, x1)
    top = min(y0, y1)
    bottom = max(y0, y1)
    safe_radius = max(0, min(radius, int((right - left) / 2), int((bottom - top) / 2)))
    try:
        draw.rounded_rectangle((left, top, right, bottom), radius=safe_radius, **kwargs)
    except Exception:
        draw.rectangle((left, top, right, bottom), **kwargs)


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")
