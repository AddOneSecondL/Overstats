from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class HTTPUIFieldOption:
    value: str
    label: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "value": self.value,
            "label": self.label,
        }


@dataclass(frozen=True)
class HTTPUIFieldSpec:
    id: str
    label: str
    payload_key: str
    control_type: str = "text"
    placeholder: str = ""
    default: Any = ""
    help_text: str = ""
    options: Tuple[HTTPUIFieldOption, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "payload_key": self.payload_key,
            "control_type": self.control_type,
            "placeholder": self.placeholder,
            "default": self.default,
            "help_text": self.help_text,
            "options": [item.to_dict() for item in self.options],
        }


@dataclass(frozen=True)
class HTTPUIModuleSpec:
    id: str
    title: str
    description: str
    json_endpoint: str
    image_endpoint: str
    requires_target: bool = True
    default_target_key: str = "bnet_id"
    fields: Tuple[HTTPUIFieldSpec, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "json_endpoint": self.json_endpoint,
            "image_endpoint": self.image_endpoint,
            "requires_target": self.requires_target,
            "default_target_key": self.default_target_key,
            "fields": [item.to_dict() for item in self.fields],
        }


def _bool_field(field_id: str, label: str, payload_key: str, *, default: bool, help_text: str = "") -> HTTPUIFieldSpec:
    return HTTPUIFieldSpec(
        id=field_id,
        label=label,
        payload_key=payload_key,
        control_type="checkbox",
        default=bool(default),
        help_text=help_text,
    )


def _number_field(
    field_id: str,
    label: str,
    payload_key: str,
    *,
    placeholder: str = "",
    default: str = "",
    help_text: str = "",
) -> HTTPUIFieldSpec:
    return HTTPUIFieldSpec(
        id=field_id,
        label=label,
        payload_key=payload_key,
        control_type="number",
        placeholder=placeholder,
        default=default,
        help_text=help_text,
    )


def _select_field(
    field_id: str,
    label: str,
    payload_key: str,
    *,
    default: str,
    help_text: str = "",
    options: Tuple[HTTPUIFieldOption, ...],
) -> HTTPUIFieldSpec:
    return HTTPUIFieldSpec(
        id=field_id,
        label=label,
        payload_key=payload_key,
        control_type="select",
        default=default,
        help_text=help_text,
        options=options,
    )


