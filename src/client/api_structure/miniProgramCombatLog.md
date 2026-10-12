# 守望先锋助手：其他玩家战绩与英雄统计

以下仅包含协议结构，不包含真实玩家 ID、战网名称、票据或抓包内容。

Base URL: `https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog`

请求头：`xcxtoken: <XCXTOKEN>`。请求方法均为 GET。

| 路径 | 查询参数 | 用途 |
|---|---|---|
| `/season/total/summary` | `type`, `season_id=total`, `account_id` | 玩家基本信息、总体统计和前三英雄 |
| `/season/total/heroes/summary` | `type`, `season_id=total`, `mode=0`, `account_id` | 完整英雄统计列表，云图使用此接口 |
| `/recently/matches` | `type`, `mode=0`, `account_id` | 近期比赛；不与生涯英雄统计混合 |
| `/season/total/hexagon` | `type`, `season_id=total`, `account_id` | 生涯职责雷达图；云图不依赖 |

URL 模板（`<ENCODED_ID>` 必须再按 URL 查询参数转义）：

```text
https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog/season/total/summary?type=1&season_id=total&account_id=<ENCODED_ID>
https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog/season/total/heroes/summary?type=1&season_id=total&mode=0&account_id=<ENCODED_ID>
https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog/recently/matches?type=1&mode=0&account_id=<ENCODED_ID>
https://webapi.blizzard.cn/ow-combat-logs-api-server/api/ow/combatlog/season/total/hexagon?season_id=total&type=1&account_id=<ENCODED_ID>
```

`type`：1 快速、2 竞技、3 角斗领域竞技、4 角斗领域快速。
这些映射和完整英雄列表路径来自小程序客户端定义；列表读取已通过真实只读请求验证。

## account_id 编码

将九位数字 ID 当作字符串 JSON 编码（包含英文双引号），与 ASCII 常量 `SyC9B6eBOqQ` 逐字节 XOR，再做标准 Base64。
该常量是 ID 混淆规则，不是身份凭据。认证仍由 `xcxtoken` 完成，不绕过目标玩家的隐私控制。
HTTP 客户端应使用 `params` 编码 Base64 中的 `+`、`/`、`=`，不要直接拼接未经转义的参数。
其他长度尚未验证，当前拒绝此类输入，不推断密钥循环规则。

## 响应

HTTP 200 不等于成功，必须检查 JSON `code == 0`。
云图读取 `data.basic_info` 和完整列表响应的 `data.hero_summaries`。
每个英雄包含 `hero_id`、`hero_name`、`hero_role_type`、`simple_summary`。
后者通过 `item_name` 匹配：`胜率.item_value` 为百分数，`胜率.item_comment` 为 `胜场/场次`，`KDA.item_value` 为比值，`游戏时间.item_value` 为取整小时数。
不依赖数组顺序；缺失统计不制造真实数据。`Tank/Damage/Support` 对应重装/输出/支援。

公开头像配置：`https://ld5.res.netease.com/pc/zt/20241115153332/static/heroConfigs.json`，使用 `heroConfigs[].id/headSrc`。
该请求不携带 xcxtoken，仅缓存公开头像元数据。头像失败不影响统计返回。
