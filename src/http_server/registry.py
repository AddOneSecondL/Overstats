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
        title="\u73a9\u5bb6\u8d44\u6599",
        description="\u67e5\u770b\u57fa\u7840\u751f\u6daf\u8d44\u6599\uff0c\u652f\u6301 JSON \u6216\u56fe\u7247\u5361\u7247\u3002",
        json_endpoint="/api/v2/dashen-profile",
        image_endpoint="/api/v2/dashen-profile/image",
        fields=(
            _number_field("season", "\u8d5b\u5b63", "season", placeholder="\u7559\u7a7a\u4e3a\u5f53\u524d\u8d5b\u5b63"),
            _bool_field(
                "include_previous_season",
                "\u5141\u8bb8\u56de\u9000\u4e0a\u8d5b\u5b63",
                "include_previous_season",
                default=True,
            ),
            _select_field(
                "profile_mode",
                "\u8d44\u6599\u6a21\u5f0f",
                "mode",
                default="quick",
                options=(
                    HTTPUIFieldOption("quick", "\u5feb\u901f"),
                    HTTPUIFieldOption("competitive", "\u7ade\u6280"),
                ),
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-match",
        title="\u8fd1\u671f\u5bf9\u5c40",
        description="\u67e5\u770b\u8fd1\u671f\u5bf9\u5c40\u5217\u8868\uff0c\u652f\u6301 JSON \u6216\u6218\u7ee9\u56fe\u7247\u3002",
        json_endpoint="/api/v2/dashen-match",
        image_endpoint="/api/v2/dashen-match/image",
        fields=(
            _number_field("limit", "\u6570\u91cf", "limit", placeholder="\u9ed8\u8ba4 20", default="20"),
            _bool_field("include_fight", "\u5305\u542b\u89d2\u6597\u9886\u57df", "include_fight", default=True),
            _bool_field(
                "include_previous_season",
                "\u5141\u8bb8\u56de\u9000\u4e0a\u8d5b\u5b63",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-match-detail",
        title="\u5355\u5c40\u5bf9\u5c40\u8be6\u60c5",
        description="\u67e5\u770b\u5355\u5c40\u4e3b\u9762\u677f\u3001\u8be6\u7ec6\u4fe1\u606f\u548c AI \u603b\u7ed3\uff0cJSON \u56de\u590d\u4f1a\u76f4\u63a5\u5728 HTML \u4e2d\u5c55\u5f00\u3002",
        json_endpoint="/api/v2/dashen-match/detail/replies",
        image_endpoint="/api/v2/dashen-match/detail/image",
        fields=(
            _number_field(
                "index",
                "\u5bf9\u5c40\u7d22\u5f15",
                "index",
                placeholder="\u9ed8\u8ba4 0",
                default="0",
                help_text="\u4ece\u8fd1\u671f\u5bf9\u5c40\u5217\u8868\u6309 0 \u5f00\u59cb\u53d6\u503c\u3002",
            ),
            _number_field(
                "limit",
                "\u56de\u6eaf\u6570\u91cf",
                "limit",
                placeholder="\u9ed8\u8ba4 20",
                default="20",
                help_text="\u5148\u62c9\u53d6\u591a\u5c11\u573a\u8fd1\u671f\u5bf9\u5c40\uff0c\u518d\u6309\u7d22\u5f15\u5b9a\u4f4d\u5355\u5c40\u3002",
            ),
            _bool_field("include_fight", "\u5305\u542b\u89d2\u6597\u9886\u57df", "include_fight", default=True),
            _bool_field(
                "include_previous_season",
                "\u5141\u8bb8\u56de\u9000\u4e0a\u8d5b\u5b63",
                "include_previous_season",
                default=True,
            ),
            _bool_field(
                "show_all_heroes",
                "\u5c55\u793a\u8be6\u7ec6\u4fe1\u606f",
                "show_all_heroes",
                default=True,
                help_text="\u5f00\u542f\u540e\u5c55\u793a\u5168\u5458\u8be6\u7ec6\uff1b\u5173\u95ed\u65f6\u4ec5\u5c55\u793a\u5f53\u524d\u73a9\u5bb6\u82f1\u96c4\u8be6\u60c5\u3002",
            ),
            _bool_field(
                "analyze",
                "\u751f\u6210 AI \u603b\u7ed3",
                "analyze",
                default=True,
                help_text="\u5f00\u542f\u540e\u4f1a\u8ffd\u52a0 AI \u603b\u7ed3\u5361\u7247\uff0c\u8017\u65f6\u4f1a\u66f4\u957f\u3002",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-rank-history",
        title="\u6bb5\u4f4d\u5386\u53f2",
        description="\u67e5\u770b\u8d5b\u5b63\u6bb5\u4f4d\u53d8\u5316\uff0c\u652f\u6301 JSON \u6216\u56fe\u7247\u3002",
        json_endpoint="/api/v2/dashen-rank-history",
        image_endpoint="/api/v2/dashen-rank-history/image",
        fields=(
            _number_field("start_season", "\u5f00\u59cb\u8d5b\u5b63", "start_season", placeholder="\u81ea\u52a8"),
            _number_field("end_season", "\u7ed3\u675f\u8d5b\u5b63", "end_season", placeholder="\u81ea\u52a8"),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-quick-strength",
        title="\u5feb\u901f\u5f3a\u5ea6",
        description="\u4f30\u7b97\u5feb\u901f\u6a21\u5f0f\u5f3a\u5ea6\uff0c\u652f\u6301 JSON \u6216\u56fe\u7247\u3002",
        json_endpoint="/api/v2/dashen-quick-strength",
        image_endpoint="/api/v2/dashen-quick-strength/image",
        fields=(
            _number_field("limit", "\u6570\u91cf", "limit", placeholder="3-12", default="12"),
            _bool_field(
                "include_previous_season",
                "\u5141\u8bb8\u56de\u9000\u4e0a\u8d5b\u5b63",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-competitive-strength",
        title="\u7ade\u6280\u5f3a\u5ea6",
        description="\u4f30\u7b97\u7ade\u6280\u6a21\u5f0f\u5f3a\u5ea6\uff0c\u652f\u6301 JSON \u6216\u56fe\u7247\u3002",
        json_endpoint="/api/v2/dashen-competitive-strength",
        image_endpoint="/api/v2/dashen-competitive-strength/image",
        fields=(
            _number_field("limit", "\u6570\u91cf", "limit", placeholder="3-12", default="12"),
            _bool_field(
                "include_previous_season",
                "\u5141\u8bb8\u56de\u9000\u4e0a\u8d5b\u5b63",
                "include_previous_season",
                default=True,
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="ow-hero-pick-rate",
        title="\u82f1\u96c4\u9009\u53d6\u7387",
        description="\u67e5\u770b\u5168\u82f1\u96c4\u6700\u65b0\u9009\u53d6\u7387\u699c\u5355\uff0c\u6216\u67e5\u770b\u5355\u4e2a\u82f1\u96c4\u7684\u5386\u53f2\u9009\u53d6\u7387\u66f2\u7ebf\u3002",
        json_endpoint="/api/v2/ow-hero-pick-rate",
        image_endpoint="/api/v2/ow-hero-pick-rate/image",
        requires_target=False,
        fields=(
            _select_field(
                "view",
                "\u89c6\u56fe",
                "view",
                default="ranking",
                options=(
                    HTTPUIFieldOption("ranking", "\u699c\u5355"),
                    HTTPUIFieldOption("history", "\u5386\u53f2"),
                ),
            ),
            _select_field(
                "game_mode",
                "\u6a21\u5f0f",
                "game_mode",
                default="quick",
                options=(
                    HTTPUIFieldOption("quick", "\u5feb\u901f"),
                    HTTPUIFieldOption("competitive", "\u7ade\u6280"),
                ),
            ),
            _select_field(
                "mmr",
                "\u6bb5\u4f4d",
                "mmr",
                default="all",
                options=(
                    HTTPUIFieldOption("all", "\u5168\u6bb5\u4f4d"),
                    HTTPUIFieldOption("Bronze", "\u9752\u94dc"),
                    HTTPUIFieldOption("Silver", "\u767d\u94f6"),
                    HTTPUIFieldOption("Gold", "\u9ec4\u91d1"),
                    HTTPUIFieldOption("Platinum", "\u767d\u91d1"),
                    HTTPUIFieldOption("Diamond", "\u94bb\u77f3"),
                    HTTPUIFieldOption("Master", "\u5927\u5e08"),
                    HTTPUIFieldOption("Grandmaster", "\u5b97\u5e08"),
                    HTTPUIFieldOption("Champion", "\u82f1\u6770"),
                ),
            ),
            HTTPUIFieldSpec(
                id="hero",
                label="\u82f1\u96c4",
                payload_key="hero",
                placeholder="\u4ec5 history \u89c6\u56fe\u4f7f\u7528\uff0c\u652f\u6301\u4e2d\u6587\u540d\u6216 heroGuid",
                help_text="\u4ec5 history \u89c6\u56fe\u4f7f\u7528\u3002",
            ),
            _number_field(
                "history_limit",
                "\u5386\u53f2\u6761\u6570",
                "history_limit",
                placeholder="\u9ed8\u8ba4 20\uff0c\u4ec5 history \u89c6\u56fe\u4f7f\u7528",
                default="20",
                help_text="\u4ec5 history \u89c6\u56fe\u4f7f\u7528\u3002",
            ),
        ),
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-today",
        title="\u4eca\u65e5\u603b\u7ed3",
        description="\u751f\u6210\u4eca\u65e5\u603b\u7ed3\uff1b\u5468\u603b\u7ed3\u4f1a\u66f4\u6162\u4e00\u4e9b\u3002",
        json_endpoint="/api/v2/dashen-summary/today",
        image_endpoint="/api/v2/dashen-summary/today/image",
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-yesterday",
        title="\u6628\u65e5\u603b\u7ed3",
        description="\u751f\u6210\u6628\u65e5\u603b\u7ed3\u3002",
        json_endpoint="/api/v2/dashen-summary/yesterday",
        image_endpoint="/api/v2/dashen-summary/yesterday/image",
    ),
    HTTPUIModuleSpec(
        id="dashen-summary-week",
        title="\u672c\u5468\u603b\u7ed3",
        description="\u751f\u6210\u4e00\u5468\u603b\u7ed3\uff1b\u8fd9\u662f\u6700\u6162\u7684\u4e00\u9879\u3002",
        json_endpoint="/api/v2/dashen-summary/week",
        image_endpoint="/api/v2/dashen-summary/week/image",
    ),
    HTTPUIModuleSpec(
        id="ow-shop",
        title="OW \u5546\u5e97",
        description="\u67e5\u770b\u5f53\u524d\u5546\u5e97\uff0c\u4e0d\u9700\u8981\u73a9\u5bb6\u76ee\u6807\u3002",
        json_endpoint="/api/v2/ow-shop",
        image_endpoint="/api/v2/ow-shop/image",
        requires_target=False,
    ),
    HTTPUIModuleSpec(
        id="patch-notes",
        title="\u8865\u4e01\u8bf4\u660e",
        description="\u67e5\u770b\u6700\u65b0\u8865\u4e01\uff0c\u6216\u6309\u7c7b\u578b\u67e5\u770b\u8865\u4e01\u8bf4\u660e\u3002",
        json_endpoint="/api/v2/patch-notes",
        image_endpoint="/api/v2/patch-notes/image",
        requires_target=False,
        fields=(
            _select_field(
                "patch_kind",
                "\u8865\u4e01\u7c7b\u578b",
                "patch_kind",
                default="latest",
                options=(
                    HTTPUIFieldOption("latest", "\u6700\u65b0"),
                    HTTPUIFieldOption("small", "\u5c0f\u66f4\u65b0"),
                    HTTPUIFieldOption("big", "\u5927\u66f4\u65b0"),
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
