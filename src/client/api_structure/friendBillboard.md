# friendBillboard

来源：2026-11-12 用户提供的 HAR，合并 3 次响应的字段类型。仅记录结构，不包含原始值；空数组的元素结构未知。字段可能缺失，观察类型不代表完整服务端契约。

`GET https://datamsapi.ds.163.com/v1/a19ld5tool/bnFriend/getBillboard`

客户端：`DashenAPIClient.get_friend_billboard`。返回完整 JSON，调用方检查 `code`、`success`，不能只判断 HTTP 200。

参数：season、mode（观察到 LeisurePreset）。oauth 是响应字段，不据此推断授权流程。

认证：显式传入 `credential: DashenCredential`，由同一凭据提供查询参数 `server/dts/roleId/token` 和认证头。此处 token 是登录凭据，不是 customerToken。必须选择要查询的账号，不自动轮换账号。

隐私：响应中的玩家 ID、昵称、头像、伙伴关系及 customerTokenMap 都可能敏感；不记录原始请求 URL、认证头或响应。文档中的动态映射键已替换。抓包文件不纳入仓库。

## 响应字段

| 字段 | 观察类型 |
|---|---|
| `$` | object |
| `$.code` | integer |
| `$.data` | object |
| `$.data.billboardList` | array |
| `$.data.billboardList[]` | object |
| `$.data.billboardList[].bnetAccountName` | string |
| `$.data.billboardList[].bnetId` | integer |
| `$.data.billboardList[].dt` | string |
| `$.data.billboardList[].icon` | string |
| `$.data.billboardList[].matchCnt` | integer |
| `$.data.billboardList[].matchTime` | integer |
| `$.data.billboardList[].maxWinningStreak` | integer |
| `$.data.billboardList[].rulesetQueueGuid` | string |
| `$.data.billboardList[].season` | integer |
| `$.data.billboardList[].title` | string |
| `$.data.billboardList[].titleIcon` | string |
| `$.data.billboardList[].winMatchCnt` | integer |
| `$.data.billboardList[].winRatio` | number |
| `$.data.customerTokenMap` | object |
| `$.data.customerTokenMap.<dynamic-key>` | string |
| `$.data.matchTimeFriend` | object |
| `$.data.matchTimeFriend.bnetAccountName` | string |
| `$.data.matchTimeFriend.bnetId` | integer |
| `$.data.matchTimeFriend.dt` | string |
| `$.data.matchTimeFriend.icon` | string |
| `$.data.matchTimeFriend.matchCnt` | integer |
| `$.data.matchTimeFriend.matchTime` | integer |
| `$.data.matchTimeFriend.maxWinningStreak` | integer |
| `$.data.matchTimeFriend.rulesetQueueGuid` | string |
| `$.data.matchTimeFriend.season` | integer |
| `$.data.matchTimeFriend.title` | string |
| `$.data.matchTimeFriend.titleIcon` | string |
| `$.data.matchTimeFriend.winMatchCnt` | integer |
| `$.data.matchTimeFriend.winRatio` | number |
| `$.data.maxWinningStreakFriend` | object |
| `$.data.maxWinningStreakFriend.bnetAccountName` | string |
| `$.data.maxWinningStreakFriend.bnetId` | integer |
| `$.data.maxWinningStreakFriend.dt` | string |
| `$.data.maxWinningStreakFriend.icon` | string |
| `$.data.maxWinningStreakFriend.matchCnt` | integer |
| `$.data.maxWinningStreakFriend.matchTime` | integer |
| `$.data.maxWinningStreakFriend.maxWinningStreak` | integer |
| `$.data.maxWinningStreakFriend.rulesetQueueGuid` | string |
| `$.data.maxWinningStreakFriend.season` | integer |
| `$.data.maxWinningStreakFriend.title` | string |
| `$.data.maxWinningStreakFriend.titleIcon` | string |
| `$.data.maxWinningStreakFriend.winMatchCnt` | integer |
| `$.data.maxWinningStreakFriend.winRatio` | number |
| `$.data.oauth` | boolean |
| `$.data.rankLevelFriend` | object |
| `$.data.rankLevelFriend.bnetAccountName` | string |
| `$.data.rankLevelFriend.bnetId` | integer |
| `$.data.rankLevelFriend.dt` | string |
| `$.data.rankLevelFriend.icon` | string |
| `$.data.rankLevelFriend.matchCnt` | integer |
| `$.data.rankLevelFriend.matchTime` | integer |
| `$.data.rankLevelFriend.maxWinningStreak` | integer |
| `$.data.rankLevelFriend.rulesetQueueGuid` | string |
| `$.data.rankLevelFriend.season` | integer |
| `$.data.rankLevelFriend.title` | string |
| `$.data.rankLevelFriend.titleIcon` | string |
| `$.data.rankLevelFriend.winMatchCnt` | integer |
| `$.data.rankLevelFriend.winRatio` | number |
| `$.data.winRatioFriend` | object |
| `$.data.winRatioFriend.bnetAccountName` | string |
| `$.data.winRatioFriend.bnetId` | integer |
| `$.data.winRatioFriend.dt` | string |
| `$.data.winRatioFriend.icon` | string |
| `$.data.winRatioFriend.matchCnt` | integer |
| `$.data.winRatioFriend.matchTime` | integer |
| `$.data.winRatioFriend.maxWinningStreak` | integer |
| `$.data.winRatioFriend.rulesetQueueGuid` | string |
| `$.data.winRatioFriend.season` | integer |
| `$.data.winRatioFriend.title` | string |
| `$.data.winRatioFriend.titleIcon` | string |
| `$.data.winRatioFriend.winMatchCnt` | integer |
| `$.data.winRatioFriend.winRatio` | number |
| `$.success` | boolean |
| `$.traceId` | string |
