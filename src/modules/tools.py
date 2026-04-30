from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModuleEntry:
    name: str
    import_path: str
    description: str
    public: bool = True


MODULE_REGISTRY: Dict[str, ModuleEntry] = {}


def register_module(name: str, import_path: str, description: str = "", *, public: bool = True) -> ModuleEntry:
    entry = ModuleEntry(name=name, import_path=import_path, description=description, public=public)
    MODULE_REGISTRY[name] = entry
    return entry


def get_module_registry() -> Dict[str, ModuleEntry]:
    return dict(MODULE_REGISTRY)


def get_public_module_registry() -> Dict[str, ModuleEntry]:
    return {name: entry for name, entry in MODULE_REGISTRY.items() if entry.public}


register_module(
    "query_tool",
    "overstats.src.modules.query_tool",
    "Overwatch query tool config loader and refresher.",
)

register_module(
    "bnet_search",
    "overstats.src.modules.bnet_search",
    "BattleTag search and customer token resolving.",
)

register_module(
    "dashen_match",
    "overstats.src.modules.dashen_match",
    "Dashen match list and detail data orchestration.",
)

register_module(
    "dashen_profile",
    "overstats.src.modules.dashen_profile",
    "Dashen profile card plus sport and leisure count data orchestration.",
)

register_module(
    "dashen_summary",
    "overstats.src.modules.dashen_summary",
    "Dashen daily and periodic summary worker bridge.",
)

register_module(
    "dashen_rank_history",
    "overstats.src.modules.dashen_rank_history",
    "Dashen historical competitive and stadium rank timeline renderer.",
)

register_module(
    "dashen_quick_strength",
    "overstats.src.modules.dashen_quick_strength",
    "Dashen quick-match strength index data builder and PIL renderer.",
)

register_module(
    "dashen_competitive_strength",
    "overstats.src.modules.dashen_competitive_strength",
    "Dashen competitive-match strength index data builder and PIL renderer.",
)

register_module(
    "ow_hero_pick_rate",
    "overstats.src.modules.ow_hero_pick_rate",
    "Global Overwatch hero pick-rate snapshot and history data reader plus PIL renderer.",
)

register_module(
    "ow_shop",
    "overstats.src.modules.ow_shop",
    "Overwatch shop fetcher, cache manager, and PIL renderer.",
)

register_module(
    "patch_notes",
    "overstats.src.modules.patch_notes",
    "Overwatch patch notes fetcher, translator, cache manager, and PIL renderer.",
)

register_module(
    "player_identity_search",
    "overstats.src.modules.player_identity_search",
    "Private local SQLite lookup from Battle.net numeric ID to candidate BattleTags.",
    public=False,
)
