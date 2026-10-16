from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from dataclasses import asdict

from ..errors import ModuleError
from ..dashen_profile import DashenProfileQuery, dashen_profile_module
from ..dashen_profile.engine import build_role_panel_entries, _resolve_hero_payload_rows, _payload_data


def decode_players(value):
    def invalid(message):
        raise ModuleError(error='invalid_team_base64', message=message, status_code=400)
    if not isinstance(value, str) or len(value) > 32768:
        invalid('请粘贴带队伍信息的 Base64，长度不能超过 32768 字符。')
    try:
        payload = json.loads(base64.b64decode(''.join(value.split()), validate=True).decode('utf-8'))
    except (ValueError, UnicodeError, binascii.Error, RecursionError):
        invalid('Base64 或 UTF-8 JSON 无效。')
    if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 2:
        invalid('需要导出器版本 2 数据；旧 ID 数组没有队伍信息，请重新导出。')
    players = payload.get('players')
    if not isinstance(players, list) or not 1 <= len(players) <= 24:
        invalid('players 必须包含 1 至 24 个玩家。')
    result, seen = [], set()
    for player in players:
        if not isinstance(player, dict):
            invalid('玩家记录格式无效。')
        tag, team = player.get('battletag'), player.get('team_type')
        if not isinstance(tag, str) or len(tag) > 128 or not re.fullmatch(r'[^#\s\x00-\x1f]+#[0-9]{4,12}', tag):
            invalid('每个玩家都需要完整 BattleTag（名字#数字）。')
        if team not in ('teammate', 'enemy'):
            invalid('team_type 必须是 teammate 或 enemy。')
        if tag in seen:
            invalid('同一 BattleTag 不能重复或出现在双方。')
        seen.add(tag)
        result.append({'battletag': tag, 'team_type': team})
    return result


def summarize(bundle, billboard):
    sport, leisure = _payload_data(bundle.sport), _payload_data(bundle.leisure)
    title, heroes = _resolve_hero_payload_rows(sport, quick_mode=False)
    if not heroes:
        title, heroes = _resolve_hero_payload_rows(leisure, quick_mode=True)
    boards = []
    data = _payload_data(billboard)
    for key, mode in [('sportPresetHeroBillboardList', '职责'), ('sportOpenHeroBillboardList', '开放')]:
        for item in data.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            try:
                rank = int(item.get('rankNum') or 0)
            except (ValueError, TypeError):
                continue
            if rank > 0 and item.get('province') and item.get('heroGuid'):
                boards.append({'hero_guid': str(item['heroGuid']), 'province': str(item['province']),
                               'rank': rank, 'mode': mode})
    return {
        'season': bundle.logical_season,
        'hero_source': title,
        'heroes': [{'hero_guid': str(h.get('heroGuid') or h.get('heroId') or ''),
                    'name': str(h.get('heroName') or ''), 'game_time': float(h.get('gameTime') or 0)}
                   for h in heroes[:3]],
        'ranks': [asdict(role) for role in build_role_panel_entries(sport.get('guideCountData') or [], [])],
        'leaderboards': sorted(boards, key=lambda b: b['rank']),
        'leaderboard_status': 'ok' if isinstance(billboard, dict) and billboard.get('code') == 0 else 'unavailable',
    }


class TeamOverviewModule:
    def __init__(self, profile_module=None):
        self.profile = profile_module or dashen_profile_module

    async def query(self, value):
        players = decode_players(value)
        semaphore = asyncio.Semaphore(3)

        async def fetch(player):
            async with semaphore:
                try:
                    async def request():
                        profile = await self.profile.query_profile(
                            DashenProfileQuery(bnet_id=player['battletag'], include_previous_season=False), render=False)
                        billboard = await self.profile.requests.get_billboard_user(profile.customer_token)
                        return summarize(profile.bundle, billboard)
                    summary = await asyncio.wait_for(request(), timeout=45)
                    return {**player, 'status': 'ok', **summary}
                except ModuleError as exc:
                    return {**player, 'status': 'error', 'error': exc.error, 'message': '资料查询失败或不可见'}
                except asyncio.TimeoutError:
                    return {**player, 'status': 'error', 'error': 'timeout', 'message': '查询超时'}
                except Exception:
                    return {**player, 'status': 'error', 'error': 'query_failed', 'message': '资料暂时无法读取'}

        records = await asyncio.gather(*(fetch(player) for player in players))
        return {'ok': True, 'version': 2,
                'teams': {team: [p for p in records if p['team_type'] == team] for team in ('teammate', 'enemy')},
                'partial': any(p['status'] != 'ok' for p in records)}


team_overview_module = TeamOverviewModule()
