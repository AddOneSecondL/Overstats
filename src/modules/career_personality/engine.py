"""Explainable game-preference summaries from one mode's lifetime hero records.

Style scores describe a hero pool and deliberately do not measure psychology,
player strength, or actual teamwork. No network requests or credential storage.
"""
from __future__ import annotations

from copy import deepcopy
import math


ROLE_NAMES = {"Tank": "重装", "Damage": "输出", "Support": "支援",
              "tank": "重装", "dps": "输出", "healer": "支援",
              "重装": "重装", "输出": "输出", "支援": "支援"}
MODE_NAMES = {"quick": "快速比赛", "competitive": "竞技比赛",
              "stadium_quick": "角斗领域快速", "stadium_competitive": "角斗领域竞技"}
MIN_PERSONA_HOURS = 10
MIN_OVERLAY_HOURS = 5
OVERLAY_DELTA = 10
AXES = {"伤害": "对英雄伤害量", "消灭": "消灭", "助攻": "助攻", "治疗": "治疗量"}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _pct(part, total):
    return round(part / total * 100, 2) if total > 0 else None


def _complete(dimension):
    return (dimension["eligible_hours"] > 0
            and math.isclose(dimension["covered_hours"], dimension["eligible_hours"], rel_tol=0, abs_tol=1e-9))


def _weighted(heroes, key, categories=None, role=None):
    eligible = [hero for hero in heroes if role is None or hero["role"] == role]
    denominator = sum(hero["hours"] for hero in eligible)
    totals = {name: 0.0 for name in categories} if categories else 0.0
    contributions = []
    for hero in eligible:
        value = hero["style"].get(key)
        if categories:
            if not isinstance(value, dict):
                continue
            parsed = {name: _number(value.get(name)) for name in categories}
            if any(v is None or not 0 <= v <= 1 for v in parsed.values()):
                continue
            if not math.isclose(sum(parsed.values()), 1.0, abs_tol=1e-6):
                continue
            contribution = {name: hero["hours"] * parsed[name] for name in categories}
            for name in categories:
                totals[name] += contribution[name]
            value = parsed
        else:
            value = _number(value)
            if value is None or not 0 <= value <= 1:
                continue
            contribution = hero["hours"] * value
            totals += contribution
        contributions.append({"hero": hero["name"], "hours": hero["hours"],
                              "tag": deepcopy(value), "weighted_hours": contribution})
    covered = sum(row["hours"] for row in contributions)
    value = ({name: _pct(value, covered) for name, value in totals.items()}
             if categories else _pct(totals, covered))
    return {"value": value, "eligible_hours": denominator, "covered_hours": covered,
            "coverage_pct": _pct(covered, denominator), "contributions": contributions}


def _distribution(heroes, field, total):
    hours = {}
    for hero in heroes:
        if hero.get(field):
            hours[hero[field]] = hours.get(hero[field], 0) + hero["hours"]
    covered = sum(hours.values())
    return {"hours": hours, "pct_of_total": {key: _pct(value, total) for key, value in hours.items()},
            "eligible_hours": total, "covered_hours": covered, "coverage_pct": _pct(covered, total)}


