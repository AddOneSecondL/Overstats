from io import BytesIO
import re

from PIL import Image, ImageDraw, ImageOps
from ..dashen_rank_history.render import (_font_chinese, _load_ow_config,
                                         _find_hero, _load_remote_asset_image, ROLE_LABELS)
from ..font_resolver import load_font, resolve_resource_dir
try:
    from overstats.src.constants.backgrounds import build_random_map_background
    from overstats.src.constants.ranks import RANK_LABELS_CN, rank_name_to_icon_level, raw_rank_score_to_icon_level
except ModuleNotFoundError:
    from src.constants.backgrounds import build_random_map_background
    from src.constants.ranks import RANK_LABELS_CN, rank_name_to_icon_level, raw_rank_score_to_icon_level


# Icon asset IDs are not rank order: Emerald (9) sits below Diamond (5).
RANK_BORDER_STYLES = [
    (1, '#bc8968'), (2, '#c6d2e0'), (3, '#edc65d'),
    (4, '#63c6df'), (9, '#52d69a'), (5, '#719dff'),
    (6, '#bd87ff'), (7, '#ff9860'), (8, '#ff527c'),
]


def opponent_border(player):
    levels = {rank_name_to_icon_level(rank.get('rank_name')) or
              raw_rank_score_to_icon_level(rank.get('score'))
              for rank in player.get('ranks', []) if rank.get('score', 0) > 0}
    if player.get('status') == 'ok':
        for level, color in reversed(RANK_BORDER_STYLES):
            if level in levels:
                return color
    return '#78869b'


def playtime_style(hours):
    """Color total hours; emphasize strictly below 50 or above 1000."""
    if hours is None:
        return '#a9b9d1', False
    if hours < 50:
        return '#ff718b', True
    if hours < 200:
        return '#66c9f4', False
    if hours < 500:
        return '#63d6ae', False
    if hours <= 1000:
        return '#edc65d', False
    if hours <= 2000:
        return '#ffab62', True
    return '#cd94ff', True


def win_rate_color(rate):
    if rate is None:
        return '#a9b9d1'
    if rate >= 70:
        return '#63e6a6'
    if rate >= 55:
        return '#66c9f4'
    if rate >= 45:
        return '#edc65d'
    return '#ff718b'


def streak_color(streak):
    if streak is None or streak == 0:
        return '#a9b9d1'
    if streak >= 5:
        return '#63e6a6'
    if streak > 0:
        return '#66c9f4'
    if streak <= -5:
        return '#ff527c'
    return '#ffab62'


