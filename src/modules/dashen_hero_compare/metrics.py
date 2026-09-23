"""Unit-aware comparison rows and optional database references."""
import asyncio
import math
from ..dashen_summary.runtime.season_baseline import stat_values
from ..dashen_summary.runtime.stat_reference import is_hero_avg_percent_stat
from ..personal_data_percentile import is_database_write_enabled, IDPoolDB

CORE=(("603482350067646495","消灭","kill","aveKill"),("603482350067648392","助攻","assist","aveAssist"),("603482350067646506","阵亡","death","aveDeath"),("603482350067647671","英雄伤害","heroDamage","aveHeroDamage"),("603482350067646913","治疗量","cure","aveCure"))

def direction(label):
    if any(w in label for w in ("阵亡","死亡","被消灭","未命中","受到伤害","承受伤害")):return -1
    if any(w in label for w in ("消灭","命中","治疗","伤害","助攻","拯救","恢复","阻挡","吸收","摧毁","击退","击晕","击倒","充能","暴击","救援","复活","干扰","睡眠","睡着","阻止","减伤","胜率","KDA","麻醉敌人","侵入敌人")):return 1
    return 0

def collect_metrics(raw,hero,config):
    ten=stat_values(raw.get("statPerTenMinCount"));average=stat_values(raw.get("statAveCount"))
    rows=[dict(key="win_rate",label="胜率",value=hero["win_rate"],unit="%",direction=1),dict(key="kda",label="KDA",value=hero.get("kda"),unit="",direction=1),dict(key="match_sum",label="场次",value=hero["match_sum"],unit="场",direction=0),dict(key="game_time",label="游玩时长",value=hero["game_time_sec"]/3600,unit="小时",direction=0)]
    attrs=[];seen=set()
    for guid,label,*aliases in CORE:attrs.append((guid,label,aliases,"基础数据"))
    for attr in config.get("heroAttrList",[]) or []:
        if str(attr.get("heroGuid"))==hero["hero_guid"] and attr.get("valueType")=="特色数据":
            attrs.append((str(attr.get("valueGuid")),str(attr.get("valueText") or ""),[],"特色数据"))
    for guid,label,aliases,kind in attrs:
        if guid in seen or not label:continue
        seen.add(guid)
        ratio=is_hero_avg_percent_stat(label)
        value=None;unit="%" if ratio else "每10分钟"
        for values,source in ((ten,"每10分钟"),(average,"场均")):
            value=next((values[k] for k in (guid,*aliases) if k in values),None)
            if value is not None:
                unit="%" if ratio else source
                break
        rows.append(dict(key=guid,label=label,value=value*100 if ratio and value is not None else value,unit=unit,direction=direction(label),kind=kind,reference_value=value if ratio or unit=="每10分钟" else None))
    return rows

def winner(left,right,same_hero):
    if not same_hero or not left or not right or left['unit']!=right['unit'] or not left.get('direction') or left.get('direction')!=right.get('direction'):return None
    a,b=left.get('value'),right.get('value')
    if a is None or b is None or math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-8):return None
    return 0 if (a-b)*left['direction']>0 else 1

async def attach_references(data, *, db=None, enabled=None):
    enabled=is_database_write_enabled() if enabled is None else enabled
    data['database_enabled']=bool(enabled)
    if not enabled:return
    database=db or IDPoolDB()
    # Query each player separately: their values for the same hero/stat must not be deduplicated together.
    def query_player(player):
        targets=[];lookup={};kdas=[]
        for hero in player['heroes']:
            for row in hero.get('metrics',[]):
                if row['key']=='kda' and row.get('value') is not None:
                    kdas.append(dict(hero_guid=hero['hero_guid'],value=row['value']))
                    lookup[(hero['hero_guid'],'KDA')]=row
                if row.get('reference_value') is None:continue
                key=(hero['hero_guid'],row['key']);lookup[key]=row
                targets.append(dict(hero_guid=key[0],statmap_name=key[1],value=row['reference_value'],reverse=row['direction']==-1))
        comparisons=database.get_personal_stat_percentiles(targets) if targets else []
        if kdas:comparisons+=database.get_personal_kda_percentiles(kdas,death_floor=0.)
        for ref in comparisons:
            row=lookup.get((ref['hero_guid'],ref['statmap_name']))
            if row is None:continue
            count=int(ref.get('player_count') or 0)
            average=ref.get('average')
            row['reference']=dict(average=average*100 if average is not None and row['unit']=='%' else average,top_percent=max(0.,min(100.,100-float(ref['exceeded_percent']))) if count>=5 and row['direction'] else None,player_count=count)
    try:
        for player in data['players']:await asyncio.to_thread(query_player,player)
        data['database_status']='available'
    except Exception:
        data['database_status']='unavailable'
