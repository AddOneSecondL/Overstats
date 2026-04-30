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

## OW Shop API

Endpoints:

- `POST /api/v2/ow-shop`
- `POST /api/v2/ow-shop/image`

Request body:

```json
{}
```

JSON response shape:

```json
{
  "ok": true,
  "generated_at": "2026-04-29 12:34:56",
  "cache_ttl_seconds": 900,
  "sections": [
    {
      "title": "精选商品",
      "expires_text": "5天3小时12分",
      "item_count": 3,
      "items": [
        {
          "title": "礼包名称",
          "description": "传奇 | 礼包（10件物品）",
          "product_ids": [123, 456],
          "price_raw": 1900,
          "price_currency": "XWC",
          "price_discount_percentage": 50,
          "image_url": "https://catalog.blzstatic.cn/example.png"
        }
      ]
    }
  ]
}
```

The `/image` endpoint returns `image/png` rendered in the same overshop-style card layout used by the legacy bot module.

## Patch Notes API

Endpoints:

- `POST /api/v2/patch-notes`
- `POST /api/v2/patch-notes/image`

Request body:

```json
{}
```

Optional request fields:

```json
{
  "patch_kind": "latest"
}
```

`patch_kind` also accepts `small` or `big`, and `kind` is supported as a compatibility alias.

JSON response shape:

```json
{
  "ok": true,
  "requested_kind": "latest",
  "selected_kind": "latest",
  "source": "en",
  "source_name": "外服",
  "translated": true,
  "summary": "国服最新：2026-04-17\n外服最新：2026-04-18",
  "selected": {
    "title": "April 18, 2026 Retail Patch",
    "section_title": "Hero Updates",
    "date_text": "April 18, 2026",
    "date": "2026-04-18",
    "bucket": "small",
    "bucket_name": "小更新",
    "text": "Patch body",
    "sections": [],
    "hero_updates": []
  },
  "sources": {
    "cn": {
      "source_name": "国服",
      "latest": "2026-04-17",
      "small": "2026-04-17",
      "big": "2026-04-01"
    },
    "en": {
      "source_name": "外服",
      "latest": "2026-04-18",
      "small": "2026-04-18",
      "big": "2026-04-10"
    }
  }
}
```

The `/image` endpoint returns `image/png` rendered in the same dark patch-note card style as the legacy overshop patch note output. External-source translation follows the configured `ANALYSIS_*` model settings, and only translated external renders are persisted under `cache/patch_notes/`.

## Quick Strength API

Endpoints:

- `POST /api/v2/dashen-quick-strength`
- `POST /api/v2/dashen-quick-strength/image`

Request body:

```json
{
  "bnet_id": "Player#12345",
  "limit": 12,
  "include_previous_season": true
}
```

You may provide `customer_token` instead of `bnet_id`. `limit` is clamped to `3-12`.

JSON response shape:

```json
{
  "ok": true,
  "customer_token": "...",
  "full_id": "Player#12345",
  "bnet_id": "123456",
  "resolved": {
    "query": "Player#12345",
    "full_id": "Player#12345",
    "bnet_id": "123456",
    "has_customer_token": true
  },
  "summary": {
    "match_count": 12,
    "overall_avg_score": 2875.4,
    "overall_avg_rank": "Platinum 2",
    "score_range": {
      "min": 2410,
      "max": 3310
    },
    "used_previous_season_fallback": false
  },
  "matches": [
    {
      "match_id": "uuid",
      "begin_ts": 1777098388787,
      "result": 1,
      "map_guid": "map-guid",
      "avg_score": 2920.0,
      "avg_rank": "Platinum 1",
      "role_range": {
        "min": 2510,
        "max": 3350
      },
      "all_role_range": {
        "min": 2320,
        "max": 3470
      },
      "current_role_range": {
        "min": 2550,
        "max": 3220
      },
      "current_all_role_range": {
        "min": 2410,
        "max": 3340
      },
      "team_scores": [3010, 2890, 2760],
      "enemy_scores": [2940, 2810, 2670],
      "team_streak_avg": 1.2,
      "enemy_streak_avg": -0.4
    }
  ]
}
```

