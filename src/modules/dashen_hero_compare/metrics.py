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

def aggregate_band(value, summary, direction):
    """Match stored sample quantiles; this is not an exact player ranking."""
    if not direction or int(summary.get('count') or 0) < 5:
        return None
    prefix = 'bottom' if direction < 0 else 'top'
    for percent in (2, 5, 10, 20):
        threshold = summary.get(f'{prefix}{percent}')
        if threshold is not None and (value <= threshold if direction < 0 else value >= threshold):
            return f'达到前{percent}%线'
    threshold = summary.get(f'{prefix}20')
    return '未达前20%线' if threshold is not None else None


async def attach_references(data, *, db=None, enabled=None):
    enabled = is_database_write_enabled() if enabled is None else enabled
    data['database_enabled'] = bool(enabled)
    if not enabled:
        return
    database = db or IDPoolDB()

    def load_references():
        # Both players share one read per hero. Never fall back to raw records.
        heroes = {}
        for player in data['players']:
            for hero in player['heroes']:
                rows = [row for row in hero.get('metrics', []) if row.get('reference_value') is not None]
                if rows:
                    heroes.setdefault(hero['hero_guid'], []).extend(rows)
        available = False
        for hero_guid, rows in heroes.items():
            summaries = database.get_statmap_summary(
                hero_guid,
                statmap_names=list(dict.fromkeys(row['key'] for row in rows)),
                group_by_rank=False,
                preaggregated_only=True,
            )
            for row in rows:
                summary = summaries.get((row['key'], None))
                if not summary:
                    continue
                available = True
                average = summary.get('avg')
                row['reference'] = dict(
                    average=average * 100 if average is not None and row['unit'] == '%' else average,
                    percentile_band=aggregate_band(row['reference_value'], summary, row['direction']),
                    sample_count=int(summary.get('count') or 0),
                )
        return available

    try:
        available = await asyncio.to_thread(load_references)
        data['database_status'] = 'available' if available else 'unavailable'
    except Exception:
        data['database_status'] = 'unavailable'
