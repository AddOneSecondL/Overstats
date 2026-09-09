"""A single 24-unit, two-unit-stroke, pure-white parameter icon family."""
from functools import lru_cache
import math

from PIL import Image, ImageDraw


LABEL_KEYS = {
    "伤害": "damage", "治疗": "heal", "冷却": "cooldown", "持续": "duration",
    "充能": "ult_req", "范围": "range", "半径": "radius", "宽度": "width", "高度": "height",
    "射速": "fire_rate", "弹药": "ammo", "耗弹": "ammo_drain", "装弹": "reload_time",
    "弹丸": "pellets", "飞行速度": "pspeed", "弹体半径": "pradius", "扩散": "spread",
    "移速": "mspeed", "移速加成": "mspeed_buff", "减速": "mspeed_slow", "移速惩罚": "mspeed_pen",
    "伤害增幅": "damage_amp", "减伤": "damage_red", "治疗修正": "healing_mod",
    "攻击类型": "shot_type", "施放": "cast_time", "充能次数": "charges",
    "屏障生命": "barrier_health", "护甲": "armor", "生命": "health", "额外生命": "overhealth",
    "DPS": "dps", "HPS": "hps", "击退速度": "kbspeed", "爆头倍率": "headshot_mod",
    "视角": "view_angle", "击退抗性": "kbmod",
}


def stat_icon(key: str = "", label: str = "", size: int = 36) -> Image.Image:
    return _icon(str(key or LABEL_KEYS.get(label, "unknown")), size)


