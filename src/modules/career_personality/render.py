"""Render an explainable career profile without assuming any particular player."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..font_resolver import load_font, resolve_resource_dir

WIDTH, SCALE = 1120, 2
BG, NAVY, INK = "#EEF2F7", "#142440", "#192B46"
MUTED, ORANGE, BLUE, PURPLE, TEAL = "#69778B", "#EF8D42", "#587CD6", "#8C83CB", "#48AA9D"
PALE = "#E7EDF5"
ROLE_COLORS = {"输出": ORANGE, "重装": BLUE, "支援": TEAL}
MODE_NAMES = {"quick": "快速比赛", "competitive": "竞技比赛",
              "stadium_quick": "角斗领域 · 快速", "stadium_competitive": "角斗领域 · 竞技"}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _fmt(value, places=1):
    value = _number(value)
    if value is None:
        return "—"
    if places == 0:
        return f"{value:,.0f}"
    return f"{value:,.{places}f}".rstrip("0").rstrip(".")


def _pct(value, places=1):
    return "—" if _number(value) is None else _fmt(value, places) + "%"


@lru_cache(maxsize=64)
def _font(size, bold=False):
    # Preserve the prototype's typeface on Windows; the shared resolver supports Linux.
    windows = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    if windows.exists():
        try:
            return ImageFont.truetype(str(windows), round(size * SCALE))
        except OSError:
            pass
    return load_font(round(size * SCALE), prefer_cjk=True, bold=bold)


@lru_cache(maxsize=1)
def _hero_index():
    try:
        config = json.loads((resolve_resource_dir() / "query_tool.json").read_text("utf-8-sig"))
        return {h["name"]: h for h in config.get("heroList", []) if h.get("name")}
    except (OSError, ValueError, TypeError):
        return {}


def _portrait_image(hero):
    resource = resolve_resource_dir()
    entry = _hero_index().get(str(hero.get("name", "")), {})
    urls = [entry.get(key) for key in ("smallIconUrl", "icon", "ddHeroIcon")]
    urls.append(hero.get("icon_url"))
    for url in urls:
        if not isinstance(url, str) or not url:
            continue
        digest = hashlib.sha256(url.encode()).hexdigest()
        for path in (resource / "query_tool_assets" / "heroes" / (digest[:24] + ".png"),
                     resource / "cache_img" / (digest + ".png")):
            try:
                with Image.open(path) as source:
                    return source.convert("RGBA")
            except (OSError, ValueError):
                continue
    return None


class _Surface:
    def __init__(self, height=2600):
        self.image = Image.new("RGB", (WIDTH * SCALE, height * SCALE), BG)
        self.draw = ImageDraw.Draw(self.image)

    def box(self, rect, color="#FFFFFF", radius=22, outline=None):
        self.draw.rounded_rectangle(tuple(round(v * SCALE) for v in rect), radius=round(radius * SCALE),
                                    fill=color, outline=outline, width=SCALE)

    def text(self, x, y, text, size=24, color=INK, bold=False, anchor=None):
        self.draw.text((round(x * SCALE), round(y * SCALE)), str(text), font=_font(size, bold),
                       fill=color, anchor=anchor)

    def width(self, text, size=24, bold=False):
        return self.draw.textlength(str(text), font=_font(size, bold)) / SCALE

    def fit(self, x, y, text, available, size=24, minimum=15, **kwargs):
        text = str(text)
        while self.width(text, size, kwargs.get("bold", False)) > available and size > minimum:
            size -= 1
        while text and self.width(text, size, kwargs.get("bold", False)) > available:
            text = text[:-2] + "…" if len(text) > 1 else ""
        self.text(x, y, text, size=size, **kwargs)

    def wrap(self, text, available, size=20, bold=False):
        result = []
        for paragraph in str(text).splitlines() or [""]:
            current = ""
            for char in paragraph:
                if current and self.width(current + char, size, bold) > available:
                    result.append(current)
                    current = char
                else:
                    current += char
            result.append(current)
        return result

    def paragraph(self, x, y, text, available, size=20, color=MUTED, leading=None):
        leading = leading or size + 9
        for line in self.wrap(text, available, size):
            self.text(x, y, line, size, color)
            y += leading
        return y

    def line(self, x1, y1, x2, y2, color=PALE):
        self.draw.line(tuple(round(v * SCALE) for v in (x1, y1, x2, y2)), fill=color, width=SCALE)

    def pill(self, x, y, text, color="#EAF0F7", ink=INK, size=17, height=32, maximum=1012):
        text = str(text)
        while text and self.width(text, size) + 24 > maximum:
            text = text[:-2] + "…" if len(text) > 1 else ""
        width = self.width(text, size) + 24
        self.box((x, y, x + width, y + height), color, height / 2)
        self.text(x + 12, y + (height - size) / 2 - 2, text, size, ink)
        return width

    def title(self, x, y, eyebrow, title, available=1000):
        self.text(x, y, eyebrow, 15, MUTED, True)
        self.fit(x, y + 25, title, available, size=28, bold=True)

    def portrait(self, hero, x, y, size=74):
        part = Image.new("RGBA", (size * SCALE, size * SCALE), "#EDF1F8")
        source = _portrait_image(hero)
        if source is not None:
            source = ImageOps.contain(source, part.size)
            part.alpha_composite(source, ((part.width - source.width) // 2, part.height - source.height))
        mask = Image.new("L", part.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, part.width, part.height), radius=16 * SCALE, fill=255)
        self.image.paste(part, (x * SCALE, y * SCALE), mask)
        if source is None:
            self.fit(x + 10, y + 23, str(hero.get("name") or "?")[:2], size - 20, size=24, bold=True)

    def segments(self, x, y, width, height, segments):
        self.box((x, y, x + width, y + height), "#EBEFF5", 5)
        valid = [(max(0, _number(value) or 0), color) for value, color in segments]
        total = sum(value for value, _ in valid)
        if not total:
            return
        cursor = x
        for value, color in valid:
            part = width * value / total
            if part > 2:
                self.box((cursor, y, cursor + part - min(2, part / 4), y + height), color, min(5, part / 2))
            cursor += part


def _dimension(data, key):
    return (data.get("dimensions") or {}).get(key) or {}


def _select_statistics(data, heroes):
    rows = [row for row in data.get("statistics", []) if isinstance(row, dict)]
    tags = (data.get("data_overlay") or {}).get("tags") or []
    preferred = [h.get("name") for h in heroes] + [row.get("hero") for row in tags if isinstance(row, dict)]
    comparable = [row for row in rows if _number(row.get("personal")) is not None
                  and _number(row.get("reference")) is not None and row.get("display_delta") is not None]
    pool = comparable or [row for row in rows if _number(row.get("personal")) is not None]
    hero = next((name for name in preferred if any(row.get("hero") == name for row in pool)), None)
    if hero is None and pool:
        hero = pool[0].get("hero")
    chosen = [row for row in pool if row.get("hero") == hero][:4]
    labels = list(dict.fromkeys(str(row["label"]) for row in tags if isinstance(row, dict)
                                and row.get("hero") == hero and row.get("label")))
    tag = " / ".join(labels[:2]) or None
    return hero, tag, chosen


def render_career_personality(data):
    """Return a PIL image. Rendering never performs network calls or reads credentials."""
    s = _Surface()
    persona = data.get("persona") or {}
    heroes = sorted([h for h in data.get("heroes", []) if isinstance(h, dict)],
                    key=lambda h: _number(h.get("hours")) or 0, reverse=True)
    total = _number(data.get("total_hours")) or 0
    player = data.get("player") or {}
    display_name = player.get("display_name", "玩家") if isinstance(player, dict) else str(player)
    mode = data.get("mode_label") or MODE_NAMES.get(data.get("mode"), str(data.get("mode") or "未知模式"))
    is_demo = data.get("is_demo") is True
    status = persona.get("status")
    status_text = {"empty": "暂无有效时长", "low_sample": "样本较少", "incomplete_tags": "标签待补全"}.get(status)

    s.box((24, 24, 1096, 350), NAVY, 30)
    s.text(58, 48, "OVERSTATS", 22, "#DCE6F7", True)
    s.text(236, 53, "CAREER PERSONALITY", 14, "#9AAECC")
    s.pill(882, 48, "模拟数据" if is_demo else "小程序真实数据", "#34445F", "#E2EAF8", size=16, maximum=175)
    s.fit(58, 94, "生涯人格测试 · " + display_name, 985, size=24, color="#C2D0E5")
    s.fit(54, 135, persona.get("title") or "画像待补全", 990, size=57, minimum=28, color="#FFFFFF", bold=True)
    quote = persona.get("quote") or persona.get("summary") or "等待更多英雄记录，逐步补全你的生涯画像。"
    s.fit(58, 218, quote, 980, size=24, minimum=17, color="#DCE6F7")
    chips = list(persona.get("chips") or [])[:4]
    if status_text:
        chips.insert(0, status_text)
    x = 58
    for chip in chips[:4]:
        if not isinstance(chip, str):
            continue
        if x > 850:
            break
        x += s.pill(x, 270, chip, "#2C3E5B", "#FFD1A7", maximum=min(250, 1020 - x)) + 10
    s.text(58, 313, mode + " · 生涯累计 · 英雄选择与数据表现", 16, "#9AAECC")

    y = 370
    s.box((24, y, 1096, y + 311))
    s.title(54, y + 20, "01 / 英雄选择", "你的英雄池，已经写下了线索", available=670)
    s.fit(790, y + 27, f"{_fmt(total, 0)} 小时 / {len(heroes)} 位英雄", 275, size=21, color=MUTED)
    shown = heroes[:6]
    for index, hero in enumerate(shown):
        x = 54 + index * 169
        s.portrait(hero, x, y + 91)
        s.fit(x + 83, y + 90, hero.get("name", "未知英雄"), 78, size=21, minimum=14, bold=True)
        color = ROLE_COLORS.get(hero.get("role"), PURPLE)
        s.fit(x + 83, y + 124, _fmt(hero.get("hours")) + " h", 78, size=23, color=color, bold=True)
        s.fit(x, y + 171, f"{hero.get('role') or '未知职责'} / {hero.get('subrole') or '子职责待补'}", 157, size=15, minimum=12, color=MUTED)
    if not shown:
        s.text(54, y + 112, "所选模式暂无可用于画像的英雄时长。", 24, MUTED)
    remaining = heroes[6:]
    s.text(54, y + 202, f"另有 {len(remaining)} 位英雄，共 {_fmt(sum(_number(h.get('hours')) or 0 for h in remaining))} 小时" if remaining else "已展示全部有效时长英雄", 17, MUTED)
    role_pcts = _dimension(data, "roles").get("pct_of_total") or {}
    s.segments(54, y + 235, 1012, 10, [(role_pcts.get(role), color) for role, color in ROLE_COLORS.items()])
    role_text = "    ".join(role + " " + _pct(role_pcts.get(role), 1) for role in ROLE_COLORS)
    s.text(54, y + 259, role_text, 19, MUTED)
    conc = _dimension(data, "concentration")
    ctext = (str(conc.get("title") or "英雄池待统计") + " · 前三占 " + _pct(conc.get("top_three_pct")))
    s.fit(625, y + 259, ctext, 440, size=19, minimum=14)

    y += 331
    weapon_dim, tactics_dim = _dimension(data, "weapon"), _dimension(data, "tactics")
    weapon, tactics = weapon_dim.get("value") or {}, tactics_dim.get("value") or {}
    s.box((24, y, 550, y + 334))
    s.box((570, y, 1096, y + 334))
    valid_weapon = {key: _number(value) for key, value in weapon.items() if _number(value) is not None}
    top_weapon = max(valid_weapon, key=valid_weapon.get) if valid_weapon else None
    weapon_title = (("其他武器风格为主" if top_weapon == "其他" else top_weapon + "偏好")
                    if top_weapon else "暂无输出枪型数据")
    if status in {"low_sample", "incomplete_tags"} and top_weapon:
        weapon_title = "已知样本中的枪型构成"
    s.title(54, y + 20, "02 / 武器偏好", weapon_title, 466)
    s.text(54, y + 84, "仅统计输出英雄 · " + _fmt(weapon_dim.get("eligible_hours")) + " 小时", 18, MUTED)
    s.segments(54, y + 124, 466, 21, [(weapon.get(key), color) for key, color in (("短枪", ORANGE), ("长枪", BLUE), ("其他", PURPLE))])
    for index, (key, color) in enumerate((("短枪", ORANGE), ("长枪", BLUE), ("其他", PURPLE))):
        yy = y + 164 + index * 37
        s.box((54, yy + 8, 65, yy + 19), color, 3)
        s.text(77, yy, key + (" / 飞行物、光束等" if key == "其他" else ""), 21)
        s.text(520, yy, _pct(weapon.get(key)), 23, color, True, "ra")
    s.text(54, y + 282, "标签覆盖 " + _pct(weapon_dim.get("coverage_pct")), 16, MUTED)
    s.text(54, y + 307, "枪型按作战风格划分；混合武器可多标签", 15, MUTED)
    valid_tactics = {key: _number(value) for key, value in tactics.items() if _number(value) is not None}
    top_tactic = max(valid_tactics, key=valid_tactics.get) if valid_tactics else None
    tactic_values = sorted(valid_tactics.values(), reverse=True)
    if not top_tactic:
        title = "阵容倾向待补全"
    elif tactic_values[0] < 40 or (len(tactic_values) > 1 and tactic_values[0] - tactic_values[1] < 10):
        title = "多种阵容均有涉猎"
    else:
        title = "较偏" + top_tactic
    if status in {"low_sample", "incomplete_tags"} and top_tactic:
        title = "已知样本中的阵容倾向"
    s.title(600, y + 20, "03 / 阵容适配", title, 466)
    s.text(600, y + 84, "英雄软标签 × 游玩时长", 18, MUTED)
    for index, (key, en, color) in enumerate((("放狗", "Dive", ORANGE), ("地推", "Brawl", BLUE), ("消耗", "Poke", PURPLE))):
        yy = y + 126 + index * 52
        s.text(600, yy, key + " / " + en, 20)
        s.box((762, yy + 8, 987, yy + 23), "#EBEFF5", 5)
        value = _number(tactics.get(key))
        if value is not None and value > 0:
            s.box((762, yy + 8, 762 + 225 * min(100, max(0, value)) / 100, yy + 23), color, 5)
        s.text(1066, yy, _pct(value), 21, color, True, "ra")
    s.text(600, y + 282, "标签覆盖 " + _pct(tactics_dim.get("coverage_pct")), 16, MUTED)
    s.text(600, y + 307, "标签加权构成，不代表实际阵容占比", 15, MUTED)

    y += 354
    s.box((24, y, 1096, y + 273))
    s.title(54, y + 20, "04 / 英雄工具偏好", "常用英雄，为你提供什么工具")
    for index, (key, label, color, explanation) in enumerate((
        ("mobility", "机动", ORANGE, "位移与转点"), ("flank", "侧翼", BLUE, "绕侧与切入"),
        ("independence", "自主作战", PURPLE, "自保与续航"), ("team_utility", "协同工具", TEAL, "保护、控制或增益"))):
        x = 54 + index * 258
        value = _dimension(data, key).get("value")
        s.text(x, y + 87, label, 21)
        s.text(x, y + 121, _fmt(value, 0), 40, color, True)
        s.text(x + 83, y + 142, "/ 100", 17, MUTED)
        s.text(x, y + 182, explanation, 17, MUTED)
        s.text(x, y + 209, "覆盖 " + _pct(_dimension(data, key).get("coverage_pct"), 0), 15, MUTED)
        if index < 3:
            s.line(x + 231, y + 93, x + 231, y + 226)
    s.text(54, y + 242, "这些分数描述英雄选择，不等于玩家实际走位、团队协作或实力排名。", 17, MUTED)

    y += 293
    stat_hero, stat_tag, stats = _select_statistics(data, heroes)
    stats_h = 187 + max(1, len(stats)) * 43 + 49
    s.box((24, y, 1096, y + stats_h))
    stat_title = ((str(stat_hero) + " · " + (stat_tag or "同英雄数据对照"))
                  if stat_hero else "暂缺可比较的详细统计")
    s.title(54, y + 20, "05 / 数据补充", stat_title, available=1000)
    s.text(54, y + 84, "每 10 分钟 · " + ("个人值与中位数均为模拟" if is_demo else "小程序同英雄中位数"), 18, MUTED)
    stat_hours = next((_number(h.get("hours")) or 0 for h in heroes if h.get("name") == stat_hero), 0)
    scope_text = (f"本表仅对应 {stat_hero} · {_fmt(stat_hours)} 小时 / 生涯时长 {_pct(stat_hours / total * 100 if total else None)}"
                  if stat_hero else "缺失数据保留为空；不使用其他英雄或模式的基准补齐。")
    s.fit(54, y + 116, scope_text, 1012, size=17, color=MUTED)
    for x, label in ((54, "指标"), (520, "玩家"), (790, "参考中位数"), (1066, "差异")):
        s.text(x, y + 154, label, 17, MUTED, anchor=None if x == 54 else "ra")
    s.line(54, y + 181, 1066, y + 181)
    for index, row in enumerate(stats):
        yy = y + 193 + index * 43
        label = str(row.get("metric") or "统计").removeprefix("每10分钟")
        s.fit(54, yy, label, 350, size=23)
        s.text(520, yy, _fmt(row.get("personal"), 2), 24, INK, True, "ra")
        s.text(790, yy, _fmt(row.get("reference"), 2), 23, MUTED, anchor="ra")
        delta = row.get("display_delta") or "—"
        s.text(1066, yy, str(delta).replace("-", "−"), 23, ORANGE if str(delta).startswith("+") else MUTED, True, "ra")
    if not stats:
        s.text(54, y + 195, "暂未取得同口径明细与基准，保留英雄选择画像。", 22, MUTED)
    s.text(54, y + stats_h - 33, "差异只描述对应英雄的统计表现；参考未提供段位分层信息，不用于实力或配合排名。", 16, MUTED)

    y += stats_h + 20
    explanation = ((data.get("team_vs_solo") or {}).get("explanation")
                   or "英雄选择说明你拥有哪些工具，无法单独识别是否脱离团队、集火时机与实际配合。")
    expl_lines = s.wrap(explanation, 1012, 21)
    team_h = 127 + len(expl_lines) * 30
    s.box((24, y, 1096, y + team_h), "#E4EAF5", outline="#D5DFEF")
    s.text(54, y + 22, "团队，还是独狼？", 28, INK, True)
    s.pill(876, y + 23, "证据不足", "#D4DEEF", "#344969", maximum=180)
    s.paragraph(54, y + 76, explanation, 1012, size=21, color=INK, leading=30)
    s.text(54, y + team_h - 35, "自主作战与协同工具可以同时偏好；实际打法需要更多对局证据。", 18, "#3E5680")
    y += team_h + 24
    version = str(data.get("tag_version") or data.get("rules_version") or "v1")
    s.fit(30, y, ("演示数据" if is_demo else "小程序生涯数据") + " · 标签规则 " + version + " · 时长按上游取整小时统计", 1060, size=17, color=MUTED)
    s.text(30, y + 32, "描述游戏偏好，不推断现实性格。", 18, MUTED)
    fetched = str(data.get("fetched_at") or "")[:10]
    s.text(1090, y + 32, "OVERSTATS" + (" / " + fetched if fetched else ""), 16, MUTED, anchor="ra")
    height = y + 73
    if height > s.image.height / SCALE:
        raise ValueError("Career personality card exceeds the layout canvas.")
    return s.image.crop((0, 0, WIDTH * SCALE, height * SCALE)).resize((WIDTH, height), Image.Resampling.LANCZOS)
