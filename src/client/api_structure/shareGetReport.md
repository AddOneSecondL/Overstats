# shareGetReport

来源：2026-11-12 用户提供的 HAR，合并 6 次响应的字段类型。仅记录结构，不包含原始值；空数组的元素结构未知。字段可能缺失，观察类型不代表完整服务端契约。

`GET https://datamsapi.ds.163.com/v1/a19ld5tool/share/getReport`

客户端：`DashenAPIClient.get_share_report`。返回完整 JSON，调用方检查 `code`、`success`，不能只判断 HTTP 200。

参数：gameMode（leisure / sport）、roleType（preset / open）、timeType（sevenDays / today）。默认 sevenDays 用于周总结；实际日期以 dateRange 为准，不假定自然周。未验证所有参数组合。

认证：显式传入 `credential: DashenCredential`，由同一凭据提供查询参数 `server/dts/roleId/token` 和认证头。此处 token 是登录凭据，不是 customerToken。必须选择要查询的账号，不自动轮换账号。

隐私：响应中的玩家 ID、昵称、头像、伙伴关系及 customerTokenMap 都可能敏感；不记录原始请求 URL、认证头或响应。文档中的动态映射键已替换。抓包文件不纳入仓库。

## 响应字段

| 字段 | 观察类型 |
|---|---|
| `$` | object |
| `$.code` | integer |
| `$.data` | object |
| `$.data.daily` | array |
| `$.data.daily[]` | object |
| `$.data.daily[].date` | string |
| `$.data.daily[].loss` | integer |
| `$.data.daily[].win` | integer |
| `$.data.dateRange` | object |
| `$.data.dateRange.end` | integer |
| `$.data.dateRange.start` | integer |
| `$.data.heroTop3` | array |
| `$.data.heroTop3[]` | object |
| `$.data.heroTop3[].gameTimeSeconds` | integer |
| `$.data.heroTop3[].heroGuid` | string |
| `$.data.heroTop3[].matchSum` | integer |
| `$.data.heroTop3[].winRate` | string |
| `$.data.matches` | array |
| `$.data.matches[]` | object |
| `$.data.matches[].assist` | integer |
| `$.data.matches[].beginTs` | integer |
| `$.data.matches[].death` | integer |
| `$.data.matches[].kill` | integer |
| `$.data.matches[].matchId` | string |
| `$.data.overview` | object |
| `$.data.overview.drawSum` | integer |
| `$.data.overview.gameTimeMs` | integer |
| `$.data.overview.lossSum` | integer |
| `$.data.overview.matchSum` | integer |
| `$.data.overview.winRate` | string |
| `$.data.overview.winSum` | integer |
| `$.data.partners` | object |
| `$.data.partners.best` | array |
| `$.data.partners.best[]` | object |
| `$.data.partners.best[].avatar` | string |
| `$.data.partners.best[].bnetId` | integer |
| `$.data.partners.best[].matchSum` | integer |
| `$.data.partners.best[].nickname` | string |
| `$.data.partners.best[].winRate` | string |
| `$.data.partners.worst` | array |
| `$.data.ratingDist` | array |
| `$.data.sportOpenHeroBillboardList` | array |
| `$.data.sportPresetHeroBillboardList` | array |
| `$.data.teamSize` | array |
| `$.data.teamSize[]` | object |
| `$.data.teamSize[].matchSum` | integer |
| `$.data.teamSize[].teamSize` | integer |
| `$.data.teamSize[].winRate` | string |
| `$.data.user` | object |
| `$.data.user.icon` | string |
| `$.data.user.name` | string |
| `$.data.user.title` | string |
| `$.data.user.titleIcon` | string |
| `$.data.userProvinceRankList` | array |
| `$.success` | boolean |
| `$.traceId` | string |
