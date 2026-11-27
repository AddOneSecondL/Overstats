"""Queue and role identifiers shared by Dashen season and rank-history APIs."""

ROLE_LABELS = {"tank": "重装", "dps": "输出", "healer": "支援"}
QUEUE_LABELS = {"preset": "预设职责", "open": "开放职责", "stadium": "角斗领域", "unknown": "竞技排位"}
ROLE_GUIDS = {
    972777519512029264: "tank",
    972777519512029262: "dps",
    972777519512029265: "healer",
}
QUEUE_MODES = {
    "sportpreset": "preset", "preset": "preset", "预设职责": "preset",
    "sportopen": "open", "open": "open", "开放职责": "open",
    "sportfight": "stadium", "stadium": "stadium", "角斗领域": "stadium",
}
RANK_QUEUE_ORDER = (
    "preset:tank", "preset:dps", "preset:healer", "open:overall",
    "stadium:tank", "stadium:dps", "stadium:healer",
)


def queue_mode(value):
    return QUEUE_MODES.get(str(value or "").strip().casefold())


def normalize_rank_role(value):
    role = str(value or "").strip().casefold()
    if role == "support":
        return "healer"
    if role in ROLE_LABELS or role == "open":
        return role
    try:
        role_id = int(role, 16 if role.startswith("0x") else 10)
    except ValueError:
        return None
    return ROLE_GUIDS.get(role_id)


def rank_queue_key(queue, role):
    if queue == "open":
        return "open:overall"
    if queue in ("preset", "stadium") and role in ROLE_LABELS:
        return f"{queue}:{role}"
    return None


def rank_card_track(card, scope):
    """Classify a role card from queryCountInfo or fight/queryCount."""
    role = next((role for field in ("roleType", "role_type", "roleGuid", "role_guid")
                 if (role := normalize_rank_role(card.get(field)))), None)
    mode = card.get("gameMode") or card.get("game_mode")
    queue = queue_mode(mode)
    if scope == "stadium":
        return ("stadium", role) if queue in (None, "stadium") and role in ROLE_LABELS else (None, role)
    if queue == "open":
        return "open", "open"
    if (queue is None and str(mode or "").strip().casefold() in {"", "sport"}) or queue == "preset":
        return "open" if role == "open" and queue is None else "preset", role
    return None, role