@lru_cache(maxsize=128)
def _icon(key: str, size: int) -> Image.Image:
    scale = max(4, math.ceil(size/24)*2)
    mask = Image.new("L", (24*scale, 24*scale))
    draw = ImageDraw.Draw(mask)
    stroke = 2*scale

    def path(points, close=False):
        points = [(round(x*scale), round(y*scale)) for x, y in points]
        if close:
            points.append(points[0])
        draw.line(points, fill=255, width=stroke, joint="curve")
        for x, y in (points[0], points[-1]):
            r = stroke/2
            draw.ellipse((int(x-r), int(y-r), int(x+r), int(y+r)), fill=255)

    def circle(x, y, r, solid=False):
        box = tuple(round(v*scale) for v in (x-r, y-r, x+r, y+r))
        draw.ellipse(box, fill=255 if solid else None, outline=255, width=stroke)

    def arc(box, start, end):
        draw.arc(tuple(round(v*scale) for v in box), start, end, fill=255, width=stroke)

    def plus(x=12, y=12, r=4):
        path([(x-r, y), (x+r, y)])
        path([(x, y-r), (x, y+r)])

    def shield():
        path([(12,3),(20,6),(19,14),(16,18),(12,21),(8,18),(5,14),(4,6)], True)

    def bullet(x=12, y=3, width=6, height=17):
        path([(x-width/2,y+5),(x,y),(x+width/2,y+5),(x+width/2,y+height),
              (x-width/2,y+height)], True)
        path([(x-width/2,y+height-4),(x+width/2,y+height-4)])

    def arrow(x1, y1, x2, y2):
        path([(x1,y1),(x2,y2)])
        angle = math.atan2(y2-y1,x2-x1)
        path([(x2-4*math.cos(angle-.7),y2-4*math.sin(angle-.7)),(x2,y2),
              (x2-4*math.cos(angle+.7),y2-4*math.sin(angle+.7))])

    if key in {"damage", "damage_amp", "dps"}:
        path([(5,19),(9,15),(6,12),(16,3),(21,3),(21,8),(12,18),(9,15)])
        path([(3,16),(8,21)])
        if key == "damage_amp":
            plus(5,5,2)
        elif key == "dps":
            path([(3,5),(7,5)])
            path([(3,8),(5,8)])
    elif key in {"heal", "healing_mod", "hps"}:
        path([(9,3),(15,3),(15,9),(21,9),(21,15),(15,15),(15,21),(9,21),(9,15),(3,15),(3,9),(9,9)], True)
        if key == "healing_mod":
            circle(12,12,1,True)
        elif key == "hps":
            path([(10,12),(14,12)])
    elif key in {"health", "overhealth"}:
        path([(12,20),(4,12),(3,8),(5,4),(9,4),(12,7),(15,4),(19,4),(21,8),(20,12)], True)
        if key == "overhealth":
            plus(12,12,3)
    elif key in {"armor", "barrier_health", "damage_red", "kbmod"}:
        shield()
        if key == "barrier_health":
            plus(12,11,3)
        elif key == "damage_red":
            path([(9,11),(15,11)])
        elif key == "kbmod":
            path([(8,9),(12,13),(16,9)])
        else:
            path([(12,7),(12,16)])
    elif key in {"cooldown", "reload_time"}:
        arc((3,3,21,21), 40, 330)
        path([(20,3),(20,8),(15,8)])
        if key == "cooldown":
            path([(12,7),(12,12),(15,14)])
        else:
            bullet(11,7,4,10)
    elif key == "duration":
        path([(5,3),(19,3)])
        path([(5,21),(19,21)])
        path([(7,3),(7,7),(17,17),(17,21)])
        path([(17,3),(17,7),(7,17),(7,21)])
    elif key in {"ult_req", "cast_time"}:
        path([(14,3),(5,14),(11,14),(10,21),(19,10),(13,10)], True)
        if key == "cast_time":
            path([(3,5),(6,5)])
            path([(19,19),(21,19)])
    elif key == "charges":
        for x in (5,12,19):
            path([(x-2,6),(x+2,6),(x+2,19),(x-2,19)], True)
            path([(x,3),(x,5)])
    elif key in {"ammo", "ammo_drain"}:
        bullet(7,3,5,17)
        if key == "ammo":
            bullet(17,3,5,17)
        else:
            arrow(17,5,17,19)
    elif key == "pellets":
        for x,y in ((8,7),(17,7),(12,17)):
            circle(x,y,3)
    elif key in {"fire_rate", "pspeed", "mspeed", "mspeed_buff", "mspeed_slow", "mspeed_pen", "kbspeed"}:
        path([(3,7),(9,7)])
        path([(3,12),(7,12)])
        path([(3,17),(9,17)])
        if key == "fire_rate":
            bullet(16,3,6,17)
        else:
            arrow(11,12,21,12)
            if key == "mspeed_buff":
                plus(16,5,2)
            elif key in {"mspeed_slow", "mspeed_pen"}:
                path([(14,5),(18,5)])
            elif key == "kbspeed":
                path([(21,4),(21,8)])
                path([(21,16),(21,20)])
    elif key in {"range", "width", "height"}:
        if key == "height":
            path([(7,3),(17,3)])
            path([(7,21),(17,21)])
            arrow(12,12,12,5)
            arrow(12,12,12,19)
        else:
            path([(3,7),(3,17)])
            path([(21,7),(21,17)])
            arrow(12,12,5,12)
            arrow(12,12,19,12)
    elif key in {"radius", "pradius"}:
        circle(12,12,9)
        circle(12,12,1,True)
        arrow(12,12,18,6)
        if key == "pradius":
            arc((6,6,18,18), 90, 200)
    elif key in {"spread", "view_angle"}:
        path([(4,20),(12,4),(20,20)])
        if key == "spread":
            path([(12,12),(12,20)])
            circle(4,20,1,True)
            circle(20,20,1,True)
        else:
            arc((4,12,20,22), 5, 175)
    elif key in {"shot_type", "headshot_mod"}:
        circle(12,12,6)
        for points in ([(12,2),(12,6)],[(12,18),(12,22)],[(2,12),(6,12)],[(18,12),(22,12)]):
            path(points)
        if key == "headshot_mod":
            circle(12,12,2,True)
    else:
        for y,x in ((6,8),(12,16),(18,10)):
            path([(3,y),(21,y)])
            circle(x,y,2)
    # Draw alpha only: all visible RGB pixels remain exactly white, including AA.
    icon = Image.new("RGBA", (size,size), (255,255,255,0))
    icon.putalpha(mask.resize((size,size), Image.Resampling.LANCZOS))
    return icon
