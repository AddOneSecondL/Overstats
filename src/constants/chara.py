from __future__ import annotations

# 按照代码名-英文名-俗名
CHARA_NAME = {
    "安娜": ["ana", "Ana", "ana", "ANA", "安娜", "鸡妈", "恐怖老太太", "娜娜", "激素老太", "禁疗摩西"],
    "艾什": ["ashe", "Ashe", "ashe", "ASHE", "艾什", "ash", "艾许", "Ash", "ASH", "王母娘娘", "老八"],
    "巴蒂斯特": ["baptiste", "Baptiste", "baptiste", "BAPTISTE", "巴蒂斯特", "巴蒂", "8d", "8D", "八弟", "大76"],
    "堡垒": ["bastion", "Bastion", "bastion", "BASTION", "堡垒"],
    "布丽吉塔": ["brigitte", "Brigitte", "brigitte", "BRIGITTE", "布丽吉塔", "锤妹", "那个女人", "小锤", "锤女", "tiger", "布里", "brig", "nt", "脑瘫"],
    "卡西迪": ["cassidy", "Cassidy", "cassidy", "CASSIDY", "卡西迪", "麦克雷", "天王老子", "幽默左轮人", "麦卡利", "麦爹", "午时已到"],
    "末日铁拳": ["doomfist", "Doomfist", "doomfist", "DOOMFIST", "末日铁拳", "铁拳", "那个男人", "牢肘", "牢大", "毁天灭地", "肘击王", "卤蛋", "屁王", "pva", "上勾拳"],
    "D.Va": ["d.va", "D.va", "dva", "D.VA", "dva", "Dva", "DVA", "宋哈娜", "机甲摩西", "宋荷娜", "网瘾少女"],
    "回声": ["echo", "Echo", "echo", "ECHO", "回声"],
    "源氏": ["genji", "Genji", "genji", "GENJI", "源氏", "忍者", "根基", "飞镖人", "源", "原", "源劈", "原始", "原氏", "有基佬开我裤链", "源批"],
    "半藏": ["hanzo", "Hanzo", "hanzo", "HANZO", "半藏"],
    "骇灾": ["hazard", "Hazard", "hazard", "HAZARD", "骇灾", "三体人", "唐人", "哈扎德", "嗨仔"],
    "伊拉锐": ["illari", "Illari", "illari", "ILLARI", "伊拉锐", "太阳摩西", "光塔摩西", "依拉瑞", "伊拉锐", "日女"],
    "渣客女王": ["junkerqueen", "Junkerqueen", "junker-queen", "JUNKERQUEEN", "渣客女王", "女王", "渣女", "扎克"],
    "狂鼠": ["junkrat", "Junkrat", "junkrat", "JUNKRAT", "狂鼠", "老鼠", "炸弹人"],
    "朱诺": ["juno", "Juno", "juno", "JUNO", "朱诺", "火星摩西", "轨投", "火星雨姐"],
    "雾子": ["kiriko", "Kiriko", "kiriko", "KIRIKO", "雾子", "物资", "污渍", "乌兹"],
    "生命之梭": ["lifeweaver", "Lifeweaver", "lifeweaver", "LIFEWEEVER", "生命之梭", "花男", "男摩西", "大树摩西"],
    "卢西奥": ["lucio", "Lucio", "lucio", "LUCIO", "卢西奥", "dj", "DJ", "Dj", "音乐摩西", "打碟摩西"],
    "毛加": ["mauga", "Mauga", "mauga", "MAUGA", "毛加", "ssvgg", "SSVGG", "Ssvgg", "毛加", "体育生"],
    "美": ["mei", "Mei", "mei", "MEI", "美", "小美", "美妈", "周美玲", "麦克美", "贾玲", "周美灵"],
    "天使": ["mercy", "Mercy", "mercy", "MERCY", "天使", "摩西", "摩西本西", "摩西女", "神秘摩西女", "安吉拉", "angel", "怜悯"],
    "莫伊拉": ["moira", "Moira", "moira", "MOIRA", "莫伊拉", "莫伊", "莫姨"],
    "奥丽莎": ["orisa", "Orisa", "orisa", "ORISA", "奥丽莎", "羊驼", "佐巴杨", "羊", "美羊羊", "左巴杨", "传奇机长", "传奇机长左巴杨", "佐巴扬", "肘巴羊", "金色答辩"],
    "法老之鹰": ["pharah", "Pharah", "pharah", "PHARAH", "法老之鹰", "法鸡", "法拉", "鸡", "瓦鸡", "挖机"],
    "拉玛刹": ["ramattra", "Ramattra", "ramattra", "RAMATTRA", "拉玛刹", "拉玛", "牢玛", "拉答辩", "鲑鱼", "鲑鱼大帝", "老马", "鳜鱼", "紫色答辩"],
    "死神": ["reaper", "Reaper", "reaper", "REAPER", "死神", "活神", "谐星"],
    "莱因哈特": ["reinhardt", "Reinhardt", "reinhardt", "REINHARDT", "莱因哈特", "莱因", "大锤", "大锤哥", "锤哥"],
    "路霸": ["roadhog", "Roadhog", "roadhog", "ROADHOG", "路霸", "猪猪", "猪", "🐖", "🐷"],
    "西格玛": ["sigma", "Sigma", "sigma", "SIGMA", "西格玛", "老大爷", "大爷"],
    "索杰恩": ["sojourn", "Sojourn", "sojourn", "SOJOURN", "索杰恩", "索杰", "索姐", "索", "超人强"],
    "士兵：76": ["soldier76", "Soldier76", "soldier-76", "SOLDIER76", "士兵76", "76", "士兵", "逃兵", "逃兵76", "跑男", "小巴蒂", "小8d", "小8D", "幽默跑步男"],
    "黑影": ["sombra", "Sombra", "sombra", "SOMBRA", "黑影", "邓紫琪", "邓紫棋"],
    "秩序之光": ["symmetra", "Symmetra", "symmetra", "SYMMETRA", "秩序之光", "光子", "光子妹", "光妹", "三妹", "阿三", "辛梅塔"],
    "托比昂": ["torbjorn", "Torbjorn", "torbjorn", "TORBJORN", "托比昂", "托比", "托比昂哥", "托比哥", "中锤", "矮子", "炮台", "矮人"],
    "猎空": ["tracer", "Tracer", "tracer", "TRACER", "猎空", "闪光", "裂空"],
    "探奇": ["venture", "Venture", "venture", "VENTURE", "探奇", "地鼠", "钻机", "轰轰钻机", "丁真", "顶针", "顶真", "末日铁钻", "土行孙", "钻地狗", "钻地婆", "钻头小子"],
    "黑百合": ["widowmaker", "Widowmaker", "widowmaker", "WIDOWMAKER", "黑百合", "百合", "黑寡妇", "狙", "大狙", "紫薯", "紫薯小人"],
    "温斯顿": ["winston", "Winston", "winston", "WINSTON", "温斯顿", "猩猩", "星星", "老詹", "牢詹", "猴子", "詹姆斯"],
    "破坏球": ["wreckingball", "Wreckingball", "wrecking-ball", "WRECKINGBALL", "破坏球", "球球", "球", "仓鼠"],
    "查莉娅": ["zarya", "Zarya", "zarya", "ZARYA", "查莉娅", "毛妹", "俄罗斯雨姐", "雨姐", "东北雨姐", "国潮", "国潮来袭"],
    "禅雅塔": ["zenyatta", "Zenyatta", "zenyatta", "ZENYATTA", "禅雅塔", "和尚", "光头摩西", "悬浮摩西"],
    "弗蕾娅": ["freja", "Freja", "freja", "FREJA", "弗蕾娅", "弗蕾娅大人", "芙蕾雅", "芙蕾雅大人"],
    "无漾": ["wuyang", "Wuyang", "wuyang", "WUYANG", "无漾", "玩水摩西", "水男", "无恙", "水摩西", "五羊"],
    "斩仇": ["vendetta", "Vendetta", "vendetta", "VENDETTA", "斩仇", "Lupa", "lupa", "狼女", "大剑"],
    "安燃": ["anran", "Anran", "anran", "ANRAN", "安燃", "姐姐", "火女", "凤凰女", "不知火舞", "凤凰", "朱雀", "不知火", "火舞", "扇子摩西"],
    "金驭": ["domina", "Domina", "domina", "DOMINA", "金驭", "金玉", "禁欲", "金御", "妈妈", "妈", "总裁", "金羽"],
    "埃姆雷": ["emre", "Emre", "emre", "EMRE", "埃姆雷", "m雷", "M雷", "猫雷", "艾姆雷"],
    "飞天猫": ["jetpackcat", "Jetpack-cat", "jetpackcat", "jetpack-cat", "飞天猫", "耄耋", "哈基米", "猫", "猫猫", "豪猫", "键帽"],
    "瑞稀": ["mizuki", "Mizuki", "mizuki", "MIZUKI", "瑞稀", "瑞希", "斗笠男", "绿帽", "乌龟", "锁链男", "斗笠摩西", "河童", "镰刀男"],
    "西拉": ["sierra", "Sierra", "sierra", "SIERRA", "西拉", "鸟人", "拉稀", "埃科", "希拉", "茜拉", "拉西"],
    "死怨": ["shion", "Shion", "shion", "SHION", "死怨"],
    "D.Mon": ["d.mon","D.Mon","d.mon","D.MON","D.Mon"]
}

RANK_DIST = {
    0: ["青铜", "bronze", "Bronze"],
    1: ["白银", "silver", "Silver"],
    2: ["黄金", "gold", "Gold"],
    3: ["白金", "platinum", "Platinum", "platium", "Platium", "铂金"],
    8: ["翡翠", "emerald", "Emerald"],
    4: ["钻石", "diamond", "Diamond"],
    5: ["大师", "master", "Master", "带师"],
    6: ["宗师", "grandmaster", "Grandmaster", "GM", "gm"],
    7: ["英杰", "champion", "Champion"],
}


def iter_hero_alias_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for hero_name, aliases in CHARA_NAME.items():
        pairs.append((hero_name, hero_name))
        for alias in aliases:
            pairs.append((str(alias), hero_name))
    return pairs