def _statistics(raw, hero):
    """A radar median is usable only after its value matches the per-ten row."""
    per_ten = {}
    for item in _rows(raw.get("summary")):
        name = str(item.get("item_name") or "").strip()
        explicit_per_ten = name.startswith(("每10分钟", "每十分钟"))
        if str(item.get("item_type")) != "3" and not explicit_per_ten:
            continue
        name = name.removeprefix("每10分钟").removeprefix("每十分钟")
        # A percentage, elapsed duration, or per-match unit cannot be a count/rate.
        unit = str(item.get("item_unit") or "").strip()
        if any(word in unit for word in ("%", "秒", "场", "每分钟", "/分钟")):
            continue
        if name in AXES.values() or name in {"阵亡", "单独消灭", "最后一击"}:
            per_ten.setdefault(name, _number(item.get("item_value")))
    chart = raw.get("hexagon_chart")
    chart = chart if isinstance(chart, dict) else {}
    axes = {item.get("title"): item for item in _rows(chart.get("dimensions"))}
    result = []
    for axis, label in AXES.items():
        dimension = axes.get(axis, {})
        if label not in per_ten and not dimension:
            continue
        personal = per_ten.get(label)
        chart_value = _number(dimension.get("value"))
        median = _number(dimension.get("median"))
        consistent = (personal is not None and personal >= 0 and chart_value is not None
                      and chart_value >= 0 and math.isclose(personal, chart_value, rel_tol=0, abs_tol=0.011))
        reference = median if consistent and median is not None and median >= 0 else None
        delta = (personal / reference - 1) * 100 if reference is not None and reference > 0 else None
        status = ("comparable" if delta is not None else "zero_reference" if reference == 0
                  else "missing_per_ten_value" if personal is None else "unverified_reference")
        result.append({"hero": hero["name"], "hero_id": hero["hero_id"], "metric": "每10分钟" + axis,
                       "axis": axis, "unit": "伤害/10分钟" if axis == "伤害" else "治疗/10分钟" if axis == "治疗" else "次/10分钟",
                       "personal": personal if personal is not None and personal >= 0 else None,
                       "reference": reference, "reference_kind": "小程序同英雄、同模式、生涯中位数" if reference is not None else None,
                       "reference_is_demo": False, "same_scope": consistent and reference is not None,
                       "status": status, "relative_to_reference_pct": round(delta, 2) if delta is not None else None,
                       "display_delta": f"{delta:+.0f}%" if delta is not None else None})
    for label in ("阵亡", "单独消灭", "最后一击"):
        personal = per_ten.get(label)
        if personal is not None and personal >= 0:
            result.append({"hero": hero["name"], "hero_id": hero["hero_id"], "metric": "每10分钟" + label,
                           "axis": label, "unit": "次/10分钟", "personal": personal,
                           "reference": None, "reference_kind": None, "reference_is_demo": False,
                           "same_scope": False, "status": "no_benchmark", "relative_to_reference_pct": None,
                           "display_delta": None})
    return result


