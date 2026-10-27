"""Versioned editorial style tags; official roles remain separate from style weights."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path


CATALOG_PATH = Path(__file__).with_name("hero_tags.json")
TACTICS = ("放狗", "地推", "消耗")
WEAPONS = ("长枪", "短枪", "其他")
SCALARS = ("mobility", "flank", "independence", "team_utility")
ROLES = ("输出", "重装", "支援")


def _weight(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 1)


def _distribution(value, names):
    return (isinstance(value, dict) and set(value) == set(names)
            and all(_weight(value[key]) for key in names)
            and math.isclose(sum(value.values()), 1.0, abs_tol=1e-8))


def validate_catalog(catalog):
    """Fail explicitly on malformed editorial data rather than silently scoring it."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("version"), str) or not catalog["version"]:
        raise ValueError("Hero tag catalog requires a version.")
    heroes = catalog.get("heroes")
    if not isinstance(heroes, dict) or not heroes:
        raise ValueError("Hero tag catalog requires heroes.")
    identifiers = set()
    for name, hero in heroes.items():
        if not isinstance(hero, dict) or hero.get("name") != name:
            raise ValueError(f"Hero name mismatch: {name}")
        if hero.get("role") not in ROLES or not hero.get("subrole"):
            raise ValueError(f"Hero role/subrole missing: {name}")
        hero_id = hero.get("hero_id")
        if not isinstance(hero_id, str) or not hero_id or hero_id in identifiers:
            raise ValueError(f"Hero ID missing or duplicated: {name}")
        identifiers.add(hero_id)
        if not _distribution(hero.get("tactics"), TACTICS):
            raise ValueError(f"Tactics weights must sum to one: {name}")
        weapon = hero.get("weapon")
        if hero["role"] == "输出":
            if not _distribution(weapon, WEAPONS):
                raise ValueError(f"Damage hero weapon weights must sum to one: {name}")
        elif weapon is not None:
            raise ValueError(f"Non-damage hero must not enter the weapon dimension: {name}")
        if any(not _weight(hero.get(key)) for key in SCALARS):
            raise ValueError(f"Invalid scalar style weight: {name}")
        labels = hero.get("labels")
        if not isinstance(labels, list) or len(labels) < 2 or any(not isinstance(v, str) or not v for v in labels):
            raise ValueError(f"Hero needs explanatory labels: {name}")
        if not hero.get("rationale") or not hero.get("source") or not hero.get("evidence"):
            raise ValueError(f"Hero needs traceable evidence: {name}")
    return catalog


@lru_cache(maxsize=4)
def _read_catalog(path, stamp, size):
    del stamp, size
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return validate_catalog(data)


def load_catalog(path=None):
    """Return an isolated catalog; caller edits cannot mutate cached shared tags."""
    source = Path(path) if path is not None else CATALOG_PATH
    stat = source.stat()
    return deepcopy(_read_catalog(str(source.resolve()), stat.st_mtime_ns, stat.st_size))


def resolve_hero_tag(hero, catalog=None):
    """Resolve names, official slugs and the local GUID forms without guessing IDs."""
    data = catalog if catalog is not None else load_catalog()
    if isinstance(hero, dict):
        candidates = [hero.get(key) for key in ("hero_name", "name", "Name", "hero_id", "heroId", "hero_guid", "heroGuid", "id")]
    else:
        candidates = [hero]
    candidates = {str(value).strip().casefold() for value in candidates if value is not None and str(value).strip()}
    for row in data["heroes"].values():
        names = [row["name"], row["hero_id"], row.get("slug"), row.get("config_guid"), *row.get("aliases", [])]
        if candidates.intersection(str(value).casefold() for value in names if value):
            return deepcopy(row)
    return None


def catalog_coverage(catalog, config):
    """Report roster drift explicitly so a future hero cannot disappear unnoticed."""
    configured = {h["Name"] for h in config.get("heroConfig", {}).values()
                  if isinstance(h, dict) and h.get("IsHero") and h.get("Name")}
    tagged = set(catalog["heroes"])
    return {"configured_count": len(configured), "tagged_count": len(tagged),
            "missing": sorted(configured - tagged), "extra": sorted(tagged - configured)}
