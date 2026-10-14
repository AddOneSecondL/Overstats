from __future__ import annotations

import datetime as dt
import math
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont
from PIL import Image, ImageDraw
from .render import _load_font, _load_logo_image, _encode_image
from .schedule import REGIONS


@lru_cache(maxsize=64)
def schedule_font(size, bold=False):
    candidates = (["C:/Windows/Fonts/msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"] if bold else
                  ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"])
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return _load_font(size, bold=bold)


TRANSLATIONS = {"Playoffs Seeding Decider Matches": "季后赛种子排位赛", "Last Chance Qualifier": "最后机会资格赛", "Regional Playoffs": "区域季后赛", "Round Robin Stage": "循环赛", "Group Stage": "小组赛", "Regular Season": "常规赛", "Playoffs": "淘汰赛", "Lower Bracket Semifinal": "败者组半决赛", "Lower Bracket Final": "败者组决赛", "Upper Bracket Final": "胜者组决赛", "3rd Place Match": "季军赛", "Grand Final": "总决赛", "Quarterfinal": "八强赛", "Semifinal": "半决赛"}


def label(value):
    for old, new in TRANSLATIONS.items():
        value = value.replace(old, new)
    return value


def bracket_layout(rows):
    by_id = {r["id"]: r for r in rows}
    levels, visiting = {}, set()
    def depth(mid):
        if mid in levels:
            return levels[mid]
        if mid in visiting:
            raise ValueError("cyclic bracket")
        visiting.add(mid)
        parents = by_id[mid].get("previous_matches", [])
        if any(p.get("match_id") not in by_id for p in parents):
            raise ValueError("incomplete bracket")
        levels[mid] = max((depth(p["match_id"]) + 1 for p in parents), default=0)
        visiting.remove(mid)
        return levels[mid]
    grouped = {}
    for row in rows:
        grouped.setdefault(depth(row["id"]), []).append(row)
    if len(grouped) > 4:
        raise ValueError("bracket too wide")
    return grouped


def render_schedule(sections, *, requested_region, region, generated_at, logo_assets=None):
    assets = logo_assets or {}
    layouts = []
    for section in sections:
        levels = None
        if section.get("bracket"):
            try:
                levels = bracket_layout(section["rows"])
            except ValueError:
                pass
        columns = max(3, len(levels)) if levels else 2
        height = (max(len(v) for v in levels.values()) * 254 if levels else math.ceil(len(section["rows"]) / 2) * 214) + 124
        layouts.append((section, levels, columns, height))
    width = 1800
    height = 290 + sum(item[3] + 28 for item in layouts) + 100
    if not layouts:
        height = 520
    canvas = Image.new("RGB", (width, height), "#101B29")
    draw = ImageDraw.Draw(canvas)
    def text(x, y, value, size=23, color="#E9F0F7", bold=False, limit=None):
        value = str(value)
        font = schedule_font(size, bold=bold)
        if limit:
            while draw.textlength(value, font=font) > limit and len(value) > 1:
                value = value[:-2] + "…"
        draw.text((x, y), value, font=font, fill=color)
    def panel(rect, fill="#1B2C40", border="#344B64"):
        x, y, right, bottom = rect
        draw.rounded_rectangle((x, y+5, right, bottom+5), radius=16, fill="#09121D")
        draw.rounded_rectangle(rect, radius=16, fill=fill, outline=border, width=2)
    def when(row):
        timestamp = row.get("start_timestamp")
        return dt.datetime.fromtimestamp(timestamp, dt.timezone(dt.timedelta(hours=8))).strftime("%m/%d %H:%M") if timestamp else "时间待定"
    text(50, 34, "OVERSTATS / ESPORTS", 22, "#91A6BD", True)
    text(50, 85, REGIONS[region] + "赛事", 50, bold=True)
    subtitle = "中国暂无赛事，已展示世界赛程" if requested_region != region else "赛程、赛果与晋级路线"
    text(52, 157, subtitle, 25, "#A8BDCF")
    text(1350, 58, "比赛时间 UTC+8", 24, "#9CB3CB")
    text(1350, 104, generated_at, 19, "#8298B0")
    if not layouts:
        text(60, 290, "当前赛区暂无进行中或待开始的赛事。", 30)
    y = 244
    for section, levels, columns, section_h in layouts:
        panel((30, y, 1770, y+section_h), "#142233", "#293D53")
        text(54, y+19, REGIONS[section["region"]] + " / " + label(section["name"]), 30, bold=True)
        text(55, y+64, section["series"], 20, "#94ABC3", limit=1670)
        rows = section["rows"]
        names = {r["id"]: label(r["match_name"].split(":")[0]) for r in rows}
        if levels:
            step = 1710 // columns
            card_w = step-80
            positions = {r["id"]: (55+lv*step, y+108+i*254) for lv, group in levels.items() for i, r in enumerate(group)}
            for r in rows:
                x, yy = positions[r["id"]]
                for edge in r.get("previous_matches", []):
                    sx, sy = positions[edge["match_id"]]
                    # Separate winner and loser lanes so routes cannot cover one another.
                    mid = x-24 if edge.get("type") == "winner" else x-44
                    color = "#68BFA9" if edge.get("type") == "winner" else "#BE926A"
                    draw.line([(sx+card_w, sy+95), (mid, sy+95), (mid, yy+95), (x, yy+95)], fill=color, width=3)
        else:
            card_w = 810
            positions = {r["id"]: (55+(i%2)*870, y+108+(i//2)*214) for i, r in enumerate(rows)}
        for row in rows:
            x, yy = positions[row["id"]]
            live = row["raw_status"] in {"running", "live"}
            panel((x, yy, x+card_w, yy+186), border="#66CBAA" if live else "#344B64")
            text(x+15, yy+10, names[row["id"]] if levels else when(row), 19, "#ABC0D5", True, card_w-128)
            text(x+card_w-93, yy+12, row["status"], 17, "#76E0BD" if live else ("#91A6BD" if row["raw_status"] == "finished" else "#E3B778"))
            previous = list(row.get("previous_matches", []))
            for i in range(2):
                team = row["team"+str(i+1)]
                name = team.get("name") or "TBD"
                if name == "TBD":
                    name = names.get(previous[i].get("match_id"), "前场") + (" 胜者" if previous[i].get("type") == "winner" else " 败者") if i < len(previous) else "待定队伍"
                top = yy+48+i*58
                won = row.get("winner_id") is not None and team.get("id") == row["winner_id"]
                if won:
                    draw.rounded_rectangle((x+8, top-2, x+card_w-8, top+52), radius=9, fill="#24483E")
                draw.rounded_rectangle((x+15, top, x+65, top+50), radius=10, fill="#E3EAF0")
                logo = _load_logo_image(team.get("logo", ""), (48,48), team.get("short_name") or "?", logo_assets=assets)
                canvas.paste(logo, (x+16, top+1), logo)
                text(x+78, top+11, name, 23, "#A2EBD4" if won else "#E9F0F7", True, card_w-137)
                score = row.get("score"+str(i+1))
                text(x+card_w-40, top+10, "—" if row["raw_status"] == "not_started" or score is None else score, 25, "#85E8C9" if won else "#CAD7E6", True)
            count = row.get("number_of_games")
            rule = (f"先赢 {count} 局" if row.get("match_type") == "first_to" else f"BO{count}") if count else "赛制待定"
            text(x+16, yy+163, (when(row)+" · " if levels else "")+rule, 16, "#90A6BF")
        y += section_h+28
    text(50, height-63, "OW赛事 [中国 / 韩国 / 日本 / 北美 / EMEA / 世界]", 21, "#9CB2C9")
    text(1175, height-63, "PandaScore · 绿色晋级 / 棕色败者路线", 18, "#91A6BD")
    return _encode_image(canvas)