def render_overview(result):
    teams = result['teams']
    columns = max(1, len(teams['teammate']), len(teams['enemy']))
    width, height = 48 + columns * 332, 1272
    canvas = build_random_map_background(
        (width, height), blur_radius=14, brightness=.85, color=.9,
        overlay=(12,22,38,100), directory=resolve_resource_dir()/'query_tool_assets'/'maps')
    if canvas is None:
        canvas = Image.new('RGBA',(width,height),(24,34,56,255))
    draw = ImageDraw.Draw(canvas)
    fonts = {size: _font_chinese(size) for size in (12,14,16,18,20,24,28)}
    number_fonts = {size: load_font(size, name='GrotaRoundedExtraBold.otf') for size in fonts}
    config = _load_ow_config()

    def text(x,y,value,size=18,color='#f3f6ff',limit=280):
        value = str(value)
        def runs(value):
            return [(part, number_fonts[size] if part[0].isascii() and part[0].isdigit() else fonts[size])
                    for part in re.split(r'([0-9]+(?:[.,][0-9]+)*)', value) if part]
        def measure(value):
            return sum(draw.textlength(part,font=font) for part,font in runs(value))
        while len(value)>1 and measure(value)>limit:
            value=value[:-2]+'…'
        for part,font in runs(value):
            draw.text((x,y+size),part,font=font,fill=color,anchor='ls')
            x+=draw.textlength(part,font=font)

    def portrait(image,x,y,size,radius=12):
        if image is None:
            return False
        image=ImageOps.fit(image.convert('RGBA'),(size,size),method=Image.Resampling.LANCZOS)
        mask=Image.new('L',(size,size));ImageDraw.Draw(mask).rounded_rectangle((0,0,size-1,size-1),radius=radius,fill=255)
        canvas.paste(image,(x,y),mask)
        return True

    text(24,14,'双方概览',28,limit=width-48)
    for row,(team,label,color) in enumerate([('teammate','队友','#63d6ae'),('enemy','对手','#ff889a')]):
        top=60+row*596
        text(24,top,f'{label}  {len(teams[team])}',20,color)
        if not teams[team]:
            text(24,top+54,'暂无玩家',18,'#a9b9d1')
        for col,player in enumerate(teams[team]):
            x,y=24+col*332,top+30
            panel=Image.new('RGBA',(316,560))
            ImageDraw.Draw(panel).rounded_rectangle(
                (0,0,315,559),radius=18,fill=(22,32,50,205),
                outline=opponent_border(player) if team=='enemy' else (105,124,151,150),
                width=5 if team=='enemy' else 1)
            canvas.alpha_composite(panel,(x,y))
            name,number=player['battletag'].rsplit('#',1)
            avatar=None
            if player.get('_avatar_bytes'):
                try:
                    with Image.open(BytesIO(player['_avatar_bytes'])) as source:
                        avatar=source.convert('RGBA')
                except (OSError,ValueError):
                    pass
            if not portrait(avatar,x+16,y+16,56):
                draw.rounded_rectangle((x+16,y+16,x+72,y+72),radius=12,fill='#34445e')
                text(x+31,y+29,name[:1],24,color,26)
            text(x+84,y+17,name,20,limit=216)
            text(x+84,y+46,'#'+number,16,'#a9b9d1',216)
            if player['status']!='ok':
                text(x+16,y+113,player['message'],18,'#ffba9b')
                continue
            hours=player.get('total_playtime_hours')
            time_color,emphasized=playtime_style(hours)
            text(x+16,y+83,'总时长',16,'#a9b9d1',78)
            if emphasized:
                draw.rounded_rectangle((x+80,y+78,x+300,y+108),radius=8,
                                       fill='#172237',outline=time_color,width=2)
            text(x+88,y+80,'—' if hours is None else f'{hours:,.1f} h',
                 24 if emphasized else 20,time_color,208)
            draw.line((x+16,y+112,x+300,y+112),fill='#41516b')
            text(x+16,y+122,'段位',16,color)
            text(x+244,y+122,f'S{player["season"] or "—"}',16,'#a9b9d1',56)
            for i,rank in enumerate(player['ranks'][:4]):
                rx,ry=x+16+(i%2)*146,y+147+(i//2)*45
                text(rx,ry,ROLE_LABELS.get(rank['role_type'],rank['role_type']),14,'#a9b9d1',138)
                if rank.get('is_history') and rank['score'] > 0:
                    text(rx,ry+18,rank.get('history_season',''),12,'#f3cd86',36)
                level=rank_name_to_icon_level(rank['rank_name']) or raw_rank_score_to_icon_level(rank['score'])
                asset=resolve_resource_dir()/'rank_flat'/f'{level}.png'
                if level and asset.exists():
                    with Image.open(asset) as badge:
                        canvas.alpha_composite(badge.convert('RGBA').resize((100,29),Image.Resampling.LANCZOS),(rx+36,ry+3))
                    text(rx+103,ry+7,rank['tier'],18,'#18263a',28)
                else:
                    label_rank=RANK_LABELS_CN.get(rank['rank_name'],rank['rank_name']) if rank['score']>0 else '未定级'
                    text(rx+38,ry+5,label_rank+str(rank['tier'] if rank['score']>0 else ''),16,limit=100)
            draw.line((x+16,y+235,x+300,y+235),fill='#41516b')
            text(x+16,y+247,'常用英雄',16,color)
            mode='快速' if '快速' in player['hero_source'] else '竞技'
            if '6V6' in player['hero_source']:mode+=' 6V6'
            text(x+226,y+247,mode,14,'#a9b9d1',74)
            if not player['heroes']:
                text(x+16,y+296,'暂无记录',16,'#a9b9d1')
            for i,hero in enumerate(player['heroes'][:3]):
                hx,hy=x+16+i*98,y+278
                info=_find_hero(config,hero['hero_guid'])
                hero_name=info.get('name') or hero['name'] or '未知英雄'
                icon=_load_remote_asset_image(str(info.get('icon') or ''),category='heroes')
                if not portrait(icon,hx+9,hy,64,10):
                    draw.rounded_rectangle((hx+9,hy,hx+73,hy+64),radius=10,fill='#34445e')
                    text(hx+26,hy+20,hero_name[:1],24,color,32)
                text(hx,hy+71,hero_name,16,limit=92)
                text(hx,hy+94,f'{hero["game_time"]/3600:.1f} h',14,'#a9b9d1',92)
            draw.line((x+16,y+400,x+300,y+400),fill='#41516b')
            stats=player.get('recent_stats',{})
            text(x+16,y+407,'近期战绩',14,color)
            for i,(key,mode_label) in enumerate([('quick','快速'),('competitive','竞技')]):
                stat=stats.get(key,{})
                count=stat.get('sample_size',0)
                rate=stat.get('win_rate')
                streak=stat.get('streak')
                sy=y+430+i*27
                # Actual counts remain visible even when the API returns fewer than 24.
                text(x+112+i*94,y+407,f'{mode_label}{count}场'+('*' if stat.get('incomplete') else ''),12,'#a9b9d1',94)
                text(x+16,sy,f'{mode_label}胜率',14,limit=64)
                text(x+80,sy,'—' if rate is None else f'{rate:.0f}%',18,win_rate_color(rate),70)
                text(x+163,sy,'连胜场',14,limit=60)
                text(x+232,sy,'—' if streak is None else f'{streak:+d}' if streak else '0',18,streak_color(streak),65)
            draw.line((x+16,y+490,x+300,y+490),fill='#41516b')
            boards=player['leaderboards']
            if not boards:
                text(x+16,y+509,'省榜暂不可用' if player['leaderboard_status']!='ok' else '暂无省榜',16,'#a9b9d1')
            for i,b in enumerate(boards[:2]):
                info=_find_hero(config,b['hero_guid'])
                province=b['province']
                if not province.endswith(('省','市','区')) and province not in ('全国','香港','澳门','台湾'):
                    province+='省'
                hero_name=info.get('name') or next((h['name'] for h in player['heroes'] if h['hero_guid']==b['hero_guid']),'英雄')
                text(x+16,y+502+i*26,f'{hero_name} · {province}{b["rank"]}强',16,'#f3cd86',284)
    output=BytesIO();canvas.convert('RGB').save(output,format='PNG')
    return output.getvalue()
