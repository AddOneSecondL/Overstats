from io import BytesIO
from PIL import Image, ImageDraw, ImageOps
from ..dashen_hero_treemap.render import (_load_fonts, _load_summary_font, _build_treemap_background, _mode_label, _truncate_text, _fit_font, _wrap_text, _open_cached_asset, _load_role_icon, RESOURCE_DIR, RenderedImage)
from ..dashen_summary.runtime.summary_typography import SummaryDraw
from .metrics import winner

WHITE=(233,240,248);MUTED=(146,164,186);GREEN=(108,232,185)

def metric_rows(left,right):
    a=(left or {}).get('metrics',[]);b=(right or {}).get('metrics',[])
    if left and right and left['hero_guid']==right['hero_guid']:
        keys=list(dict.fromkeys([m['key'] for m in a]+[m['key'] for m in b]))
        aa={m['key']:m for m in a};bb={m['key']:m for m in b}
        return [(aa.get(k),bb.get(k)) for k in keys]
    return [(a[i] if i<len(a) else None,b[i] if i<len(b) else None) for i in range(max(len(a),len(b)))]

def formatted(value,unit):
    if value is None:return '—'
    if unit=='场':return f'{value:,.0f}'
    return f'{value:,.1f}' if unit else f'{value:,.2f}'

