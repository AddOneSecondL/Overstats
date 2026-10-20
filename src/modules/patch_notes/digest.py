"""Single share image: all hero changes, no developer commentary.

Numeric labels are conservative local rules, never an estimate of overall hero strength.
The original change string remains available beside every compact display string.
"""
from io import BytesIO
import re

from .parser import iter_entries

COLORS = {"buff": "#69DDB0", "nerf": "#FF8C96", "adjust": "#F2C779"}
TAGS = {"buff": "增强", "nerf": "削弱", "adjust": "调整"}
COMMENT = re.compile(r"^\s*(?:开发者(?:说明|评论|评价)|设计师(?:观点|评论)|Developer\s+(?:Comments?|Notes?))\s*[:：]", re.I)
CN_NUMBER = re.compile(
    r"^(?P<metric>.+?)从\s*(?P<prefix1>[^\d，。；;]*?)(?P<before>\d+(?:\.\d+)?(?:[-–]\d+(?:\.\d+)?)?)(?P<unit1>[^，。；;]*?)"
    r"(?:增加|提高|提升|降低|减少|缩短|延长|调整|变更|增大|缩小|改)(?:至|为|到)\s*"
    r"(?P<prefix2>[^\d，。；;]*?)(?P<after>\d+(?:\.\d+)?(?:[-–]\d+(?:\.\d+)?)?)(?P<unit2>[^，。；;（(]*)(?P<scope>[（(].*?[）)])?[。.]?$"
)
EN_NUMBER = re.compile(
    r"^(?P<metric>.+?)\s+(?:increased|decreased|reduced|changed|adjusted)\s+from\s+"
    r"(?P<before>\d+(?:\.\d+)?)(?P<unit1>[^.;]*?)\s+to\s+"
    r"(?P<after>\d+(?:\.\d+)?)(?P<unit2>[^.;(]*)(?P<scope>\(.*?\))?\.?$", re.I
)


def numeric_change(text):
    cleaned = re.sub(r"[。.]\s*(?=[（(])", "", text.strip())
    match = CN_NUMBER.fullmatch(cleaned) or EN_NUMBER.fullmatch(cleaned)
    if not match:
        return None
    value = {key: (value or "").strip().rstrip("。.") for key, value in match.groupdict().items()}
    value.setdefault("prefix1", "")
    value.setdefault("prefix2", "")
    if any(re.search(r"\d|从|增加|降低|提高|\b(?:from|to|and)\b", value[key], re.I)
           for key in ("unit1", "unit2")):
        return None
    return value


