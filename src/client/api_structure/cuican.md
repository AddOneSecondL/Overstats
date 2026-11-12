# 璀璨排位赛查询 API

来源：工作区 2026-11-05 璀璨抓包研究及后续匿名查询验证。2026-11-12 09:56 HAR 不含这些实时 leaderboard 请求。10:04 HAR 另含 minitool 生涯 JSON，见 [cuicanMinitoolCareer.md](cuicanMinitoolCareer.md)。本次仅整理现有证据，未重新在线验证。

Base URL：`https://webapi.blizzard.cn/ow-cuican-qualifying-server`。以下均为 GET，客户端返回完整 JSON；检查 `code == 0`，响应通常为 `{code, message, data}`。

| 客户端方法 | 路径 | 参数 | data 结构 |
|---|---|---|---|
| cuican_seasons | /leaderboard/seasons | 无 | event_types[].season_id/season_no/match_types |
| cuican_ranking | /leaderboard/ranking | season_id, profession, match_type | rankings[], my_rank, my_info |
| cuican_search | /leaderboard/search | key_word, season_id, match_type | rankings[] |
| cuican_active_professions | /leaderboard/player/active-professions | user_id, user_token, season_id, match_type | professions |
| cuican_best_records | /leaderboard/player/best-records | user_id, user_token | 基本资料与荣誉，完整字段未在此约束 |
| cuican_season_stats | /leaderboard/player/season-stats | user_id, user_token, season_id, profession, match_type | matches, wins, play_duration 等累计统计 |
| cuican_matches | /leaderboard/player/matches | user_id, user_token, season_id, profession, match_type, last_id, page_size | matches[], last_id, has_more；对局含 match_id, match_id_token |
| cuican_match_detail | /leaderboard/match/detail | match_id, season_id, match_id_token | team_a.player_stats[], team_b.player_stats[] |

`match_type`：1 排位赛（默认），2 体验赛，3 季后赛；不是每个赛季都支持所有类型。赛季从 seasons 获取，不硬编码当前赛季。`profession`：1 重装、2 输出、3 支援；0 仅已知可用于 matches 的全部职责查询。matches 初始游标 -1、默认 page_size 20，后续使用响应 last_id，依据 has_more 终止。

rankings 短字段：r 名次、ui 玩家 ID、ut 查询 token、b 昵称、a 头像、si 签名、p 职责、s 竞等分、m 场次、w 胜场。排行榜 m/w 可能为零，不能替代赛季统计。my_rank=-1、my_info=null 不一定是失败。

查询链：seasons → ranking/search → 用 ui/ut 查询玩家统计及列表 → 用 match_id/match_id_token 查询详情。查询 token 必须来自上游响应，不能省略或用大神登录 token 替代。

这些封装不注入大神认证信息，不读取本地 Cookie 或令牌文件。返回值可能包含身份及查询令牌，不应原样记录、发布或作为测试样本。本次不封装报名、匹配和其他写操作。
