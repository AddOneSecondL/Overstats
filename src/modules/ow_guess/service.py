from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime
import random

from .catalog import OWGuessCatalog
from .render import render_stages, LABELS
from ..errors import ModuleError


@dataclass(frozen=True)
class OWGuessQuery:
    question_type: str = ""


@dataclass(frozen=True)
class OWGuessOutput:
    payload: dict

    def to_dict(self):
        return self.payload


class OWGuessModule:
    def __init__(self, *, catalog=None, random_source=None):
        self.random = random_source or random.Random()
        self.catalog = catalog or OWGuessCatalog(random_source=self.random)

    async def query_guess_replies(self, query):
        value = query.question_type.strip().lower()
        aliases = {"map_image": "map_crop", "5": "map_crop", "1": "map_crop", "局部": "map_crop", "地图": "map_crop", "地图图片": "map_crop", "局部模式": "map_crop", "map_crop": "map_crop", "2": "map_blur", "模糊": "map_blur", "模糊模式": "map_blur", "map_blur": "map_blur"}
        aliases.update({key: "perk_icon_hero" for key in ("威能", "威能猜英雄", "威能图标", "perk_icon_hero", "3", "4")})
        for key, names in {
            "hero_crop": ("头像", "英雄头像", "头像猜英雄", "6"),
            "hero_description": ("英雄描述", "描述猜英雄", "英雄描述猜英雄", "7"),
            "skill_description_hero": ("技能描述", "技能猜英雄", "技能描述猜英雄", "8"),
            "skill_description_name": ("技能名", "技能描述猜技能", "技能描述猜技能名", "9"),
            "hero_color": ("颜色", "代表色", "英雄代表色", "颜色猜英雄", "10"),
        }.items():
            aliases.update({name: key for name in (*names, key)})
        aliases.update({"地图局部": "map_crop", "地图模糊": "map_blur", "威能图标猜英雄": "perk_icon_hero"})
        from .packs import questions
        music_questions = await asyncio.to_thread(questions, "map_music")
        aliases.update({key: "map_music" for key in ("音乐", "地图音乐", "听歌猜地图", "map_music")})
        available = tuple(LABELS) + (("map_music",) if music_questions else ())
        mode = self.random.choice(available) if value in ("", "随机", "random") else aliases.get(value)
        if mode == "map_music":
            if not music_questions:
                raise ModuleError(error="ow_guess_pack_missing", message="未安装地图音乐扩展包，请在服务器执行 python -m src.modules.ow_guess.packs install map-music。", status_code=400)
            entry = self.random.choice(music_questions)
            data = await asyncio.to_thread(entry["media_path"].read_bytes)
            map_names = entry.get("maps") or [entry["answers"][0]]
            answer_name = " / ".join(map_names)
            answer_text = "答案：" + answer_name + ("\n以上地图共用此主题，任意一张均算正确。" if len(map_names) > 1 else "")
            prompt = "地图音乐猜地图：听音频回复地图名称，限时45秒。"
            replies = [{"type": "text", "data": prompt}, {"type": "audio", "media_type": "audio/mpeg",
                       "filename": "question.mp3", "base64": base64.b64encode(data).decode("ascii")}]
            return OWGuessOutput({
                "ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"),
                "question_type": mode, "question_type_label": "地图音乐猜地图", "question_id": entry["id"],
                "recommended_wait_seconds": 45, "duration_seconds": 45, "stage_seconds": 0,
                "question": {"prompt_text": prompt, "media_kind": "audio"},
                "answer": {"canonical": answer_name, "aliases": entry["answers"]},
                "replies": replies, "stages": [{"stage": 1, "at_seconds": 0, "replies": replies}],
                "reveal_replies": [{"type": "text", "data": answer_text}],
            })
        if not mode:
            raise ModuleError(error="ow_guess_invalid_type", message="猜一猜支持地图局部、地图模糊、威能、头像、英雄描述、技能猜英雄、技能名和代表色。", status_code=400)
        text_only = mode in {"hero_description", "skill_description_hero", "skill_description_name"}
        last_error = None
        for _ in range(3):
            if mode == "perk_icon_hero":
                entry = self.catalog.pick_perk_question()
            elif mode.startswith("map_"):
                entry = self.catalog.pick_question()
            else:
                entry = self.catalog.pick_hero_question(mode)
            if text_only:
                images, reveal = [], None
                break
            try:
                path = await self.catalog.resolve_media_path(entry) if entry.get("icon") else None
                images, reveal = await asyncio.to_thread(render_stages, path, mode, self.random, entry)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ModuleError(error="ow_guess_resources_unavailable", message="题目图片暂时无法加载，请稍后重试。", status_code=503) from last_error
        label = LABELS[mode]
        answer_hint = "提示：本题需回答完整的地图名＋小图名，不能只答主地图名。" if entry.get("requires_submap") else ""
        stages = [{"stage": i + 1, "at_seconds": i * 15, "replies": [{"type": "text", "data": f"{label} · 第{i + 1}/3张 · 剩余{45 - i * 15}秒" + (f"\n{answer_hint}" if answer_hint else "")}, img]} for i, img in enumerate(images)]
        target = "地图名称" if mode.startswith("map_") else "技能名" if mode == "skill_description_name" else "英雄名"
        prompt = f"{label}：请回复{target}，限时45秒。" + answer_hint
        if len(images) == 1:
            stages = [{"stage": 1, "at_seconds": 0, "replies": [{"type": "text", "data": prompt}, images[0]]}]
        if text_only:
            clues = entry["clues"] if mode == "hero_description" else [entry["clue"]]
            stages = [{"stage": i + 1, "at_seconds": i * 15, "replies": [{
                "type": "text", "data": (
                    f"{label} · 提示 {i + 1}/{len(clues)} · 剩余 {45 - i * 15} 秒\n{clue}"
                    if len(clues) > 1 else prompt + "\n\n" + clue
                )}]} for i, clue in enumerate(clues)]
            prompt = stages[0]["replies"][0]["data"]
        name = entry["name"].strip()
        answer_text = f"答案：{name}"
        if mode == "perk_icon_hero":
            answer_text += f"\n威能：{entry['perk_name']}\n{entry.get('perk_description') or '暂无描述'}"
        elif entry.get("skill_name"):
            answer_text += f"\n{entry['hero_name']} · {entry['skill_name']}\n{entry['description']}"
        elif mode == "hero_description":
            answer_text += "\n" + entry["description"]
        elif mode == "hero_color" and len(entry.get("names", [])) > 1:
            answer_text += "\n以上任意一位均算正确。"
        reveal_replies = [{"type": "text", "data": answer_text}]
        if mode in {"map_crop", "map_blur", "hero_crop"}:
            reveal_replies.append(reveal)
        return OWGuessOutput({
            "ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"),
            "question_type": mode, "question_type_label": label,
            "question_id": str(entry.get("id") or entry.get("guid") or name),
            "recommended_wait_seconds": 45, "duration_seconds": 45, "stage_seconds": 15 if len(stages) > 1 else 0,
            "question": {"prompt_text": prompt, "media_kind": "text" if text_only else "image"},
            "answer": {"canonical": name, "aliases": entry.get("answer_aliases") or [name]},
            "replies": stages[0]["replies"], "stages": stages,
            "reveal_replies": reveal_replies,
        })


ow_guess_module = OWGuessModule()