def classify_change(text, ability=""):
    """Return (tag, reason); unknown and context-sensitive mechanics stay amber."""
    if re.search(r"修复|错误|漏洞|不再|fixed|bug|no longer", text, re.I):
        return "adjust", "规则或修复，不推断强弱"
    value = numeric_change(text)
    if not value:
        relative = re.fullmatch(r"(.+?)(增加|提高|提升|降低|减少|缩短|延长)(\d+(?:\.\d+)?)\s*(%|％|秒)[。.]?", text.strip())
        if relative:
            metric, verb, amount, unit = relative.groups()
            if any(word in metric for word in ("期间", "可使", "现在", "新增", "获得", "施放后")):
                return "adjust", "条件或新机制不能当作既有数值比较"
            # An explicit delta has the same sign as an equivalent scalar comparison.
            down = verb in {"降低", "减少", "缩短"}
            return classify_change(f"{metric}从100{unit}{verb}至{99 if down else 101}{unit}", ability)
        return "adjust", "无法可靠识别单一数值方向"
    metric = value["metric"].lower()
    before = [float(number) for number in re.split("[-–]", value["before"])]
    after = [float(number) for number in re.split("[-–]", value["after"])]
    if len(before) != len(after) or not (all(a >= b for a, b in zip(after, before)) or all(a <= b for a, b in zip(after, before))):
        return "adjust", "区间各端点方向不一致"
    direction = sum(a - b for a, b in zip(after, before))
    if direction == 0:
        return "adjust", "数值相同"
    def decide(higher):
        return ("buff" if (direction > 0) == higher else "nerf"), "已识别属性及方向"
    if re.search(r"(头部|躯干|腿部|手部|手臂|前臂|腰部|肩部|脚部|小腿|拳头|背部机枪|钳形手).*判定", metric):
        return decide(False)
    if re.search(r"衰减距离|falloff.*range", metric):
        return decide(True)
    if re.search(r"冷却.*缩短|消耗.*缩减|消耗.*降低|冷却.*减少", metric):
        return decide(True)
    if re.search(r"受伤减免|减伤|伤害减免|生命汲取|充能获取|转化率|返还.*数量", metric):
        return decide(True)
    if re.search(r"施放时间|变形时间|延迟时间|恢复时间|进入.*时间|衔接动作持续时间|挥击的持续时间", metric):
        return decide(False)
    if re.search(r"视野超时时间", metric):
        return decide(True)
    if re.search(r"持续时间", metric) and (
        re.search(r"击晕|相移无敌|潜行|侵入急救包|过量生命值", metric)
        or re.search(r"屏障|呼吸器|切换模式|音障", ability)):
        return decide(True)
    if re.search(r"受到|承受|自伤|自身伤害|衰减|敌人|敌方|判定|体积|尺寸|received|taken|self.damage|falloff|enemy|enemies|hitbox|size", metric):
        return "adjust", "属性依赖上下文"
    if re.search(r"缩短|减少|降低|减免|返还|reduction|refund", metric):
        return "adjust", "此处改变的是增减幅度，不能按基础属性方向判断"
    if re.search(r"消耗|cost|consumption", metric) and not re.search(r"终极技能|燃料|ultimate|fuel", metric):
        return "adjust", "资源消耗依赖上下文"
    inverse = re.search(r"冷却(?:时间)?|装填时间|换弹时间|终极技能消耗|终极技能所需|燃料消耗|散布|后坐力|cooldown|reload time|ultimate cost|fuel consumption|spread|recoil", metric)
    positive = re.search(r"伤害|治疗量|治疗效果|生命值|护甲|护盾|弹药|装填弹药量|移动速度|速度加成|弹道速度|恢复速度|射速|攻击速度|挥砍速度|弹丸总数|放置范围|投掷范围|投掷距离|追踪距离|爆炸半径|减伤|damage|healing|health|armor|shield health|ammo|movement speed|fire rate|attack speed", metric)
    if not inverse and re.search(r"时间|持续|延迟|间隔|duration|time|delay|interval", metric):
        return "adjust", "时长收益依赖技能机制"
    if not inverse and not positive:
        return "adjust", "未配置此属性的收益方向"
    better = direction < 0 if inverse else direction > 0
    return ("buff" if better else "nerf"), ("此属性越低越有利" if inverse else "此属性越高越有利")


def _pick(ability, original, icon):
    value = numeric_change(original)
    kind, reason = classify_change(original, ability)
    if value:
        compact = f"{value['metric']} {value['prefix1']}{value['before']}{value['unit1']} → {value['prefix2']}{value['after']}{value['unit2']}"
        if value["scope"]:
            compact += " " + value["scope"]
    else:
        compact = original
    return dict(ability=ability, text=original, compact=compact, icon=icon,
                number=value, kind=kind, reason=reason)


def hero_changes(item):
    """Keep document order and perk context; never count commentary or headings as changes."""
    result, context = [], ""
    general = item.get("general_changes") or []
    order = item.get("order") or (
        [dict(kind="general", index=i) for i in range(len(general))]
        + [dict(kind="ability", index=i) for i in range(len(item.get("abilities") or []))]
    )
    for entry in order:
        kind, index = entry["kind"], entry["index"]
        if kind in {"dev", "note"}:
            continue
        if kind == "ability":
            ability = item["abilities"][index]
            for line in ability.get("changes") or []:
                if not COMMENT.match(line):
                    result.append(_pick(ability.get("name", ""), line, ability.get("icon_url", "")))
            context = ""
            continue
        line = general[index]
        if COMMENT.match(line):
            continue
        next_line = general[index + 1] if index + 1 < len(general) else ""
        is_heading = (
            re.search(r"(?:——| - ).*(?:威能|被动|异能|Perk|Passive|Power)", line, re.I)
            or next_line.strip("。.").lower() in {
                "新增", "已移除", "新次级威能", "新主要威能",
                "new", "removed", "new minor perk", "new major perk",
            }
        )
        if is_heading:
            context = line
            continue
        result.append(_pick(context, line, ""))
        if line.strip("。.").lower() in {"已移除", "removed"}:
            context = ""
    return result


