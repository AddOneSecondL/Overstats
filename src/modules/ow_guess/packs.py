from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = ROOT / 'res' / 'ow_guess' / 'packs'
INDEX = ROOT / 'res' / 'ow_guess' / 'packs.json'
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_AUDIO = 2 * 1024 * 1024


def _inside(path, root):
    # Path.is_relative_to is unavailable on Python 3.8.
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def catalog():
    return json.loads(INDEX.read_text(encoding='utf-8'))['packs']


def pack_path(pack_id):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', pack_id):
        raise ValueError('无效的扩展包名称')
    path = PACK_ROOT / pack_id
    if path.is_symlink() or not _inside(path, PACK_ROOT):
        raise ValueError('扩展包目录不合法')
    return path


def active_pack(pack_id):
    root = pack_path(pack_id)
    pointer = root / 'current.json'
    if not pointer.is_file():
        return None
    value = json.loads(pointer.read_text(encoding='utf-8'))
    revision = value['revision']
    if not re.fullmatch(r'[0-9a-f]{64}', revision):
        raise ValueError('扩展包版本路径不合法')
    folder = root / revision
    if folder.is_symlink() or not _inside(folder, root):
        raise ValueError('扩展包版本路径不合法')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    return folder, manifest


def media_path(folder, relative):
    name = PurePosixPath(relative)
    if name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
        raise ValueError('资源路径不合法')
    path = folder.joinpath(*name.parts)
    if not _inside(path, folder) or path.is_symlink():
        raise ValueError('资源路径超出扩展包')
    return path


def questions(mode='map_music'):
    result = []
    if not PACK_ROOT.exists():
        return result
    for root in PACK_ROOT.iterdir():
        if not root.is_dir() or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', root.name):
            continue
        try:
            active = active_pack(root.name)
            if not active:
                continue
            folder, manifest = active
            for question in manifest['questions']:
                if question['mode'] != mode:
                    continue
                path = media_path(folder, question['media'])
                if path.is_file() and 0 < path.stat().st_size <= MAX_AUDIO:
                    result.append({**question, 'media_path': path, 'pack_id': root.name})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def _validate(folder, pack_id):
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('id') != pack_id or not isinstance(manifest.get('version'), str):
        raise ValueError('扩展包清单版本或名称不匹配')
    entries = manifest.get('questions')
    if not isinstance(entries, list) or not entries or len(entries) > 2000:
        raise ValueError('扩展包题目数量不合法')
    seen = set()
    for entry in entries:
        if entry.get('mode') != 'map_music' or not isinstance(entry.get('id'), str) or entry['id'] in seen:
            raise ValueError('不支持的题型或重复的题目 ID')
        seen.add(entry['id'])
        aliases = entry.get('answers')
        if not isinstance(aliases, list) or not aliases or any(not isinstance(a, str) or not a.strip() for a in aliases):
            raise ValueError('题目缺少有效答案')
        maps = entry.get('maps', [aliases[0]])
        if not isinstance(maps, list) or not maps or any(not isinstance(name, str) or name not in aliases for name in maps):
            raise ValueError('地图列表必须包含在可接受答案中')
        path = media_path(folder, entry['media'])
        if path.suffix != '.mp3' or not 0 < path.stat().st_size <= MAX_AUDIO:
            raise ValueError('音频需为不超过 2 MiB 的 MP3')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get('sha256'):
            raise ValueError(f"音频校验失败：{entry['id']}")
    return manifest


def install(pack_id, source=None):
    root = pack_path(pack_id)
    expected = None
    if source is None:
        info = catalog().get(pack_id)
        if not info:
            raise ValueError('未找到该扩展包')
        source, expected = info['url'], info['sha256']
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.install-', dir=root) as temporary:
        stage = Path(temporary)
        archive = stage / 'pack.zip'
        if str(source).startswith('https://'):
            with httpx.stream('GET', source, follow_redirects=True, timeout=60) as response:
                if response.status_code == 404:
                    raise ValueError("远程扩展包尚未发布或地址失效；可使用 --source 本地ZIP路径 安装")
                response.raise_for_status()
                size = 0
                with archive.open('wb') as stream:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_ARCHIVE:
                            raise ValueError('扩展包下载超过大小限制')
                        stream.write(chunk)
        else:
            local = Path(source)
            if local.stat().st_size > MAX_ARCHIVE:
                raise ValueError('扩展包超过大小限制')
            shutil.copyfile(local, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError('扩展包 SHA256 校验失败，原版本保持不变')
        unpacked = stage / 'content'
        unpacked.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > 4000 or sum(m.file_size for m in members) > MAX_ARCHIVE:
                raise ValueError('解压大小超过限制')
            seen = set()
            for member in members:
                target = media_path(unpacked, member.filename)
                if member.filename in seen or (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('扩展包存在重复路径或符号链接')
                seen.add(member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as src, target.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
        manifest = _validate(unpacked, pack_id)
        revision = root / digest
        if not revision.exists():
            unpacked.rename(revision)
        _validate(revision, pack_id)
        pointer = stage / 'current.json'
        pointer.write_text(json.dumps({'revision': digest}), encoding='utf-8')
        os.replace(pointer, root / 'current.json')
    print(f"已安装 {pack_id} {manifest['version']}，共 {len(manifest['questions'])} 题")


def remove(pack_id):
    root = pack_path(pack_id)
    if root.exists():
        shutil.rmtree(root)
    print(f'已卸载 {pack_id}')


def main():
    parser = argparse.ArgumentParser(description='猜一猜可选扩展包管理；音频不会随 git pull 下载')
    parser.add_argument('action', nargs='?', default='list',
                        choices=['list', 'install', 'update', 'remove', 'uninstall'],
                        help='list 列出；install 安装；update 更新；remove/uninstall 卸载；默认列出')
    parser.add_argument('pack', nargs='?')
    parser.add_argument('--source', help='本地 ZIP 路径或 HTTPS 地址；省略时自动从 GitHub Releases 下载')
    args = parser.parse_args()
    try:
        if args.action == 'list':
            entries = catalog()
            ids = set(entries) | ({p.name for p in PACK_ROOT.iterdir() if p.is_dir() and not p.name.startswith('.')} if PACK_ROOT.exists() else set())
            for key in sorted(ids):
                active = active_pack(key)
                current = active[1]['version'] if active else '未安装'
                print(f"{key}: {current} / 可用 {entries.get(key, {}).get('version', '本地包')}")
        elif args.action == 'update':
            ids = [args.pack] if args.pack else [key for key in catalog() if active_pack(key)]
            for key in ids:
                active = active_pack(key)
                if active and not args.source and active[1]['version'] == catalog().get(key, {}).get('version'):
                    print(f'{key} 已是当前版本')
                else:
                    install(key, args.source)
        elif not args.pack:
            parser.error('请指定扩展包名称')
        elif args.action in ('remove', 'uninstall'):
            remove(args.pack)
        else:
            install(args.pack, args.source)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, httpx.HTTPError) as exc:
        parser.exit(1, f'扩展包操作失败：{exc}\n')


if __name__ == '__main__':
    main()
