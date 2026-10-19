from __future__ import annotations

import html
import hashlib
from pathlib import Path
import random
import re
import tempfile

import httpx

from ..query_tool import read_query_tool, get_cached_asset_path
from ..errors import ModuleError
from ...constants import iter_hero_alias_pairs


EXCLUDED_MAP_MARKERS = (
    "地图工坊", "英雄精通", "vppgreenroom", "怪鼠复仇", "教学模式", "高架车站",
    "workshop", "heromastery", "junkenstein", "tutorial",
)


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]*>|\{[^}]*\}", "", value)
    value = re.sub(r"%\d+\$s", "对应按键", value)
    return re.sub(r"\s+", " ", value).strip()


def hero_aliases(name):
    return list(dict.fromkeys([name] + [a for a, canonical in iter_hero_alias_pairs() if canonical == name]))


def hide_names(text, names):
    for name in sorted(set(names), key=len, reverse=True):
        if name:
            text = re.sub(re.escape(name), "■■", text, flags=re.I)
    return text


def is_excluded_map(item):
    values = (str(item.get(key) or "") for key in ("name", "mode"))
    return any(marker in re.sub(r"[\s_-]+", "", value).casefold()
               for value in values for marker in EXCLUDED_MAP_MARKERS)


def simplify_map_name(name):
    return re.sub(r"\s*[-‐‑–—－]\s*", "", str(name or "")).strip()


