from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import re
import time
from typing import Any, Dict, Sequence
from urllib.parse import urlparse

try:
    from overstats.src.modules.query_tool import get_cached_asset_path, load_query_tool
except ModuleNotFoundError:
    from src.modules.query_tool import get_cached_asset_path, load_query_tool


RESOURCE_DIR = Path(__file__).resolve().parents[4] / "overstats" / "res"
ASSET_MANIFEST_PATH = RESOURCE_DIR / "query_tool_assets" / "assets_manifest.json"
_ASSET_MANIFEST_CACHE: Dict[str, Any] | None = None
ROLE_ICON_FILENAMES = {
    "tank": "tank.png",
    "dps": "dps.png",
    "healer": "healer.png",
}


@dataclass(frozen=True)
class RenderedImage:
    content: bytes
    media_type: str = "image/png"


def _resampling_lanczos() -> Any:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS")


def _resize_image(image: Any, size: tuple[int, int]) -> Any:
    return image.resize(size, _resampling_lanczos())


def render_match_list(
    matches: Sequence[Dict[str, Any]],
    *,
    title: str = "大神对局列表",
    full_id: str = "",
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    config = _load_ow_config()
    recent_matches = list(matches or [])[:20]
    row_h = 60
    footer_h = 58
    img_h = row_h * max(len(recent_matches), 1) + 70 + footer_h
    img = Image.new("RGBA", (700, img_h), (22, 23, 30, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    font_title = _font(24)
    font = _font(18)
    font_sm = _font(16)

    title_text = title
    if full_id:
        title_text = f"{full_id} \u8fd1\u671f\u5bf9\u5c40\u5217\u8868"
    draw.text((20, 15), title_text, fill=(0, 255, 200), font=font_title)

    total_recent = len(recent_matches)
    wins_recent = sum(1 for match in recent_matches if match.get("matchRet") == 1)
    win_rate = (wins_recent / total_recent * 100) if total_recent else 0
    wr_color = (100, 255, 120) if win_rate >= 50 else (255, 100, 100)
    wr_label = f"\u8fd1 {total_recent} \u573a\u80dc\u7387:"
    draw.text((430, 18), wr_label, fill=(220, 220, 220), font=font)
    draw.text((430 + _text_width(draw, wr_label, font) + 10, 15), f"{win_rate:.1f}%", fill=wr_color, font=font_title)

    y = 60
    if not recent_matches:
        _rounded_rect(draw, [20, y, 680, y + 50], radius=8, fill=(35, 37, 45, 255))
        draw.text((40, y + 15), "未找到可用对局。", fill=(230, 235, 245), font=font)
    for index, match in enumerate(recent_matches, start=1):
        _draw_match_row(draw, img, config, match, index, y, font, font_sm)
        y += row_h

    footer_top = img_h - footer_h
    draw.line([(20, footer_top), (680, footer_top)], fill=(60, 67, 82, 255), width=1)
    hint_text = "回复此图并@机器人发送 1 / 1* / 1**，可查看单场详情 / 全员详细 / AI锐评"
    draw.text((20, footer_top + 16), _fit_text(draw, hint_text, font_sm, 660), fill=(190, 198, 210), font=font_sm)

    output = BytesIO()
    img.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def render_match_detail(
    detail_payload: Dict[str, Any],
    *,
    title: str = "Dashen Match Detail",
    source_match: Dict[str, Any] | None = None,
    query_full_id: str = "",
    query_bnet_id: str = "",
) -> RenderedImage:
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError as exc:
        raise RuntimeError("render.py requires Pillow to output images") from exc

    data = _extract_match_detail_data(detail_payload)
    source_match = source_match or {}
    config = _load_ow_config()
    if data.get("totalCount") or data.get("roundCountList"):
        return _render_fight_match_detail(
            data,
            config,
            title=title,
            source_match=source_match,
        )

    return _render_scoreboard_match_detail(
        data,
        config,
        title=title,
        source_match=source_match,
        query_full_id=query_full_id,
        query_bnet_id=query_bnet_id,
    )


def _render_scoreboard_match_detail(
    data: Dict[str, Any],
    config: Dict[str, Any],
    *,
    title: str,
    source_match: Dict[str, Any],
    query_full_id: str,
    query_bnet_id: str,
) -> RenderedImage:
    from PIL import Image, ImageDraw

    template_path = RESOURCE_DIR / "score_board.png"
    if template_path.exists():
        img = Image.open(template_path).convert("RGBA")
    else:
        img = Image.new("RGBA", (1825, 994), (24, 26, 34, 255))
        ImageDraw.Draw(img).rectangle((1125, 0, 1825, 994), fill=(32, 35, 45, 255))

    draw = ImageDraw.Draw(img, "RGBA")
    font_en_large = _font_en_oblique(80)
    font_cn = _font_chinese(40)
    font_meta = _font_meta(25)

    map_guid = data.get("mapGuid") or source_match.get("mapGuid")
    map_info = _find_map(config, map_guid)
    map_name = map_info.get("name") or str(map_guid or "\u672a\u77e5\u5730\u56fe")
    _paste_map_image(img, map_info, (1125, 0), (700, 440))

    match_ret = data.get("matchRet", source_match.get("matchRet"))
    result_en = "VICTORY" if match_ret == 1 else "TIE" if match_ret == 0 else "DEFEAT"
    result_color = (100, 255, 120) if match_ret == 1 else (255, 255, 150) if match_ret == 0 else (255, 100, 100)
    draw.text((1165, 465), result_en, font=font_en_large, fill=result_color)
    draw.text((1140, 20), _fit_text(draw, map_name, font_cn, 620), font=font_cn, fill="white")

    team_score = data.get("teamScore", source_match.get("teamScore", "-"))
    opponent_score = data.get("opponentScore", source_match.get("opponentScore", "-"))
    game_time_sec = data.get("gameTimeSec")
    start_time = data.get("startTime")
    if start_time:
        try:
            date_text = time.strftime("%m/%d/%y - %H:%M", time.localtime(int(start_time) + int(game_time_sec or 0)))
        except Exception:
            date_text = _format_begin_ts(source_match.get("beginTs"))
    else:
        date_text = _format_begin_ts(source_match.get("beginTs"))
    mode_label, _ = _mode_label({**source_match, **data})
    font_mode_value = _font_chinese(25) if re.search(r"[\u4e00-\u9fff]", str(mode_label)) else font_meta
    font_num_display = _font_num_display(25)

    _draw_labeled_value(draw, 1165, 570, "\u00b7 FINAL SCORE: ", f"{team_score} VS {opponent_score}", font_meta, font_num_display, fill="white")
    _draw_labeled_value(draw, 1165, 610, "\u00b7 DATE: ", date_text, font_meta, font_num_display, fill="white")
    _draw_labeled_value(draw, 1165, 650, "\u00b7 GAME MODE: ", str(mode_label), font_meta, font_mode_value, fill="white")
    _draw_labeled_value(draw, 1165, 690, "\u00b7 GAME LENGTH: ", _format_duration(game_time_sec), font_meta, font_num_display, fill="white")
    _draw_ban_heroes(img, draw, data, config)

    teammate_list = list(data.get("teammateList") or [])
    enemy_list = list(data.get("enemyList") or [])
    teammates = _sort_players(teammate_list, config)
    enemies = _sort_players(enemy_list, config)
    teammate_parties = _process_friend_list(teammate_list)
    enemy_parties = _process_friend_list(enemy_list)
    _prepare_scoreboard_section_lines(img, draw, len(teammates), 44, 415)
    _prepare_scoreboard_section_lines(img, draw, len(enemies), 579, 415)
    _draw_scoreboard_players(
        draw,
        img,
        teammates,
        config,
        44,
        415,
        False,
        party_list=teammate_parties,
        query_full_id=query_full_id,
        query_bnet_id=query_bnet_id,
    )
    _draw_scoreboard_players(
        draw,
        img,
        enemies,
        config,
        579,
        415,
        True,
        party_list=enemy_parties,
        query_full_id=query_full_id,
        query_bnet_id=query_bnet_id,
    )

    output = BytesIO()
    img.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _extract_match_detail_data(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    roots: list[Dict[str, Any]] = []
    data = payload.get("data")
    if isinstance(data, dict):
        roots.append(data)
    roots.append(payload)

    best = roots[0] if roots else {}
    best_score = _detail_dict_score(best)
    for root in roots:
        for candidate in _walk_detail_dicts(root):
            score = _detail_dict_score(candidate)
            if score > best_score:
                best = candidate
                best_score = score

    merged = {}
    for root in roots:
        if isinstance(root, dict):
            merged.update(root)
    if isinstance(best, dict):
        merged.update(best)

    teammate_list = _find_nested_value(merged, "teammateList", "teammate_list")
    enemy_list = _find_nested_value(merged, "enemyList", "enemy_list")
    round_count_list = _find_nested_value(merged, "roundCountList", "round_count_list")
    total_count = _find_nested_value(merged, "totalCount", "total_count")
    name_map = _find_nested_value(merged, "nameMap", "name_map")

    if isinstance(teammate_list, list):
        merged["teammateList"] = teammate_list
    if isinstance(enemy_list, list):
        merged["enemyList"] = enemy_list
    if isinstance(round_count_list, list):
        merged["roundCountList"] = round_count_list
    if isinstance(total_count, dict):
        merged["totalCount"] = total_count
    if isinstance(name_map, dict):
        merged["nameMap"] = name_map

    return merged


def _normalize_numeric_id(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _process_friend_list(player_list: Sequence[Dict[str, Any]]) -> list[list[int] | int]:
    friend_groups: list[set[int]] = []
    processed_ids: set[int] = set()
    for player in player_list:
        if not isinstance(player, dict):
            continue
        bnet_id = _normalize_numeric_id(player.get("bnetId"))
        if bnet_id is None or bnet_id in processed_ids:
            continue
        current_group = {
            friend_id
            for friend_id in (
                _normalize_numeric_id(friend)
                for friend in (player.get("friendBnetIds") or [])
            )
            if friend_id is not None
        }
        current_group.add(bnet_id)
        merged = False
        for group in friend_groups:
            if not group.isdisjoint(current_group):
                group.update(current_group)
                merged = True
                break
        if not merged:
            friend_groups.append(set(current_group))
        processed_ids.update(current_group)
    all_partied_ids = set().union(*friend_groups) if friend_groups else set()
    single_players = [
        player_id
        for player_id in (_normalize_numeric_id(player.get("bnetId")) for player in player_list if isinstance(player, dict))
        if player_id is not None and player_id not in all_partied_ids
    ]
    return [sorted(group) for group in friend_groups] + single_players


def _player_battletag(player: Dict[str, Any]) -> str:
    name = str(player.get("name") or player.get("battletag") or "").strip()
    return name.split("#", 1)[0]


def _is_query_player(
    player: Dict[str, Any],
    *,
    query_full_id: str,
    query_bnet_id: str,
) -> bool:
    player_bnet_id = str(player.get("bnetId") or "").strip()
    if query_bnet_id and player_bnet_id and player_bnet_id == str(query_bnet_id).strip():
        return True
    query_name = str(query_full_id or "").strip()
    if not query_name:
        return False
    player_name = str(player.get("name") or player.get("battletag") or "").strip()
    if player_name and player_name.lower() == query_name.lower():
        return True
    query_tag = query_name.split("#", 1)[0].strip().lower()
    return bool(query_tag and _player_battletag(player).strip().lower() == query_tag)


def _resolve_query_party_index(
    players: Sequence[Dict[str, Any]],
    party_list: Sequence[Sequence[int] | int],
    *,
    query_full_id: str,
    query_bnet_id: str,
) -> int:
    for player in players:
        if not isinstance(player, dict) or not _is_query_player(player, query_full_id=query_full_id, query_bnet_id=query_bnet_id):
            continue
        return _party_index_for_player(player, party_list)
    return -1


def _party_index_for_player(player: Dict[str, Any], party_list: Sequence[Sequence[int] | int]) -> int:
    player_bnet_id = _normalize_numeric_id(player.get("bnetId"))
    if player_bnet_id is None:
        return -1
    for index, party in enumerate(party_list):
        if isinstance(party, Sequence) and not isinstance(party, (str, bytes)):
            normalized_party = {
                member_id
                for member_id in (_normalize_numeric_id(member) for member in party)
                if member_id is not None
            }
            if player_bnet_id in normalized_party:
                return index
            continue
        if _normalize_numeric_id(party) == player_bnet_id:
            return index
    return -1


def _party_color(party_index: int, *, is_enemy: bool) -> tuple[int, int, int, int]:
    team_colors = [
        (173, 255, 47, 255),
        (0, 255, 255, 255),
        (255, 215, 0, 255),
        (50, 205, 50, 255),
        (0, 191, 255, 255),
        (255, 165, 0, 255),
        (0, 255, 127, 255),
        (30, 144, 255, 255),
        (255, 255, 0, 255),
        (64, 224, 208, 255),
    ] if not is_enemy else [
        (255, 182, 193, 255),
        (255, 99, 71, 255),
        (221, 160, 221, 255),
        (220, 20, 60, 255),
        (153, 50, 204, 255),
        (255, 105, 180, 255),
        (255, 69, 0, 255),
        (255, 0, 255, 255),
        (238, 130, 238, 255),
        (250, 128, 114, 255),
    ]
    if party_index < 0:
        return team_colors[0 if not is_enemy else 1]
    return team_colors[party_index % len(team_colors)]


def _scoreboard_name_colors(*, is_me: bool, is_my_teammate: bool) -> tuple[str, str]:
    if is_me:
        return "#FFD700", "#DAA520"
    if is_my_teammate:
        return "#FFE4B5", "#DEB887"
    return "white", "white"


def _render_fight_match_detail(
    data: Dict[str, Any],
    config: Dict[str, Any],
    *,
    title: str,
    source_match: Dict[str, Any],
) -> RenderedImage:
    from PIL import Image, ImageDraw

    total_count = data.get("totalCount") or {}
    rounds = list(data.get("roundCountList") or [])
    if not rounds:
        rounds = [total_count] if total_count else []

    row_h = 58
    left_w = 230
    top_h = 96
    round_header_h = 38
    team_separator_h = 26
    round_gap = 16
    round_h = round_header_h + 10 * row_h + team_separator_h + 12
    image_w = 1900
    image_h = top_h + max(len(rounds), 1) * (round_h + round_gap) + 24
    img = Image.new("RGBA", (image_w, image_h), (22, 24, 32, 255))
    draw = ImageDraw.Draw(img)
    font_title = _font_en(46)
    font_en = _font_meta(22)
    font_sm = _font_chinese(17)
    font_tiny = _font_chinese(12)

    map_guid = total_count.get("mapGuid") or source_match.get("mapGuid")
    map_name = (_find_map(config, map_guid) or {}).get("name") or str(map_guid or "\u672a\u77e5\u5730\u56fe")
    score_text = f"{total_count.get('teamScore', source_match.get('teamScore', 0))} : {total_count.get('opponentScore', source_match.get('opponentScore', 0))}"
    draw.rectangle((0, 0, image_w, top_h), fill=(28, 31, 42, 255))
    draw.text((32, 20), "STADIUM MATCH", font=font_title, fill=(255, 190, 60, 255))
    draw.text((520, 25), _fit_text(draw, map_name, font_sm, 420), font=font_sm, fill=(245, 247, 250, 255))
    draw.text((520, 58), f"FINAL {score_text}", font=font_en, fill=(178, 184, 198, 255))

    y = top_h
    for idx, round_data in enumerate(rounds or [{}], 1):
        round_map = (_find_map(config, round_data.get("mapGuid") or map_guid) or {}).get("name") or map_name
        draw.rectangle((24, y, left_w - 14, y + round_h - 4), fill=(32, 38, 53, 255), outline=(255, 190, 60, 120), width=2)
        draw.text((44, y + 24), _fit_text(draw, round_map, font_sm, 160), font=font_sm, fill=(245, 247, 250, 255))
        draw.text((44, y + 56), f"\u7b2c {idx} \u56de\u5408", font=font_sm, fill=(255, 190, 60, 255))
        draw.text((44, y + 92), f"{round_data.get('teamScore', 0)} : {round_data.get('opponentScore', 0)}", font=font_title, fill=(245, 247, 250, 255))
        draw.text((44, y + 150), _format_duration(round_data.get("gameTimeSec")), font=font_en, fill=(178, 184, 198, 255))

        draw.rectangle((left_w, y, image_w - 24, y + round_header_h), fill=(40, 44, 58, 255))
        for label, x in [
            ("RANK", 246),
            ("\u82f1\u96c4", 326),
            ("\u73a9\u5bb6", 386),
            ("KAD", 568),
            ("\u4f24\u5bb3", 660),
            ("\u6cbb\u7597", 762),
            ("\u627f\u4f24", 864),
            ("\u8d44\u91d1", 966),
            ("\u5f02\u80fd", 1072),
            ("\u88c5\u5907", 1266),
        ]:
            label_font = font_en if str(label).isascii() else font_sm
            draw.text((x, y + 9), label, font=label_font, fill=(178, 184, 198, 255))

        allies = list(round_data.get("teammateList") or [])
        enemies = list(round_data.get("enemyList") or [])
        row_y = y + round_header_h
        for player_index, player in enumerate(allies + enemies):
            if player_index == len(allies):
                sep_y = row_y + 2
                draw.rectangle((left_w, sep_y, image_w - 24, sep_y + team_separator_h - 4), fill=(18, 20, 27, 255))
                draw.text((left_w + 28, sep_y + 4), "ALLY  VS  ENEMY", font=font_en, fill=(245, 247, 250, 255))
                row_y += team_separator_h
            team_color = (76, 211, 128, 255) if player_index < len(allies) else (225, 92, 96, 255)
            _draw_fight_player_row(draw, img, config, data, player, row_y, team_color, font_sm, font_tiny)
            row_y += row_h
        y += round_h + round_gap

    output = BytesIO()
    img.convert("RGB").save(output, format="PNG", optimize=True)
    return RenderedImage(content=output.getvalue())


def _draw_match_row(draw: Any, img: Any, config: Dict[str, Any], match: Dict[str, Any], index: int, y: int, font: Any, font_sm: Any) -> None:
    _rounded_rect(draw, [20, y, 680, y + 50], radius=8, fill=(35, 37, 45, 255))
    _draw_map_background(img, map_info := _find_map(config, match.get("mapGuid")), y)
    _draw_row_accent(draw, y, match)

    map_name = map_info.get("name") or "\u672a\u77e5\u5730\u56fe"
    mode, mode_color = _mode_label(match)
    begin_text = _format_begin_ts(match.get("beginTs"))
    result_text, result_color = _result_label(match.get("matchRet"))

    draw.text((40, y + 15), f"{index}. {map_name}", fill=(255, 255, 255), font=font)
    draw.text((375, y + 15), mode, fill=mode_color, font=font_sm)
    draw.text((375 + _text_width(draw, mode, font_sm) + 6, y + 15), f"| {begin_text}", fill=(180, 180, 180), font=font_sm)
    draw.text((580, y + 15), result_text, fill=result_color, font=font_sm)


def _draw_detail_map_background(img: Any, map_info: Dict[str, Any], width: int, height: int) -> None:
    icon_url = map_info.get("icon")
    if not icon_url:
        return
    local_path = get_cached_asset_path(str(icon_url), "maps")
    if not local_path or not local_path.exists():
        return
    try:
        from PIL import Image

        icon = Image.open(local_path).convert("RGBA")
        bg = _crop_center_to_size(icon, (width, height))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 125))
        img.paste(bg, (0, 0))
        img.alpha_composite(overlay, (0, 0))
    except Exception:
        return


def _draw_detail_team(
    draw: Any,
    img: Any,
    config: Dict[str, Any],
    label: str,
    players: Sequence[Dict[str, Any]],
    y: int,
    accent: tuple[int, int, int],
    font: Any,
    font_md: Any,
    font_sm: Any,
) -> None:
    draw.text((34, y), label, fill=accent, font=font)
    header_y = y + 42
    draw.rectangle((34, header_y, 1146, header_y + 34), fill=(35, 38, 50, 255))
    headers = [
        ("\u82f1\u96c4", 82),
        ("\u73a9\u5bb6", 166),
        ("K / A / D", 434),
        ("\u4f24\u5bb3", 560),
        ("\u6cbb\u7597", 682),
        ("\u627f\u4f24", 804),
        ("\u6bb5\u4f4d", 930),
    ]
    for text, x in headers:
        header_font = _font_meta(max(15, int(getattr(font_sm, "size", 16)))) if str(text).isascii() else font_sm
        draw.text((x, header_y + 8), text, fill=(178, 184, 198), font=header_font)

    row_y = header_y + 34
    if not players:
        draw.rectangle((34, row_y, 1146, row_y + 54), fill=(28, 31, 42, 255))
        draw.text((58, row_y + 16), "\u6ca1\u6709\u73a9\u5bb6\u6570\u636e", fill=(178, 184, 198), font=font_sm)
        return

    for player in players:
        _draw_detail_player_row(draw, img, config, player, row_y, accent, font_md, font_sm)
        row_y += 62


def _draw_detail_player_row(
    draw: Any,
    img: Any,
    config: Dict[str, Any],
    player: Dict[str, Any],
    y: int,
    accent: tuple[int, int, int],
    font: Any,
    font_sm: Any,
) -> None:
    name = _player_name(player)
    base_size = max(18, int(getattr(font, "size", 20)))
    name_is_ascii = bool(re.match(r"^[a-zA-Z0-9_\\-]+$", name))
    font_name = _fit_font(
        draw,
        name.upper() if name_is_ascii else name,
        _font_en_oblique if name_is_ascii else _font_chinese,
        base_size,
        max(12, int(base_size * 0.6)),
        230,
    )
    font_stat = _font_num_small(max(14, int(getattr(font_sm, "size", 16))))
    draw.rectangle((34, y, 1146, y + 56), fill=(28, 31, 42, 255))
    draw.rectangle((34, y, 40, y + 56), fill=accent)

    hero_info = _resolve_player_hero(config, player)
    _draw_player_role_icon(img, hero_info, player, 48, y + 12, 30)
    _draw_hero_icon(img, hero_info, 82, y + 8, 40)
    hero_name = hero_info.get("name") or _short_id(player.get("heroGuid"))
    draw.text((132, y + 8), _fit_text(draw, hero_name, font_sm, 120), fill=(245, 247, 250), font=font_sm)
    draw.text(
        (166, y + 8),
        _fit_text(draw, name.upper() if name_is_ascii else name, font_name, 230),
        fill=(245, 247, 250),
        font=font_name,
    )
    role_label = _role_label(player, hero_info)
    if role_label:
        draw.text((166, y + 34), role_label, fill=(178, 184, 198), font=font_sm)

    kad = f"{_fmt_num(player.get('kill'))} / {_fmt_num(player.get('assist'))} / {_fmt_num(player.get('death'))}"
    draw.text((434, y + 17), kad, fill=(245, 247, 250), font=font_stat)
    draw.text((560, y + 17), _fmt_num(player.get("heroDamage")), fill=(255, 138, 104), font=font_stat)
    draw.text((682, y + 17), _fmt_num(player.get("cure")), fill=(94, 221, 139), font=font_stat)
    draw.text((804, y + 17), _fmt_num(player.get("resistDamage")), fill=(104, 184, 255), font=font_stat)
    _draw_rank_badge(draw, img, player.get("rankInfo"), 930, y + 10, 120, 34, mode="normal")


def _draw_scoreboard_players(
    draw: Any,
    img: Any,
    players: Sequence[Dict[str, Any]],
    config: Dict[str, Any],
    start_y: int,
    section_h: int,
    is_enemy: bool,
    *,
    party_list: Sequence[Sequence[int] | int],
    query_full_id: str,
    query_bnet_id: str,
) -> None:
    if not players:
        return
    row_h = section_h / len(players)
    font_num = _font_num(max(int(23 * row_h / 82), 10))
    font_num_small = _font_num_small(max(int(15 * row_h / 82), 10))
    font_cn_sm = _font_chinese(max(int(15 * row_h / 82), 8))
    team_final_hit = sum(_safe_int(player.get("finalHit")) for player in players)
    me_party_index = _resolve_query_party_index(players, party_list, query_full_id=query_full_id, query_bnet_id=query_bnet_id)

    for index, player in enumerate(players):
        y = start_y + index * row_h
        party_index = _party_index_for_player(player, party_list)
        accent = _party_color(party_index, is_enemy=is_enemy)
        draw.rectangle((126, int(y + 3), 132, int(y + row_h - 3)), fill=accent)
        if party_index >= 0:
            draw.text((129, int(y + 12)), f"{party_index + 1}", font=font_cn_sm, fill=accent)

        hero_info = _resolve_player_hero(config, player)
        role_icon_size = max(int(32 * row_h / 82), 10)
        _draw_player_role_icon(img, hero_info, player, 4, int(y + (row_h - role_icon_size) / 2) - 3, role_icon_size)

        icon_url = _hero_icon_url(hero_info, player)
        hero_size = max(int(80 * row_h / 82), 20)
        _paste_icon_from_url(img, icon_url, (38, int(y + (row_h - hero_size) / 2)), (hero_size, hero_size), ("heroes", "misc"))

        rank_h = max(int(21 * row_h / 82), 9)
        rank_w = max(int(63 * row_h / 82), 28)
        _draw_rank_badge(draw, img, player.get("rankInfo"), 0, int(y + row_h - rank_h - 3), rank_w, rank_h, mode="normal")

        perks = _extract_player_perks(player)
        _draw_perks(draw, img, config, perks, y, row_h)

        stat_y = y + row_h * 0.4
        sub_y = y + row_h * 0.75
        stats = [
            ("kill", 500, player.get("killMax")),
            ("assist", 570, False),
            ("death", 640, False),
            ("heroDamage", 750, player.get("heroDamageMax")),
            ("cure", 870, player.get("cureMax")),
            ("resistDamage", 1000, player.get("resistDamageMax")),
        ]
        for key, x, is_max in stats:
            value = _safe_int(player.get(key))
            fill = "gold" if is_max else ("white" if value else "lightgrey")
            draw.text((x, stat_y), f"{value:,}" if key in {"heroDamage", "cure", "resistDamage"} else str(value), font=font_num, fill=fill, anchor="ms")

        final_hit = _safe_int(player.get("finalHit"))
        target_time = _format_duration(player.get("targetCompetingTime"))
        damage_taken = _safe_int(player.get("damageTaken"))
        healing_taken = _safe_int(player.get("healingTaken"))
        fleta_pct = (final_hit / (team_final_hit * 0.5) * 100) if team_final_hit > 0 else 0
        draw.text((500, sub_y), f"F:{final_hit}", font=font_num_small, fill="lightgrey", anchor="ms")
        draw.text((570, sub_y), target_time, font=font_num_small, fill="lightgrey", anchor="ms")
        draw.text((750, sub_y), f"DT:{damage_taken:,}", font=font_num_small, fill="lightgrey", anchor="ms")
        draw.text((870, sub_y), f"HT:{healing_taken:,}", font=font_num_small, fill="lightgrey", anchor="ms")
        draw.text((1000, sub_y), f"FLETA:{fleta_pct:.2f}%", font=font_num_small, fill="lightgrey", anchor="ms")

        battletag, battlenum = _split_battletag(player)
        name_y = y + row_h * 0.35
        num_y = y + row_h * 0.70
        is_me = _is_query_player(player, query_full_id=query_full_id, query_bnet_id=query_bnet_id)
        is_my_teammate = bool(not is_me and me_party_index != -1 and party_index == me_party_index)
        name_color, num_color = _scoreboard_name_colors(is_me=is_me, is_my_teammate=is_my_teammate)
        name_is_ascii = bool(re.match(r"^[a-zA-Z0-9_\\-]+$", battletag))
        font_name = _fit_font(
            draw,
            battletag.upper() if name_is_ascii else battletag,
            _font_en_oblique if name_is_ascii else _font_chinese,
            max(int(40 * row_h / 82), 10),
            max(int(16 * row_h / 82), 8),
            175,
        )
        draw.text(
            (140, name_y),
            _fit_text(draw, battletag.upper() if name_is_ascii else battletag, font_name, 175),
            font=font_name,
            fill=name_color,
            anchor="lm",
        )
        draw.text((140, num_y), f"#{battlenum}" if battlenum else "", font=font_num_small, fill=num_color, anchor="lm")


def _prepare_scoreboard_section_lines(
    img: Any,
    draw: Any,
    player_count: int,
    start_y: int,
    section_h: int,
) -> None:
    section_right = min(1061, img.width - 1)
    section_left = 0
    _erase_scoreboard_template_lines(img, section_left, section_right, start_y, section_h)

    if player_count <= 1:
        return

    line_color = (0, 0, 0, 86)
    for index in range(1, player_count):
        y = int(round(start_y + section_h * index / player_count))
        draw.rectangle((section_left, y - 1, section_right, y + 1), fill=line_color)


def _erase_scoreboard_template_lines(
    img: Any,
    x1: int,
    x2: int,
    start_y: int,
    section_h: int,
) -> None:
    pixel = img.load()
    width = img.width
    height = img.height
    x1 = max(0, min(x1, width - 1))
    x2 = max(0, min(x2, width - 1))
    end_y = start_y + section_h

    fixed_row_count = 5
    for index in range(1, fixed_row_count):
        y = int(round(start_y + section_h * index / fixed_row_count))
        for yy in range(max(start_y, y - 2), min(end_y, y + 3)):
            source_y = yy - 5 if yy - start_y > section_h / 2 else yy + 5
            source_y = max(start_y, min(end_y - 1, source_y))
            for x in range(x1, x2 + 1):
                pixel[x, yy] = pixel[x, source_y]


def _draw_fight_player_row(
    draw: Any,
    img: Any,
    config: Dict[str, Any],
    data: Dict[str, Any],
    player: Dict[str, Any],
    y: int,
    team_color: tuple[int, int, int, int],
    font: Any,
    font_tiny: Any,
) -> None:
    font_stat = _font_num_small(max(15, int(getattr(font, "size", 16))))
    name_map = {str(k): v for k, v in (data.get("nameMap") or {}).items()}
    bnet_id = str(player.get("bnetId") or "")
    name = name_map.get(bnet_id) or _player_name(player)
    display_name = name.split("#", 1)[0]
    name_is_ascii = bool(re.match(r"^[a-zA-Z0-9_\\-]+$", display_name))
    font_name = _fit_font(
        draw,
        display_name.upper() if name_is_ascii else display_name,
        _font_en_oblique if name_is_ascii else _font_chinese,
        max(15, int(getattr(font, "size", 16))),
        10,
        160,
    )
    hero_info = _resolve_player_hero(config, player)
    draw.rectangle((230, y, 1876, y + 54), fill=(34, 37, 49, 255))
    draw.rectangle((230, y, 236, y + 54), fill=team_color)
    _draw_rank_badge(draw, img, player.get("rankInfo"), 244, y + 11, 78, 32, mode="fight")
    _paste_icon_from_url(
        img,
        _hero_icon_url(hero_info, player),
        (333, y + 8),
        (36, 36),
        ("heroes", "misc"),
    )
    _draw_player_role_icon(img, hero_info, player, 288, y + 11, 28)
    draw.text(
        (386, y + 7),
        _fit_text(draw, display_name.upper() if name_is_ascii else display_name, font_name, 160),
        font=font_name,
        fill=(245, 247, 250, 255),
    )
    hero_name = hero_info.get("name") or ""
    if hero_name:
        draw.text((386, y + 30), _fit_text(draw, hero_name, font_tiny, 160), font=font_tiny, fill=(178, 184, 198, 255))
    draw.text((568, y + 18), f"{_fmt_num(player.get('kill'))}/{_fmt_num(player.get('assist'))}/{_fmt_num(player.get('death'))}", font=font_stat, fill=(245, 247, 250, 255))
    draw.text((660, y + 18), _fmt_num(player.get("heroDamage")), font=font_stat, fill=(255, 138, 104, 255))
    draw.text((762, y + 18), _fmt_num(player.get("cure")), font=font_stat, fill=(94, 221, 139, 255))
    draw.text((864, y + 18), _fmt_num(player.get("resistDamage")), font=font_stat, fill=(104, 184, 255, 255))
    draw.text((966, y + 18), _fmt_num(player.get("endWorth", player.get("worth", 0))), font=font_stat, fill=(255, 212, 96, 255))
    _draw_guid_slots(draw, img, config, player.get("traitGuids") or [], 1072, y + 11, 4, "mod_traits")
    _draw_guid_slots(draw, img, config, player.get("modGuids") or [], 1266, y + 11, 6, "mod_traits")


def _draw_hero_icon(img: Any, hero_info: Dict[str, Any], x: int, y: int, size: int) -> None:
    icon_url = _hero_icon_url(hero_info)
    _paste_icon_from_url(img, icon_url, (x, y), (size, size), ("heroes", "misc"))


def _normalize_role_name(role: Any) -> str:
    normalized = str(role or "").strip().lower()
    if normalized == "support":
        return "healer"
    return normalized


def _load_role_icon_asset(role: Any, *, size: tuple[int, int]) -> Any:
    from PIL import Image

    role_type = _normalize_role_name(role)
    filename = ROLE_ICON_FILENAMES.get(role_type)
    if not filename:
        return None
    path = RESOURCE_DIR / filename
    if not path.exists():
        return None
    try:
        with Image.open(path) as raw_icon:
            return _resize_image(raw_icon.convert("RGBA"), size)
    except Exception:
        return None


def _draw_player_role_icon(img: Any, hero_info: Dict[str, Any], player: Dict[str, Any], x: int, y: int, size: int) -> None:
    from PIL import Image, ImageDraw

    role = _role_type(player, hero_info)
    if not role or size <= 0:
        return
    role_icon = _load_role_icon_asset(role, size=(size, size))
    if role_icon is not None:
        img.paste(role_icon, (int(x), int(y)), role_icon)
        return
    bg_fill, border_fill, text_fill, label = _role_style(role)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon, "RGBA")
    try:
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(4, size // 4), fill=bg_fill, outline=border_fill, width=max(1, size // 10))
    except Exception:
        draw.rectangle((0, 0, size - 1, size - 1), fill=bg_fill, outline=border_fill)
    font = _font_chinese(max(10, int(size * 0.54)))
    tw, th = _text_size(draw, label, font)
    draw.text(((size - tw) / 2, (size - th) / 2 - 1), label, font=font, fill=text_fill)
    img.paste(icon, (int(x), int(y)), icon)


def _draw_rank_badge(
    draw: Any,
    img: Any,
    rank_info: Any,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    mode: str,
) -> None:
    if not isinstance(rank_info, dict) or not rank_info:
        return

    score = _safe_int(rank_info.get("rankScore") or rank_info.get("score"))
    tier = str(rank_info.get("rankSubTier") or rank_info.get("rank_sub_tier") or "").strip()
    if score <= 0 and not tier:
        return

    badge_image = _build_rank_badge_image(rank_info, width=width, height=height, mode=mode)
    if badge_image is not None:
        img.paste(badge_image, (x, y), badge_image)
        return

    rank_label = _rank_label(rank_info, mode=mode)
    if not rank_label:
        return

    fill, outline = _rank_colors(score, mode)
    try:
        draw.rounded_rectangle((x, y, x + width, y + height), radius=max(5, height // 3), fill=fill, outline=outline, width=2)
    except Exception:
        draw.rectangle((x, y, x + width, y + height), fill=fill, outline=outline)

    font = _font_chinese(max(10, int(height * 0.54)))
    small_font = _font_num_small(max(9, int(height * 0.42)))
    label = _fit_text(draw, rank_label, font, max(width - 8, 24))
    tw, th = _text_size(draw, label, font)
    draw.text((x + (width - tw) / 2, y + (height - th) / 2 - 1), label, font=font, fill=(255, 248, 220, 255))

    if score > 0 and width >= 72:
        score_text = str(score)
        sw, sh = _text_size(draw, score_text, small_font)
        draw.text((x + width - sw - 5, y + height - sh - 1), score_text, font=small_font, fill=(40, 26, 12, 220))


def _build_rank_badge_image(rank_info: Dict[str, Any], *, width: int, height: int, mode: str) -> Any:
    from PIL import Image, ImageDraw

    score = _safe_int(rank_info.get("rankScore") or rank_info.get("score"))
    tier = str(rank_info.get("rankSubTier") or rank_info.get("rank_sub_tier") or "").strip()
    asset_path = _rank_badge_asset_path(score, mode=mode)
    if asset_path is None or not asset_path.exists():
        return None
    try:
        icon = Image.open(asset_path).convert("RGBA")
    except Exception:
        return None

    original_width, original_height = icon.size
    if tier:
        draw = ImageDraw.Draw(icon)
        font = _font_num(max(18, int(original_height * 0.56)))
        center_x = original_width * (332 / max(1, 460))
        center_y = original_height * (52 / max(1, 156))
        try:
            box = draw.textbbox((0, 0), tier, font=font)
            draw_x = center_x - (box[2] - box[0]) / 2 - box[0]
            draw_y = center_y - (box[3] - box[1]) / 2 - box[1]
            draw.text((draw_x, draw_y), tier, font=font, fill=(22, 25, 32, 255))
        except Exception:
            try:
                draw.text((center_x, center_y), tier, font=font, fill=(22, 25, 32, 255), anchor="mm")
            except TypeError:
                draw.text((original_width * 0.72, original_height * 0.33), tier, font=font, fill=(22, 25, 32, 255))

    return _resize_image(icon, (width, height))


def _rank_badge_asset_path(score: int, *, mode: str) -> Path | None:
    rank_flat_dir = RESOURCE_DIR / "rank_flat"
    if score <= 0:
        return None

    if mode == "fight":
        level = max(1, min(7, (_safe_int(score) // 100) + 1))
        fight_path = rank_flat_dir / f"c{level}.png"
        if fight_path.exists():
            return fight_path
        normal_path = rank_flat_dir / f"{level}.png"
        return normal_path if normal_path.exists() else None

    max_level = 9 if (rank_flat_dir / "9.png").exists() else 8
    level = max(1, min(max_level, (_safe_int(score) // 100) + 1))
    normal_path = rank_flat_dir / f"{level}.png"
    if normal_path.exists():
        return normal_path
    fallback_path = rank_flat_dir / f"c{min(level, 7)}.png"
    return fallback_path if fallback_path.exists() else None


def _draw_map_background(img: Any, map_info: Dict[str, Any], y: int) -> None:
    icon_url = map_info.get("icon")
    if not icon_url:
        return
    local_path = get_cached_asset_path(str(icon_url), "maps")
    if not local_path or not local_path.exists():
        return
    try:
        from PIL import Image

        icon = Image.open(local_path).convert("RGBA")
        bg = _crop_center_to_size(icon, (660, 50))
        mask = _left_fade_mask((660, 50))
        img.paste(bg, (20, y), mask)
    except Exception:
        return


def _paste_map_image(img: Any, map_info: Dict[str, Any], pos: tuple[int, int], size: tuple[int, int]) -> None:
    icon_url = map_info.get("icon")
    if not icon_url:
        return
    path = _cached_path_for_url(str(icon_url), ("maps", "misc"))
    if not path:
        return
    try:
        from PIL import Image

        icon = Image.open(path).convert("RGBA")
        bg = _crop_center_to_size(icon, size)
        img.paste(bg, pos)
    except Exception:
        return


def _paste_icon_from_url(
    img: Any,
    url: Any,
    pos: tuple[int, int],
    size: tuple[int, int],
    categories: Sequence[str],
) -> bool:
    if not url:
        return False
    path = _cached_path_for_url(str(url), categories)
    if not path:
        return False
    try:
        from PIL import Image

        icon = _resize_image(Image.open(path).convert("RGBA"), size)
        img.paste(icon, pos, icon)
        return True
    except Exception:
        return False


def _cached_path_for_url(url: str, categories: Sequence[str]) -> Path | None:
    normalized = str(url or "").strip()
    for category in categories:
        path = get_cached_asset_path(normalized, category)
        if path and path.exists():
            return path
    manifest_path = _manifest_asset_path(normalized, categories)
    if manifest_path:
        return manifest_path
    if "?" in normalized:
        clean_url = normalized.split("?", 1)[0]
        for category in categories:
            path = get_cached_asset_path(clean_url, category)
            if path and path.exists():
                return path
        manifest_path = _manifest_asset_path(clean_url, categories)
        if manifest_path:
            return manifest_path
    return None


def _walk_detail_dicts(value: Any) -> list[Dict[str, Any]]:
    found: list[Dict[str, Any]] = []
    stack = [value]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        if isinstance(current, dict):
            found.append(current)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _detail_dict_score(data: Any) -> int:
    if not isinstance(data, dict):
        return -1
    score = 0
    if isinstance(data.get("teammateList"), list):
        score += 50 + len(data.get("teammateList") or [])
    if isinstance(data.get("enemyList"), list):
        score += 50 + len(data.get("enemyList") or [])
    if isinstance(data.get("roundCountList"), list):
        score += 60 + len(data.get("roundCountList") or [])
    if isinstance(data.get("totalCount"), dict):
        score += 20
    if data.get("matchRet") is not None:
        score += 8
    if data.get("mapGuid") is not None:
        score += 6
    if data.get("teamScore") is not None:
        score += 4
    if data.get("heroList") is not None:
        score += 2
    return score


def _find_nested_value(value: Any, *keys: str) -> Any:
    if not keys:
        return None
    wanted = {str(key) for key in keys}
    for candidate in _walk_detail_dicts(value):
        for key in wanted:
            if key in candidate and candidate.get(key) not in (None, [], {}):
                return candidate.get(key)
    return None


def _manifest_asset_path(url: str, categories: Sequence[str]) -> Path | None:
    if not url:
        return None
    manifest = _asset_manifest()
    entry = manifest.get(url)
    path = _manifest_entry_path(entry, categories)
    if path:
        return path

    basename = Path(urlparse(url).path).name.lower()
    if not basename:
        return None
    for raw_url, item in manifest.items():
        if Path(urlparse(str(raw_url)).path).name.lower() != basename:
            continue
        path = _manifest_entry_path(item, categories)
        if path:
            return path
    return None


def _manifest_entry_path(entry: Any, categories: Sequence[str]) -> Path | None:
    if not isinstance(entry, dict):
        return None
    relative_path = str(entry.get("path") or "").strip()
    if not relative_path:
        return None
    category = str(entry.get("category") or "").strip().lower()
    if categories and category and category not in {str(item).lower() for item in categories}:
        folder_name = Path(relative_path).parts[0].lower() if Path(relative_path).parts else ""
        if folder_name not in {str(item).lower() for item in categories}:
            return None
    path = RESOURCE_DIR / "query_tool_assets" / Path(relative_path)
    return path if path.exists() else None


def _asset_manifest() -> Dict[str, Any]:
    global _ASSET_MANIFEST_CACHE
    if _ASSET_MANIFEST_CACHE is not None:
        return _ASSET_MANIFEST_CACHE
    if not ASSET_MANIFEST_PATH.exists():
        _ASSET_MANIFEST_CACHE = {}
        return _ASSET_MANIFEST_CACHE
    try:
        data = json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
        _ASSET_MANIFEST_CACHE = data if isinstance(data, dict) else {}
    except Exception:
        _ASSET_MANIFEST_CACHE = {}
    return _ASSET_MANIFEST_CACHE


def _paste_perk_icon(img: Any, url: Any, pos: tuple[int, int], icon_width: int) -> bool:
    if not url:
        return False
    path = _cached_path_for_url(str(url), ("perk", "hero_perks", "misc"))
    if not path:
        return False
    try:
        from PIL import Image

        icon = Image.open(path).convert("RGBA")
        if icon.width <= 0 or icon.height <= 0:
            return False
        icon_height = max(1, int(icon.height * icon_width / icon.width))
        icon = _resize_image(icon, (icon_width, icon_height)).convert("RGBA")

        pixels = icon.load()
        for py in range(icon.height):
            for px in range(icon.width):
                r, g, b, a = pixels[px, py]
                if a > 0 and r >= 245 and g >= 245 and b >= 245:
                    pixels[px, py] = (0, 0, 0, a)

        img.paste(icon, (pos[0], pos[1] + max((icon_width - icon_height) // 2, 0)), icon)
        return True
    except Exception:
        return False


def _draw_perks(draw: Any, img: Any, config: Dict[str, Any], perks: Sequence[Dict[str, Any]], y: float, row_h: float) -> None:
    if not perks:
        return
    bg_path = RESOURCE_DIR / "perk_bg.png"
    perk_lookup = _perk_lookup(config)
    for idx, perk in enumerate(list(perks)[:2]):
        candidates = _perk_guid_candidates(perk)
        perk_info = next((perk_lookup.get(candidate) for candidate in candidates if perk_lookup.get(candidate)), {})
        icon_url = perk_info.get("icon") or perk.get("icon")
        size = max(int(62 * row_h / 82), 18)
        x = int(320 + idx * (size + 4))
        py = int(y + (row_h - size) / 2)
        if bg_path.exists():
            try:
                from PIL import Image

                bg = _resize_image(Image.open(bg_path).convert("RGBA"), (size, size))
                img.paste(bg, (x, py), bg)
            except Exception:
                draw.rectangle((x, py, x + size, py + size), outline=(255, 190, 60))
        else:
            draw.rectangle((x, py, x + size, py + size), outline=(255, 190, 60))
        if icon_url:
            inner = max(int(size * 0.55), 12)
            pasted = _paste_perk_icon(
                img,
                icon_url,
                (x + (size - inner) // 2, py + (size - inner) // 2),
                inner,
            )
            if not pasted:
                label = _fit_text(draw, str(perk_info.get("name") or candidates[0])[:6], _font(10), size - 6)
                draw.text((x + 3, py + size // 2 - 6), label, font=_font(10), fill=(230, 235, 245))


def _extract_player_perks(player: Dict[str, Any]) -> list[Any]:
    for key in ("perks", "perkList", "heroPerks", "perkGuids", "perkGuidList"):
        value = player.get(key)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, str) and value.strip():
            parsed = _parse_listish_string(value)
            if parsed:
                return parsed

    hero_list = player.get("heroList")
    if isinstance(hero_list, list):
        for hero_item in hero_list:
            if not isinstance(hero_item, dict):
                continue
            nested = _extract_player_perks(hero_item)
            if nested:
                return nested
    return []


def _parse_listish_string(value: str) -> list[Any]:
    import ast
    import json

    text = str(value or "").strip()
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except Exception:
            continue
        if isinstance(parsed, list):
            return parsed
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return [text]


def _draw_guid_slots(
    draw: Any,
    img: Any,
    config: Dict[str, Any],
    guids: Sequence[Any],
    x: int,
    y: int,
    max_slots: int,
    category: str,
) -> None:
    lookup = _mod_trait_lookup(config)
    slot_size = 32
    gap = 7
    for idx in range(max_slots):
        sx = x + idx * (slot_size + gap)
        draw.rounded_rectangle((sx, y, sx + slot_size, y + slot_size), radius=6, fill=(31, 34, 46), outline=(120, 180, 255))
        if idx >= len(guids):
            continue
        item = lookup.get(str(guids[idx])) or {}
        _paste_icon_from_url(img, item.get("icon"), (sx + 2, y + 2), (slot_size - 4, slot_size - 4), (category, "perk", "mod_traits", "misc"))


def _draw_ban_heroes(img: Any, draw: Any, data: Dict[str, Any], config: Dict[str, Any]) -> None:
    has_bans = any(key in data for key in ("enemyBanHeroGuids", "teamBanHeroGuids"))
    if data.get("gameMode") != "SportPreset" and not has_bans:
        return
    hero_lookup = {str(hero.get("heroGuid")): hero for hero in config.get("heroList", []) or [] if hero.get("heroGuid")}
    banned = []
    seen = set()
    for key in ("enemyBanHeroGuids", "teamBanHeroGuids"):
        for guid in data.get(key) or []:
            guid = str(guid)
            if not guid or guid == "0" or guid in seen:
                continue
            seen.add(guid)
            banned.append(hero_lookup.get(guid) or {"heroGuid": guid})
            if len(banned) >= 4:
                break
    if not banned:
        return
    font = _font(20)
    draw.text((1165, 742), "BAN HEROES", font=_font(24, prefer_en=True), fill=(245, 245, 245))
    for idx, hero in enumerate(banned[:4]):
        x = 1165 + idx * 138
        y = 786
        draw.rounded_rectangle((x, y, x + 104, y + 104), radius=8, outline=(225, 0, 18), width=4)
        _paste_icon_from_url(img, _hero_icon_url(hero), (x + 8, y + 8), (88, 88), ("heroes", "misc"))
        name = str(hero.get("name") or hero.get("heroGuid") or "")
        draw.text((x, y + 120), _fit_text(draw, name, font, 104), font=font, fill=(245, 245, 245))


def _crop_center_to_size(img: Any, target_size: tuple[int, int]) -> Any:
    tw, th = target_size
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    new_w, new_h = int(sw * scale), int(sh * scale)
    img = _resize_image(img, (new_w, new_h))
    left, top = (new_w - tw) / 2, (new_h - th) / 2
    return img.crop((left, top, left + tw, top + th))


def _left_fade_mask(size: tuple[int, int]) -> Any:
    from PIL import Image

    mask = Image.new("L", size, 0)
    for x in range(size[0]):
        alpha = int(180 * (1 - min(1, x / 450)))
        for y in range(size[1]):
            mask.putpixel((x, y), alpha)
    return mask


def _draw_row_accent(draw: Any, y: int, match: Dict[str, Any]) -> None:
    result = match.get("matchRet")
    color = (100, 255, 120, 255) if result == 1 else (255, 255, 150, 255) if result == 0 else (255, 100, 100, 255)
    draw.rectangle([20, y, 26, y + 50], fill=color)


def _mode_label(match: Dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
    rank_info = match.get("rankInfo")
    game_mode = str(match.get("gameMode") or match.get("instanceType") or "")
    lower = game_mode.lower()
    if "sportfight" in lower:
        return "\u89d2\u6597\u7ade\u6280", (255, 190, 60)
    if "quickfight" in lower or "leisurefight" in lower or ("fight" in lower and not rank_info):
        return "\u89d2\u6597\u5feb\u901f", (180, 255, 70)
    if rank_info or "sport" in lower or "rank" in lower:
        return "\u7ade\u6280", (255, 80, 80)
    return "\u5feb\u901f", (0, 200, 255)


def _result_label(value: Any) -> tuple[str, tuple[int, int, int]]:
    if value == 1:
        return "\u80dc\u5229", (100, 255, 120)
    if value == 0:
        return "\u5e73\u5c40", (255, 255, 150)
    return "\u6218\u8d25", (255, 100, 100)


def _format_begin_ts(value: Any) -> str:
    try:
        ts = int(value or 0) / 1000
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return "--"
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def _format_duration(value: Any) -> str:
    try:
        sec = int(value or 0)
    except (TypeError, ValueError):
        sec = 0
    if sec <= 0:
        return "--:--"
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _find_map(config: Dict[str, Any], map_guid: Any) -> Dict[str, Any]:
    for item in config.get("mapList", []) or []:
        if str(item.get("guid")) == str(map_guid):
            return item
    return {}


def _find_hero(config: Dict[str, Any], hero_guid: Any) -> Dict[str, Any]:
    candidates = _hero_guid_candidates(hero_guid)
    for item in config.get("heroList", []) or []:
        for key in ("heroGuid", "heroId", "guid", "id"):
            value = item.get(key)
            if value is None:
                continue
            if str(value) in candidates:
                return item
    return {}


def _hero_guid_candidates(hero_guid: Any) -> list[str]:
    text = str(hero_guid or "").strip()
    if not text:
        return []
    candidates = [text]
    try:
        number = int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return candidates
    candidates.append(str(number))
    candidates.append(f"0x{number:016X}")
    candidates.append(f"0x0{number:015X}")
    return list(dict.fromkeys(candidates))


def _resolve_player_hero(config: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
    for raw in (
        player.get("heroGuid"),
        player.get("heroId"),
        player.get("guid"),
        player.get("id"),
    ):
        hero = _find_hero(config, raw)
        if hero:
            return hero

    for hero_item in player.get("heroList") or []:
        if not isinstance(hero_item, dict):
            continue
        for raw in (
            hero_item.get("heroGuid"),
            hero_item.get("heroId"),
            hero_item.get("guid"),
            hero_item.get("id"),
        ):
            hero = _find_hero(config, raw)
            if hero:
                return hero
    return {}


def _first_cached_asset_url(candidates: Sequence[Any], categories: Sequence[str]) -> str:
    fallback = ""
    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        if not fallback:
            fallback = text
        if _cached_path_for_url(text, categories):
            return text
    return fallback


def _hero_icon_url(hero_info: Dict[str, Any], player: Dict[str, Any] | None = None) -> str:
    hero_candidates: list[Any] = []
    if isinstance(hero_info, dict):
        hero_candidates.extend(
            [
                hero_info.get("smallIconUrl"),
                hero_info.get("ddHeroIcon"),
                hero_info.get("icon"),
                hero_info.get("circleIcon"),
                hero_info.get("portrait"),
                hero_info.get("avatar"),
            ]
        )
    hero_url = _first_cached_asset_url(hero_candidates, ("heroes", "misc"))
    if hero_url:
        return hero_url

    player_candidates: list[Any] = []
    if isinstance(player, dict):
        player_candidates.extend(
            [
                player.get("heroIcon"),
                player.get("icon"),
                player.get("avatar"),
            ]
        )
        for hero_item in player.get("heroList") or []:
            if not isinstance(hero_item, dict):
                continue
            player_candidates.extend(
                [
                    hero_item.get("smallIconUrl"),
                    hero_item.get("ddHeroIcon"),
                    hero_item.get("icon"),
                    hero_item.get("circleIcon"),
                    hero_item.get("heroIcon"),
                ]
            )
    return _first_cached_asset_url(player_candidates, ("heroes", "misc"))


def _perk_lookup(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup = {}
    groups = config.get("heroPerkList") or config.get("perk") or {}
    if isinstance(groups, dict):
        iterable = groups.values()
    else:
        iterable = groups if isinstance(groups, list) else []
    for group in iterable:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("guid") or "")
            if item_id:
                lookup[item_id] = item
                try:
                    lookup[str(int(item_id, 16))] = item
                except Exception:
                    pass
    return lookup


def _perk_guid_candidates(perk: Any) -> list[str]:
    if isinstance(perk, dict):
        raw_values = [
            perk.get("guid"),
            perk.get("id"),
            perk.get("perkGuid"),
            perk.get("value"),
        ]
    else:
        raw_values = [perk]

    candidates = []
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        candidates.append(text)
        try:
            number = int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            continue
        candidates.append(str(number))
        candidates.append(f"0x{number:016X}")
        candidates.append(f"0x0{number:015X}")
    return list(dict.fromkeys(candidates))


def _mod_trait_lookup(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup = {}
    groups = config.get("modTrait") or {}
    if isinstance(groups, dict):
        iterable = groups.values()
    else:
        iterable = groups if isinstance(groups, list) else []
    for group in iterable:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("guid") or "")
            if item_id:
                lookup[item_id] = item
                try:
                    lookup[str(int(item_id, 16))] = item
                except Exception:
                    pass
    return lookup


def _sort_players(players: Sequence[Dict[str, Any]], config: Dict[str, Any]) -> list[Dict[str, Any]]:
    def weight(player: Dict[str, Any]) -> int:
        role = (_resolve_player_hero(config, player) or {}).get("roleType") or player.get("roleType")
        return {"tank": 1, "dps": 2, "healer": 3, "support": 3}.get(str(role), 99)

    return sorted([player for player in players if isinstance(player, dict)], key=weight)


def _player_name(player: Dict[str, Any]) -> str:
    name = str(player.get("name") or player.get("battletag") or player.get("bnetId") or "Unknown")
    return name.split("#", 1)[0]


def _split_battletag(player: Dict[str, Any]) -> tuple[str, str]:
    name = str(player.get("name") or player.get("battletag") or player.get("bnetId") or "Unknown")
    if "#" in name:
        tag, num = name.split("#", 1)
        return tag, num
    return name, ""


def _fmt_num(value: Any) -> str:
    try:
        return f"{int(round(float(value or 0))):,}"
    except (TypeError, ValueError):
        return str(value or "-")


def _rank_text(rank_info: Any) -> str:
    if not isinstance(rank_info, dict) or not rank_info:
        return "-"
    score = rank_info.get("rankScore") or rank_info.get("score")
    tier = rank_info.get("rankSubTier") or rank_info.get("rank_sub_tier") or ""
    if score:
        return f"{score}{tier}"
    return str(tier or "-")


def _role_type(player: Dict[str, Any], hero_info: Dict[str, Any]) -> str:
    return _normalize_role_name(
        player.get("roleType")
        or (player.get("rankInfo") or {}).get("roleType")
        or (player.get("rankInfo") or {}).get("role")
        or hero_info.get("roleType")
        or hero_info.get("role")
        or ""
    )


def _role_label(player: Dict[str, Any], hero_info: Dict[str, Any]) -> str:
    return {
        "tank": "重装",
        "dps": "输出",
        "healer": "支援",
        "open": "开放",
    }.get(_role_type(player, hero_info), "")


def _role_style(role: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int], str]:
    styles = {
        "tank": ((76, 157, 255, 220), (185, 225, 255, 255), (255, 255, 255, 255), "重"),
        "dps": ((255, 122, 94, 220), (255, 220, 197, 255), (255, 255, 255, 255), "输"),
        "healer": ((88, 199, 126, 220), (220, 255, 228, 255), (255, 255, 255, 255), "援"),
        "open": ((164, 123, 255, 220), (234, 223, 255, 255), (255, 255, 255, 255), "开"),
    }
    return styles.get(role, ((90, 96, 112, 220), (200, 205, 218, 255), (255, 255, 255, 255), "?"))


def _rank_label(rank_info: Dict[str, Any], *, mode: str) -> str:
    score = _safe_int(rank_info.get("rankScore") or rank_info.get("score"))
    tier = str(rank_info.get("rankSubTier") or rank_info.get("rank_sub_tier") or "").strip()
    rank_name = str(rank_info.get("rankName") or rank_info.get("rank_name") or "").strip()
    if rank_name and tier:
        return f"{rank_name}{tier}"
    if rank_name:
        return rank_name
    if score > 0:
        rank_text = _score_to_rank_fight(score) if mode == "fight" else _score_to_rank(score)
        if rank_text != "未定义":
            return rank_text
    if tier:
        return tier
    return ""


def _rank_colors(score: int, mode: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    if score >= 4500:
        return (164, 45, 255, 230), (248, 219, 255, 255)
    if score >= 4000:
        return (255, 96, 145, 230) if mode == "fight" else (230, 126, 34, 230), (255, 239, 199, 255)
    if score >= 3500:
        return (175, 88, 255, 230), (230, 214, 255, 255)
    if score >= 3000:
        return (82, 178, 255, 230), (222, 241, 255, 255)
    if score >= 2500:
        return (57, 205, 174, 230), (215, 255, 244, 255)
    if score >= 2000:
        return (255, 196, 70, 230), (255, 245, 207, 255)
    if score >= 1500:
        return (185, 191, 203, 230), (245, 247, 252, 255)
    return (156, 106, 73, 235), (235, 214, 196, 255)


def _score_to_rank(score: int) -> str:
    if score < 0:
        return "未定义"
    if score < 1500:
        idx = int((score - 1000) // 100)
        return f"青铜{5 - idx}"
    if score < 2000:
        idx = int((score - 1500) // 100)
        return f"白银{5 - idx}"
    if score < 2500:
        idx = int((score - 2000) // 100)
        return f"黄金{5 - idx}"
    if score < 3000:
        idx = int((score - 2500) // 100)
        return f"白金{5 - idx}"
    if score < 3500:
        idx = int((score - 3000) // 100)
        return f"钻石{5 - idx}"
    if score < 4000:
        idx = int((score - 3500) // 100)
        return f"大师{5 - idx}"
    if score < 4500:
        idx = int((score - 4000) // 100)
        return f"宗师{5 - idx}"
    if score < 5000:
        idx = int((score - 4500) // 100)
        return f"英杰{5 - idx}"
    return "未定义"


def _score_to_rank_fight(score: int) -> str:
    if score < 0:
        return "未定义"
    if score < 1500:
        idx = int((score - 999) // 100)
        return f"菜鸟{5 - idx}"
    if score < 2000:
        idx = int((score - 1500) // 100)
        return f"新秀{5 - idx}"
    if score < 2500:
        idx = int((score - 2000) // 100)
        return f"斗士{5 - idx}"
    if score < 3000:
        idx = int((score - 2500) // 100)
        return f"精英{5 - idx}"
    if score < 3500:
        idx = int((score - 3000) // 100)
        return f"专家{5 - idx}"
    if score < 4000:
        idx = int((score - 3500) // 100)
        return f"全明星{5 - idx}"
    if score < 4500:
        idx = int((score - 4000) // 100)
        return f"传奇{5 - idx}"
    if score < 5000:
        idx = int((score - 4500) // 100)
        return f"巅峰{5 - idx}"
    return "未定义"


def _short_id(value: Any) -> str:
    text = str(value or "-")
    return text[-6:] if len(text) > 6 else text


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _role_label(player: Dict[str, Any], hero_info: Dict[str, Any]) -> str:
    return {
        "tank": "\u91cd\u88c5",
        "dps": "\u8f93\u51fa",
        "healer": "\u652f\u63f4",
        "open": "\u5f00\u653e",
    }.get(_role_type(player, hero_info), "")


def _role_style(role: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int], str]:
    styles = {
        "tank": ((76, 157, 255, 220), (185, 225, 255, 255), (255, 255, 255, 255), "\u91cd"),
        "dps": ((255, 122, 94, 220), (255, 220, 197, 255), (255, 255, 255, 255), "\u8f93"),
        "healer": ((88, 199, 126, 220), (220, 255, 228, 255), (255, 255, 255, 255), "\u63f4"),
        "open": ((164, 123, 255, 220), (234, 223, 255, 255), (255, 255, 255, 255), "\u5f00"),
    }
    return styles.get(role, ((90, 96, 112, 220), (200, 205, 218, 255), (255, 255, 255, 255), "?"))


def _rank_label(rank_info: Dict[str, Any], *, mode: str) -> str:
    score = _safe_int(rank_info.get("rankScore") or rank_info.get("score"))
    tier = str(rank_info.get("rankSubTier") or rank_info.get("rank_sub_tier") or "").strip()
    rank_name = str(rank_info.get("rankName") or rank_info.get("rank_name") or "").strip()
    if rank_name and tier:
        return f"{rank_name}{tier}"
    if rank_name:
        return rank_name
    if score > 0:
        rank_text = _score_to_rank_fight(score) if mode == "fight" else _score_to_rank(score)
        if rank_text != "\u672a\u5b9a\u7ea7":
            return rank_text
    if tier:
        return tier
    return ""


def _score_to_rank(score: int) -> str:
    if score < 0:
        return "\u672a\u5b9a\u7ea7"
    if score < 1500:
        idx = int((score - 1000) // 100)
        return f"\u9752\u94dc{5 - idx}"
    if score < 2000:
        idx = int((score - 1500) // 100)
        return f"\u767d\u94f6{5 - idx}"
    if score < 2500:
        idx = int((score - 2000) // 100)
        return f"\u9ec4\u91d1{5 - idx}"
    if score < 3000:
        idx = int((score - 2500) // 100)
        return f"\u94c2\u91d1{5 - idx}"
    if score < 3500:
        idx = int((score - 3000) // 100)
        return f"\u94bb\u77f3{5 - idx}"
    if score < 4000:
        idx = int((score - 3500) // 100)
        return f"\u5927\u5e08{5 - idx}"
    if score < 4500:
        idx = int((score - 4000) // 100)
        return f"\u5b97\u5e08{5 - idx}"
    if score < 5000:
        idx = int((score - 4500) // 100)
        return f"\u82f1\u6770{5 - idx}"
    return "\u672a\u5b9a\u7ea7"


def _score_to_rank_fight(score: int) -> str:
    if score < 0:
        return "\u672a\u5b9a\u7ea7"
    if score < 1500:
        idx = int((score - 999) // 100)
        return f"\u83dc\u9e1f{5 - idx}"
    if score < 2000:
        idx = int((score - 1500) // 100)
        return f"\u65b0\u79c0{5 - idx}"
    if score < 2500:
        idx = int((score - 2000) // 100)
        return f"\u6597\u58eb{5 - idx}"
    if score < 3000:
        idx = int((score - 2500) // 100)
        return f"\u7cbe\u82f1{5 - idx}"
    if score < 3500:
        idx = int((score - 3000) // 100)
        return f"\u4e13\u5bb6{5 - idx}"
    if score < 4000:
        idx = int((score - 3500) // 100)
        return f"\u5168\u660e\u661f{5 - idx}"
    if score < 4500:
        idx = int((score - 4000) // 100)
        return f"\u4f20\u5947{5 - idx}"
    if score < 5000:
        idx = int((score - 4500) // 100)
        return f"\u5dc5\u5cf0{5 - idx}"
    return "\u672a\u5b9a\u7ea7"


def _load_ow_config() -> Dict[str, Any]:
    try:
        return load_query_tool()
    except Exception as exc:
        print(f"[overstats] failed to load query_tool config: {exc}")
        return {}


def _font_resource(name: str, size: int, *, fallback: str | None = None) -> Any:
    from PIL import ImageFont

    candidates = [RESOURCE_DIR / name]
    if fallback:
        candidates.append(RESOURCE_DIR / fallback)
    candidates.extend(
        [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_chinese(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
    ):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font(size: int, *, prefer_en: bool = False) -> Any:
    from PIL import ImageFont

    if prefer_en:
        font_paths = (
            RESOURCE_DIR / "en.ttf",
            RESOURCE_DIR / "en2.ttf",
            RESOURCE_DIR / "BigNoodleToo.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        )
    else:
        font_paths = (
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            RESOURCE_DIR / "GrotaRoundedExtraBold.otf",
            RESOURCE_DIR / "en2.ttf",
            RESOURCE_DIR / "en.ttf",
            "C:/Windows/Fonts/arial.ttf",
        )
    for path in font_paths:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _font_en(size: int) -> Any:
    return _font_resource("en.ttf", size, fallback="en2.ttf")


def _font_en_oblique(size: int) -> Any:
    return _font_resource("bignoodletoooblique.ttf", size, fallback="BigNoodleToo.ttf")


def _font_meta(size: int) -> Any:
    return _font_resource("en2.ttf", size, fallback="BigNoodleToo.ttf")


def _font_num(size: int) -> Any:
    return _font_resource("GrotaRoundedExtraBold.otf", size, fallback="en.ttf")


def _font_num_small(size: int) -> Any:
    return _font_resource("GrotaRoundedExtraBold.otf", size, fallback="en.ttf")


def _font_num_display(size: int) -> Any:
    return _font_resource("GrotaRoundedExtraBold.otf", size, fallback="en.ttf")


def _text_width(draw: Any, text: str, font: Any) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])
    except Exception:
        return int(draw.textlength(text, font=font))


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    except Exception:
        width = _text_width(draw, text, font)
        try:
            _, _, _, height = font.getbbox(text)
            return width, int(height)
        except Exception:
            return width, int(getattr(font, "size", 16))


def _fit_font(
    draw: Any,
    text: str,
    font_factory: Any,
    base_size: int,
    min_size: int,
    max_width: int,
) -> Any:
    text = str(text or "")
    for size in range(max(base_size, min_size), max(min_size - 1, 0), -1):
        font = font_factory(size)
        if _text_width(draw, text, font) <= max_width:
            return font
    return font_factory(max(1, min_size))


def _draw_labeled_value(
    draw: Any,
    x: int,
    y: int,
    label: str,
    value: str,
    label_font: Any,
    value_font: Any,
    *,
    fill: Any,
) -> None:
    label = str(label or "")
    value = str(value or "")
    draw.text((x, y), label, font=label_font, fill=fill)
    draw.text((x + _text_width(draw, label, label_font), y), value, font=value_font, fill=fill)


def _fit_text(draw: Any, text: str, font: Any, max_width: int) -> str:
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def _rounded_rect(draw: Any, box: Sequence[int], *, radius: int, fill: tuple[int, int, int, int]) -> None:
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    except Exception:
        draw.rectangle(box, fill=fill)
