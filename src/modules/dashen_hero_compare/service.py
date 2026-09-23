from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Optional
from ...constants import iter_hero_alias_pairs
from ..errors import ModuleError
from .metrics import collect_metrics, attach_references
from ..query_tool import load_query_tool
from ..dashen_profile.requests import DashenProfileBundle, get_live_dashen_season
from ..dashen_hero_treemap.requests import DashenHeroTreemapQuery, normalize_treemap_mode, is_quick
from ..dashen_hero_treemap.service import DashenHeroTreemapModule, _prefetch_hero_icons
from ..dashen_hero_treemap.engine import DashenHeroTreemapEngine, cloud_summary

@dataclass(frozen=True)
class DashenHeroCompareQuery:
    player1: str
    player2: str
    hero: str = ""
    mode: str = "quick"
    season: Optional[int] = None

@dataclass(frozen=True)
class CompareOutput:
    data: dict
    image: object = None
    def to_dict(self):return self.data

class DashenHeroCompareModule:
    def __init__(self, api_client=None, search_module=None, config_loader=None):
        self.resolver=DashenHeroTreemapModule(api_client=api_client,search_module=search_module)
        self.client=self.resolver.requests.api_client
        self.config_loader=config_loader or load_query_tool

    async def query_compare(self, query, *, render=False):
        try:
            mode=normalize_treemap_mode(query.mode)
        except ValueError as exc:
            raise ModuleError(error="invalid_compare_mode",message=str(exc),status_code=400) from exc
        if not query.player1.strip() or not query.player2.strip():
            raise ModuleError(error="missing_players",message="需要两名玩家。",status_code=400)
        config=self.config_loader()
        selected=None
        if query.hero.strip():
            text=query.hero.strip().casefold()
            aliases={str(a).casefold():str(b).casefold() for a,b in iter_hero_alias_pairs()}
            text=aliases.get(text,text)
            selected=next((h for h in config.get("heroList",[]) if text in {str(h.get(k) or "").casefold() for k in ("name","heroGuid","id","heroId")}),None)
            if selected is None:
                raise ModuleError(error="unknown_hero",message=f"无法识别英雄：{query.hero}",status_code=400)
        start=int(query.season if query.season is not None else get_live_dashen_season())
        if start<1:raise ModuleError(error="invalid_season",message="赛季必须大于0。",status_code=400)
        engine=DashenHeroTreemapEngine(config_loader=lambda:config)
        async def player(target):
            prefix,_,token=target.partition(":")
            q=DashenHeroTreemapQuery(customer_token=token if prefix.lower() in ("token","ctoken") else "",bnet_id=target,mode=mode)
            resolved,identity=await self.resolver._resolve_query(q)
            card=await self.client.query_card(resolved.customer_token)
            if card.get("code",0)!=0:
                raise ModuleError(error="upstream_error",message="读取玩家资料失败。",status_code=502)
            tried=[]
            for season in range(start,max(0,start-4),-1):
                tried.append(season)
                raw=await self.client.query_count_info(resolved.customer_token,"leisure" if is_quick(mode) else "sport",season=None if season==get_live_dashen_season() else season)
                if raw.get("code",0)!=0:
                    raise ModuleError(error="upstream_error",message="读取英雄统计失败，请稍后重试。",status_code=502)
                rows=engine._resolve_hero_payload_rows(raw.get("data") or {},mode=mode)
                if selected:
                    rows=[r for r in rows if str(r.get("heroGuid") or r.get("heroId"))==str(selected.get("heroGuid") or selected.get("heroId"))]
                if not any(float(r.get("gameTime") or 0)>0 for r in rows):continue
                # Supply filtered rows without altering upstream response or mixing queues.
                from ..dashen_hero_treemap.requests import hero_queue_keys
                payload={"data":{hero_queue_keys(mode)[0]:rows}}
                bundle=DashenProfileBundle(resolved.customer_token,card,payload,payload,season,season)
                p,_,heroes=engine.build_output(bundle,mode=mode,resolved_name=identity.full_id if identity else target)
                summary=("指定英雄 · "+str(selected.get("name"))) if selected else cloud_summary(heroes)
                total_time=sum(h.game_time_sec for h in heroes)
                heroes=heroes[:1 if selected else 3]
                hero_data=[]
                for h in heroes:
                    item=h.to_dict()
                    source=next(r for r in rows if str(r.get("heroGuid") or r.get("heroId"))==h.hero_guid)
                    item["metrics"]=collect_metrics(source,item,config)
                    hero_data.append(item)
                return dict(player=p.to_dict(),season=season,total_game_time_sec=total_time,searched_seasons=tried,summary=summary,heroes=hero_data),heroes
            name=(card.get("data") or {}).get("name") or target
            return dict(player={"display_name":name},season=None,searched_seasons=tried,summary="暂无可用记录",heroes=[]),()
        sides=await asyncio.gather(player(query.player1),player(query.player2))
        data=dict(ok=True,mode=mode,hero=selected.get("name") if selected else None,selection="specified_hero" if selected else "top3",start_season=start,players=[s[0] for s in sides])
        await attach_references(data)
        image=None
        if render:
            await _prefetch_hero_icons([h for _,heroes in sides for h in heroes])
            from .render import render_compare
            image=render_compare(data)
        return CompareOutput(data,image)

dashen_hero_compare_module=DashenHeroCompareModule()
