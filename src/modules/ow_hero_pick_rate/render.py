from __future__ import annotations

from ..subroles import draw_subrole_badge

from ..dashen_promo import append_dashen_promo
from ..dashen_quick_strength.render import QUICK_STRENGTH_THEME, COMPETITIVE_STRENGTH_THEME

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from overstats.src.modules.query_tool import get_cached_asset_path
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path

try:
    from overstats.src.modules.font_resolver import load_font
except ModuleNotFoundError:
    from src.modules.font_resolver import load_font


def _resolve_resource_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        here.parents[3] / "res",
        here.parents[4] / "overstats" / "res",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


RESOURCE_DIR = _resolve_resource_dir()
MMR_LABELS_CN = {
    "all": "全段位",
    "bronze": "青铜",
    "silver": "白银",
    "gold": "黄金",
    "platinum": "白金",
    "emerald": "翡翠",
    "diamond": "钻石",
    "master": "大师",
    "grandmaster": "宗师",
    "champion": "英杰",
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


TIER_ORDER = ("all", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master", "Grandmaster", "Champion")
TIER_COLORS = ((239,145,44),(163,109,76),(120,136,155),(195,153,44),(61,157,159),(49,161,107),(75,141,210),(161,117,52),(173,81,92),(134,90,192))


def _ow_canvas(height):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGBA", (1600, height), (216,228,223,255))
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        c = int(222 - 12*y/max(1,height))
        draw.line((0,y,1600,y),fill=(c-5,c+5,c))
    draw.polygon([(1050,0),(1600,0),(1600,370),(850,370)],fill=(209,223,219))
    return canvas,draw


def _ow_header(draw, title, subtitle, *, section, canvas=None, hero=None):
    draw.rounded_rectangle((24,16,1576,124),radius=18,fill=(24,41,59))
    draw.rounded_rectangle((44,33,51,106),radius=3,fill=(249,191,97))
    x=76
    if hero and canvas is not None:
        _paste_icon_or_placeholder(canvas,draw,hero,position=(76,32),size=72,font=_font_chinese(32))
        draw_subrole_badge(canvas,hero,129,84,24)
        x=172
    draw.text((x,38),title,font=_font_chinese(30,bold=True),fill=(248,250,254))
    draw.text((x,86),subtitle,font=_font_chinese(17),fill=(177,197,216))
    if hero and canvas is not None:
        _draw_role(canvas,hero,1280,58,26)
        draw.text((1318,58),_hero_role_label(hero.get("hero_role")),font=_font_chinese(20),fill=(205,222,237))


def _rank_glyph(canvas, tier, x, y, size=44):
    from PIL import Image
    from ...constants.ranks import rank_name_to_icon_level
    if tier == "all":
        return
    path = RESOURCE_DIR / "rank_flat" / f"{rank_name_to_icon_level(tier)}_pure.png"
    try:
        with Image.open(path) as source:
            im=source.convert("RGBA")
        im.thumbnail((size,size),Image.Resampling.LANCZOS)
        canvas.paste(im,(int(x+(size-im.width)/2),int(y+(size-im.height)/2)),im)
    except OSError:
        pass


def _finish_ow(canvas):
    from PIL import Image
    compact = Image.new("RGBA", (canvas.width, canvas.height-50))
    compact.paste(canvas.crop((0,0,canvas.width,124)), (0,0))
    compact.paste(canvas.crop((0,174,canvas.width,canvas.height)), (0,124))
    canvas = compact
    output=BytesIO()
    append_dashen_promo(canvas).save(output,format="PNG")
    return RenderedImage(content=output.getvalue())


def render_pick_rate_overview(*, game_mode, mmr, snapshot, heroes, theme=None, tier_data=()):
    canvas, draw = _ow_canvas(1068)
    ink = (38, 58, 72)
    muted = (99, 120, 124)
    _ow_header(draw, "英雄选取率", f"{_game_mode_label(game_mode)}  /  {_mmr_label(mmr)}  /  S{snapshot.get('season') or '—'}  /  {snapshot.get('ds') or '—'}", section="META OVERVIEW")
    metrics = (("selection_ratio", "选取率", (192,131,48)), ("win_ratio", "胜率", (49,133,113)), ("ban_ratio", "禁用率", (166,92,94)))
    for col, (key, label, color) in enumerate(metrics):
        x = 32 + col*516
        draw.rounded_rectangle((x,186,x+504,737),18,fill=(233,240,234))
        draw.rounded_rectangle((x,186,x+504,248),18,fill=(48,68,78))
        draw.rectangle((x+18,204,x+23,230),fill=color)
        draw.text((x+38,202), label + " TOP 6",font=_font_chinese(23,bold=True),fill=(244,247,241))
        ordered = sorted(heroes,key=lambda h: (-float(h.get(key) or 0),str(h.get("hero_guid"))))[:6]
        peak = max([float(h.get(key) or 0) for h in ordered] or [1]) or 1
        for i,h in enumerate(ordered):
            y=262+i*76
            draw.text((x+18,y+13),str(i+1).zfill(2),font=_font_resource("BigNoodleToo.ttf",28),fill=color if i<3 else muted)
            _paste_icon_or_placeholder(canvas,draw,h,position=(x+57,y+2),size=54,font=_font_chinese(18))
            draw_subrole_badge(canvas,h,x+96,y+39,19)
            draw.text((x+127,y+1),_fit_label(draw,h.get("hero_name"),_font_chinese(21,bold=True),210),font=_font_chinese(21,bold=True),fill=ink)
            _draw_role(canvas,h,x+128,y+33,16)
            draw.text((x+150,y+32),_hero_role_label(h.get("hero_role")),font=_font_chinese(13),fill=muted)
            value=float(h.get(key) or 0)
            text=f"{value:.2f}%"; font=_font_chinese(24,bold=True)
            draw.text((x+481-_measure_text(draw,text,font),y+8),text,font=font,fill=color)
            draw.rounded_rectangle((x+127,y+59,x+480,y+63),2,fill=(211,224,217))
            if value>0: draw.rounded_rectangle((x+127,y+59,x+127+353*value/peak,y+63),2,fill=color)
    for col, role in enumerate(("重装","输出","支援")):
        x=32+col*516
        entries=sorted([h for h in heroes if _hero_role_label(h.get("hero_role"))==role],key=lambda h:-float(h.get("selection_ratio") or 0))
        draw.rounded_rectangle((x,764,x+504,1016),18,fill=(229,238,231))
        if entries: _draw_role(canvas,entries[0],x+23,786,26)
        draw.text((x+61,786),role,font=_font_chinese(23,bold=True),fill=ink)
        draw.text((x+393,792),f"{len(entries)} 位",font=_font_chinese(16),fill=muted)
        for i,h in enumerate(entries[:5]):
            px=x+22+i*96
            _paste_icon_or_placeholder(canvas,draw,h,position=(px,839),size=76,font=_font_chinese(20))
            draw_subrole_badge(canvas,h,px+55,894,22)
            draw.text((px,926),_fit_label(draw,h.get("hero_name"),_font_chinese(15,bold=True),88),font=_font_chinese(15,bold=True),fill=ink)
            draw.text((px,960),f"{float(h.get('selection_ratio') or 0):.2f}%",font=_font_chinese(18,bold=True),fill=(64,119,109))
    return _finish_ow(canvas)


def render_pick_rate_ranking(*, game_mode, mmr, snapshot, heroes, theme=None, tier_data=()):
    # Align all columns to one snapshot, never fill absent tiers with older data.
    peers={str(t["mmr"]).lower():{str(h.get("hero_guid")):h for h in t.get("heroes",[])} for t in tier_data}
    peers[str(mmr).lower()]={str(h.get("hero_guid")):h for h in heroes}
    all_heroes={str(h.get("hero_guid")):h for h in heroes}
    for rows in peers.values():
        for guid,hero in rows.items(): all_heroes.setdefault(guid,hero)
    ordered=list(heroes)+[h for guid,h in all_heroes.items() if guid not in {str(h.get("hero_guid")) for h in heroes}]
    height=378+max(1,len(ordered))*54
    canvas,draw=_ow_canvas(height)
    _ow_header(draw,"英雄选取率",f"{_game_mode_label(game_mode)}  /  S{snapshot.get('season') or '—'}  /  {snapshot.get('ds') or '日期未记录'}",section="HERO META")
    draw.text((40,197),f"按{_mmr_label(mmr)}选取率排序",font=_font_chinese(23,bold=True),fill=(39,56,78))
    draw.text((1300,204),"选取率  /  胜率 · BAN",font=_font_chinese(16),fill=(92,110,131))
    left=310;cw=125
    draw.rectangle((32,244,1568,324),fill=(54,70,91))
    draw.text((58,270),"英雄 / 职责",font=_font_chinese(19,bold=True),fill="white")
    for j,tier in enumerate(TIER_ORDER):
        x=left+j*cw
        if tier.lower()==str(mmr).lower():
            draw.rectangle((x,244,x+cw-3,324),fill=(78,94,113))
            draw.rectangle((x,244,x+cw-3,248),fill=(255,158,46))
        _rank_glyph(canvas,tier,x+(cw-40)/2,250,40)
        if tier=='all': draw.text((x+40,263),"ALL",font=_font_resource("BigNoodleToo.ttf",25),fill=(255,171,61))
        name=_mmr_label(tier);f=_font_chinese(14,bold=True)
        draw.text((x+(cw-_measure_text(draw,name,f))/2,298),name,font=f,fill="white")
    if not ordered: draw.text((60,342),"暂无可用快照",font=_font_chinese(20),fill=(71,88,111))
    for i,item in enumerate(ordered):
        y=330+i*54;guid=str(item.get("hero_guid"));color=_role_color(item)
        draw.rectangle((32,y,1568,y+50),fill=(228,237,231) if i%2==0 else (216,229,222))
        draw.polygon([(32,y),(307,y),(294,y+50),(32,y+50)],fill=(56,73,96))
        draw.rectangle((32,y,36,y+50),fill=color)
        draw.text((45,y+10),str(i+1).zfill(2),font=_font_resource("BigNoodleToo.ttf",25),fill=(255,171,61) if i<3 else (171,191,214))
        _paste_icon_or_placeholder(canvas,draw,item,position=(82,y+3),size=44,font=_font_chinese(18))
        draw_subrole_badge(canvas,item,115,y+30,18)
        draw.text((143,y+4),_fit_label(draw,item.get("hero_name"),_font_chinese(17,bold=True),145),font=_font_chinese(17,bold=True),fill="white")
        _draw_role(canvas,item,143,y+29,13)
        draw.text((162,y+28),_hero_role_label(item.get("hero_role")),font=_font_chinese(11),fill=color)
        vals=[peers.get(t.lower(),{}).get(guid) for t in TIER_ORDER]
        peak=max([float(v.get('selection_ratio') or 0) for v in vals if v] or [1]) or 1
        marks = _metric_marks([float(v.get("selection_ratio") or 0) if v else None for v in vals])
        for j,value in enumerate(vals):
            x=left+j*cw
            if value is None:
                draw.text((x+54,y+13),"—",font=_font_chinese(18),fill=(160,173,188));continue
            _draw_metric_mark(draw,x+7,y+11,marks[j])
            pick=float(value.get('selection_ratio') or 0);win=float(value.get('win_ratio') or 0)
            f=_font_chinese(19,bold=True);text=f"{pick:.2f}%"
            draw.text((x+(cw-_measure_text(draw,text,f))/2,y+2),text,font=f,fill=(37,55,79))
            text=f"{win:.1f}% · {float(value.get('ban_ratio') or 0):.1f}%";f=_font_chinese(11)
            draw.text((x+(cw-_measure_text(draw,text,f))/2,y+27),text,font=f,fill=(35,124,107) if win>=50 else (146,93,83))
            draw.rectangle((x+17,y+46,x+cw-17,y+48),fill=(213,222,233))
            if pick>0:draw.rectangle((x+17,y+46,x+17+(cw-34)*pick/peak,y+48),fill=(244,159,56))
    return _finish_ow(canvas)


def _pick_rate_axis_ceiling(values):
    import math
    peak = max((float(value) for value in values if math.isfinite(float(value))), default=0)
    if peak <= 0:
        return 1.0
    raw_step = peak * 1.08 / 5
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(factor * magnitude for factor in (1, 1.5, 2, 2.5, 4, 5, 7.5, 10) if factor * magnitude >= raw_step)
    return step * 5


def render_pick_rate_history(*, game_mode, mmr, hero, latest, history_total, history_limit, series, theme=None, tier_data=(), patch_events=(), patch_dates_available=True):
    role_heroes = next((row.get("role_heroes", []) for row in tier_data if str(row["mmr"]).lower()=="all"), [])
    canvas,draw=_ow_canvas(1050 + max(0, (len(role_heroes)+25)//26-1)*48)
    _ow_header(draw,f"{hero.get('hero_name') or '英雄'} · 选取率",f"{_game_mode_label(game_mode)}  /  {_mmr_label(mmr)}  /  {series[-1].get('ds') if series else '—'}",section="HERO TRENDS",canvas=canvas,hero=hero)
    peers={str(t['mmr']).lower():t.get('series',[]) for t in tier_data}
    peers[str(mmr).lower()]=series
    draw.text((40,197),"选取率趋势",font=_font_chinese(25,bold=True),fill=(40,58,81))
    draw.text((1040,197),"段位数据",font=_font_chinese(23,bold=True),fill=(40,58,81))
    draw.rectangle((32,242,1008,909),fill=(228,237,231));draw.rectangle((1028,242,1568,1018),fill=(228,237,231))
    if not series:
        draw.text((60,300),"暂无可用历史数据",font=_font_chinese(23),fill=(84,103,125))
        return _finish_ow(canvas)
    keys=[(int(p.get('season') or 0),str(p.get('ds') or '')) for p in series]
    lookups = {tier.lower(): {(int(p.get('season') or 0), str(p.get('ds') or '')): p for p in peers.get(tier.lower(), [])} for tier in TIER_ORDER}
    baselines = {str(tier['mmr']).lower(): {(int(p.get('season') or 0), str(p.get('ds') or '')): float(p.get('selection_ratio') or 0) for p in tier.get('baseline', [])} for tier in tier_data}
    # Scale only the points actually drawn, including the selected tier's baseline.
    values = [float(lookup[key].get('selection_ratio') or 0) for lookup in lookups.values() for key in keys if key in lookup]
    baseline = baselines.get(str(mmr).lower(), {})
    values += [baseline[key] for key in keys if key in baseline]
    ceiling = _pick_rate_axis_ceiling(values)
    try:
        days = [date.fromisoformat(k[1][:10]).toordinal() for k in keys]
        span = days[-1] - days[0]
        fractions = [(d-days[0])/span if span>0 else .5 for d in days]
    except ValueError:
        fractions = [i/(len(keys)-1) if len(keys)>1 else .5 for i in range(len(keys))]
    metrics = [('selection_ratio',1180),('win_ratio',1280),('ban_ratio',1380),('kda',1480)]
    marks = {metric: _metric_marks([float(lookups[t.lower()][keys[-1]].get(metric) or 0) if keys[-1] in lookups[t.lower()] else None for t in TIER_ORDER]) for metric,_ in metrics}
    selected = next((row for row in tier_data if str(row['mmr']).lower()=='all'), {})
    role = _hero_role_label(hero.get('hero_role'))
    for y, label, rank_key, total_key in [(860, '全段位选取率', 'role_rank', 'role_total'), (886, '全段位胜率', 'role_win_rank', 'role_win_total')]:
        rank = selected.get(rank_key)
        text = f"{label} · {role}内 {rank}/{selected.get(total_key)} 名" if rank else f"{label} · {role}内 —"
        draw.text((1050,y),text,font=_font_chinese(16,bold=True),fill=(57,78,104))
    draw.line((1045,918,1550,918),fill=(193,210,204))
    for px,label in [(1050,'全段位变化率'),(1250,'选取率'),(1410,'胜率')]:
        draw.text((px,930),label,font=_font_chinese(14),fill=(104,125,149))
    for days,py in [(7,958),(30,987)]:
        draw.text((1050,py),f"近 {days} 天",font=_font_chinese(16),fill=(57,78,104))
        for metric,px in [('selection_ratio',1250),('win_ratio',1410)]:
            delta=selected.get('relative_changes',{}).get(str(days),{}).get(metric)
            label=f"{delta:+.2f}%" if delta is not None else '—'
            color=(38,151,126) if delta is not None and delta>0 else (206,105,99) if delta is not None and delta<0 else (110,130,151)
            draw.text((px,py),label,font=_font_chinese(14,bold=True),fill=color)
    l,r,t,b=103,870,300,817
    yy=lambda v:b-v/ceiling*(b-t)
    for tick in range(6):
        value=ceiling*tick/5;py=yy(value)
        draw.line((l,py,r,py),fill=(193,210,204))
        draw.text((44,py-8),f"{value:.1f}%",font=_font_chinese(12),fill=(116,135,157))
    season_labels = []
    for i in range(1, len(keys)):
        if keys[i][0] == keys[i-1][0]:
            continue
        px = l + (r-l)*fractions[i]
        color = (102, 123, 149)
        _dashed_line(draw, (px,t), (px,b), (170,189,192), 1)
        draw.polygon([(px-4,b+5),(px+4,b+5),(px,b)],fill=color)
        label = f"{keys[i][1][5:]}  S{keys[i-1][0]} → S{keys[i][0]}"
        font = _font_chinese(12)
        width = _measure_text(draw,label,font)
        x = max(l,min(r-width,px-width/2))
        lane = 1 if season_labels and x < season_labels[-1]+8 else 0
        draw.text((x,866+lane*18),label,font=font,fill=color)
        season_labels.append(x+width)
    label_ends=[-100,-100]
    for event in sorted(patch_events,key=lambda row:row.get('date','')):
        try:
            patch_day=date.fromisoformat(event['date']).toordinal()
            first_day=date.fromisoformat(keys[0][1][:10]).toordinal()
            last_day=date.fromisoformat(keys[-1][1][:10]).toordinal()
        except (ValueError,KeyError):continue
        if not first_day<=patch_day<=last_day:continue
        px=l+(r-l)*(patch_day-first_day)/(last_day-first_day) if last_day>first_day else (l+r)/2
        kind=event.get("kind","更新")
        marker_color={"增强":(38,143,113),"削弱":(193,103,98),"调整":(157,124,69)}.get(kind,(153,143,115))
        _dashed_line(draw,(px,t),(px,b),tuple(int(v*.65+base*.35) for v,base in zip(marker_color,(228,237,231))),1)
        draw.polygon([(px-4,t-5),(px+4,t-5),(px,t)],fill=marker_color)
        for lane in range(2):
            label_x=max(l,min(r-88,px-35))
            if label_x>label_ends[lane]+6:
                draw.text((label_x,254+lane*20),event['date'][5:]+' '+kind,font=_font_chinese(12),fill=marker_color)
                label_ends[lane]=label_x+84
                break
    if not patch_dates_available:
        draw.text((50,876),'更新日期暂不可用',font=_font_chinese(12),fill=(137,145,155))
    curve_draw = _CurveLayer((98, 280, 880, 824))
    previous=None
    for fraction,key in zip(fractions,keys):
        base=baselines.get(str(mmr).lower(),{}).get(key)
        if base is None:previous=None;continue
        pos=(l+(r-l)*fraction,yy(base))
        if previous:_dashed_line(curve_draw,previous,pos,(125,140,160),2)
        previous=pos
    labels=[]
    for j,tier in enumerate(TIER_ORDER):
        color=TIER_COLORS[j];lookup=lookups[tier.lower()];end=lookup.get(keys[-1]);previous=None
        emphasized=tier.lower()==str(mmr).lower()
        for fraction,key in zip(fractions,keys):
            point=lookup.get(key)
            if point is None:previous=None;continue
            pos=(l+(r-l)*fraction,yy(float(point.get('selection_ratio') or 0)))
            if previous:
                if j%2 and not emphasized:_dashed_line(curve_draw,previous,pos,color,2)
                else:curve_draw.line((previous,pos),fill=color,width=4 if emphasized else 2)
            previous=pos
        if end:
            py=yy(float(end.get('selection_ratio') or 0))
            curve_draw.ellipse((r-3,py-3,r+3,py+3),fill=color)
            labels.append((py,tier,color))
        y=300+j*55
        _rank_glyph(canvas,tier,1040,y,38)
        draw.text((1090,y+10),_mmr_label(tier),font=_font_chinese(16,bold=True),fill=color)
        for metric,px in metrics:
            text=(f"{float(end.get(metric) or 0):.2f}"+('%' if metric!='kda' else '')) if end else '—'
            _draw_metric_mark(draw,px-10,y+19,marks[metric][j])
            draw.text((px,y+12),text,font=_font_chinese(15,bold=True),fill=(54,73,96))
        draw.line((1045,y+48,1550,y+48),fill=(193,210,204))
    curve_draw.paste_onto(canvas)
    labels.sort()
    placed=[]
    for py,tier,color in labels:
        label_y=max(py,placed[-1][0]+24 if placed else t)
        placed.append((label_y,py,tier,color))
    overflow=max(0,(placed[-1][0] if placed else b)-b)
    for label_y,py,tier,color in placed:
        label_y-=overflow
        draw.line((r+5,py,r+22,label_y,r+29,label_y),fill=color,width=1)
        draw.text((r+34,label_y-9),_mmr_label(tier),font=_font_chinese(14,bold=True),fill=color)
    for i in sorted({0,len(keys)//2,len(keys)-1}):
        text=keys[i][1];font=_font_chinese(12);px=l+(r-l)*fractions[i]
        draw.text((px-_measure_text(draw,text,font)/2,842),text,font=font,fill=(108,128,150))
    for x,label in [(1180,'选取率'),(1280,'胜率'),(1380,'BAN'),(1480,'KDA')]:draw.text((x,268),label,font=_font_chinese(14),fill=(110,127,147))
    _dashed_line(draw,(46,932),(76,932),(125,140,160),2)
    draw.text((84,921),f'{_mmr_label(mmr)} · 全英雄均值',font=_font_chinese(13),fill=(95,116,140))
    draw.text((350,921),f"{keys[0][1]} — {keys[-1][1]}",font=_font_chinese(13),fill=(95,116,140))
    draw.text((44,952),f"{_hero_role_label(hero.get('hero_role'))} · 全段位选取率排行",font=_font_chinese(14,bold=True),fill=(70,97,104))
    if not role_heroes:
        draw.text((44,984),'暂无排行数据',font=_font_chinese(13),fill=(115,137,140))
    for i, item in enumerate(role_heroes):
        x=47+(i%26)*36; y=980+(i//26)*48
        _paste_icon_or_placeholder(canvas,draw,item,position=(x,y),size=30,font=_font_chinese(13))
        current=str(item.get('hero_guid'))==str(hero.get('hero_guid'))
        if current:
            draw.rounded_rectangle((x-3,y-3,x+33,y+33),radius=5,outline=(212,139,42),width=3)
        label=str(item.get('rank') or i+1);font=_font_chinese(10,bold=current)
        draw.text((x+15-_measure_text(draw,label,font)/2,y+33),label,font=font,fill=(155,103,31) if current else (89,115,122))
    return _finish_ow(canvas)



class _CurveLayer:
    """Supersample curves independently, preserving the existing layout scale."""
    def __init__(self, box):
        from PIL import Image, ImageDraw
        self.box = box
        self.scale = 4
        self.image = Image.new('RGBA', ((box[2]-box[0])*4, (box[3]-box[1])*4))
        self.draw = ImageDraw.Draw(self.image)

    def _coordinates(self, xy):
        if isinstance(xy[0], (tuple, list)):
            return [((x-self.box[0])*4, (y-self.box[1])*4) for x,y in xy]
        return [(v-self.box[i%2])*4 for i,v in enumerate(xy)]

    def line(self, xy, *, fill, width=1):
        self.draw.line(self._coordinates(xy), fill=fill, width=width*4)

    def ellipse(self, xy, *, fill):
        self.draw.ellipse(self._coordinates(xy), fill=fill)

    def paste_onto(self, canvas):
        from PIL import Image
        image = self.image.resize((self.box[2]-self.box[0], self.box[3]-self.box[1]), Image.Resampling.LANCZOS)
        canvas.paste(image, self.box[:2], image)


def _metric_marks(values):
    valid = [v for v in values if v is not None]
    unique = sorted(set(valid))
    if not valid:
        return [None] * len(values)
    ordered = sorted(valid)
    middle = {ordered[(len(ordered)-1)//2], ordered[len(ordered)//2]}
    result=[]
    for v in values:
        if v is None: mark=None
        elif v in middle: mark='median'
        elif v == unique[-1]: mark='top1'
        elif v == unique[0]: mark='bottom1'
        elif len(unique)>2 and v == unique[-2]: mark='top2'
        elif len(unique)>2 and v == unique[1]: mark='bottom2'
        else: mark=None
        result.append(mark)
    return result


def _draw_metric_mark(draw,x,y,mark):
    if mark is None:return
    if mark=='median':
        draw.line((x-3,y,x+3,y),fill=(115,131,151),width=2);return
    up=mark.startswith('top');color=(38,151,126) if up else (206,105,99)
    for i in range(2 if mark.endswith('1') else 1):
        cy=y+i*5
        vertices=[(x,cy-4),(x-4,cy+2),(x+4,cy+2)] if up else [(x,cy+4),(x-4,cy-2),(x+4,cy-2)]
        draw.polygon(vertices,fill=color)


def _dashed_line(draw,start,end,color,width):
    import math
    dx,dy=end[0]-start[0],end[1]-start[1];length=math.hypot(dx,dy)
    if length==0:return
    for d in range(0,int(length)+1,10):
        stop=min(d+5,length)
        draw.line((start[0]+dx*d/length,start[1]+dy*d/length,start[0]+dx*stop/length,start[1]+dy*stop/length),fill=color,width=width)


ROLE_COLORS = {"tank": (113, 180, 255), "dps": (255, 153, 121), "healer": (106, 219, 179), "support": (106, 219, 179)}


def _role_color(item):
    return ROLE_COLORS.get(str(item.get("hero_role") or "").lower(), (167, 187, 215))


@lru_cache(maxsize=24)
def _role_icon(role, size):
    from PIL import Image

    role = "healer" if role == "support" else role
    if role not in {"tank", "dps", "healer"}:
        return None
    try:
        with Image.open(RESOURCE_DIR / f"{role}.png") as source:
            icon = source.convert("RGBA")
        icon.thumbnail((size, size), Image.Resampling.LANCZOS)
        return icon
    except OSError:
        return None


def _draw_role(canvas, item, x, y, size):
    icon = _role_icon(str(item.get("hero_role") or "").lower(), size)
    if icon is not None:
        canvas.paste(icon, (int(x), int(y)), icon)


def _fit_label(draw, text, font, width):
    text = str(text or "—")
    if _measure_text(draw, text, font) <= width:
        return text
    while text and _measure_text(draw, text + "…", font) > width:
        text = text[:-1]
    return text + "…"


def _paste_icon_or_placeholder(
    canvas: Any,
    draw: Any,
    payload: Dict[str, Any],
    *,
    position: Tuple[int, int],
    size: int,
    font: Any,
) -> None:
    icon = _load_hero_icon(payload, size=size)
    if icon is not None:
        canvas.paste(icon, position, icon)
        return
    x, y = position
    draw.ellipse((x, y, x + size, y + size), fill=(32, 49, 73, 255))
    text = str(payload.get("hero_name") or payload.get("hero_guid") or "?")[:1]
    _draw_text_center(draw, text, (x, y, x + size, y + size), font=font, fill=(236, 243, 252, 255))


def _load_hero_icon(payload: Dict[str, Any], *, size: int) -> Any:
    from PIL import Image, ImageDraw, ImageOps

    hero_icon_url = str(payload.get("icon_url") or "").strip()
    if not hero_icon_url:
        return None
    local_path = get_cached_asset_path(hero_icon_url, "heroes")
    if not local_path or not Path(local_path).exists():
        return None
    try:
        with Image.open(local_path) as source:
            icon = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.LANCZOS)
    except Exception:
        return None
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    icon.putalpha(mask)
    return icon


def _game_mode_label(game_mode: str) -> str:
    return "竞技" if str(game_mode or "").strip().lower() == "competitive" else "快速"


def _mmr_label(mmr: str) -> str:
    normalized = str(mmr or "").strip()
    return MMR_LABELS_CN.get(normalized.lower(), normalized or "--")


def _hero_role_label(role_type: Any) -> str:
    normalized = str(role_type or "").strip().lower()
    if normalized == "tank":
        return "重装"
    if normalized == "dps":
        return "输出"
    if normalized in {"healer", "support"}:
        return "支援"
    return normalized or "未知职责"


def _ratio_text(value: float) -> str:
    return f"{float(value or 0):.2f}%"


def _draw_text_center(draw: Any, text: str, box: Tuple[int, int, int, int], *, font: Any, fill: Tuple[int, int, int, int]) -> None:
    text_width = _measure_text(draw, text, font)
    text_height = _measure_text_height(draw, text, font)
    x = int((box[0] + box[2] - text_width) / 2)
    y = int((box[1] + box[3] - text_height) / 2) - 2
    draw.text((x, y), text, font=font, fill=fill)


def _new_draw(image: Any) -> Any:
    from PIL import ImageDraw

    return ImageDraw.Draw(image, "RGBA")


def _font_resource(name: str, size: int, *, fallback: str | None = None) -> Any:
    return load_font(size, name=name, fallback=fallback)


def _font_chinese(size: int, *, bold: bool = False) -> Any:
    return load_font(
        size,
        name="simhei.ttf",
        fallback="GrotaRoundedExtraBold.otf",
        prefer_cjk=True,
        bold=bold,
    )


def _measure_text(draw: Any, text: str, font: Any) -> int:
    try:
        return int(draw.textlength(str(text or ""), font=font))
    except Exception:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[2] - box[0])


def _measure_text_height(draw: Any, text: str, font: Any) -> int:
    try:
        box = draw.textbbox((0, 0), str(text or ""), font=font)
        return int(box[3] - box[1])
    except Exception:
        return int(font.size if hasattr(font, "size") else 12)


__all__ = [
    "RenderedImage",
    "QUICK_STRENGTH_THEME",
    "COMPETITIVE_STRENGTH_THEME",
    "render_pick_rate_history",
    "render_pick_rate_ranking",
]