def render_compare(data):
    count=max(1,*(len(p['heroes']) for p in data['players']))
    measure=SummaryDraw(Image.new('RGB',(1,1)),numeric_font_path=RESOURCE_DIR/'GrotaRoundedExtraBold.otf')
    font=_load_summary_font(17,bold=False)
    sections=[]
    for i in range(count):
        heroes=[p['heroes'][i] if i<len(p['heroes']) else None for p in data['players']]
        rows=[]
        for pair in metric_rows(*heroes):
            lines=[_wrap_text(measure,m['label'],font,220,100) if m else [] for m in pair]
            row_h=max(58,max((len(line)*22+26 for line in lines),default=58))
            rows.append((pair,lines,row_h))
        sections.append((heroes,rows,184+sum(r[2] for r in rows)))
    width,height=1680,226+sum(s[2]+20 for s in sections)+64
    canvas=Image.new('RGBA',(width,height),(12,20,32,255))
    bg=_build_treemap_background((width,260))
    if bg is not None:
        fade=Image.new('L',bg.size)
        f=ImageDraw.Draw(fade)
        for line in range(bg.height):f.line((0,line,width,line),fill=int(100*(1-line/max(bg.height-1,1))))
        bg.putalpha(fade);canvas.alpha_composite(bg)
    draw=SummaryDraw(canvas,numeric_font_path=RESOURCE_DIR/'GrotaRoundedExtraBold.otf')
    fonts=_load_fonts()
    draw.text((36,22),'英雄对比',font=fonts['header_title'],fill=WHITE)
    draw.text((250,39),f"{_mode_label(data['mode'])} / {data.get('hero') or '各自时长前三'}",font=fonts['header_emphasis'],fill=(139,191,224))
    draw.text((1130,43),'同英雄同单位 · 绿色表示较优',font=font,fill=GREEN)
    for side,p in enumerate(data['players']):
        x=30+side*830;color=(123,197,235) if side==0 else (239,196,115)
        draw.rounded_rectangle((x,90,x+790,194),radius=14,fill=(19,30,44),outline=(65,82,104))
        draw.text((x+20,103),_truncate_text(draw,p['player']['display_name'],fonts['header_title'],590),font=fonts['header_title'],fill=color)
        draw.text((x+660,117),f"S{p['season']}" if p['season'] else '无记录',font=fonts['header_emphasis'],fill=color)
        draw.text((x+20,164),p.get('summary',''),font=fonts['header_meta'],fill=MUTED)
    y=214
    for heroes,rows,section_h in sections:
        same=all(heroes) and heroes[0]['hero_guid']==heroes[1]['hero_guid']
        for side,hero in enumerate(heroes):
            x=30+side*830
            draw.rounded_rectangle((x,y,x+790,y+section_h),radius=14,fill=(19,29,43),outline=(63,80,101))
            if hero:
                icon=_open_cached_asset(hero.get('icon_url'),('heroes','misc','summary'))
                if icon is not None:
                    icon=ImageOps.contain(icon,(140,140))
                    canvas.alpha_composite(icon,(x+632,y+5))
                role=_load_role_icon(hero.get('hero_role'),22)
                if role is not None:canvas.alpha_composite(role,(x+22,y+22))
                draw.text((x+58,y+18),hero['hero_name'],font=fonts['header_title'],fill=WHITE)
                draw.text((x+24,y+80),f"{hero['match_sum']}场 · {hero['game_time_sec']/3600:.1f}小时",font=fonts['header_emphasis'],fill=MUTED)
                feature_count=sum(m.get('kind')=='特色数据' for m in hero.get('metrics',[]))
                draw.text((x+24,y+111),f'特色数据 {feature_count} 项',font=fonts['header_meta'],fill=(146,180,214))
            else:
                draw.text((x+25,y+50),'该范围暂无英雄记录',font=fonts['tile_name'],fill=MUTED)
            draw.text((x+18,y+153),'指标 / 单位',font=font,fill=MUTED)
            draw.text((x+282,y+153),'个人数据',font=font,fill=MUTED)
            if data.get('database_enabled'):
                draw.text((x+427,y+153),'库内均值',font=font,fill=MUTED)
                draw.text((x+587,y+153),'Top% / 样本',font=font,fill=MUTED)
        row_y=y+184
        for row_index,(pair,lines,row_h) in enumerate(rows):
            better=winner(*pair,same)
            for side,m in enumerate(pair):
                x=30+side*830
                fill=(25,39,54) if row_index%2==0 else (19,29,43)
                if better==side:fill=(22,54,49)
                draw.rectangle((x+1,row_y,x+789,row_y+row_h-1),fill=fill)
                if m is None:
                    draw.text((x+286,row_y+16),'—',font=font,fill=MUTED);continue
                for j,line in enumerate(lines[side]):
                    draw.text((x+18,row_y+8+j*22),line,font=font,fill=WHITE)
                unit=m['unit'] or '比值'
                if m.get('direction')==-1:unit+=' · 越低越好'
                draw.text((x+18,row_y+9+len(lines[side])*22),unit,font=_load_summary_font(12,bold=False),fill=MUTED)
                text=formatted(m.get('value'),m['unit'])
                draw.text((x+282,row_y+14),text,font=_fit_font(draw,text,22,130,bold=True),fill=GREEN if better==side else WHITE)
                if data.get('database_enabled'):
                    ref=m.get('reference') or {}
                    draw.text((x+427,row_y+16),formatted(ref.get('average'),m['unit']),font=fonts['header_emphasis'],fill=(156,186,214))
                    top=ref.get('top_percent');n=ref.get('player_count',0)
                    top_text='—' if top is None else f'{top:.1f}%' if top>0 else f'<{100/max(n,1):.1f}%'
                    draw.text((x+587,row_y+7),top_text,font=fonts['header_emphasis'],fill=(238,204,129) if top is not None else MUTED)
                    draw.text((x+587,row_y+32),f'{n}位玩家' if n else '无同口径样本',font=_load_summary_font(12,bold=False),fill=MUTED)
            row_y+=row_h
        y+=section_h+20
    draw.text((36,height-58),'数据以各列赛季为准；缺项、不同单位及无明确优劣方向的指标不高亮。',font=fonts['header_meta'],fill=MUTED)
    if data.get('database_enabled'):
        note='数据库暂不可用' if data.get('database_status')=='unavailable' else '数据库参考：库内同英雄全量样本，未按模式/赛季筛选；每位玩家等权，至少5人才显示Top%。'
        draw.text((36,height-30),note,font=fonts['header_meta'],fill=MUTED)
    output=BytesIO();canvas.save(output,format='PNG')
    return RenderedImage(output.getvalue())
