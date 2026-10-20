"""Lossless, ordered extraction of patch-body text using the standard HTML parser.

Legacy arrays remain available to the existing translation and API consumers.
`order` contains references into those arrays, never duplicate translatable text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def has(self, name):
        return name in self.attrs.get("class", "").split()


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        # Real patch pages occasionally omit optional closing p/li tags.
        if tag in {"p", "li"} and self.stack[-1].tag == tag:
            self.stack.pop()
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr", "meta", "link", "input", "source", "wbr", "area", "embed"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def lines(node, skip=(), exclude=()):
    """Consume each text node once, including mixed paragraphs/nested lists."""
    result, buffer = [], []
    excluded = {id(item) for item in exclude if item is not None}

    def flush():
        value = clean("".join(buffer))
        if value:
            result.append(value)
        buffer.clear()

    def walk(item):
        if isinstance(item, str):
            buffer.append(item)
            return
        if id(item) in excluded or item.tag in {"script", "style", "noscript"} or any(item.has(key) for key in skip):
            return
        boundary = item.tag in {"p", "li", "div", "br", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
        if boundary:
            flush()
        for child in item.children:
            walk(child)
        if boundary:
            flush()

    walk(node)
    flush()
    return result


def first(node, class_name):
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.has(class_name):
            return child
        # A parent's heading must not be borrowed from a nested section.
        if child.has("PatchNotes-section"):
            continue
        found = first(child, class_name)
        if found:
            return found
    return None


def text(node, class_name):
    found = first(node, class_name)
    return " ".join(lines(found)) if found else ""


def icon(node, class_name):
    found = first(node, class_name)
    value = found.attrs.get("src", "") if found else ""
    return "https:" + value if value.startswith("//") else value


def hero(node, title):
    value = {
        "name": text(node, "PatchNotesHeroUpdate-name") or "英雄改动",
        "icon_url": icon(node, "PatchNotesHeroUpdate-icon"),
        "group_title": title, "general_changes": [], "abilities": [],
        "dev_note": "", "order": [],
    }
    pending = []

    def flush():
        for line in lines(Node("div", children=pending)):
            value["order"].append({"kind": "general", "index": len(value["general_changes"])})
            value["general_changes"].append(line)
        pending.clear()

    def visit(item):
        if isinstance(item, str):
            pending.append(item)
        elif item.has("PatchNotesHeroUpdate-name") or item.has("PatchNotesHeroUpdate-icon"):
            return
        elif item.has("PatchNotesAbilityUpdate"):
            flush()
            ability = {
                "name": text(item, "PatchNotesAbilityUpdate-name") or "技能调整",
                "icon_url": icon(item, "PatchNotesAbilityUpdate-icon"),
                "changes": lines(item, ("PatchNotesAbilityUpdate-name", "PatchNotesAbilityUpdate-icon")),
            }
            value["order"].append({"kind": "ability", "index": len(value["abilities"])})
            value["abilities"].append(ability)
        elif item.has("PatchNotesHeroUpdate-dev"):
            flush()
            note = " ".join(lines(item))
            if note:
                if not value["dev_note"]:
                    value["dev_note"] = note
                    value["order"].append({"kind": "dev", "index": 0})
                else:
                    value["order"].append({"kind": "note", "index": len(value["general_changes"])})
                    value["general_changes"].append("开发者说明：" + note)
        elif any(isinstance(child, Node) and (
            child.has("PatchNotesAbilityUpdate") or child.has("PatchNotesHeroUpdate-dev")
            or child.has("PatchNotesHeroUpdate-name") or child.has("PatchNotesHeroUpdate-icon")
        ) for child in item.children) or item.tag not in {"p", "li"}:
            for child in item.children:
                visit(child)
        else:
            pending.append(item)

    for child in node.children:
        visit(child)
    flush()
    return value


def general(node, title):
    header = first(node, "PatchNotesGeneralUpdate-title")
    images = []

    def collect(item):
        if isinstance(item, Node):
            if item.tag == "img" and item.attrs.get("src"):
                url = item.attrs["src"]
                images.append("https:" + url if url.startswith("//") else url)
            for child in item.children:
                collect(child)

    collect(node)
    return {
        "title": text(node, "PatchNotesGeneralUpdate-title") or title,
        # Only the actual heading is consumed. CN uses this CSS class on
        # nested headings and even li body text; class-wide exclusion loses it.
        "paragraphs": lines(node, exclude=(header,)),
        "bullets": [], "dev_note": "", "images": images,
    }


def map_update(node, title):
    images = {}

    def walk(item):
        if isinstance(item, Node):
            slot = item.attrs.get("slot")
            if slot in {"before", "after"}:
                url = item.attrs.get("src", "")
                images[slot] = "https:" + url if url.startswith("//") else url
            for child in item.children:
                walk(child)

    walk(node)
    return {
        "name": text(node, "PatchNotesMapUpdate-name") or title,
        "paragraphs": lines(node, ("PatchNotesMapUpdate-name",)),
        "bullets": [], "comparison_label": "",
        "before_image_url": images.get("before", ""),
        "after_image_url": images.get("after", ""),
    }


def parse_sections(source):
    root = Document(source).root
    sections = []

    def emit(path, kind, value):
        title = " / ".join(path) or "补丁说明"
        if not sections or sections[-1]["title"] != title:
            sections.append({
                "type": "mixed", "title": title, "intro": [],
                "hero_updates": [], "map_updates": [], "general_updates": [], "order": [],
            })
        section = sections[-1]
        key = {"hero": "hero_updates", "map": "map_updates", "general": "general_updates"}[kind]
        section["order"].append({"kind": kind, "index": len(section[key])})
        section[key].append(value)

    def visit(container, path):
        pending = []
        active_group = []

        def flush():
            value = general(Node("div", children=list(pending)), "")
            pending.clear()
            if value["paragraphs"] or value["images"] or value["title"]:
                emit(path, "general", value)

        def walk(item):
            nonlocal active_group
            if isinstance(item, str):
                pending.append(item)
                return
            if item.tag in {"script", "style", "noscript"} or any(item.has(key) for key in (
                "PatchNotes-sectionTitle", "PatchNotes-patchTitle", "PatchNotes-date", "PatchNotesTop",
            )):
                return
            if item.has("PatchNotes-section"):
                flush()
                name = text(item, "PatchNotes-sectionTitle")
                normalized = name.strip().lower()
                groups = {"英雄更新", "hero updates", "角斗领域更新", "stadium updates",
                          "6v6更新", "6v6 更新", "6v6 updates"}
                roles = {"重装", "输出", "支援", "tank", "damage", "support",
                         "英雄重做", "hero reworks", "英雄判定体积", "hero hitbox updates"}
                if normalized in groups:
                    active_group = [name]
                    child_path = path + [name]
                elif normalized in roles:
                    child_path = path + active_group + [name]
                else:
                    active_group = []
                    child_path = path + ([name] if name else [])
                before = sum(len(section["order"]) for section in sections)
                visit(item, child_path)
                if name and sum(len(section["order"]) for section in sections) == before:
                    # Some official pages encode a mode boundary as an empty section.
                    emit(child_path, "general", {"title": name, "paragraphs": [], "bullets": [], "images": []})
            elif item.has("PatchNotesHeroUpdate"):
                flush()
                emit(path, "hero", hero(item, " / ".join(path)))
            elif item.has("PatchNotesMapUpdate"):
                flush()
                emit(path, "map", map_update(item, " / ".join(path)))
            elif item.has("PatchNotesGeneralUpdate"):
                flush()
                emit(path, "general", general(item, ""))
            elif item.tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
                pending.append(item)
            else:
                # Preserve boundaries while looking through unknown wrappers.
                flush()
                for child in item.children:
                    walk(child)
                flush()

        for child in container.children:
            walk(child)
        flush()

    visit(root, [])
    return sections


def raw_text(source):
    return "\n".join(lines(Document(source).root, ("PatchNotesTop",)))


def iter_entries(section):
    arrays = {"hero": "hero_updates", "map": "map_updates", "general": "general_updates"}
    if section.get("order"):
        for item in section["order"]:
            yield item["kind"], section[arrays[item["kind"]]][item["index"]]
    else:
        if section.get("intro"):
            yield "general", {"paragraphs": section["intro"]}
        for kind, key in arrays.items():
            for item in section.get(key) or []:
                yield kind, item
