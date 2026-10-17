"""Recent match summaries, separate from lifetime hero usage."""
import asyncio

from ..dashen_profile.requests import extract_match_entries


def unique_matches(matches):
    seen, result = set(), []
    for match in matches:
        key = str(match.get('matchId') or '') or repr(sorted(match.items()))
        if key not in seen:
            seen.add(key)
            result.append(match)
    def timestamp(match):
        try:
            return int(match.get('beginTs') or 0)
        except (ValueError, TypeError):
            return 0
    return sorted(result, key=timestamp, reverse=True)


def match_result(match):
    try:
        value = int(match['matchRet'])
        return value if value in (-1, 0, 1) else None
    except (KeyError, TypeError, ValueError):
        return None


def summarize_matches(matches, *, incomplete=False):
    matches = unique_matches(matches)[:24]
    results = [match_result(match) for match in matches]
    known = [result for result in results if result is not None]
    streak = 0
    if results and results[0] in (-1, 1):
        for result in results:
            if result != results[0]:
                break
            streak += result
    return {'sample_size': len(matches), 'known_results': len(known),
            'win_rate': 100 * known.count(1) / len(known) if known else None,
            'streak': streak if results and results[0] is not None else None,
            'incomplete': incomplete or len(known) != len(results)}


async def fetch_recent(requests, token, mode, season, current, previous):
    matches = []
    incomplete = False

    async def collect():
        nonlocal matches, incomplete
        for season_id, payload in [(season, current), (season - 1, previous)]:
            if season_id < 1 or len(matches) >= 24:
                break
            if payload is None:
                incomplete = True
                break
            rows = extract_match_entries(payload)
            matches = unique_matches(matches + rows)
            # Count endpoints return 12 matches; subsequent pages continue them.
            for page in range(2, 25):
                if len(matches) >= 24 or len(rows) < 12:
                    break
                payload = await requests.get_extra_match_page(token, mode, page=page, logical_season=season_id)
                if payload is None:
                    # The upstream helper conflates empty and unavailable pages.
                    incomplete = True
                    return
                rows = extract_match_entries(payload)
                before = len(matches)
                matches = unique_matches(matches + rows)
                if rows and len(matches) == before:
                    incomplete = True
                    return

    try:
        await asyncio.wait_for(collect(), timeout=10)
    except Exception:
        incomplete = True
    return summarize_matches(matches, incomplete=incomplete)
