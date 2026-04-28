# Overstats API

面向 `overstats` 本地服务的 HTTP 接口说明。

## 服务地址

- 默认：`http://127.0.0.1:18080`
- 健康检查：`GET /healthz`

**healthz 响应示例：**

```json
{
  "ok": true,
  "service": "overstats-core",
  "default_stream": true,
  "dashen_max_concurrent_requests": 2
}
```

## 通用约定

- 除图片接口外，返回 `application/json; charset=utf-8`
- 所有 `POST` 请求体均为 JSON 对象
- 兼容字段别名：
  - `bnet_id` / `bnetId`
  - `customer_token` / `customerToken`
  - `match_id` / `matchId`
  - `index` / `idx`

通用错误格式：

```json
{
  "ok": false,
  "error": "error_code",
  "message": "错误描述",
  "hint": "可选建议",
  "details": {}
}
```

常见错误码：

| 错误码 | 场景 | 解决方式 |
|--------|------|----------|
| `bnet_not_found` | 无法将 `bnet_id` 解析为 `customer_token` | 检查大小写和 `#` 后数字；或直接传入 `customer_token` |
| `invalid_json` | 请求体格式错误 | 检查 `Content-Type` 和 JSON 语法 |

## 1. `dashen_profile`

端点：

- `POST /api/v2/dashen-profile`
- `POST /api/v2/dashen-profile/image`

请求至少提供一项：

- `bnet_id`
- `customer_token`

可选字段：

- `season`
- `include_previous_season`
- `mode`: `quick` / `competitive`

**响应关键字段：**

```json
{
  "ok": true,
  "customer_token": "c2lnbj00OWExMjQ0MDdhNjBkMDhl...",
  "resolved": {
    "query": "Gulee#5667",
    "full_id": "Gulee#5667",
    "bnet_id": "673886420",
    "has_customer_token": true
  },
  "profile_card": {
    "data": {
      "bnetId": 673886420,
      "name": "Gulee#5667",
      "icon": "https://ld5picproxy.ds.163.com/...",
      "title": "纸糊的支援",
      "level": 3,
      "gameTime": "833.28"
    }
  },
  "sport": {
    "data": {
      "guideCountData": [
        {
          "roleType": "healer",
          "lastRankInfo": {
            "rank_name": "Platinum",
            "rank_sub_tier": 5,
            "rankScore": 395
          },
          "matchSum": 62,
          "winRate": "53.23"
        }
      ]
    }
  }
}
```

## 2. `dashen_match`

### 2.1 列表

端点：

- `POST /api/v2/dashen-match`
- `POST /api/v2/dashen-match/image`
- `POST /api/v2/dashen-match/replies`

请求至少提供一项：

- `bnet_id`
- `customer_token`

可选字段：

- `limit`
- `include_fight`
- `include_previous_season`

**`/api/v2/dashen-match` 返回结构：**

```json
{
  "ok": true,
  "customer_token": "...",
  "resolved": { "query": "Gulee#5667", ... },
  "count": 48,
  "matches": [
    {
      "mapGuid": "...",
      "matchId": "6bb47c56-6a77-3448-81b8-bcf414396391",
      "matchRet": 1,
      "instanceType": "IT_RANKED",
      "heroGuid": "...",
      "roleType": "healer",
      "heroIcon": "https://...",
      "teamScore": 2,
      "opponentScore": 0,
      "kill": 9,
      "assist": 10,
      "death": 2,
      "heroDamage": 1966,
      "cure": 8408,
      "cureMax": true,
      "beginTs": 1777098388787,
      "gameMode": "SportPreset",
      "_dashenSeason": 22
    }
  ]
}
```

`/api/v2/dashen-match/replies` 返回：

```json
{
  "ok": true,
  "customer_token": "string",
  "resolved": {
    "query": "Player#12345",
    "full_id": "Player#12345",
    "bnet_id": "12345",
    "has_customer_token": true
  },
  "replies": [
    {
      "type": "meta",
      "meta_type": "ds_match_list",
      "data": {
        "full_id": "Player#12345",
        "resolved": {},
        "match_entries": []
      }
    },
    {
      "type": "image",
      "media_type": "image/png",
      "base64": "..."
    }
  ]
}
```

### 2.2 详情

端点：

- `POST /api/v2/dashen-match/detail`
- `POST /api/v2/dashen-match/detail/image`
- `POST /api/v2/dashen-match/detail/replies`

详情请求方式二选一：

1. `bnet_id|customer_token + index`
2. `customer_token + match_id`

`/api/v2/dashen-match/detail/replies` 额外字段：

- `show_all_heroes: bool`
- `analyze: bool`

