# Overstats

Overstats 是一个基于网易大神上游接口封装的守望先锋本地数据服务。
它提供统一的本地 HTTP API，用于玩家资料查询、近期战绩查询、段位历史查询，以及总结图片生成。

当前仓库的首发重点是 `overstats` 服务本身。仓库里仍然保留了一些历史 `overshop` 相关代码，但第一版发布目标以 `overstats` 为主。

## 功能概览

- Provides a dedicated `ow_shop` module with Battle.net shop JSON and image endpoints.
- Provides a dedicated `patch_notes` module with Blizzard patch-note JSON and image endpoints.

- 提供玩家资料、战绩列表、战绩详情、段位历史、强度分析、总结模块的 HTTP API
- 提供 `dashen_sameplay` 模块，支持双目标同玩列表、详情、全员详细和 AI 锐评
- 提供 `ow_hero_pick_rate` 模块，支持全英雄最新选取率榜单与单英雄历史选取率曲线
- 提供 `dashen_rank_leaderboard` 模块，支持按省/职责查询大神省榜排名
- 提供 `dashen_hero_leaderboard` 模块，支持按省/英雄/队列查询大神英雄榜单排名
- 提供 `auto_route` 模块，LLM 智能路由，支持自然语言自动分发到对应业务模块
- 支持 BattleTag 解析为 `customer_token`
- 支持资料图、战绩图、段位历史图等图片渲染
- 内置本地请求队列，控制上游请求并发
- 内置 SQLite 请求统计记录器
- 支持 query tool 配置加载与静态资源本地缓存
- 兼容当前项目已有的总结渲染运行时与资源文件

## 项目结构

- `overstats/run.py`：本地服务启动入口
- `overstats/config/config.py`：本地运行配置
- `overstats/src/server.py`：HTTP 服务与路由处理
- `overstats/src/client/apiclient.py`：上游 Dashen 请求客户端
- `overstats/src/modules/`：各业务模块实现
- `overstats/src/db/request_metrics.py`：请求统计 SQLite 记录器
- `overstats/res/`：渲染使用的静态资源
- `overstats/test/`：测试与本地验证脚本

## 运行要求

- 推荐 Python 3.11 及以上
- 支持 Windows 或 Linux
- 需要能够访问网易大神相关上游接口

在仓库根目录安装依赖：

```bash
pip install -r requirements.txt
```

## 配置说明

当前本地运行配置集中在 `overstats/config/config.py`。

其中最重要的是 `DASHEN_ACCOUNTS`：

```python
DASHEN_DTS = 2026
DASHEN_SERVER = 1

DASHEN_ACCOUNTS = [
    {
        "name": "account-1",
        "role_id": 123456789,
        "token": "token-a",
    },
    {
        "name": "account-2",
        "role_id": 987654321,
        "token": "token-b",
    },
]

DASHEN_MAX_ACCEPTED_REQUESTS = max(len(DASHEN_ACCOUNTS) * 4, 1)
```

说明：
- 如何获取这两个值请参考 `Faststart.md`
- `token` 同时作为业务请求 token 和 `GL-Bigdata-Auth-Token` 请求头使用
- `DASHEN_DTS` 与 `DASHEN_SERVER` 对所有账号共享
- 服务会在多个账号之间轮转请求，失败账号会进入临时冷却
- `API_HOST`、`API_PORT`、`USE_STREAM_RESPONSE` 用于控制本地服务行为
- `PATCH_NOTES_USE_INTERNATIONAL_PROXY` 与 `PATCH_NOTES_INTERNATIONAL_PROXY` 用于控制外服补丁页面与外服静态资源是否走代理
- 外服补丁翻译复用 `ANALYSIS_BASE_URL`、`ANALYSIS_API_KEY` 和对应模型配置，不再单独维护补丁翻译 key

## 启动方式

在仓库根目录执行：

```bash
python -m overstats.run
```

或者：

```bash
cd overstats
python run.py
```

默认监听地址：

- `http://127.0.0.1:18080`

网页端入口：

- `http://127.0.0.1:18080/`
- 启动服务后，可直接用浏览器访问根路径进入网页控制面板，在左侧选择模块并在右侧查看 JSON、图片和回复预览。

健康检查：

```bash
curl http://127.0.0.1:18080/healthz
```

## 主要 API 端点

- `POST /api/v2/dashen-profile`
- `POST /api/v2/dashen-profile/image`
- `POST /api/v2/dashen-match`
- `POST /api/v2/dashen-match/image`
- `POST /api/v2/dashen-match/replies`
- `POST /api/v2/dashen-match/detail`
- `POST /api/v2/dashen-match/detail/image`
- `POST /api/v2/dashen-match/detail/replies`
- `POST /api/v2/dashen-sameplay`
- `POST /api/v2/dashen-sameplay/image`
- `POST /api/v2/dashen-sameplay/replies`
- `POST /api/v2/dashen-sameplay/detail`
- `POST /api/v2/dashen-sameplay/detail/image`
- `POST /api/v2/dashen-sameplay/detail/replies`
- `POST /api/v2/dashen-rank-history`
- `POST /api/v2/dashen-rank-history/image`
- `POST /api/v2/dashen-quick-strength`
- `POST /api/v2/dashen-quick-strength/image`
- `POST /api/v2/dashen-competitive-strength`
- `POST /api/v2/dashen-competitive-strength/image`
- `POST /api/v2/dashen-rank-leaderboard`
- `POST /api/v2/dashen-rank-leaderboard/image`
- `POST /api/v2/dashen-hero-leaderboard`
- `POST /api/v2/dashen-hero-leaderboard/image`
- `POST /api/v2/ow-hero-pick-rate`
- `POST /api/v2/ow-hero-pick-rate/image`
- `POST /api/v2/dashen-summary/today`
- `POST /api/v2/dashen-summary/today/image`
- `POST /api/v2/dashen-summary/yesterday`
- `POST /api/v2/dashen-summary/yesterday/image`
- `POST /api/v2/dashen-summary/week`
- `POST /api/v2/dashen-summary/week/image`
- `POST /api/v2/ow-esports`
- `POST /api/v2/ow-esports/image`
- `POST /api/v2/ow-shop`
- `POST /api/v2/ow-shop/image`
- `POST /api/v2/auto-route`
- `POST /api/v2/patch-notes`
- `POST /api/v2/patch-notes/image`

更细的请求与响应格式后续可以单独整理成 API 文档。当前以 `overstats/src/server.py` 中实际暴露的路由为准。

## 测试

可以先运行这类基础测试：

```bash
python -m unittest overstats.test.test_dashen_profile_api
python -m unittest overstats.test.test_dashen_summary_today
```

需要注意的是，`overstats/test/` 目录里有一部分文件更偏向本地联调脚本，不完全是纯单元测试，可能依赖本地资源、配置文件或已运行的服务。

## 首版说明

当前第一版可以理解为：

- 一个独立可运行的本地 API 服务
- 以现有 Dashen 请求链路为基础
- 渲染资源直接随仓库提供
- 部分总结运行时仍与历史项目结构共用资源

## 安全提示

发布前请务必检查：

- 不要提交真实的 `token`、`role_id`、Cookie 或 API key
- 将 `overstats/config/config.py` 中的敏感值替换为占位符
- 检查日志、截图、测试数据中是否包含敏感标识

`overstats/config/config.py` 是本地运行配置文件，不适合作为公开仓库中的密钥存储位置。
