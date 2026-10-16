from io import BytesIO

from PIL import Image, ImageDraw
from ..dashen_rank_history.render import (_font_chinese, _load_ow_config,
                                         _find_hero, _load_remote_asset_image, ROLE_LABELS)
from ..font_resolver import resolve_resource_dir
try:
    from overstats.src.constants.backgrounds import build_random_map_background
    from overstats.src.constants.ranks import RANK_LABELS_CN, rank_name_to_icon_level, raw_rank_score_to_icon_level
except ModuleNotFoundError:
    from src.constants.backgrounds import build_random_map_background
    from src.constants.ranks import RANK_LABELS_CN, rank_name_to_icon_level, raw_rank_score_to_icon_level


def render_overview(result):
    teams = result['teams']
    columns = max(1, len(teams['teammate']), len(teams['enemy']))
    width, height = 48 + columns * 332, 1400
    canvas = build_random_map_background(
        (width, height), blur_radius=14, brightness=0.85, color=0.9,
        overlay=(12, 22, 38, 100),
        directory=resolve_resource_dir() / 'query_tool_assets' / 'maps',
    )
    if canvas is None:
        canvas = Image.new('RGBA', (width, height), (24, 34, 56, 255))
    draw = ImageDraw.Draw(canvas)
    fonts = {size: _font_chinese(size) for size in (16, 18, 20, 24, 30)}
    config = _load_ow_config()

    def text(x, y, value, size=20, color='#f3f6ff', limit=292):
        value = str(value)
        while len(value) > 1 and draw.textlength(value, font=fonts[size]) > limit:
            value = value[:-2] + '…'
        draw.text((x, y), value, font=fonts[size], fill=color)

    text(24, 18, '双方概览', 30, limit=width-48)
    text(24, 60, '本赛季 · 常用英雄按使用时长排序 · 仅含导出器成功提取的玩家', 18, '#becbdf', width-48)
    for row, (team, label, color) in enumerate([('teammate', '队友', '#63d6ae'), ('enemy', '对手', '#ff889a')]):
        top = 108 + row * 634
        text(24, top, f'{label}  /  {len(teams[team])} 人', 24, color)
        if not teams[team]:
            text(24, top+70, '未导入此侧玩家', 24, '#aebbd0')
        for col, player in enumerate(teams[team]):
            x, y = 24+col*332, top+42
            panel = Image.new('RGBA', (316, 574))
            ImageDraw.Draw(panel).rounded_rectangle((0,0,315,573), radius=18,
                fill=(22,32,50,205), outline=(105,124,151,170), width=1)
            canvas.alpha_composite(panel, (x,y))
            draw.rounded_rectangle((x+16,y+17,x+20,y+61), radius=2, fill=color)
            name, number = player['battletag'].rsplit('#',1)
            text(x+30,y+15,name,24,limit=268)
            text(x+30,y+47,'#'+number,16,'#a9b9d1')
            if player['status'] != 'ok':
                text(x+18,y+112,player['message'],20,'#ffba9b')
                continue
            text(x+18,y+82,f'S{player["season"] or "—"}  当前段位',18,'#b7c5dc')
            for i, rank in enumerate(player['ranks']):
                rx, ry = x+18+(i%2)*146, y+113+(i//2)*49
                label_rank = RANK_LABELS_CN.get(rank['rank_name'], rank['rank_name']) if rank['score'] > 0 else '未定级'
                text(rx,ry,ROLE_LABELS.get(rank['role_type'],rank['role_type']),16,'#a9b9d1',138)
                level = rank_name_to_icon_level(rank['rank_name']) or raw_rank_score_to_icon_level(rank['score'])
                asset = resolve_resource_dir() / 'rank_flat' / f'{level}.png'
                if level and asset.exists():
                    with Image.open(asset) as badge:
                        canvas.alpha_composite(badge.convert('RGBA').resize((108,32),Image.Resampling.LANCZOS),(rx,ry+17))
                    text(rx+72,ry+21,rank['tier'],20,'#18263a',35)
                else:
                    text(rx,ry+20,label_rank+str(rank['tier'] if rank['score'] > 0 else ''),20,limit=138)
            text(x+18,y+221,'常用英雄 TOP 3',20,color)
            text(x+18,y+248,player['hero_source'].replace('英雄使用时长',''),16,'#a9b9d1')
            if not player['heroes']:
                text(x+18,y+289,'暂无英雄使用数据',18,'#a9b9d1')
            for i, hero in enumerate(player['heroes']):
                hy = y+281+i*66
                info = _find_hero(config,hero['hero_guid'])
                icon = _load_remote_asset_image(str(info.get('icon') or ''), category='heroes')
                if icon is not None:
                    canvas.alpha_composite(icon.resize((52,52),Image.Resampling.LANCZOS),(x+18,hy))
                else:
                    draw.rounded_rectangle((x+18,hy,x+70,hy+52),radius=9,fill='#34445e')
                    text(x+35,hy+12,str(i+1),24)
                text(x+82,hy+1,info.get('name') or hero['name'] or hero['hero_guid'],20,limit=216)
                # Upstream gameTime is in seconds, as in the profile module.
                text(x+82,hy+29,f'{hero["game_time"]/3600:.1f} 小时',16,'#a9b9d1',216)
            draw.line((x+18,y+487,x+298,y+487),fill='#41516b')
            boards=player['leaderboards']
            if not boards:
                text(x+18,y+502,'排行榜暂不可用' if player['leaderboard_status'] != 'ok' else '暂无省级英雄上榜记录',16,'#a9b9d1')
            for i,b in enumerate(boards[:2]):
                info=_find_hero(config,b['hero_guid'])
                province=b['province']
                if not province.endswith(('省','市','区')) and province not in ('全国','香港','澳门','台湾'):
                    province += '省'
                text(x+18,y+499+i*28,f'{info.get("name") or b["hero_guid"]} · {province}{b["rank"]}强 · {b["mode"]}',16,'#f3cd86')
            if len(boards)>2:
                text(x+18,y+551,f'另有 {len(boards)-2} 条排名（JSON 可查看全部）',16,'#a9b9d1')
    output=BytesIO()
    canvas.convert('RGB').save(output,format='PNG')
    return output.getvalue()
