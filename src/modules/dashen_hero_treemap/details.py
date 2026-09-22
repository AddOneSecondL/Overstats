"""Optional personal perk selections from the selected mode's recent matches."""
import asyncio
from collections import Counter, defaultdict
from dataclasses import replace
import re
from .requests import is_quick


def guid(value):
    text=str(value or "")
    try:
        return str(int(text,16) if text.lower().startswith("0x") else int(text))
    except ValueError:
        return text


def perk_metadata(config):
    result={}
    groups=[config.get("perkList", [])]
    raw=config.get("heroPerkList", {})
    groups.extend(raw.values() if isinstance(raw,dict) else [])
    for rows in groups:
        for row in rows if isinstance(rows,list) else []:
            for key in ("id","guid"):
                if row.get(key):result[guid(row[key])]=row
    return result


async def enrich_recent_perks(heroes, bundle, mode, client, config):
    if client is None:
        return heroes
    # Fetch exactly two pages for this season/mode before choosing the top-three matches.
    top_heroes={guid(h.hero_guid) for h in sorted(heroes,key=lambda h:-h.game_time_sec)[:3]}
    expected={"quickpreset", "quickplay", "leisurepreset"} if is_quick(mode) else {"sportpreset", "competitive"}
    if mode.endswith("6v6"):
        expected={"quickv6", "leisurev6"} if is_quick(mode) else {"sportv6"}
    async def page(number):
        try:
            payload=await asyncio.wait_for(client.query_match_list(bundle.customer_token,"leisure" if is_quick(mode) else "sport",page=number,season=bundle.request_season),timeout=10)
            if payload.get("code",0)!=0:return []
            raw=payload.get("data") or []
            if isinstance(raw,dict):raw=raw.get("matchList") or raw.get("recentMatchList") or []
            return raw if isinstance(raw,list) else []
        except Exception:
            return []
    pages=await asyncio.gather(page(1),page(2))
    rows=[row for batch in pages for row in batch if isinstance(row,dict)]
    def used_heroes(row):
        return {guid(row.get("heroGuid"))} | {guid(h.get("heroGuid")) for h in row.get("heroList",[]) or [] if isinstance(h,dict)}
    ids=list(dict.fromkeys(str(r["matchId"]) for r in rows if r.get("matchId") and str(r.get("gameMode", "")).lower() in expected and used_heroes(r)&top_heroes))
    if not ids:
        return heroes
    target=str((bundle.profile_card.get("data") or {}).get("bnetId") or "")
    semaphore=asyncio.Semaphore(3)
    async def fetch(match_id):
        async with semaphore:
            try:
                payload=await asyncio.wait_for(client.query_match_info(bundle.customer_token,match_id),timeout=6)
                if payload.get("code",0)!=0:return None
                detail=payload.get("data") or {}
                for player in list(detail.get("teammateList") or [])+list(detail.get("enemyList") or []):
                    if (target and str(player.get("bnetId"))==target) or (bundle.customer_token and player.get("customerToken")==bundle.customer_token):
                        return player
            except Exception:
                # Perks are supplemental; upstream failures must not hide season stats.
                return None
    players=await asyncio.gather(*(fetch(i) for i in ids))
    counts=defaultdict(Counter);samples=Counter()
    for player in players:
        if not player:continue
        # Player-level perks cannot safely be attributed across multiple heroes.
        nested=player.get("heroList") or []
        sources=nested if nested else [player]
        if len(nested)==1 and not nested[0].get("perks") and guid(nested[0].get("heroGuid"))==guid(player.get("heroGuid")):
            sources=[dict(nested[0],perks=player.get("perks") or [])]
        selected_in_match=defaultdict(set)
        for source in sources:
            hero=guid(source.get("heroGuid"))
            if hero not in top_heroes:continue
            perks=source.get("perks") or []
            selected={(int(p.get("perkLevel") or 0),guid(p.get("guid"))) for p in perks if isinstance(p,dict) and p.get("guid") and p.get("perkLevel") in (1,2)}
            for level,perk in selected:
                selected_in_match[(hero,level)].add(perk)
        for key,selected in selected_in_match.items():
            samples[key]+=1
            counts[key].update(selected)
    metadata=perk_metadata(config)
    enriched=[]
    for hero in heroes:
        entries=[]
        for level in (1,2):
            key=(guid(hero.hero_guid),level)
            for perk,count in counts[key].most_common(1):
                meta=metadata.get(perk,{})
                name=re.sub(r"<[^>]*>","",re.split(r"<br\s*/?>",str(meta.get("name") or "未知威能"),flags=re.I)[0])
                entries.append(dict(name=name,level=level,pick_count=count,sample_count=samples[key],icon_url=meta.get("icon") or ""))
        enriched.append(replace(hero,recent_perks=tuple(entries)))
    return tuple(enriched)
