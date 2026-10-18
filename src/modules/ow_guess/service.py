from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import random

from .catalog import OWGuessCatalog
from .render import render_stages
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
        mode = self.random.choice(("map_crop", "map_blur", "perk_icon_hero")) if value in ("", "随机", "random") else aliases.get(value)
        if not mode:
            raise ModuleError(error="ow_guess_invalid_type", message="猜一猜支持地图局部、地图模糊、威能猜英雄。", status_code=400)
        last_error = None
        for _ in range(3):
            entry = self.catalog.pick_perk_question() if mode == "perk_icon_hero" else self.catalog.pick_question()
            try:
                path = await self.catalog.resolve_media_path(entry)
                images, reveal = await asyncio.to_thread(render_stages, path, mode, self.random)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ModuleError(error="ow_guess_resources_unavailable", message="题目图片暂时无法加载，请稍后重试。", status_code=503) from last_error
        label = {"map_crop": "地图局部", "map_blur": "地图模糊", "perk_icon_hero": "威能猜英雄"}[mode]
        answer_hint = "提示：本题需回答完整的地图名＋小图名，不能只答主地图名。" if entry.get("requires_submap") else ""
        stages = [{"stage": i + 1, "at_seconds": i * 15, "replies": [{"type": "text", "data": f"{label} · 第{i + 1}/3张 · 剩余{45 - i * 15}秒" + (f"\n{answer_hint}" if answer_hint else "")}, img]} for i, img in enumerate(images)]
        prompt = "猜出地图名称，每15秒更新图片，共45秒。" + answer_hint
        if mode == "perk_icon_hero":
            prompt = "请根据威能图标猜出所属英雄，限时45秒。"
            stages = [{"stage": 1, "at_seconds": 0, "replies": [{"type": "text", "data": prompt}, images[0]]}]
        name = entry["name"].strip()
        return OWGuessOutput({
            "ok": True, "generated_at": datetime.now().isoformat(timespec="seconds"),
            "question_type": mode, "question_type_label": label,
            "question_id": str(entry.get("id") or entry.get("guid") or name),
            "recommended_wait_seconds": 45, "duration_seconds": 45, "stage_seconds": 15,
            "question": {"prompt_text": prompt, "media_kind": "image"},
            "answer": {"canonical": name, "aliases": entry.get("answer_aliases") or [name]},
            "replies": stages[0]["replies"], "stages": stages,
            "reveal_replies": [{"type": "text", "data": f"答案：{name}" + (f" · 威能：{entry['perk_name']}" if mode == "perk_icon_hero" else "")}, reveal],
        })


ow_guess_module = OWGuessModule()
