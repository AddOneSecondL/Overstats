"""Data-driven fun medals shared by daily and weekly summaries.

Each category nominates its strongest teammate. Rates divided by category
benchmarks make seconds, counts and damage comparable before taking the top six.
These are playful highlight scores, not competitive performance ratings.
"""
from math import isfinite, sqrt


AWARD_LIMIT = 6
MIN_MATCH_SECONDS = 180

# metric, API aliases, title, display label, per-ten-minute scoring benchmark.
RATE_AWARDS = (
    ("objective_time", ("targetCompetingTime",), "推车金", "争夺", 90),
    ("deaths", ("death",), "返场金", "死亡", 10),
    ("damage_taken", ("damageTaken",), "挨打金", "承伤", 15000),
    ("kills", ("kill",), "人头金", "消灭", 25),
    ("assists", ("assist",), "助攻金", "助攻", 20),
    ("damage", ("heroDamage",), "火力金", "伤害", 12000),
    ("healing", ("cure",), "救死扶伤金", "治疗", 10000),
    ("blocked", ("resistDamage",), "铁壁金", "阻挡", 9000),
    ("final_blows", ("finalHit", "finalBlows"), "补刀金", "最后一击", 15),
    ("solo_kills", ("soloKills",), "单挑金", "单杀", 5),
    ("healing_taken", ("healingTaken",), "吃饼金", "受疗", 8000),
)


def _number(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) and value >= 0 else None


def accumulate_award_metrics(contact, player, seconds):
    """Track each metric with its own valid duration; missing is never zero."""
    metrics = contact.setdefault("award_metrics", {})

    def add(key, value, duration=0):
        sample = metrics.setdefault(key, {"total": 0, "seconds": 0, "games": 0})
        sample["total"] += value
        sample["seconds"] += duration
        sample["games"] += 1

    endorsers = player.get("endorserBnetIds")
    if isinstance(endorsers, list):
        add("endorsements", len({str(item) for item in endorsers if item is not None}))

    seconds = _number(seconds)
    if seconds is None or not MIN_MATCH_SECONDS <= seconds <= 21600:
        return
    values = {}
    for key, aliases, *_ in RATE_AWARDS:
        value = next((parsed for alias in aliases if (parsed := _number(player.get(alias))) is not None), None)
        if value is not None:
            values[key] = value
            add(key, value, seconds)
    # A real zero-death game needs activity, not just an empty/missing stat line.
    active = any(values.get(key, 0) > 0 for key in
                 ("kills", "assists", "damage", "healing", "blocked", "final_blows", "solo_kills", "objective_time"))
    if "deaths" in values and (values["deaths"] > 0 or active):
        add("survival", values["deaths"], seconds)


def _rate(metrics, key):
    sample = metrics.get(key) or {}
    total, seconds = _number(sample.get("total")), _number(sample.get("seconds"))
    if total is None or seconds is None or seconds < MIN_MATCH_SECONDS:
        return None
    return total * 600 / seconds


def _value_text(value):
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def select_teammate_awards(stats):
    """Nominate one winner per medal, then show the six strongest categories."""
    winners = {}

    def nominate(title, kind, name, data, score, value):
        if not isfinite(score) or score <= 0:
            return
        games = _number(data.get("games")) or 0
        wins = _number(data.get("wins")) or 0
        # Stable ties matter because layout and drawing both request the awards.
        rank = (-score, -games, -wins, str(name), str(data.get("bnet_id") or ""), kind)
        previous = winners.get(title)
        if previous is None or rank < previous[0]:
            winners[title] = (rank, {"title": title, "kind": kind, "name": name,
                                    "value": value, "score": score})

    for kind, source in (("好友", stats.get("friends") or {}), ("路人", stats.get("stranger_details") or {})):
        for name, data in source.items():
            games = _number(data.get("games")) or 0
            if games <= 0:
                continue
            metrics = data.get("award_metrics") or {}
            for key, _, title, label, benchmark in RATE_AWARDS:
                rate = _rate(metrics, key)
                if rate is None or rate <= 0:
                    continue
                unit = "秒" if key == "objective_time" else ""
                nominate(title, kind, name, data, rate / benchmark,
                         f"{label} {_value_text(rate)}{unit} / 10分钟")

            endorsements = metrics.get("endorsements") or {}
            count = _number(endorsements.get("total")) or 0
            samples = _number(endorsements.get("games")) or 0
            if count > 0 and samples > 0:
                nominate("礼貌金", kind, name, data, count / samples / 2,
                         f"场均被赞 {_value_text(count / samples)} 次")

            heroes = len(data.get("heroes") or set())
            if heroes >= 2:
                nominate("花活金", kind, name, data, sqrt(heroes / 3), f"使用 {heroes} 位英雄")

            survival = _rate(metrics, "survival")
            if survival is not None and survival <= 3 and metrics["survival"]["seconds"] >= 600:
                nominate("不死金", kind, name, data, 6 / (survival + 2),
                         f"死亡 {_value_text(survival)} / 10分钟")

            # Compress cumulative contributions so a week of play does not
            # automatically crowd every rate-based combat highlight out.
            wins = min(games, _number(data.get("wins")) or 0)
            if wins >= 2:
                nominate("上分搭子金", kind, name, data, sqrt(wins / 3) * wins / games,
                         f"同队 {int(wins)}胜 / {int(games)}场 · {wins / games:.0%}")
            if games >= 2:
                nominate("劳模金", kind, name, data, sqrt(games / 5), f"一起打了 {int(games)} 场")

    awards = [entry for _, entry in winners.values()]
    return sorted(awards, key=lambda item: (-item["score"], item["title"]))[:AWARD_LIMIT]