def _persona(dimensions, total, input_issues):
    d = dimensions
    complete = all(_complete(d[key]) for key in ("tactics", "mobility", "flank", "roles"))
    pool = d["concentration"]["title"]
    base = {"status": "ready", "chips": [pool], "rule_version": "career-personality-v1"}
    if not total:
        return {**base, "status": "empty", "title": "生涯画像待积累", "summary": "当前没有可用于时长加权的正时长英雄记录。",
                "quote": "下一场，也是新故事的开始。", "rule": "有效英雄时长为零", "chips": []}
    if not complete or input_issues:
        return {**base, "status": "incomplete_tags", "title": "生涯画像待补全", "summary": "部分英雄标签或记录尚不完整，先展示已知分布。",
                "quote": "还有一块拼图，等着被补上。", "rule": "核心维度需完整覆盖且无重复记录"}
    if total < MIN_PERSONA_HOURS:
        return {**base, "status": "low_sample", "title": "生涯画像积累中", "summary": "当前时长较少，先保留英雄偏好线索。",
                "quote": "多试几位英雄，看看自己喜欢哪种节奏。", "rule": f"正时长不足 {MIN_PERSONA_HOURS} 小时；这是产品展示阈值"}
    role = d["roles"]["pct_of_total"]
    tactics = d["tactics"]["value"]
    long_gun = d["weapon"]["value"].get("长枪")
    if role.get("支援", 0) >= 55:
        if d["mobility"]["value"] >= 60:
            title, summary, quote, chip = ("游走支援家", "你更常选择能快速转点、跟进与支援的英雄组合。", "队友走到哪里，支援就跟到哪里。", "机动支援")
            rule = "支援时长占比 ≥55%，机动工具倾向 ≥60"
        else:
            title, summary, quote, chip = ("后排守护者", "支援是你的生涯主场，英雄池更偏向治疗、保护与后排支援工具。", "有人向前，就有人守住身后。", "支援主场")
            rule = "支援时长占比 ≥55%，机动工具倾向 <60"
    elif (role.get("重装", 0) + role.get("支援", 0) >= 80
          and role.get("重装", 0) >= 25 and role.get("支援", 0) >= 25
          and _complete(d["team_utility"]) and d["team_utility"]["value"] >= 70):
        return {**base, "title": "战线支柱",
                "summary": "重装与支援占据你的大部分生涯时长，英雄池偏爱站场、保护与控制工具。",
                "quote": "前排我能顶，后排我也能守。",
                "rule": "重装与支援时长合计 ≥80%，各自 ≥25%；协同工具标签完整覆盖且倾向 ≥70。这些为产品规则。",
                "chips": ["重装×支援", "协同工具偏好", pool]}
    elif tactics["放狗"] >= 55 and d["mobility"]["value"] >= 65:
        if d["flank"]["value"] >= 60:
            title, summary, quote, chip = ("侧翼节奏猎手", "你的英雄池偏爱快速接近、换位和侧面施压的工具。", "正面有人顶，我去找另一条路。", "机动切入")
            rule = "放狗构成 ≥55%，机动倾向 ≥65，侧翼倾向 ≥60"
        else:
            title, summary, quote, chip = ("机动开路者", "你的英雄组合偏爱机动进入战场，为下一轮交战寻找机会。", "找准入口，再把节奏带起来。", "机动开团")
            rule = "放狗构成 ≥55%，机动倾向 ≥65，侧翼倾向 <60"
    elif tactics["地推"] >= 50:
        title, summary, quote, chip = ("阵线推进官", "你的英雄池更偏向近中距离接战、持续站场与正面推进。", "站住这一线，再向前一步。", "地推偏好")
        rule = "地推标签加权构成 ≥50%"
    elif (role.get("输出", 0) >= 55 and _complete(d["weapon"])
          and long_gun is not None and long_gun >= 55):
        title, summary, quote, chip = ("远点架枪手", "你在输出英雄中偏爱中远程枪线、精准枪械与火力工具。", "找个好角度，等机会进入准星。", "长枪偏好")
        rule = "输出时长占比 ≥55%，输出枪型完整覆盖，长枪占比 ≥55%"
    elif tactics["消耗"] >= 45:
        title, summary, quote, chip = ("空间压制者", "你的英雄池更偏爱距离、火力覆盖与持续施压的工具。", "先把空间拿下来，机会自然会出现。", "消耗偏好")
        rule = "消耗标签加权构成 ≥45%"
    else:
        title, summary, quote, chip = ("多面适配者", "你的英雄池横跨多种交战方式，没有一种工具倾向绝对主导。", "换一种英雄，也换一种解法。", "多面英雄池")
        rule = "完整样本未触发支援、放狗、地推、长枪或消耗主导规则"
    return {**base, "title": title, "summary": summary, "quote": quote, "rule": rule,
            "chips": [chip, pool]}


