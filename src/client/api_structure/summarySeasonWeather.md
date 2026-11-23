# 总结晴雨表：当前整赛季概览

今日、昨日、本周总结共用。入口 `engine._get_weather_matches`，分页器 `_fetch_weather_season_matches`。选取当前逻辑赛季，获取 leisure、sport、QuickFight、LeisureFight、SportFight 五个列表，按 matchId 去重并按 beginTs 倒序合并。不回退前一赛季，不使用 45 天截止线。每批默认 2 页，走现有总结请求并发限制；批次全空时结束。任何页失败或连续重复页均报错，不缓存部分结果。

缓存键：玩家查询 token（仅内存）、逻辑赛季、full-season；默认 600 秒，最多 256 个玩家/赛季组合。空赛季也能缓存。原 OVERSTATS_SUMMARY_WEATHER_LOOKBACK_DAYS 不再控制晴雨表。

“整赛季”指遍历接口当前能返回的该赛季记录，不保证上游保留了赛季全部历史。首次缓存未命中比原近 45 天可能请求更多页。这里只拉概览；不会为了晴雨表拉全赛季详情。主体仍先取近 8 天筛选今日/昨日/周，原主体请求仍存在，并未消除其与赛季列表的重复请求。

## 内部数据结构

`weather_matches: list[dict]` → 绘图的 `all_matches` → `weather_source_matches`。以下为字段结构，全部值为占位符或虚构值。普通比赛的已知字段来自 queryMatchList 文档；角斗模式可能缺字段，不强行补零。

```json
{
  "matchId": "<MATCH_ID>",
  "beginTs": 0,
  "matchRet": 1,
  "gameMode": "SportPreset",
  "instanceType": "IT_RANKED",
  "mapGuid": "<MAP_GUID>",
  "heroGuid": "<HERO_GUID>",
  "heroIcon": "<IMAGE_URL>",
  "roleType": "healer",
  "teamScore": 0,
  "opponentScore": 0,
  "kill": 0,
  "assist": 0,
  "death": 0,
  "heroDamage": 0,
  "cure": 0,
  "resistDamage": 0,
  "killMax": false,
  "heroDamageMax": false,
  "cureMax": false,
  "resistDamageMax": false,
  "rankInfo": {},
  "_dashenSeason": 0,
  "_summaryFightOnly": false
}
```

`_dashenSeason` 为本地补充的实际赛季；`_summaryFightOnly` 只在角斗记录上补 true，普通记录通常没有该键。角斗 gameMode 统一为对应查询模式。其余原始字段透传，因此示例不是每种模式都保证具备的固定模型。

## 可以不新增请求计算的内容

| 附加内容 | 使用字段 | 口径限制 |
|---|---|---|
| 赛季总场次、胜负平、胜率 | matchRet | 未知结果另列；数据范围限上游已返回记录 |
| 各地图场次、胜率、最好/最差地图 | mapGuid、matchRet | 地图名称复用本地配置；建议设置最低场数 |
| 各模式/职责表现 | gameMode、instanceType、roleType、matchRet | 不把不同模式混为一类 |
| 常用英雄、按概览英雄分组的胜率 | heroGuid、matchRet | 概览英雄不等于整局唯一英雄，不能还原换人时间 |
| 最长连胜/连败、当前连胜/连败 | beginTs、matchRet | 明确平局、未知结果与不同模式是否打断 |
| 游戏天数、连续活跃天数、最忙的一天 | beginTs | 统一时区；空白日期不等于已经验证无记录 |
| 星期/开局小时胜率与场次热图 | beginTs、matchRet | 这是开局时间分布，不是实际在线时长 |
| 近 7 天与赛季前段的胜率对比 | beginTs、matchRet | 明确样本数量与不重叠比较区间 |
| 单场击杀/助攻/伤害/治疗/承伤纪录 | kill、assist、heroDamage、cure、resistDamage | 字段缺失跳过；按模式/职责分组更公平 |
| 汇总 KDA、均场输出与治疗 | kill、assist、death、heroDamage、cure | 不等于每 10 分钟指标；零死亡处理需说明 |
| 上游最高值标记次数 | killMax 等 | 标记比较范围未经核实，不直接称为全场 MVP |
| 段位快照变化 | rankInfo | 可为空；快照不等于每局准确加减分 |

## 仅靠概览无法可靠增加的内容

整赛季实际游戏时长、每 10 分钟数据、换英雄时长分布、队友搭配与组排规模、每局精确段位增减、真实 MVP。这些所需数据不由当前概览保证提供，通常需要详情或其他接口。已有本次时段详情不代表已有整季详情。

## 展示范围

日历从整季已返回记录的最早比赛日期开始，补齐周一，至最近比赛所在周；面板高度随周数扩展。每日胜负和净胜场折线使用相同整赛季概览。小时活跃图仍使用本次总结时段的比赛和已有详情。今日主体仍按最近 24 小时、相邻开局不超过 5 小时的规则选取。

隐私：不要持久化缓存键、玩家 token、真实 matchId 或整份原始响应到公开文档/测试。新增指标优先输出聚合值。
