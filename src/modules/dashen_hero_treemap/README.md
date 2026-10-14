# 英雄云图

## 数据源选择

`config/config.py` 的 `HERO_MODULE_MODE`：`0`、空值或未配置沿用大神；`1` 使用守望先锋助手小程序接口。
这项配置只切换英雄云图，不改变英雄对比或其他模块。请求中的 `mode` 仍是游戏模式，不是数据源开关。

小程序模式仍使用 `POST /api/v2/dashen-hero-treemap`（JSON）和 `/image`（PNG）：

```json
{"bnetID":"123456789","xcxtoken":"<XCXTOKEN>","mode":"quick"}
```

或 `{"bnet_name":"Player#12345","xcxtoken":"<XCXTOKEN>","mode":"competitive"}`。
数字 ID 支持 `bnet_id`、`bnetId`、`bnetID`；完整战网名称也可放在这些字段或 `battle_tag`、`bnet_name`。
名称先复用现有战网搜索模块解析数字 ID；直接传数字 ID 不依赖大神搜索。名称解析仍需要该搜索服务可用。
`xcxtoken` 必须是业务接口票据，不是 `/ow/mp/user/login` 返回的上游 `token`；适配器不负责登录或刷新。
真实凭据只通过请求体传入，不要写入配置、文档或仓库。查询结果、错误和 dataclass repr 不回显凭据。

| mode | 小程序 type | 范围 |
|---|---|---|
| `quick`（默认） | 1 | 快速比赛 |
| `competitive` | 2 | 竞技比赛 |
| `stadium_competitive` | 3 | 角斗领域竞技 |
| `stadium_quick` | 4 | 角斗领域快速 |

目前只支持 `season_id=total` 的生涯累计。请省略 `season`；`include_previous_season` 不适用，不会跨赛季回退。
不把小程序模式映射为大神的职责/开放/6v6队列，`open`、`competitive_open` 和两个 `6v6` 模式会返回 400。
`data_source=mini_program`、`season.scope=total` 标明数据口径。

适配器先读取玩家汇总，再读取完整英雄列表（不是汇总中的前三英雄）。游戏时间为上游取整小时数，转换为秒仅为了兼容渲染；无法恢复精确分钟。
零小时条目不参与面积计算；`hero_count` 和 `total_game_time_sec` 仅统计实际绘制的条目。
胜率、胜场/场次及 KDA 直接读取接口。没有败场与平局的拆分，`loss_sum` 为 null；未提供的威能、特色统计不会从其他口径补齐。

接口结构和 ID 编码见 [miniProgramCombatLog.md](../../client/api_structure/miniProgramCombatLog.md)。

## 大神模式

`POST /api/v2/dashen-hero-treemap/image`，例如 `{"bnet_id":"Player#12345","mode":"quick"}`。
模式：`quick` 快速5v5（默认）、`competitive` 竞技5v5、`quick6v6` 快速6v6、`competitive6v6` 竞技6v6。5v5读取职责队列；6v6只读取v6HeroUseSummaryList，不再以6v6或开放队列静默替代5v5。`season` 可指定赛季。

小卡片显示英雄、胜率、KDA；空间充足时增加时长、场均消灭/助攻/阵亡及特色数据。特色指标按heroAttrList关联，保留每10分钟/场均单位；比率从接口小数换算为百分比，保留一位小数。缺失不补零。KDA优先使用接口值，否则使用同一统计口径计算。

威能：先请求当前赛季对应sport/leisure比赛列表第1、2页，按当前队列过滤并去重，只获取时长前三英雄出现的对局详情。英雄各自的威能记录逐场去重，每个等级展示最多选取的一项，附图标、完整名称及选取次数/该等级有选取记录的场数。多英雄对局不把全场威能归给任意英雄；单英雄时允许使用玩家级记录。失败或无记录时省略，绝不把近期样本当成赛季全量数据。

概括：按职责时长占比和英雄集中度确定两个短词，不推断人格或实力。职责占比至少55%才称主场；第一英雄至少50%为本命专精，否则前三至少70%为三核轮转，其余为广谱英雄池。JSON返回summary，图片标题区同步显示。


开放队列参数：`open` 为快速开放（leisure/openHeroUseSummaryList），`competitive_open` 为竞技开放（sport/openHeroUseSummaryList）。均只读取开放英雄统计并筛选对应比赛，不与职责/6v6混用。
