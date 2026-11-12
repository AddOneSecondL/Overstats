"""Season panels derived only from already-fetched match summaries."""
from collections import Counter, defaultdict
import datetime
import math
from PIL import Image, ImageDraw, ImageFilter

try:
    from ...map_modes import draw_map_mode_icon
    from .summary_style import RADIUS_CHIP, RADIUS_TILE, mix, tinted, with_alpha
    from .summary_typography import smooth_mask
except ImportError:  # loaded as a bare file (tests of build_season_data); drawing is unavailable then
    draw_map_mode_icon = smooth_mask = mix = tinted = with_alpha = None
    RADIUS_CHIP, RADIUS_TILE = 6, 10


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def mode_label(match):
    mode = str(match.get("gameMode") or "").lower()
    if "fight" in mode:
        return "角斗竞技" if "sport" in mode else "角斗快速"
    if "v6" in mode or "6v6" in mode:
        return "竞技6V6" if "sport" in mode else "快速6V6"
    if "sport" in mode:
        return "竞技开放" if "open" in mode else "竞技预设"
    return "快速开放" if "open" in mode else "快速"


def competitive(match):
    mode = str(match.get("gameMode") or "").lower()
    return "sport" in mode and "fight" not in mode


def build_season_data(matches, period, map_mode, rank_score, canonical=lambda x: str(x or "")):
    unique = {}
    for m in matches:
        key = str(m.get("matchId") or "")
        if key:
            unique.setdefault(key, m)
    rows = list(unique.values())
    period_ids = {str(m.get("matchId") or "") for m in period}
    current = [m for m in rows if str(m.get("matchId")) in period_ids]
    modes = Counter(mode_label(m) for m in rows)
    maps = Counter(str(m["mapGuid"]) for m in rows if m.get("mapGuid"))
    heroes = Counter(canonical(m["heroGuid"]) for m in rows if m.get("heroGuid"))
    map_modes = Counter(map_mode(m.get("mapGuid")) or "未知地图" for m in rows)
    metrics = []
    for label, field in [("击杀", "kill"), ("伤害", "heroDamage"), ("治疗", "cure"), ("阻挡", "resistDamage")]:
        values = [number(m.get(field)) for m in rows]
        recent = [number(m.get(field)) for m in current]
        total = sum(v for v in values if v is not None) if any(v is not None for v in values) else None
        delta = total - sum(v for v in recent if v is not None) if total is not None and all(v is not None for v in recent) else None
        metrics.append((label, total, delta, sum(v is not None for v in values), len(rows)))
    def kda(items):
        valid = [m for m in items if all(number(m.get(f)) is not None for f in ("kill", "assist", "death"))]
        if not valid:
            return None, 0
        return (sum(float(m["kill"])+float(m["assist"]) for m in valid) / max(1, sum(float(m["death"]) for m in valid))), len(valid)
    full_kda, covered = kda(rows)
    recent_kda, _ = kda(current)
    metrics.insert(1, ("KDA", full_kda, full_kda-recent_kda if full_kda is not None and recent_kda is not None else None, covered, len(rows)))
    trends = defaultdict(list)
    for m in sorted(rows, key=lambda m: number(m.get("beginTs")) or 0):
        if not competitive(m):
            continue
        score = rank_score(m.get("rankInfo"))
        ts = number(m.get("beginTs"))
        if score is None or not ts or ts <= 0:
            continue
        queue = "开放" if "open" in str(m.get("gameMode")).lower() else {"tank":"重装", "dps":"输出", "damage":"输出", "healer":"支援", "support":"支援"}.get(str(m.get("roleType")), "未分类")
        trends[queue].append((ts, score))
    period_ts = [ts for ts in (number(m.get("beginTs")) for m in period) if ts and ts > 0]
    return {"total":len(rows), "modes":modes.most_common(), "map_modes":map_modes.most_common(),
            "maps":maps.most_common(3), "heroes":heroes.most_common(3), "metrics":metrics,
            "show_trend":any(competitive(m) for m in period), "trends":dict(trends),
            "period_start":min(period_ts) if period_ts else None, "period_end":max(period_ts) if period_ts else None}


# ---------------------------------------------------------------- highlights