**`/api/v2/dashen-match/detail` 返回结构：**

```json
{
  "ok": true,
  "customer_token": "...",
  "resolved": {},
  "match_id": "6bb47c56-6a77-3448-81b8-bcf414396391",
  "match_kind": "normal",
  "source_match": { ... },
  "detail": { ... }
}
```

**`/api/v2/dashen-match/detail/replies` 返回结构：**

```json
{
  "ok": true,
  "customer_token": "string",
  "resolved": {},
  "match_id": "6bb47c56-6a77-3448-81b8-bcf414396391",
  "match_kind": "normal",
  "replies": [
    {
      "type": "meta",
      "meta_type": "ds_match_detail_players",
      "data": {
        "player_ids": [],
        "competitive": true
      }
    },
    {
      "type": "image",
      "media_type": "image/png",
      "base64": "..."
    },
    {
      "type": "image",
      "media_type": "image/png",
      "base64": "..."
    }
  ]
}
```

详情输出规则：

- 默认：主战绩图 + 查询者英雄详细图
- `show_all_heroes=true`：主战绩图 + 全员瀑布图
- `show_all_heroes=true` 且 `analyze=true`：主战绩图 + 全员瀑布图 + AI锐评图
- `match_kind == "fight"`：只返回角斗主图；若请求全员详细 / AI锐评，会追加文本说明

## 3. `dashen_summary`

端点：

- `POST /api/v2/dashen-summary/today`
- `POST /api/v2/dashen-summary/today/image`
- `POST /api/v2/dashen-summary/yesterday`
- `POST /api/v2/dashen-summary/yesterday/image`
- `POST /api/v2/dashen-summary/week`
- `POST /api/v2/dashen-summary/week/image`

请求至少提供一项：

- `bnet_id`
- `full_id`
- `customer_token`

**响应关键字段：**

```json
{
  "ok": true,
  "scope": "today",
  "title": "今日总结",
  "customer_token": "...",
  "resolved": { ... },
  "summary": {
    "worker_url": "local-module",
    "match_count": 3,
    "all_match_count": 307,
    "payload_kb": 361,
    "timings": [
      { "stage": "REQUEST_START", "delta_ms": 0, "total_ms": 0 },
      { "stage": "MATCH_LIST_FETCHED", "delta_ms": 6893, "total_ms": 6893 },
      { "stage": "RENDER_DONE", "delta_ms": 0, "total_ms": 18470 },
      { "stage": "ENCODE_DONE", "delta_ms": 17, "total_ms": 18488 }
    ]
  }
}
```

**超时建议：**

| 范围 | 典型场次 | 渲染耗时 | 建议 timeout |
|------|----------|----------|-------------|
| today | 3~10 场 | ~18s | 30s |
| yesterday | 10~20 场 | ~27s | 45s |
| week | 100~200 场 | **~62s** | **90s+** |

> ⚠️ `week` 数据量大，默认 30s 超时几乎一定失败，请调高 timeout。

`/image` 端点直接返回 `image/png` 二进制流。

## 4. `dashen_rank_history`

端点：

- `POST /api/v2/dashen-rank-history`
- `POST /api/v2/dashen-rank-history/image`

请求至少提供一项：

- `bnet_id`
- `customer_token`

可选字段：

- `start_season`
- `end_season`

**响应关键字段：**

```json
{
  "ok": true,
  "customer_token": "...",
  "resolved": { ... },
  "season_range": {
    "start_season": 15,
    "end_season": 22
  },
  "seasons": [
    {
      "season": 22,
      "has_competitive": true,
      "competitive": {
        "roles": [
          {
            "role_type": "healer",
            "match_sum": 62,
            "win_rate": 53.23,
            "current": {
              "rankScore": 395,
              "rank_sub_tier": 5,
              "rank_level": 4
            },
            "peak": {
              "rankScore": 395,
              "rank_sub_tier": 5,
              "rank_level": 4
            }
          }
        ]
      },
      "stadium": null
    }
  ],
  "missing_assets": [
    "overstats/res/season_logo/s22.png"
  ]
}
```

## 5. 其他公共接口

### `POST /api/v2/query`

默认流式响应（`default_stream: true`），返回 NDJSON（每行一个 JSON 对象）：

```ndjson
{"type": "meta", "data": {"route": "default", "stream": true}}
{"type": "text", "data": "overstats core received: default"}
{"type": "done", "data": {"ok": true}}
```

### `GET /healthz`

```json
{
  "ok": true,
  "service": "overstats-core",
  "default_stream": true,
  "dashen_max_concurrent_requests": 2
}
```
