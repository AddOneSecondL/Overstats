# Overstats

Overstats 是一个基于网易大神上游接口封装的守望先锋本地数据服务。
它提供统一的本地 HTTP API，用于玩家资料查询、近期战绩查询、段位历史查询，以及总结图片生成。

当前仓库的首发重点是 `overstats` 服务本身。仓库里仍然保留了一些历史 `overshop` 相关代码，但第一版发布目标以 `overstats` 为主。

## 功能概览

- Provides a dedicated `ow_shop` module with Battle.net shop JSON and image endpoints.

- Provides a dedicated `ow_guess` module with bot-facing OW quiz replies endpoints.

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
- 猜一猜扩展包按需安装到 `res/ow_guess/packs/`，不随 Git 下载；未安装的扩展题型不会参与随机出题，使用方法见下文。
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
- `POST /api/v2/dashen-match/detail/llm`
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
- `POST /api/v2/ow-guess/replies`
- `POST /api/v2/ow-shop`
- `POST /api/v2/ow-shop/image`
- `POST /api/v2/auto-route`
- `POST /api/v2/patch-notes`
- `POST /api/v2/patch-notes/image`

更细的请求与响应格式后续可以单独整理成 API 文档。当前以 `overstats/src/server.py` 中实际暴露的路由为准。

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
- 检查日志、截图中是否包含敏感标识

`overstats/config/config.py` 是本地运行配置文件，不适合作为公开仓库中的密钥存储位置。

## 扩展包使用方法

扩展包提供猜一猜的可选资源，支持地图音乐和英雄对话。音频存放在 GitHub Release 附件中，不会随 `git clone` 或 `git pull` 下载。

在项目根目录执行：

```bash
# 列出可用扩展包和已安装版本（不加参数也会列出）
python packs.py list

# 自动从 GitHub 下载并安装地图音乐包
python packs.py install map-music

# 英雄对话：播放前一句，猜接话英雄
python packs.py install hero-conversation

# 使用代理下载（替换为服务器可访问的代理地址）
python packs.py install map-music --proxy http://127.0.0.1:7890

# 更新全部已安装且在清单中的扩展包
python packs.py update

# 仅更新地图音乐包
python packs.py update map-music

# 卸载地图音乐包
python packs.py uninstall map-music
```

扩展包版本和下载地址由 `res/ow_guess/packs.json` 管理。更新前先执行 `git pull` 获取最新清单，再执行更新命令。安装会校验资源完整性，安装失败时保留原版本。

使用 `ow猜一猜 对话`（也支持 `接话`、`英雄对话`）开始对话题，限时 45 秒，揭晓时显示双方台词。未安装对应扩展包时不会随机抽到此题型。

可通过环境变量 `OVERSTATS_PACK_ROOT` 将扩展包放在其他磁盘，例如 `E:\OverstatsResources\packs`；安装命令和服务启动时需使用相同的变量值。未设置时仍使用 `res/ow_guess/packs/`。

如果服务器无法访问 GitHub，可手动下载 Release 中的 ZIP，上传服务器后安装：

```bash
python packs.py install map-music --source /path/to/map-music-2026.10.19.2.zip
```

资源安装在 `res/ow_guess/packs/`，该目录已被 Git 忽略。安装完成后无需重启服务，使用已同步更新的 nb2 core 发送 `ow猜一猜 地图音乐` 即可开始；不加参数的随机出题也会包含地图音乐。未安装时，其他内置题型仍可正常使用。

同一个 Release 可以上传多个扩展包 ZIP，每个包独立配置下载地址、版本和 SHA256，并独立安装、更新或卸载。下载附件必须已公开发布，文件名及 Release 标签需与清单中的地址一致；新增题型还需接入相应的出题和回复逻辑。

## 参考项目

- 外服数据获取：[TeKrop/overfast-api](https://github.com/TeKrop/overfast-api)
- 游戏资源提取：[overtools/OWLib（DataTool）](https://github.com/overtools/OWLib)
- 资料与地图音乐来源：[Overwatch Wiki](https://overwatch.fandom.com/wiki/Overwatch_Wiki)
