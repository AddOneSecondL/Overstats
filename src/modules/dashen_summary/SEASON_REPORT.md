# 赛季总结

网页端仍不注册入口，使用现有 HTTP 服务的 POST 接口：

- `/api/v2/dashen-summary/season`：返回筛选后的结构化 `summary`。
- `/api/v2/dashen-summary/season/image`：返回 `image/png`。

```json
{"token": "完整的大神赛季接口 token", "roleId": "玩家数字 ID", "season": 23}
```

`season` 可省略，默认调用项目的 `get_dashen_current_season()` 后减一；当前配置最新赛季为 24，默认报告为 23。显式支持正整数赛季值（含字符串数字），不会把无效值悄悄替换为默认值。`role_id` 是 `roleId` 的别名。

上游 `dts=2026`、`appKey=ld5`、`server=1`，兼容已检查的 16–23 赛季。`dts` 是接口参数，不根据历史赛季年份改写。

## 玩家身份

报告接口本身没有 BattleTag，模块使用报告中与 roleId 匹配的 `myMatchDetail.customerToken`，携带本次请求的认证信息补查 queryCard。只接受返回 bnetId 与目标一致的昵称。历史报告对局详情已过期时，最多补查一次最新已结束赛季报告获取玩家凭证；仍失败则以 roleId 显示，不猜测昵称。

完整 BattleTag 以主昵称和较小的 #编号展示，赛季号放在小标签中。凭证只在请求期间使用，不进入结构化输出或错误信息。

## 版式与字段

`season_report.py` 负责请求、默认赛季、解析；`season_report_render.py` 负责动态排版。复用今日总结的背景、字体、头像缓存、本地段位及职责素材。

- 顶部玩家身份、赛季、职责、模式、首次登陆日期和核心指标。
- 排位表现含段位、最高段位、场次、胜率、常用英雄、省份与排名。未定级使用灰色英杰徽章。
- 赛季足迹保留 season_summary；角斗领域场次与经济展示已存在的值，真实 0 保留，旧赛季缺失时隐藏该行。
- 赛季数据收录 season_overview_summary 中所有非赛事身份字段，排除 competition_team / competition_role / competition_area / competition_rank。
- 代表英雄与英雄专项；完全相同的专项条目去重。效率不因名称含“率”就被误加百分号。
- 单场高光保留伤害、承伤、治疗三类，配地图、英雄、可用段位和最多两个威能。威能标题移除 HTML 标签。
- true_match_summary 单独作为“对局表现”，展示分类场次及示例对局。目前按用户确认保留类型 1/2/3 编号，未推测其官方名称。
- 低胜率英雄使用更小头像、字体和低对比度横条。
- 组队好友与补给箱。补给箱、史诗、传奇分别采用蓝、紫、金色。

## 数据口径与历史兼容

总场次、排位场次、总览场次按各自字段保留，不相加。顶部在线时长使用 season_summary 的精确值，赛季数据中的在线时长使用 overview 的值；接口中两者精度不同。

总览 win_rate 为 0–1，绘制时乘 100；英雄及排位胜率已为 0–100。overview 的各比例按原值标为“排名比例”，不擅自翻转或命名为“超越”。season_summary.ahead_rate 单独显示在线时长超越比例。

overview 的 kill_sum / damage_sum 等字段不保证是完整赛季累计值，故不加“总计”标签，也不据此生成累计图表。高光样本不会累加为赛季总量。

可选数组为 null、空或缺失时兼容；没有低胜率英雄、对局表现、专项、补给箱时收起相应区域。缺失数字显示 —，不会变成 0；素材不可用时保留文字与占位。

无报告（上游 NOT_REPORT_DATA）返回 404；参数无效返回 400；网络、格式或上游业务异常返回 502。玩家名补查失败不阻止生成报告。

## 验证

排位通过同一赛季的竞技与角斗统计接口中的 rulesetQueueGuid 精确匹配，分别标注预设职责、开放职责、角斗领域；职责读取 mode_type，不从常用英雄推断。新增 queue_type、queue_label、role_type 字段。角斗领域使用独立段位名称和图标。补查失败、队列缺失或来源冲突时显示“未识别队列”，保留原始成绩，不猜测归属。

```powershell
python -m unittest discover -s test -p test_season_report.py -v
```

已对两个指定账号的 16–23 赛季响应进行检查，其中有报告的样本用于渲染验证；另以模拟响应覆盖缺少角斗字段、空数据、零值、去重、默认赛季、身份匹配和凭证过滤。
