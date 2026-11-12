# 璀璨 minitool 生涯数据

来源：用户提供的 2026-11-12 10:04 HAR，实际捕获 career/4.json、career/15.json、career/6.json，均为 HTTP 200 JSON。较早的 09:56 HAR 只记录同一 minitool 的 index.html（304），不足以识别其生涯数据结构。此接口补充此前仅整理实时 leaderboard 接口的遗漏。

`GET https://act.ds.163.com/wp/minitool/b6556abe-49be-426e-9d8c-1fab05ca5d6a/career/{shard_id}.json`

客户端：`DashenAPIClient.cuican_minitool_career(shard_id)`。

这是页面使用的生涯 JSON 分片，每份含多个玩家。文件编号不是玩家 ID，也不能据此解释为赛季编号。后续于 2026-11-12 直接访问页面，确认 HTML 内嵌 window.__CAREER_INDEX__（uids、generatedAt）和 window.__RANKING_DATA__，无需单独请求索引。玩家键映射见下节；更新频率仍未知，不自动遍历下载全部分片。

请求没有查询参数。封装不注入大神凭据、不复制抓包 Cookie，尚未在线验证匿名访问。路径中的固定 UUID 是页面资源标识。响应直接为 `{players: {"<player-key>": ...}}`，没有 code/data 包装；HTTP 错误由客户端抛出。与实时璀璨 leaderboard 服务分开使用，不保证两者同步。

每名玩家包含 profile（资料）、best（历史荣誉）、totals（累计数据）、seasons（赛季及职责统计）。保留原始字段名；winRate、kd 的单位与计算规则未由本抓包验证，不能直接沿用其他接口的规则。数组中未出现元素的类型未知。

隐私：players 的动态键、battletag、头像地址、签名及个人统计都不作为示例保存；下表合并三个分片全部记录的字段类型，不含原始值。调用方不要记录完整响应。

## 响应结构

| 字段 | 观察类型 |
|---|---|
| `$` | object |
| `$.players` | object |
| `$.players.<player-key>` | object |
| `$.players.<player-key>.best` | object |
| `$.players.<player-key>.best.arenaChampion` | integer |
| `$.players.<player-key>.best.arenaSecond` | integer |
| `$.players.<player-key>.best.arenaThird` | integer |
| `$.players.<player-key>.best.finalChampion` | integer |
| `$.players.<player-key>.best.finalSecond` | integer |
| `$.players.<player-key>.best.finalThird` | integer |
| `$.players.<player-key>.best.playoffCount` | integer |
| `$.players.<player-key>.best.rankBest` | integer |
| `$.players.<player-key>.best.rankBestProfession` | string |
| `$.players.<player-key>.best.rankBestSeason` | integer |
| `$.players.<player-key>.best.signature` | string |
| `$.players.<player-key>.profile` | object |
| `$.players.<player-key>.profile.avatar` | string |
| `$.players.<player-key>.profile.battletag` | string |
| `$.players.<player-key>.profile.labels` | array |
| `$.players.<player-key>.profile.labels[]` | integer |
| `$.players.<player-key>.profile.seasonProfession` | string |
| `$.players.<player-key>.profile.seasonRank` | integer |
| `$.players.<player-key>.seasons` | array |
| `$.players.<player-key>.seasons[]` | object |
| `$.players.<player-key>.seasons[].match_type` | integer |
| `$.players.<player-key>.seasons[].match_type_name` | string |
| `$.players.<player-key>.seasons[].professions` | array |
| `$.players.<player-key>.seasons[].professions[]` | object |
| `$.players.<player-key>.seasons[].professions[].assists` | integer |
| `$.players.<player-key>.seasons[].professions[].deaths` | integer |
| `$.players.<player-key>.seasons[].professions[].eliminations` | integer |
| `$.players.<player-key>.seasons[].professions[].finalBlows` | integer |
| `$.players.<player-key>.seasons[].professions[].matches` | integer |
| `$.players.<player-key>.seasons[].professions[].name` | string |
| `$.players.<player-key>.seasons[].professions[].playDuration` | integer |
| `$.players.<player-key>.seasons[].professions[].profession` | integer |
| `$.players.<player-key>.seasons[].professions[].rankNo` | integer |
| `$.players.<player-key>.seasons[].professions[].score` | integer |
| `$.players.<player-key>.seasons[].professions[].soloKills` | integer |
| `$.players.<player-key>.seasons[].professions[].winRate` | integer / number |
| `$.players.<player-key>.seasons[].professions[].wins` | integer |
| `$.players.<player-key>.seasons[].season_id` | string |
| `$.players.<player-key>.seasons[].season_no` | integer |
| `$.players.<player-key>.totals` | object |
| `$.players.<player-key>.totals.assists` | integer |
| `$.players.<player-key>.totals.deaths` | integer |
| `$.players.<player-key>.totals.eliminations` | integer |
| `$.players.<player-key>.totals.finalBlows` | integer |
| `$.players.<player-key>.totals.kd` | integer / number |
| `$.players.<player-key>.totals.matches` | integer |
| `$.players.<player-key>.totals.playDuration` | integer |
| `$.players.<player-key>.totals.soloKills` | integer |
| `$.players.<player-key>.totals.winRate` | integer / number |
| `$.players.<player-key>.totals.wins` | integer |

## 页面内嵌索引与分片映射（2026-11-12 在线核验）

入口：`index.html?season=26s4_ranked&type=1`，HTTP 200。页面优先使用内嵌排行榜、赛季及生涯索引。`/api/ranking`、`/api/seasons` 是内嵌数据缺失时的备用分支，不能仅据代码认定部署环境提供这些接口。

`window.__CAREER_INDEX__.uids` 为可查询的玩家键列表，`generatedAt` 为生成时间。`window.__RANKING_DATA__` 为页面内嵌榜单数据；不要将整份 HTML 作为公开测试夹具保存，其中包含玩家资料。

页面 `uidShard(uid)` 算法：从 hash=0 开始，按 JavaScript UTF-16 code unit 遍历 uid，每步 `hash = (hash * 31 + codeUnit) >>> 0`，最终 `hash % 16`。对应 `career/0.json` 至 `career/15.json` 的地址空间，并未逐个请求确认可用性。已用抓包三个分片的全部 507 个玩家键核验，全部匹配。

页面先检查玩家键是否在索引中，再按需读取一个分片并取 `players[uid]`。`season/type` 用于选择榜单展示，不是分片编号。索引、昵称和玩家键仅在内存分析，文档不保存真实值。