def build_digest(candidate):
    from .render import label
    heroes, general, other = [], [], []
    for section in candidate.get("sections") or []:
        title = label(section["title"])
        for kind, item in iter_entries(section):
            if kind == "hero":
                picks = hero_changes(item)
                heroes.append(dict(name=item.get("name", ""), icon=item.get("icon_url", ""),
                                   section=title, picks=picks, total=len(picks),
                                   rework=bool(re.search(r"重做|rework", title, re.I))))
            else:
                paragraphs = list(item.get("paragraphs") or []) + list(item.get("bullets") or [])
                paragraphs = [line for line in paragraphs if not COMMENT.match(line)]
                general.append(dict(title=item.get("title") or item.get("name") or title,
                                    section=title, lines=paragraphs,
                                    mode=mode_of(title + " / " + (item.get("title") or item.get("name") or "")),
                                    images=([url for url in [item.get("before_image_url"), item.get("after_image_url")] if url]
                                            if kind == "map" else list(item.get("images") or []))))
                if title not in other:
                    other.append(title)
    counts = {kind: sum(pick["kind"] == kind for hero in heroes for pick in hero["picks"])
              for kind in COLORS}
    return dict(heroes=heroes, hero_count=len({hero["name"] for hero in heroes}),
                change_count=sum(hero["total"] for hero in heroes), counts=counts,
                omitted_heroes=0, omitted_changes=0,
                other=other, general=general, section_count=len(candidate.get("sections") or []))


def digest_assets(model):
    # Compact view uses hero portraits; ability names remain text for unambiguous context.
    urls = [hero["icon"] for hero in model["heroes"] if hero.get("icon")]
    urls += [pick["icon"] for hero in model["heroes"] for pick in hero["picks"] if pick.get("icon")]
    urls += [url for item in model["general"] for url in item["images"]]
    return list(dict.fromkeys(urls))


def mode_of(section):
    return "stadium" if re.search(r"角斗|stadium", section, re.I) else "normal"


def metric_icon(metric):
    """Return an attribute symbol and concise label, retaining nontrivial qualifiers."""
    patterns = [
        ("health", r"生命值$"), ("armor", r"护甲$"), ("shield", r"护盾$"),
        ("cooldown", r"冷却时间$"), ("damage", r"伤害(?:量)?$"),
        ("heal", r"治疗量$"), ("speed", r"(?:弹道速度|移动速度|射速)$"),
    ]
    for kind, pattern in patterns:
        match = re.search(pattern, metric)
        if match:
            remaining = metric[:match.start()].rstrip("的")
            if kind == "speed":
                remaining = metric.replace("速度", "") if "速度" in metric else metric
            return kind, remaining
    return "", metric