HTTP_UI_MODULE_SPECS: Tuple[HTTPUIModuleSpec, ...] = (
    HTTPUIModuleSpec(
        id="dashen-profile",
        title="玩家资料",
        description="查看基础生涯资料，支持 JSON 或图片卡片。",
        json_endpoint="/api/v2/dashen-profile",
        image_endpoint="/api/v2/dashen-profile/image",
        fields=(
            _number_field("season", "赛季", "season", placeholder="留空为当前赛季"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
            _select_field(
                "profile_mode",
                "资料模式",
                "mode",
                default="quick",
                options=(
                    HTTPUIFieldOption("quick", "快速"),
                    HTTPUIFieldOption("competitive", "竞技"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-hero-treemap",
        title="英雄云图",
        description="按英雄游玩时长生成胜率大盘云图，支持 JSON 或图片输出。",
        json_endpoint="/api/v2/dashen-hero-treemap",
        image_endpoint="/api/v2/dashen-hero-treemap/image",
        fields=(
            _number_field("season", "赛季", "season", placeholder="留空为当前赛季"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
            _select_field(
                "treemap_mode",
                "数据模式",
                "mode",
                default="competitive",
                options=(
                    HTTPUIFieldOption("competitive", "竞技"),
                    HTTPUIFieldOption("quick", "快速"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-match",
        title="近期对局",
        description="查看近期对局列表，支持 JSON 或战绩图片。",
        json_endpoint="/api/v2/dashen-match",
        image_endpoint="/api/v2/dashen-match/image",
        fields=(
            _number_field("limit", "数量", "limit", placeholder="默认 20", default="20"),
            _bool_field("include_fight", "包含角斗领域", "include_fight", default=True),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-match-detail",
        title="单局对局详情",
        description="查看单局主面板、详细信息和 AI 总结，JSON 回复会直接在 HTML 中展开。",
        json_endpoint="/api/v2/dashen-match/detail/replies",
        image_endpoint="/api/v2/dashen-match/detail/image",
        fields=(
            _number_field(
                "index",
                "对局索引",
                "index",
                placeholder="默认 0",
                default="0",
                help_text="从近期对局列表按 0 开始取值。",
            ),
            _number_field(
                "limit",
                "回溯数量",
                "limit",
                placeholder="默认 20",
                default="20",
                help_text="先拉取多少场近期对局，再按索引定位单局。",
            ),
            _bool_field("include_fight", "包含角斗领域", "include_fight", default=True),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
            _bool_field(
                "show_all_heroes",
                "展示详细信息",
                "show_all_heroes",
                default=True,
                help_text="开启后展示全员详细；关闭时仅展示当前玩家英雄详情。",
            ),
            _bool_field(
                "analyze",
                "生成 AI 总结",
                "analyze",
                default=True,
                help_text="开启后会追加 AI 总结卡片，耗时会更长。",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-sameplay",
        title="同玩查询",
        description="查看两位玩家近两赛季的共同快速/竞技对局。",
        json_endpoint="/api/v2/dashen-sameplay",
        image_endpoint="/api/v2/dashen-sameplay/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="player1_bnet_id",
                label="玩家1",
                payload_key="player1_bnet_id",
                placeholder="BattleTag 或 token 请直接写在 raw JSON",
            ),
            HTTPUIFieldSpec(
                id="player2_bnet_id",
                label="玩家2",
                payload_key="player2_bnet_id",
                placeholder="BattleTag 或 token 请直接写在 raw JSON",
            ),
            _number_field("limit", "数量", "limit", placeholder="默认 20", default="20"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-sameplay-detail",
        title="同玩详情",
        description="查看同玩某场对局的主战绩、双人英雄详情、全员详细和 AI 锐评。",
        json_endpoint="/api/v2/dashen-sameplay/detail/replies",
        image_endpoint="/api/v2/dashen-sameplay/detail/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="player1_bnet_id",
                label="玩家1",
                payload_key="player1_bnet_id",
                placeholder="BattleTag 或 token 请直接写在 raw JSON",
            ),
            HTTPUIFieldSpec(
                id="player2_bnet_id",
                label="玩家2",
                payload_key="player2_bnet_id",
                placeholder="BattleTag 或 token 请直接写在 raw JSON",
            ),
            _number_field(
                "index",
                "对局索引",
                "index",
                placeholder="默认 0",
                default="0",
                help_text="从同玩列表按 0 开始取值。",
            ),
            HTTPUIFieldSpec(
                id="match_id",
                label="match_id",
                payload_key="match_id",
                placeholder="可选，与 index 二选一",
            ),
            _number_field("limit", "回溯数量", "limit", placeholder="默认 20", default="20"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
            _bool_field(
                "show_all_heroes",
                "展示全员详细",
                "show_all_heroes",
                default=False,
            ),
            _bool_field(
                "analyze",
                "生成 AI 锐评",
                "analyze",
                default=False,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-rank-history",
        title="段位历史",
        description="查看赛季段位变化，支持 JSON 或图片。",
        json_endpoint="/api/v2/dashen-rank-history",
        image_endpoint="/api/v2/dashen-rank-history/image",
        fields=(
            _number_field("start_season", "开始赛季", "start_season", placeholder="自动"),
            _number_field("end_season", "结束赛季", "end_season", placeholder="自动"),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-quick-strength",
        title="快速强度",
        description="估算快速模式强度，支持 JSON 或图片。",
        json_endpoint="/api/v2/dashen-quick-strength",
        image_endpoint="/api/v2/dashen-quick-strength/image",
        fields=(
            _number_field("limit", "数量", "limit", placeholder="3-12", default="12"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-competitive-strength",
        title="竞技强度",
        description="估算竞技模式强度，支持 JSON 或图片。",
        json_endpoint="/api/v2/dashen-competitive-strength",
        image_endpoint="/api/v2/dashen-competitive-strength/image",
        fields=(
            _number_field("limit", "数量", "limit", placeholder="3-12", default="12"),
            _bool_field(
                "include_previous_season",
                "允许回退上赛季",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-rank-leaderboard",
        title="Dashen 排行榜",
        description="查看 Dashen 省榜，按职责返回 JSON 或榜单图。",
        json_endpoint="/api/v2/dashen-rank-leaderboard",
        image_endpoint="/api/v2/dashen-rank-leaderboard/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="province",
                label="地区",
                payload_key="province",
                placeholder="例如：北京",
            ),
            _select_field(
                "role",
                "职责",
                "role",
                default="tank",
                options=(
                    HTTPUIFieldOption("tank", "重装"),
                    HTTPUIFieldOption("dps", "输出"),
                    HTTPUIFieldOption("healer", "支援"),
                    HTTPUIFieldOption("open", "开放"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-hero-leaderboard",
        title="Dashen 英雄榜",
        description="查看 Dashen 省榜英雄排名，支持 JSON 或榜单图。",
        json_endpoint="/api/v2/dashen-hero-leaderboard",
        image_endpoint="/api/v2/dashen-hero-leaderboard/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="province",
                label="地区",
                payload_key="province",
                placeholder="例如：北京",
            ),
            HTTPUIFieldSpec(
                id="hero",
                label="英雄",
                payload_key="hero",
                placeholder="例如：猎空 / Tracer / heroGuid",
            ),
            _select_field(
                "mode",
                "队列",
                "mode",
                default="preset",
                options=(
                    HTTPUIFieldOption("preset", "预设"),
                    HTTPUIFieldOption("open", "开放"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-hero-pick-rate",
        title="英雄选取率",
        description="查看全英雄最新选取率榜单，或查看单个英雄的历史选取率曲线。",
        json_endpoint="/api/v2/ow-hero-pick-rate",
        image_endpoint="/api/v2/ow-hero-pick-rate/image",
        requires_target=False,
        fields=(
            _select_field(
                "view",
                "视图",
                "view",
                default="ranking",
                options=(
                    HTTPUIFieldOption("ranking", "榜单"),
                    HTTPUIFieldOption("history", "历史"),
                ),
            ),
            _select_field(
                "game_mode",
                "模式",
                "game_mode",
                default="quick",
                options=(
                    HTTPUIFieldOption("quick", "快速"),
                    HTTPUIFieldOption("competitive", "竞技"),
                ),
            ),
            _select_field(
                "mmr",
                "段位",
                "mmr",
                default="all",
                options=(
                    HTTPUIFieldOption("all", "全段位"),
                    HTTPUIFieldOption("Bronze", "青铜"),
                    HTTPUIFieldOption("Silver", "白银"),
                    HTTPUIFieldOption("Gold", "黄金"),
                    HTTPUIFieldOption("Platinum", "白金"),
                    HTTPUIFieldOption("Emerald", "翡翠"),
                    HTTPUIFieldOption("Diamond", "钻石"),
                    HTTPUIFieldOption("Master", "大师"),
                    HTTPUIFieldOption("Grandmaster", "宗师"),
                    HTTPUIFieldOption("Champion", "英杰"),
                ),
            ),
            HTTPUIFieldSpec(
                id="hero",
                label="英雄",
                payload_key="hero",
                placeholder="仅 history 视图使用，支持中文名或 heroGuid",
                help_text="仅 history 视图使用。",
            ),
            _number_field(
                "history_limit",
                "历史条数",
                "history_limit",
                placeholder="默认 20，仅 history 视图使用",
                default="20",
                help_text="仅 history 视图使用。",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-hero-perk",
        title="威能总览",
        description="查看指定英雄的次级/主要威能总览，JSON 返回完整排序，图片展示每档前 2 项。",
        json_endpoint="/api/v2/ow-hero-perk",
        image_endpoint="/api/v2/ow-hero-perk/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="hero",
                label="英雄",
                payload_key="hero",
                placeholder="例如：安娜 / Tracer / heroGuid",
                help_text="支持中文名、常见别名和 heroGuid。",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-hero-wiki",
        title="英雄百科",
        description="查看英雄维基资料卡，或结合当前英雄资料进行问答。",
        json_endpoint="/api/v2/ow_hero_wiki",
        image_endpoint="/api/v2/ow_hero_wiki/image",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="hero",
                label="英雄",
                payload_key="hero",
                placeholder="例如：猎空 / Tracer / heroGuid",
                help_text="支持中文名、英文名、常见别名，以及 hero?问题 的旧格式。",
            ),
            HTTPUIFieldSpec(
                id="question",
                label="问题",
                payload_key="question",
                placeholder="可选，例如：闪现最多有几层？",
                help_text="留空时返回结构化资料卡；填写后返回资料并附带问答结果。",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-today",
        title="今日总结",
        description="生成今日总结；周总结会更慢一些。",
        json_endpoint="/api/v2/dashen-summary/today",
        image_endpoint="/api/v2/dashen-summary/today/image",
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-yesterday",
        title="昨日总结",
        description="生成昨日总结。",
        json_endpoint="/api/v2/dashen-summary/yesterday",
        image_endpoint="/api/v2/dashen-summary/yesterday/image",
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-week",
        title="本周总结",
        description="生成一周总结；这是最慢的一项。",
        json_endpoint="/api/v2/dashen-summary/week",
        image_endpoint="/api/v2/dashen-summary/week/image",
    ),
    HTTPUIModuleSpec(
        id="ow-esports",
        title="OW 赛事",
        description="查看当前 OW 赛事，不需要玩家目标。",
        json_endpoint="/api/v2/ow-esports",
        image_endpoint="/api/v2/ow-esports/image",
        requires_target=False,
    ),
    HTTPUIModuleSpec(
        id="blizzard-player-search",
        title="Blizzard Player Search",
        description="Search public international Overwatch player profiles from Blizzard.",
        json_endpoint="/api/v2/blizzard-player-search",
        image_endpoint="",
        requires_target=False,
        fields=(
            HTTPUIFieldSpec(
                id="name",
                label="Player",
                payload_key="name",
                placeholder="e.g. ABC or ABC#1234",
            ),
            HTTPUIFieldSpec(
                id="blizzard_id",
                label="Blizzard ID",
                payload_key="blizzard_id",
                placeholder="Optional exact-match resolver",
            ),
            HTTPUIFieldSpec(
                id="locale",
                label="Locale",
                payload_key="locale",
                placeholder="zh-tw / en-us",
                default="zh-tw",
            ),
            _select_field(
                "order_by",
                "Sort",
                "order_by",
                default="name:asc",
                options=(
                    HTTPUIFieldOption("name:asc", "Name asc"),
                    HTTPUIFieldOption("name:desc", "Name desc"),
                    HTTPUIFieldOption("last_updated_at:desc", "Updated desc"),
                    HTTPUIFieldOption("last_updated_at:asc", "Updated asc"),
                ),
            ),
            _number_field("offset", "Offset", "offset", placeholder="0", default="0"),
            _number_field("limit", "Limit", "limit", placeholder="20", default="20"),
        ),
    ),
    HTTPUIModuleSpec(
        id="blizzard-profile",
        title="Blizzard Profile",
        description="Query public Blizzard career data and render it with the dashen-profile layout.",
        json_endpoint="/api/v2/blizzard-profile",
        image_endpoint="/api/v2/blizzard-profile/image",
        requires_target=False,
        default_target_key="player_id",
        fields=(
            HTTPUIFieldSpec(
                id="player_id",
                label="Player",
                payload_key="player_id",
                placeholder="e.g. ABC or ABC#1234",
                help_text="Exact BattleTag works best. Name-only queries may require a Blizzard ID if multiple public profiles match.",
            ),
            HTTPUIFieldSpec(
                id="blizzard_id",
                label="Blizzard ID",
                payload_key="blizzard_id",
                placeholder="Optional canonical career id",
            ),
            HTTPUIFieldSpec(
                id="locale",
                label="Locale",
                payload_key="locale",
                placeholder="zh-tw / en-us",
                default="zh-tw",
            ),
            _select_field(
                "profile_mode",
                "Mode",
                "mode",
                default="quick",
                options=(
                    HTTPUIFieldOption("quick", "Quick Play"),
                    HTTPUIFieldOption("competitive", "Competitive"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-guess",
        title="OW 猜一猜",
        description="调用 OW 猜一猜 replies 接口，生成示例请求并直接预览文字、图片或音频题面，方便 API 对接参考。",
        json_endpoint="/api/v2/ow-guess/replies",
        image_endpoint="",
        requires_target=False,
        fields=(
            _select_field(
                "question_type",
                "题型",
                "question_type",
                default="hero_icon",
                help_text="支持 slug、旧数字 ID 和中文标签；这里默认输出标准 question_type 字段。",
                options=(
                    HTTPUIFieldOption("hero_icon", "英雄图标"),
                    HTTPUIFieldOption("map_music", "地图音乐"),
                    HTTPUIFieldOption("skill_icon_hero", "技能图标猜英雄"),
                    HTTPUIFieldOption("perk_icon_hero", "威能图标猜英雄"),
                    HTTPUIFieldOption("map_image", "地图图片"),
                    HTTPUIFieldOption("ult_voice", "终极语音"),
                    HTTPUIFieldOption("hero_silhouette", "猜猜我是谁"),
                    HTTPUIFieldOption("skill_icon_name", "技能图标猜技能名"),
                    HTTPUIFieldOption("hero_description", "描述猜英雄"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-shop",
        title="OW 商店",
        description="查看当前商店，不需要玩家目标。",
        json_endpoint="/api/v2/ow-shop",
        image_endpoint="/api/v2/ow-shop/image",
        requires_target=False,
    ),
    HTTPUIModuleSpec(
        id="patch-notes",
        title="补丁说明",
        description="查看最新补丁，或按类型查看补丁说明。",
        json_endpoint="/api/v2/patch-notes",
        image_endpoint="/api/v2/patch-notes/image",
        requires_target=False,
        fields=(
            _select_field(
                "patch_kind",
                "补丁类型",
                "patch_kind",
                default="latest",
                options=(
                    HTTPUIFieldOption("latest", "最新"),
                    HTTPUIFieldOption("small", "小更新"),
                    HTTPUIFieldOption("big", "大更新"),
                ),
            ),
        ),
    ),
)


def get_http_ui_module_specs() -> Tuple[HTTPUIModuleSpec, ...]:
    return HTTP_UI_MODULE_SPECS


def get_http_ui_bootstrap_payload() -> Dict[str, Any]:
    modules = [item.to_dict() for item in HTTP_UI_MODULE_SPECS]
    return {
        "default_module_id": HTTP_UI_MODULE_SPECS[0].id if HTTP_UI_MODULE_SPECS else "",
        "modules": modules,
    }
