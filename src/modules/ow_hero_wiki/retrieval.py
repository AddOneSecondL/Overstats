"""Small, deterministic BM25 index over one hero's versioned wiki payload.

No embedding service is required. All notes are indexed, including mode-specific
notes; generated answers receive only retrieved evidence, never the entire page.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any, Mapping
from urllib.parse import quote

TERMS = {
    "冷却": "cooldown", "伤害": "damage", "治疗": "healing heal",
    "几次": "charges 充能次数", "几层": "charges 充能次数", "层数": "charges 充能次数", "充能": "charges",
    "持续": "duration", "射程": "range", "距离": "range distance",
    "弹药": "ammo", "装弹": "reload", "护甲": "armor", "护盾": "shield",
    "生命": "health hp", "大招": "ultimate 终极技能", "威能": "perk",
    "穿盾": "barrier", "爆头": "headshot critical", "无敌": "invulnerable",
}


def tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(len(run) - 1))
    return result


def build_chunks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = payload.get("source") or {}
    url = str(source.get("fandom_url") or "")
    chunks: list[dict[str, Any]] = []

    def add(title: str, text: str, section: str, card_index: int = -1, anchor: str = "", facts: Any = ()) -> None:
        # Keep sentences intact where possible, bounding individual evidence sizes.
        for offset in range(0, len(text), 1200):
            chunks.append({"title": title, "text": text[offset:offset + 1200],
                           "url": url + ("#" + quote(anchor.replace(" ", "_")) if anchor else ""),
                           "section": section, "card_index": card_index,
                           "facts": list(facts),
                           "page_hash": payload.get("_page_hash", "")})

    add("英雄概览", str(payload.get("overview") or ""), "overview")
    labels = {"health": "生命 health", "armor": "护甲 armor", "shield": "护盾 shield",
              "total_hp": "总生命 HP", "total_hp_6v6": "6v6 总生命",
              "minor_perk_xp": "次级威能经验", "major_perk_xp": "主要威能经验"}
    add("基础属性", "；".join(f"{label}：{payload['stats'][key]}" for key, label in labels.items()
                            if key in (payload.get("stats") or {})), "stats")
    for section in ("abilities", "perks"):
        for index, card in enumerate(payload.get(section) or []):
            title = str(card.get("name_cn") or card.get("name_en") or "未命名条目")
            heading = f"{title} / {card.get('name_en', '')} · {card.get('group_title_cn', '')}"
            lines = [str(card.get("description") or ""), str(card.get("description_en") or "")]
            lines.extend(f"{s.get('label', '')}：{s.get('value', '')}" for s in card.get("stats") or [])
            lines.extend(str(t) for t in card.get("tags") or [])
            add(heading, "\n".join(lines), section, index, str(card.get("name_en") or ""), card.get("stats") or [])
            for key, label in (("notes", "机制说明"), ("mode_notes", "6v6 模式说明")):
                for note in card.get(key) or []:
                    add(heading + " · " + label, str(note), section, index, str(card.get("name_en") or ""))
    return chunks


def retrieve(payload: Mapping[str, Any], question: str, limit: int = 5) -> list[dict[str, Any]]:
    query = question
    for name in (payload.get("hero_cn"), payload.get("hero_en")):
        if name:
            query = re.sub(re.escape(str(name)), " ", query, flags=re.I)
    expanded = query + " " + " ".join(value for key, value in TERMS.items() if key in query)
    terms = set(tokens(expanded))
    chunks = build_chunks(payload)
    named = []
    for section in ("abilities", "perks"):
        for index, card in enumerate(payload.get(section) or []):
            for key in ("name_cn", "name_en"):
                name = str(card.get(key) or "").strip()
                if name and name.lower() in query.lower():
                    named.append((name, section, index))
    if named:
        # Keep explicitly requested cards, avoiding a short name matching a perk
        # whose longer full name was requested instead.
        selected = {(s, i) for name, s, i in named
                    if not any(name.lower() != other.lower() and name.lower() in other.lower() for other, _, _ in named)}
        chunks = [c for c in chunks if (c["section"], c["card_index"]) in selected]
    documents = [Counter(tokens(c["title"] + " " + c["text"] + " " +
                                " ".join(str(f.get("key") or "") for f in c.get("facts", [])))) for c in chunks]
    average = sum(sum(d.values()) for d in documents) / max(1, len(documents))
    frequencies = Counter(t for d in documents for t in d)
    ranked = []
    for chunk, document in zip(chunks, documents):
        score = 0.0
        for term in terms & document.keys():
            tf = document[term]
            idf = math.log(1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(document.values()) / max(1, average)))
        if score > 0:
            if named and "机制说明" not in chunk["title"] and "模式说明" not in chunk["title"]:
                score += 4
            ranked.append(dict(chunk, score=round(score, 4)))
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return [dict(item, id=i + 1) for i, item in enumerate(ranked[:max(0, limit)])]


def evidence_context(hits: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"[{h['id']}] {h['title']}\n{h['text']}\n来源：{h['url']}" for h in hits)


def extractive_answer(hits: list[dict[str, Any]], question: str = "") -> str:
    if not hits:
        return "当前资料不足以回答这个问题。请补充技能名或要查询的数值、机制。"
    expanded = question + " " + " ".join(value for key, value in TERMS.items() if key in question)
    query_terms = set(tokens(expanded))
    facts = []
    # An explicitly requested parameter can be displayed verbatim without an LLM.
    # Mode-specific queries need the full evidence to retain their conditions.
    if not re.search(r"6\s*v\s*6|pve|合作|模式|改动|版本", question, re.I):
        for hit in hits:
            selected = [f"{f['label']}：{f.get('value', '')}" for f in hit.get("facts", [])
                        if query_terms & set(tokens(str(f.get("label") or "") + " " + str(f.get("key") or "")))]
            if selected:
                facts.append(f"{hit['title']} [{hit['id']}]\n" + "\n".join(selected))
    if facts:
        return "相关参数（资料摘录）：\n\n" + "\n\n".join(facts)
    return "以下为检索到的资料片段，尚未生成归纳回答：\n\n" + "\n\n".join(
        f"[{h['id']}] {h['title']}\n{h['text']}" for h in hits[:3])