class OWGuessCatalog:
    """Internal questions are derived directly from the resource configuration."""

    def __init__(self, *, random_source=None):
        self.random = random_source or random.Random()

    def pick_question(self):
        payload = read_query_tool(default={})
        entries = {}
        control_names = {
            simplify_map_name(item.get("name"))
            for item in payload.get("mapList", [])
            if isinstance(item, dict) and item.get("mode") == "占领要点"
            and not is_excluded_map(item) and item.get("name")
        }
        for item in payload.get("mapList", []):
            if not isinstance(item, dict) or is_excluded_map(item):
                continue
            original_name = str(item.get("name") or "").strip()
            name = simplify_map_name(original_name)
            url = str(item.get("icon") or "").strip()
            if name and url.startswith("https://"):
                entries[(name, url)] = {**item, "name": name, "answer_aliases": list(dict.fromkeys((name, original_name))),
                    "requires_submap": item.get("mode") == "占领要点" and any(
                        parent != name and parent in name for parent in control_names
                    )}
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="地图题库暂无可用图片，请更新资源配置。", status_code=503)
        return self.random.choice(list(entries.values()))

    def pick_perk_question(self):
        payload = read_query_tool(default={})
        heroes = {str(h.get("id")): h.get("name") for h in payload.get("heroList", []) if h.get("name")}
        by_icon = {}
        for hero_id, perks in payload.get("heroPerkList", {}).items():
            hero = heroes.get(str(hero_id))
            if not hero:
                continue
            for perk in perks:
                url = str(perk.get("icon") or "").strip()
                title = html.unescape(re.split(r"<br\s*/?>", str(perk.get("name") or ""), flags=re.I)[0]).strip()
                if not url.startswith("https://") or not title or "[PH]" in title:
                    continue
                parts = re.split(r"<br\s*/?>", str(perk.get("name") or ""), maxsplit=1, flags=re.I)
                description = clean_text(perk.get("description") or perk.get("desc") or (parts[1] if len(parts) > 1 else ""))
                by_icon.setdefault(url, []).append((hero, title, perk.get("id"), description))
        entries = []
        aliases = iter_hero_alias_pairs()
        for url, owners in by_icon.items():
            if len({row[0] for row in owners}) != 1:
                continue
            hero, title, perk_id, description = owners[0]
            entries.append({"name": hero, "icon": url, "id": perk_id,
                            "perk_name": title, "perk_description": description,
                            "answer_aliases": list(dict.fromkeys([hero] + [a for a, canonical in aliases if canonical == hero]))})
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="威能题库暂无可用图标，请更新资源配置。", status_code=503)
        return self.random.choice(entries)

    def hero_questions(self, mode):
        payload = read_query_tool(default={})
        heroes = [h for h in payload.get("heroConfig", {}).values() if h.get("IsHero") and h.get("Name")]
        portraits = {h["name"]: h for h in payload.get("heroList", []) if h.get("name")}
        names = [a for h in heroes for a in hero_aliases(h["Name"]) if len(a) > 1]
        entries = []
        for hero in heroes:
            name = hero["Name"]
            base = {"name": name, "hero_name": name, "id": hero.get("GUID"), "answer_aliases": hero_aliases(name)}
            if mode == "hero_crop":
                portrait = portraits.get(name, {})
                url = portrait.get("smallIconUrl") or portrait.get("icon")
                if url and url.startswith("https://"):
                    entries.append({**base, "icon": url})
            elif mode == "hero_description":
                description = clean_text(hero.get("Description") or hero.get("Official", {}).get("Description"))
                official = hero.get("Official", {})
                role = {"Tank": "重装", "Damage": "输出", "Support": "支援"}.get(hero.get("Class"), "")
                fields = [("职责", role), ("出现过的地点", clean_text(official.get("Location"))),
                          ("生日", clean_text(official.get("Birthday"))), ("人物简介", description)]
                clues = [f"TA的{label}：{hide_names(value, names)}" for label, value in fields
                         if value and value not in {"未知", "不详", "暂无", "未知。"}]
                if len(description) >= 20 and len(clues) >= 3:
                    entries.append({**base, "clue": hide_names(description, names),
                                    "clues": clues, "description": description})
            elif mode == "hero_color":
                color = hero.get("Color", "")
                if re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", color):
                    entries.append({**base, "color": color[:7].upper()})
            else:
                for skill in hero.get("Loadouts", []):
                    title, description = clean_text(skill.get("Name")), clean_text(skill.get("Description"))
                    if skill.get("Category") not in {"Ability", "UltimateAbility", "PassiveAbility", "Weapon"}:
                        continue
                    if not title or len(description) < 10 or any(s in title + description for s in ("职责", "[PH]", "TODO", "未使用", "占位", "英雄数据", "对应按键")):
                        continue
                    if title in {"快速近身攻击", "近身攻击", "装填", "装弹", "切换武器", "蹲下", "跳跃", "互动", "取消"}:
                        continue
                    answers = [title]
                    short = re.sub(r"[（(].*?[）)]", "", title).strip()
                    if short and short != title:
                        answers.append(short)
                    clue = hide_names(description, names + answers)
                    if len(re.sub(r"[■\W]", "", clue)) < 10:
                        continue
                    entries.append({**base, "id": skill.get("GUID"), "skill_name": title,
                                    "name": title if mode == "skill_description_name" else name,
                                    "answer_aliases": answers if mode == "skill_description_name" else base["answer_aliases"],
                                    "clue": clue, "description": description})
        if mode == "hero_color":
            groups = {}
            for entry in entries:
                group = groups.setdefault(entry["color"], {**entry, "names": [], "answer_aliases": []})
                group["names"].append(entry["name"])
                group["answer_aliases"].extend(entry["answer_aliases"])
            for color, group in groups.items():
                group["name"] = " / ".join(group["names"])
                group["id"] = color
                group["answer_aliases"] = list(dict.fromkeys(group["answer_aliases"]))
            return list(groups.values())
        # An identical clue must not require choosing between different answers.
        owners = {}
        for entry in entries:
            key = entry.get("clue") or entry.get("color") or entry.get("icon")
            owners.setdefault(key, set()).add(entry["name"])
        return [entry for entry in entries if len(owners[entry.get("clue") or entry.get("color") or entry.get("icon")]) == 1]

    def pick_hero_question(self, mode):
        entries = self.hero_questions(mode)
        if not entries:
            raise ModuleError(error="ow_guess_resources_unavailable", message="该题型暂无可用资源，请更新资源配置。", status_code=503)
        entry = self.random.choice(entries)
        if mode == "hero_description":
            entry = {**entry, "clues": self.random.sample(entry["clues"], 3)}
        return entry

    async def resolve_media_path(self, entry):
        url = entry["icon"]
        for category in ("heroes", "perk", "maps"):
            cached = get_cached_asset_path(url, category)
            if cached:
                return cached
        directory = Path(tempfile.gettempdir()) / "overstats-map-guess"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (hashlib.sha256(url.encode()).hexdigest() + ".img")
        if target.exists():
            return target
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(response.content)
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