def _overlay(statistics, heroes, total):
    by_name = {hero["name"]: hero for hero in heroes}
    comparison_heroes = list(dict.fromkeys(row["hero"] for row in statistics
                                        if row["relative_to_reference_pct"] is not None))
    tags, evidence = [], []
    for name in comparison_heroes:
        if by_name[name]["hours"] < MIN_OVERLAY_HOURS:
            continue
        measured = {row["axis"]: row for row in statistics if row["hero"] == name
                    and row["relative_to_reference_pct"] is not None}
        for axes, label in ((("伤害", "消灭"), "火力活跃"), (("治疗", "助攻"), "支援活跃")):
            if label == "支援活跃" and by_name[name]["role"] != "支援":
                # Tank/damage healing may be self-healing, not support to teammates.
                continue
            selected = [measured.get(axis) for axis in axes]
            if all(row is not None and row["relative_to_reference_pct"] >= OVERLAY_DELTA for row in selected):
                tags.append({"hero": name, "label": label, "hours": by_name[name]["hours"]})
                evidence.extend(deepcopy(selected))
    covered = sum(by_name[name]["hours"] for name in comparison_heroes)
    return {"tags": tags, "heroes": comparison_heroes, "coverage_hours": covered,
            "coverage_pct": _pct(covered, total), "evidence": evidence,
            "rule": "同英雄每10分钟伤害与消灭均比中位数高至少10%；支援英雄也检查治疗与助攻。该英雄需有至少5小时。",
            "rule_note": "10%和5小时均为启发式展示阈值，不是经过验证的实力分档。",
            "scope_note": "只描述有可比数据的英雄，不外推全部生涯，也不改变主称号。",
            "reference_note": "参考为小程序返回的中位数；样本覆盖范围与段位构成未披露。"}