def season_glow(canvas, box, colors, radius, spread=9, strength=150):
    """Soft blue halo behind a portrait or tile marking a season favourite."""
    x1, y1, x2, y2 = [int(v) for v in box]
    width, height = x2 - x1, y2 - y1
    size = (width + spread * 2, height + spread * 2)
    mask = Image.new("L", size, 0)
    mask.paste(smooth_mask(width, height, radius), (spread, spread))
    mask = mask.filter(ImageFilter.GaussianBlur(spread / 2)).point(lambda v: v * strength // 255)
    canvas.paste(Image.new("RGBA", size, (*colors.INFO[:3], 255)), (x1 - spread, y1 - spread), mask)


def season_map_wash(canvas, box, colors, radius):
    """Diffused blue light rising from the left of a map row, fading out before the numbers."""
    x1, y1, x2, y2 = [int(v) for v in box]
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        return
    peak = 120 if colors.NAME == "night" else 84
    fade = Image.new("L", (width, 1))
    reach = max(1, int(width * .62))
    fade.putdata([int(peak * max(0.0, 1 - x / reach) ** 1.6) for x in range(width)])
    fade = fade.resize((width, height))
    # Brighter through the middle of the row, so it reads as light rather than a fill.
    rows = Image.new("L", (1, height))
    rows.putdata([int(255 * (0.55 + 0.45 * math.sin(math.pi * y / max(1, height - 1)))) for y in range(height)])
    alpha = Image.composite(fade, Image.new("L", (width, height), 0), rows.resize((width, height)))
    rounded = smooth_mask(width, height, radius)
    alpha = Image.composite(alpha, Image.new("L", (width, height), 0), rounded)
    canvas.paste(Image.new("RGBA", (width, height), (*colors.INFO[:3], 255)), (x1, y1), alpha)
    ImageDraw.Draw(canvas).rounded_rectangle((x1, y1 + 8, x1 + 3, y2 - 8), radius=2, fill=(*colors.INFO[:3], 255))


def season_chip(draw, x, center_y, place, font, colors, size=13):
    """Pill in the style of the medal chips: 赛季#1. Returns its right edge."""
    label = f"赛季#{place}"
    chip_font = font(size, bold=True)
    text_w = draw.textlength(label, font=chip_font)
    height = size + 7
    draw.rounded_rectangle((x, center_y - height / 2, x + text_w + 14, center_y + height / 2),
                           radius=RADIUS_CHIP, fill=tinted(colors.INFO, .3))
    draw.text((x + 7, center_y), label, font=chip_font, fill=colors.INFO, anchor="lm")
    return x + text_w + 14


# ---------------------------------------------------------------- season statistics

MODE_COLOR_KEYS = {
    "快速": "INFO", "快速开放": "INFO", "快速6V6": "INFO",
    "竞技预设": "ACCENT", "竞技开放": "DRAW", "竞技6V6": "ACCENT",
    "角斗快速": "WIN", "角斗竞技": "LOSS",
}


def _mode_colors(modes, colors):
    """Fixed hue per queue family; repeats within a family step lighter."""
    seen = Counter()
    result = []
    for label, _ in modes:
        key = MODE_COLOR_KEYS.get(label, "MUTED")
        base = getattr(colors, key)
        result.append(mix(base, colors.SURFACE[:3], max(.3, 1 - .25 * seen[key])) if seen[key] else base)
        seen[key] += 1
    return result


def _donut(canvas, center, outer, inner, parts, colors, gap_deg=1.6, scale=4):
    """Anti-aliased donut: each slice is cut at 4x and reduced."""
    cx, cy = center
    size = outer * 2 * scale
    total = sum(count for count, _ in parts)
    if total <= 0:
        parts = [(1, colors.HAIRLINE)]
        total = 1
    start = -90.0
    for count, color in parts:
        sweep = 360.0 * count / total
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        gap = gap_deg if len(parts) > 1 and sweep > gap_deg * 2 else 0
        md.pieslice((0, 0, size - 1, size - 1), start + gap / 2, start + sweep - gap / 2, fill=255)
        hole = (outer - inner) * scale
        md.ellipse((hole, hole, size - 1 - hole, size - 1 - hole), fill=0)
        mask = mask.resize((outer * 2, outer * 2), Image.LANCZOS)
        canvas.paste(Image.new("RGBA", mask.size, (*color[:3], 255)), (cx - outer, cy - outer), mask)
        start += sweep


def compact(value, signed=False, kda=False):
    if value is None:return "—"
    sign="+" if signed and value>0 else ""
    if kda:return f"{value:+.2f}" if signed else f"{value:.2f}"
    return sign+(f"{value/10000:.1f}万" if abs(value)>=10000 else f"{value:,.0f}")


def season_panel_height():
    return 212


def draw_season_panel(canvas, draw, data, box, font, colors, map_name, fit):
    x, y, right, bottom = [int(v) for v in box]
    total = data["total"]
    divider_top, divider_bottom = y + 2, bottom - 4

    # --- game modes: donut with the season total inside, legend beside it
    modes = data["modes"]
    mode_colors = _mode_colors(modes, colors)
    radius, ring = 78, 22
    cx, cy = x + radius + 2, y + 4 + radius
    _donut(canvas, (cx, cy), radius, radius - ring, [(count, color) for (_, count), color in zip(modes, mode_colors)], colors)
    draw.text((cx, cy - 6), f"{total:,}", font=font(30, bold=True), fill=colors.INK, anchor="mm")
    draw.text((cx, cy + 20), "赛季场次", font=font(13), fill=colors.MUTED, anchor="mm")
    legend_x, legend_right = x + radius * 2 + 26, x + 384
    pitch = min(25, 184 / max(1, len(modes)))
    legend_top = cy - pitch * len(modes) / 2 + pitch / 2
    for idx, ((label, count), color) in enumerate(zip(modes, mode_colors)):
        row_y = legend_top + idx * pitch
        draw.rounded_rectangle((legend_x, row_y - 5, legend_x + 10, row_y + 5), radius=3, fill=color)
        draw.text((legend_x + 18, row_y), label, font=font(14), fill=colors.TEXT, anchor="lm")
        draw.text((legend_right - 52, row_y), f"{count}", font=font(14, bold=True), fill=colors.INK, anchor="rm")
        draw.text((legend_right, row_y), f"{count / max(1, total):.0%}", font=font(13), fill=colors.MUTED, anchor="rm")
    zone_b = x + 414
    draw.line((zone_b - 16, divider_top, zone_b - 16, divider_bottom), fill=colors.HAIRLINE, width=1)

    # --- maps: gameplay-mode split as one stacked bar, then the three season favourites
    zone_b_right = x + 858
    width_b = zone_b_right - zone_b
    draw.text((zone_b, y + 8), "地图玩法", font=font(14, bold=True), fill=colors.MUTED, anchor="lm")
    map_modes = [(label, count) for label, count in data["map_modes"] if count > 0]
    bar_y = y + 26
    bar_total = sum(count for _, count in map_modes) or 1
    shades = [mix(colors.INFO, colors.SURFACE[:3], max(.3, 1 - step * .17)) for step in range(len(map_modes))]
    cursor = zone_b
    for idx, ((label, count), shade) in enumerate(zip(map_modes, shades)):
        seg_w = width_b * count / bar_total
        end = zone_b + width_b if idx == len(map_modes) - 1 else cursor + seg_w
        if end - cursor >= 2:
            draw.rounded_rectangle((cursor, bar_y, end - 2, bar_y + 9), radius=3, fill=shade)
        cursor = end
    if not map_modes:
        draw.rounded_rectangle((zone_b, bar_y, zone_b_right, bar_y + 9), radius=3, fill=colors.HAIRLINE)
    # Eight known/unknown map modes fit without dropping a third legend row.
    for idx, ((label, count), shade) in enumerate(zip(map_modes, shades)):
        col, row = idx % 4, idx // 4
        lx = zone_b + col * width_b / 4
        legend_y = bar_y + 24 + row * 21
        draw.rounded_rectangle((lx, legend_y - 4, lx + 6, legend_y + 4), radius=2, fill=shade)
        text = f"{label} {count}"
        draw.text((lx + 11, legend_y), fit(draw, text, font(11), width_b/4-15),
                  font=font(11), fill=colors.MUTED, anchor="lm")
    favourites_y = y + 104
    draw.text((zone_b, favourites_y - 14), "赛季常用地图", font=font(14, bold=True), fill=colors.MUTED, anchor="lm")
    for idx, (guid, count) in enumerate(data["maps"]):
        row_y = favourites_y + 6 + idx * 32
        share = count / max(1, total)
        draw.rounded_rectangle((zone_b, row_y, zone_b_right, row_y + 26), radius=RADIUS_TILE - 2, fill=with_alpha(colors.INFO, 22))
        draw.rounded_rectangle((zone_b, row_y, zone_b + max(10, (width_b) * share), row_y + 26), radius=RADIUS_TILE - 2, fill=with_alpha(colors.INFO, 46))
        mid = row_y + 13
        draw.text((zone_b + 12, mid), f"{idx + 1}", font=font(14, bold=True), fill=colors.INFO, anchor="mm")
        name_x = zone_b + 26
        if draw_map_mode_icon(canvas, guid, name_x, mid - 9, 18, color=colors.TEXT):
            name_x += 24
        draw.text((name_x, mid), fit(draw, map_name(guid), font(14, bold=True), zone_b_right - name_x - 130), font=font(14, bold=True), fill=colors.INK, anchor="lm")
        draw.text((zone_b_right - 66, mid), f"{count}场", font=font(13), fill=colors.TEXT, anchor="rm")
        draw.text((zone_b_right - 10, mid), f"{share:.1%}", font=font(14, bold=True), fill=colors.INFO, anchor="rm")
    if not data["maps"]:
        draw.text((zone_b, favourites_y + 18), "暂无地图数据", font=font(14), fill=colors.FAINT, anchor="lm")
    zone_c = zone_b_right + 32
    draw.line((zone_c - 16, divider_top, zone_c - 16, divider_bottom), fill=colors.HAIRLINE, width=1)

    # --- season totals, laid out like the 总体数据 tiles
    draw.text((zone_c, y + 8), "赛季累计", font=font(14, bold=True), fill=colors.MUTED, anchor="lm")
    draw.text((right, y + 8), "括号内为赛季减本期", font=font(12), fill=colors.FAINT, anchor="rm")
    metrics = data["metrics"]
    cell_w = (right - zone_c) / 3
    partial = False
    for idx, (label, value, delta, covered, count) in enumerate(metrics[:6]):
        col, row = idx % 3, idx // 3
        cell_x = zone_c + col * cell_w
        cell_y = y + 30 + row * 86
        is_kda = label == "KDA"
        partial |= covered < count
        draw.text((cell_x, cell_y), label + ("*" if covered < count else ""), font=font(14), fill=colors.MUTED)
        value_text = compact(value, kda=is_kda)
        draw.text((cell_x, cell_y + 22), value_text, font=fit_font(draw, value_text, font, cell_w - 12, 26, 17), fill=colors.INK)
        delta_text = "(" + compact(delta, signed=is_kda, kda=is_kda) + ")"
        delta_color = colors.FAINT
        if is_kda and delta is not None and abs(delta) >= .005:
            delta_color = colors.WIN if delta > 0 else colors.LOSS
        draw.text((cell_x, cell_y + 56), delta_text, font=font(12, bold=is_kda), fill=delta_color)
    if partial:
        draw.text((right, bottom - 2), "* 部分对局缺少该项数据", font=font(11), fill=colors.FAINT, anchor="rd")


def fit_font(draw, text, font, width, largest, smallest):
    for size in range(largest, smallest - 1, -1):
        candidate = font(size, bold=True)
        if draw.textlength(text, font=candidate) <= width:
            return candidate
    return font(smallest, bold=True)


# ---------------------------------------------------------------- competitive rank trend

QUEUE_ORDER = ("重装", "输出", "支援", "开放", "未分类")
RANK_STEP = 500
RANK_BASE = 500


def rank_panel_height():
    return 236


def _queue_color(queue, colors):
    roles = colors.ROLE_COLORS
    return {"重装": roles.get("Tank"), "输出": roles.get("Damage"), "支援": roles.get("Support"), "开放": colors.ACCENT}.get(queue) or colors.MUTED


def draw_rank_panel(draw, data, box, font, colors, rank_label):
    x, y, right, bottom = [int(v) for v in box]
    series = {queue: rows for queue, rows in data["trends"].items() if rows}
    if not series:
        draw.text((x, y + 40), "本期有竞技比赛，但赛季内暂无可用的段位记录。", font=font(15), fill=colors.MUTED)
        return
    queues = sorted(series, key=lambda q: QUEUE_ORDER.index(q) if q in QUEUE_ORDER else len(QUEUE_ORDER))

    # Legend: queue, current rank and the season change, one chip each.
    lx = x
    legend_row = 0
    for queue in queues:
        rows = series[queue]
        color = _queue_color(queue, colors)
        first, last = rows[0][1], rows[-1][1]
        change = last - first
        current = rank_label(last, chinese=True)
        change_text = f"{change:+.0f}" if change else "±0"
        required = (20 + draw.textlength(queue, font=font(14, bold=True)) + 8
                    + draw.textlength(current, font=font(14)) + 6
                    + draw.textlength(change_text, font=font(13, bold=True)) + 30)
        if lx > x and lx + required > right - 175:
            lx = x
            legend_row += 1
        ly = y + legend_row * 24
        draw.rounded_rectangle((lx, ly + 2, lx + 12, ly + 14), radius=3, fill=color)
        lx += 20
        draw.text((lx, ly + 8), queue, font=font(14, bold=True), fill=colors.INK, anchor="lm")
        lx += draw.textlength(queue, font=font(14, bold=True)) + 8
        current = rank_label(last, chinese=True)
        draw.text((lx, ly + 8), current, font=font(14), fill=colors.TEXT, anchor="lm")
        lx += draw.textlength(current, font=font(14)) + 6
        change_text = f"{change:+.0f}" if change else "±0"
        change_color = colors.WIN if change > 0 else colors.LOSS if change < 0 else colors.MUTED
        draw.text((lx, ly + 8), change_text, font=font(13, bold=True), fill=change_color, anchor="lm")
        lx += draw.textlength(change_text, font=font(13, bold=True)) + 30
    draw.text((right, y + 8), f"{sum(len(rows) for rows in series.values())} 场有段位记录", font=font(12), fill=colors.FAINT, anchor="rm")

    points = [point for rows in series.values() for point in rows]
    t0, t1 = min(p[0] for p in points), max(p[0] for p in points)
    low, high = min(p[1] for p in points), max(p[1] for p in points)
    # Pad to whole divisions and show at least one tier, so small swings are not exaggerated.
    low = max(RANK_BASE, (low - 60) // 100 * 100)
    high = -(-(high + 60) // 100) * 100
    if high - low < 400:
        mid = (high + low) / 2
        low, high = max(RANK_BASE, int(mid - 200) // 100 * 100), int(mid + 200 + 99) // 100 * 100
    left, plot_right = x + 64, right - 8
    top, end = y + 38 + legend_row * 24, bottom - 24
    span_t = max(1.0, t1 - t0)

    def px(ts):
        return left + (ts - t0) / span_t * (plot_right - left)

    def py(score):
        return end - (score - low) / max(1, high - low) * (end - top)

    # The reporting period, as a quiet band.
    p0, p1 = data.get("period_start"), data.get("period_end")
    if p0 and p1 and p1 >= t0 and p0 <= t1:
        band_left = max(left, px(max(p0, t0)) - 4)
        band_right = min(plot_right, px(min(p1, t1)) + 4)
        if band_right - band_left < 10:
            band_left = max(left, band_right - 10)
            band_right = min(plot_right, max(band_right, band_left + 10))
        draw.rounded_rectangle((band_left, top - 4, band_right, end), radius=RADIUS_CHIP, fill=with_alpha(colors.INFO, 26))
        draw.text(((band_left + band_right) / 2, top - 4), "本期", font=font(11, bold=True), fill=colors.INFO, anchor="md")

    # Tier boundaries carry the rank colours; divisions stay as faint guides.
    for score in range(int(low // 100 * 100), int(high) + 1, 100):
        if score < low:
            continue
        yy = py(score)
        if (score - RANK_BASE) % RANK_STEP == 0:
            tier = max(0, min(len(colors.RANK_COLORS) - 1, (score - RANK_BASE) // RANK_STEP))
            tier_color = colors.RANK_COLORS[tier]
            draw.line((left, yy, plot_right, yy), fill=with_alpha(tier_color, 120), width=2)
            draw.text((left - 10, yy), rank_label(score, chinese=True), font=font(12, bold=True), fill=tier_color, anchor="rm")
        else:
            draw.line((left, yy, plot_right, yy), fill=colors.HAIRLINE, width=1)
            if high - low <= 600:
                draw.text((left - 10, yy), rank_label(score, chinese=True), font=font(11), fill=colors.FAINT, anchor="rm")

    for queue in queues:
        color = _queue_color(queue, colors)
        line = [(px(ts), py(score)) for ts, score in series[queue]]
        if len(line) > 1:
            draw.line(line, fill=with_alpha(colors.SCRIM, 200), width=6, joint="curve")
            draw.line(line, fill=color, width=3, joint="curve")
        sx, sy = line[0]
        draw.ellipse((sx - 4, sy - 4, sx + 4, sy + 4), fill=colors.SURFACE_RAISED, outline=color, width=2)
        ex, ey = line[-1]
        draw.ellipse((ex - 6, ey - 6, ex + 6, ey + 6), fill=colors.SCRIM)
        draw.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), fill=color)

    ticks = 5 if t1 > t0 else 1
    for idx in range(ticks):
        ts = t0 + (t1 - t0) * idx / max(1, ticks - 1)
        anchor = "lm" if idx == 0 else "rm" if idx == ticks - 1 else "mm"
        draw.text((px(ts), bottom - 8), datetime.datetime.fromtimestamp(ts / 1000).strftime("%m/%d"),
                  font=font(12), fill=colors.AXIS_TEXT, anchor=anchor)