The `/image` endpoint returns `image/png` rendered with Pillow instead of matplotlib.

## Competitive Strength API

Endpoints:

- `POST /api/v2/dashen-competitive-strength`
- `POST /api/v2/dashen-competitive-strength/image`

Request body:

```json
{
  "bnet_id": "Player#12345",
  "limit": 12,
  "include_previous_season": true
}
```

You may provide `customer_token` instead of `bnet_id`. `limit` is clamped to `3-12`.

JSON response shape:

```json
{
  "ok": true,
  "customer_token": "...",
  "full_id": "Player#12345",
  "bnet_id": "123456",
  "resolved": {
    "query": "Player#12345",
    "full_id": "Player#12345",
    "bnet_id": "123456",
    "has_customer_token": true
  },
  "summary": {
    "match_count": 12,
    "overall_avg_score": 3322.9,
    "overall_avg_rank": "Diamond 2",
    "score_range": {
      "min": 3138,
      "max": 3657
    },
    "used_previous_season_fallback": false
  },
  "matches": [
    {
      "match_id": "uuid",
      "begin_ts": 1777098388787,
      "result": 1,
      "map_guid": "map-guid",
      "avg_score": 3410.0,
      "avg_rank": "Diamond 1",
      "role_range": {
        "min": 3250,
        "max": 3550
      },
      "all_role_range": {
        "min": 3180,
        "max": 3680
      },
      "current_role_range": {
        "min": 3250,
        "max": 3550
      },
      "current_all_role_range": {
        "min": 3180,
        "max": 3680
      },
      "team_scores": [3450, 3380, 3320],
      "enemy_scores": [3550, 3410, 3250],
      "team_streak_avg": 0.0,
      "enemy_streak_avg": 0.0
    }
  ]
}
```

The `/image` endpoint returns `image/png` rendered with the same PIL layout as quick strength, using the competitive rose-red theme.

## Hero Pick Rate API

Endpoints:

- `POST /api/v2/ow-hero-pick-rate`
- `POST /api/v2/ow-hero-pick-rate/image`

Request body for latest ranking:

```json
{
  "view": "ranking",
  "game_mode": "quick",
  "mmr": "all"
}
```

Request body for hero history:

```json
{
  "view": "history",
  "game_mode": "competitive",
  "mmr": "Master",
  "hero": "安娜",
  "history_limit": 20
}
```

`view` supports `ranking` and `history`. `game_mode` supports `quick` and `competitive`. `mmr` supports `all`, `Bronze`, `Silver`, `Gold`, `Platinum`, `Diamond`, `Master`, `Grandmaster`, and `Champion`.

Ranking JSON response shape:

```json
{
  "ok": true,
  "view": "ranking",
  "region": "cn",
  "game_mode": "quick",
  "mmr": "all",
  "snapshot": {
    "season": 2,
    "ds": "2026-04-29",
    "hero_count": 43
  },
  "heroes": [
    {
      "rank": 1,
      "hero_guid": "ana",
      "hero_name": "安娜",
      "hero_role": "support",
      "selection_ratio": 7.12,
      "ban_ratio": 0.0,
      "win_ratio": 51.4,
      "kda": 4.21,
      "icon_url": "https://..."
    }
  ]
}
```

History JSON response shape:

```json
{
  "ok": true,
  "view": "history",
  "region": "cn",
  "game_mode": "competitive",
  "mmr": "Master",
  "hero": {
    "hero_guid": "ana",
    "hero_name": "安娜",
    "hero_role": "support",
    "icon_url": "https://..."
  },
  "history_limit": 20,
  "history_total": 37,
  "latest": {
    "season": 2,
    "ds": "2026-04-29",
    "selection_ratio": 6.84,
    "ban_ratio": 0.0,
    "win_ratio": 50.9,
    "kda": 4.03
  },
  "series": [
    {
      "season": 1,
      "ds": "2026-04-10",
      "selection_ratio": 4.82,
      "ban_ratio": 0.0,
      "win_ratio": 49.5,
      "kda": 3.88
    }
  ]
}
```

The `/image` endpoint returns `image/png` in the same visual family as quick strength and competitive strength. `quick` uses the blue theme, while `competitive` uses the bright red theme.

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