def analyze_career(heroes_raw, player, mode, *, catalog=None, notes=None):
    """Build a credential-free report. The caller supplies one mode's total records."""
    if mode not in MODE_NAMES:
        raise ValueError("Unsupported career-personality mode")
    if catalog is None:
        from .tags import load_catalog
        catalog = load_catalog()
    tag_map = catalog.get("heroes", {})
    lookup = {str(key).casefold(): value for key, value in tag_map.items()}
    for name, tag in tag_map.items():
        for key in [tag.get("hero_id"), tag.get("config_guid"), tag.get("slug"), *tag.get("aliases", [])]:
            if key:
                lookup[str(key).casefold()] = tag
    report_notes = list(notes or [])
    heroes, raw_by_name, excluded, seen = [], {}, [], set()
    input_issues = not isinstance(heroes_raw, list)
    if isinstance(heroes_raw, list) and len(_rows(heroes_raw)) != len(heroes_raw):
        input_issues = True
        excluded.append({"hero": None, "hero_id": None, "reason": "invalid_hero_rows"})
    for raw in _rows(heroes_raw):
        hero_id = str(raw.get("hero_id") or "").strip()
        raw_name = str(raw.get("hero_name") or hero_id).strip()
        tag = lookup.get(raw_name.casefold(), lookup.get(hero_id.casefold(), {}))
        name = str(tag.get("name") or raw_name)
        time_rows = [row for row in _rows(raw.get("simple_summary")) if row.get("item_name") == "游戏时间"]
        hours = _number(time_rows[0].get("item_value")) if time_rows else None
        unit = str(time_rows[0].get("item_unit") or "") if time_rows else ""
        if not name or hours is None or hours <= 0 or unit not in ("", "小时", "h", "H", "hour", "hours"):
            excluded.append({"hero": name, "hero_id": hero_id, "reason": "missing_or_nonpositive_hours" if not unit or unit in ("小时", "h", "H", "hour", "hours") else "unsupported_time_unit"})
            if not name or hours is None or hours < 0 or unit not in ("", "小时", "h", "H", "hour", "hours"):
                input_issues = True
            continue
        if name in seen:
            input_issues = True
            excluded.append({"hero": name, "hero_id": hero_id, "reason": "duplicate_record"})
            continue
        seen.add(name)
        source_role = str(raw.get("hero_role_type") or "")
        role = ROLE_NAMES.get(source_role)
        if not role and tag.get("role"):
            role = tag["role"]
            report_notes.append(f"{name}未返回可识别职责，职责暂按当前英雄配置补充。")
        mismatch = bool(role and tag.get("role") and role != tag["role"])
        if mismatch:
            report_notes.append(f"{name}的上游统计职责为{role}，当前标签配置为{tag['role']}；职责时长保留上游口径。")
        entry = {"name": name, "hero_id": hero_id, "hours": hours, "role": role,
                 "subrole": tag.get("subrole"), "role_mismatch": mismatch,
                 "source_role_type": source_role, "tag_role": tag.get("role"),
                 "tags": list(tag.get("labels", [])), "style": deepcopy(tag),
                 "icon_url": str(raw.get("icon_url") or ""), "tagged": bool(tag)}
        heroes.append(entry)
        raw_by_name[name] = raw
    heroes.sort(key=lambda hero: (-hero["hours"], hero["name"]))
    total = sum(hero["hours"] for hero in heroes)
    for hero in heroes:
        hero["percent_of_total"] = _pct(hero["hours"], total)
    dimensions = {"weapon": _weighted(heroes, "weapon", ["长枪", "短枪", "其他"], "输出"),
                  "tactics": _weighted(heroes, "tactics", ["放狗", "地推", "消耗"])}
    dimensions.update({key: _weighted(heroes, key) for key in ("mobility", "flank", "independence", "team_utility")})
    dimensions["roles"] = _distribution(heroes, "role", total)
    dimensions["subroles"] = _distribution(heroes, "subrole", total)
    top_one = _pct(heroes[0]["hours"], total) if heroes else None
    top_three_hours = sum(hero["hours"] for hero in heroes[:3])
    top_three = _pct(top_three_hours, total)
    pool = "暂无分布" if not total else "本命专精" if top_one >= 50 else "三核轮转" if top_three >= 70 else "广谱英雄池"
    dimensions["concentration"] = {"title": pool, "top_one_pct": top_one,
                                   "top_one_hero": heroes[0]["name"] if heroes else None,
                                   "top_three_hours": top_three_hours, "top_three_pct": top_three,
                                   "heroes": [hero["name"] for hero in heroes[:3]]}
    statistics = [row for hero in heroes for row in _statistics(raw_by_name[hero["name"]], hero)]
    if any(not hero["tagged"] for hero in heroes):
        report_notes.append("存在未标注英雄；它们保留在总时长中，各维度单独展示标签覆盖率。")
    if input_issues:
        report_notes.append("部分英雄记录缺失、重复或格式异常，未纳入累计；请核实上游数据后再生成组合称号。")
    report_notes.extend([
        "时长为小程序取整小时；零小时可能仍有少量游玩记录，本报告只按返回的正时长计算。",
        "当前英雄标签用于解释生涯累计偏好，不能还原历史版本中的英雄机制与阵容。",
        "打法构成是英雄标签按时长加权；机动、侧翼、自主和协同工具分不代表实际打法或玩家排名。",
        "当前标签按常规英雄机制维护；角斗领域的强化组合可能改变实际打法。" if mode.startswith("stadium") else "长短枪仅在输出英雄内计算，飞行物、光束与近战等归其他。",
        "统计只比较同英雄同模式累计口径的每10分钟数值；无基准、零基准或口径不能核对时不生成相对差异。",
        "描述游戏偏好，不推断现实性格；团队与独狼需要对局层面的配合证据。"])
    identity = ({key: player[key] for key in ("display_name", "bnet_id") if key in player}
                if isinstance(player, dict) else {"display_name": str(player)})
    return {"ok": True, "schema_version": 1, "is_demo": False, "data_source": "mini_program",
            "scope": "total", "mode": mode, "mode_label": MODE_NAMES[mode],
            "player": identity, "display_name": identity.get("display_name") or "玩家",
            "tag_version": catalog.get("version", "unknown"), "catalog_hero_count": len(tag_map),
            "time_unit": "取整小时", "total_hours": total, "hero_count": len(heroes),
            "heroes": heroes, "persona": _persona(dimensions, total, input_issues),
            "dimensions": dimensions, "statistics": statistics,
            "data_overlay": _overlay(statistics, heroes, total),
            "team_vs_solo": {"value": None, "status": "证据不足",
                             "explanation": "自主与协同工具偏好可以并存；累计数据无法识别实际集火、保护时机或脱离团队行为。"},
            "excluded": excluded, "notes": list(dict.fromkeys(report_notes))}