def draw_metric(draw, kind, x, y, color, size=22):
    """Code-drawn symbols are independent of font glyphs and CDN availability."""
    if kind in {"health", "armor", "shield"}:
        fill = {"health": "#F2F4F6", "armor": "#F4BC56", "shield": "#71C9F0"}[kind]
        draw.polygon([(x+4,y),(x+size,y),(x+size,y+size-4),(x+size-4,y+size),(x,y+size),(x,y+4)], fill=fill)
    elif kind == "cooldown":
        draw.ellipse((x,y,x+size,y+size), outline=color, width=2)
        draw.line((x+size//2,y+4,x+size//2,y+size//2,x+size-4,y+size//2), fill=color, width=2)
    elif kind == "damage":
        draw.ellipse((x+4,y+4,x+size-4,y+size-4), outline=color, width=2)
        draw.line((x+size//2,y,x+size//2,y+size), fill=color, width=2)
        draw.line((x,y+size//2,x+size,y+size//2), fill=color, width=2)
    elif kind == "heal":
        draw.rectangle((x+8,y,x+14,y+size), fill=color)
        draw.rectangle((x,y+8,x+size,y+14), fill=color)
    elif kind == "speed":
        draw.line((x+3,y+2,x+12,y+11,x+3,y+20), fill=color, width=3)
        draw.line((x+12,y+2,x+21,y+11,x+12,y+20), fill=color, width=3)


def render_digest(candidate, model, assets):
    from PIL import Image, ImageDraw, ImageOps
    from .render import _font, _wrap, RenderedImage
    width, margin, gap, card_width = 1440, 40, 22, 669
    if len(model["heroes"]) == 1:
        card_width = width - margin * 2
    placements, frames, bottoms = [], [], [200, 200]
    ordered = [hero for mode in ("normal", "stadium") for hero in model["heroes"] if mode_of(hero["section"]) == mode]
    previous_mode = None
    for hero in ordered:
        mode = mode_of(hero["section"])
        if mode != previous_mode:
            if frames:
                frames[-1]["bottom"] = max(bottoms) + 6
            start = max(bottoms) + (28 if frames else 0)
            frames.append(dict(mode=mode, top=start, bottom=0))
            bottoms = [start + 64, start + 64]
            previous_mode = mode
        lines, last_ability = [], None
        for pick in hero["picks"]:
            if pick["ability"] and pick["ability"] != last_ability:
                for line_index, value in enumerate(_wrap(pick["ability"], 22, card_width - 90)):
                    lines.append(dict(text=value, style="ability", kind="adjust", height=38,
                                      icon=pick.get("icon") if line_index == 0 else ""))
            symbol, display = "", pick["compact"]
            if pick["number"]:
                symbol, short = metric_icon(pick["number"]["metric"])
                if symbol:
                    attribute = {"health": "生命值", "armor": "护甲", "shield": "护盾",
                                 "damage": "伤害", "cooldown": "CD", "heal": "治疗", "speed": "速度"}[symbol]
                    display = f"（{attribute}）" + (short + " " + pick["compact"][len(pick["number"]["metric"]):].lstrip()).strip()
            for index, value in enumerate(_wrap(display, 24, card_width - 84)):
                lines.append(dict(text=value, style="change", kind=pick["kind"], height=33,
                                  symbol=symbol if index == 0 else ""))
            last_ability = pick["ability"]
        if not lines:
            lines.append(dict(text="无独立改动条目，说明见原文", style="ability", kind="adjust", height=32))
        title_lines = _wrap(hero["name"], 32, card_width - 130)
        section_lines = _wrap(hero["section"].split(" / ")[-1], 19, card_width - 130)
        header = max(102, 22 + len(title_lines) * 38 + len(section_lines) * 25)
        height = header + sum(line["height"] for line in lines) + 24
        column = 0 if bottoms[0] <= bottoms[1] else 1
        placements.append(dict(hero=hero, x=margin + column * (card_width + gap),
                               y=bottoms[column], height=height, header=header,
                               title_lines=title_lines, section_lines=section_lines, lines=lines))
        bottoms[column] += height + gap
    if frames:
        frames[-1]["bottom"] = max(bottoms) + 6
    footer_y = max(bottoms) + 28 if placements else 200
    system_lines = []
    for mode in ("normal", "stadium"):
        items = [item for item in model["general"] if item["mode"] == mode and (item["lines"] or item["images"])]
        if not items:
            continue
        system_lines.append((mode, "group-start"))
        for item in items:
            heading = item["title"] if item["title"] == item["section"] else item["section"] + " / " + item["title"]
            system_lines.extend((line, "heading") for line in _wrap(heading, 27, width - margin * 2))
            for paragraph in item["lines"]:
                system_lines.extend((line, "body") for line in _wrap(paragraph, 24, width - margin * 2))
            for index in range(0, len(item["images"]), 2):
                system_lines.append((item["images"][index:index + 2], "images"))
        system_lines.append(("", "group-end"))
    def row_height(style):
        return {"images": 340, "group-start": 58, "group-end": 28}.get(style, 36)
    height = max(530, footer_y + sum(row_height(style) for _, style in system_lines) + 80)
    if width * height > 60_000_000:
        raise ValueError("补丁过大，单图无法安全容纳，请按章节查询。")
    image = Image.new("RGB", (width, height), "#101923")
    draw = ImageDraw.Draw(image)
    white, muted, blue = "#F1F5FA", "#AAB9C8", "#85D5F3"

    def text(x, y, value, size=24, color=white):
        draw.text((x, y), str(value), font=_font(size), fill=color)

    def portrait(hero, x, y):
        path = assets.get(hero["icon"])
        if path:
            try:
                with Image.open(path) as source:
                    tile = ImageOps.fit(source.convert("RGBA"), (72, 72))
                    image.paste(tile, (x, y), tile)
                return
            except (OSError, ValueError):
                pass
        draw.rounded_rectangle((x, y, x + 72, y + 72), radius=10, fill="#344657")
        text(x + 10, y + 24, hero["name"][:2], 23, blue)

    draw.rectangle((0, 0, width, 8), fill=blue)
    text(margin, 32, "补丁速读", 46)
    date = str(candidate.get("date") or candidate.get("date_text") or "")
    text(margin, 98, f"{date}  ·  {candidate.get('source_name', '')}", 25, muted)
    text(margin, 151, f"{model['hero_count']} 位英雄 / {model['change_count']} 条改动" if placements else "系统与修复更新", 28)
    for index, kind in enumerate(COLORS):
        x = 740 + index * 214
        draw.rounded_rectangle((x, 151, x + 18, 169), radius=4, fill=COLORS[kind])
        text(x + 28, 144, f"{TAGS[kind]} {model['counts'][kind]}", 24, COLORS[kind])
    for frame in frames:
        color = blue if frame["mode"] == "normal" else "#BEA2F3"
        draw.rounded_rectangle((20, frame["top"], width-20, frame["bottom"]), radius=20,
                               outline=color, width=2, fill="#14202C")
        text(margin, frame["top"] + 17, "普通模式" if frame["mode"] == "normal" else "角斗领域", 29, color)
    for card in placements:
        hero, x, y = card["hero"], card["x"], card["y"]
        draw.rounded_rectangle((x, y, x + card_width, y + card["height"]), radius=17, fill="#1D2A38")
        portrait(hero, x + 16, y + 16)
        ty = y + 15
        for line in card["title_lines"]:
            text(x + 106, ty, line, 32); ty += 38
        for line in card["section_lines"]:
            text(x + 106, ty, line, 19, muted); ty += 25
        ty = y + card["header"]
        for line in card["lines"]:
            if line["style"] == "ability":
                icon_path = assets.get(line.get("icon"))
                if icon_path:
                    try:
                        with Image.open(icon_path) as source:
                            tile = ImageOps.contain(source.convert("RGBA"), (30, 30))
                            image.paste(tile, (x+18, ty), tile)
                    except (OSError, ValueError):
                        draw_metric(draw, "cooldown", x+20, ty+3, muted)
                else:
                    draw.polygon([(x+30,ty+3),(x+42,ty+15),(x+30,ty+27),(x+18,ty+15)], outline=muted)
                text(x + 58, ty + 2, line["text"], 22, muted)
            else:
                color = COLORS[line["kind"]]
                if line.get("symbol"):
                    draw_metric(draw, line["symbol"], x+18, ty+4, color)
                else:
                    symbol = "+" if line["kind"] == "buff" else "-" if line["kind"] == "nerf" else "·"
                    text(x + 18, ty, symbol, 24, color)
                text(x + 50, ty, line["text"], 24, color)
            ty += line["height"]
    y = footer_y + 8
    for index, (line, style) in enumerate(system_lines):
        if style == "group-start":
            block_height = 58
            for _, next_style in system_lines[index+1:]:
                block_height += row_height(next_style)
                if next_style == "group-end":
                    break
            color = blue if line == "normal" else "#BEA2F3"
            draw.rounded_rectangle((20, y, width-20, y+block_height-12), radius=18, outline=color, width=2)
            text(margin, y+15, ("普通模式" if line == "normal" else "角斗领域") + " · 其他更新", 27, color)
            y += 58
            continue
        if style == "group-end":
            y += 28
            continue
        if style == "images":
            for slot, url in enumerate(line):
                image_width = (width - margin * 2 - gap) // 2
                x = margin + slot * (image_width + gap)
                path = assets.get(url)
                pasted = False
                if path:
                    try:
                        with Image.open(path) as source:
                            tile = ImageOps.contain(source.convert("RGBA"), (image_width, 310))
                            image.paste(tile, (x, y), tile)
                            pasted = True
                    except (OSError, ValueError):
                        pass
                if not pasted:
                    draw.rounded_rectangle((x, y, x + image_width, y + 310), radius=12, fill="#1D2A38")
                    text(x + 20, y + 130, "原文图片暂未加载 · 请查看原文", 24, muted)
            y += 340
            continue
        text(margin, y, line, 27 if style == "heading" else 23, blue if style == "heading" else muted)
        y += 36
    text(margin, y + 13, "完整原文见随图链接", 21, muted)
    buf = BytesIO()
    image.save(buf, format="PNG", compress_level=3)
    return RenderedImage(buf.getvalue())
