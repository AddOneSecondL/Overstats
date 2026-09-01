from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Sequence


_CJK_FONT_FILENAMES = {
    "simhei.ttf",
    "msyh.ttc",
    "msyhbd.ttc",
    "simsun.ttc",
    "notosanscjk-regular.ttc",
    "notosanscjk-bold.ttc",
    "notoserifcjk-regular.ttc",
    "notoserifcjk-bold.ttc",
    "wqy-microhei.ttc",
}
_LINUX_CJK_REGULAR = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
)
_LINUX_CJK_BOLD = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
)
_WINDOWS_CJK_REGULAR = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)
_WINDOWS_CJK_BOLD = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/msyh.ttc"),
)
_WINDOWS_LATIN_FALLBACKS = (
    Path("C:/Windows/Fonts/arial.ttf"),
)


def resolve_resource_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "res",
        here.parents[3] / "Overstats" / "res",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _normalize_key(path_like: str | os.PathLike[str] | None) -> str:
    return os.path.normcase(os.path.normpath(str(path_like or "")))


def _dedupe(paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in paths:
        path = Path(candidate)
        key = _normalize_key(path)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _font_name(font_path: str | os.PathLike[str] | None) -> str:
    return Path(str(font_path or "")).name.lower()


def _resource_font_path(resource_dir: Path, font_path: str | os.PathLike[str] | None) -> Path:
    """Resolve a bundled font without losing its on-disk filename casing.

    The resource files are addressed case-insensitively on Windows, but Linux
    treats ``BigNoodleToo.ttf`` and ``bignoodletoo.ttf`` as different paths.
    Keep the requested spelling when possible, then find the matching bundled
    file case-insensitively so a font never silently falls back to a system
    font just because the request used a different case.
    """
    filename = Path(str(font_path or "")).name
    exact_path = resource_dir / filename
    if exact_path.exists():
        return exact_path

    folded_name = filename.casefold()
    if folded_name:
        try:
            for candidate in resource_dir.iterdir():
                if candidate.is_file() and candidate.name.casefold() == folded_name:
                    return candidate
        except OSError:
            pass
    return exact_path


def _is_cjk_font_request(font_path: str | os.PathLike[str] | None) -> bool:
    return _font_name(font_path) in _CJK_FONT_FILENAMES


def get_cjk_font_candidates(*, bold: bool = False) -> list[Path]:
    resource_dir = resolve_resource_dir()
    env_name = "OVERSTATS_CJK_BOLD_FONT" if bold else "OVERSTATS_CJK_FONT"
    bundled_font = resource_dir / "simhei.ttf"
    linux_fonts = _LINUX_CJK_BOLD if bold else _LINUX_CJK_REGULAR
    windows_fonts = _WINDOWS_CJK_BOLD if bold else _WINDOWS_CJK_REGULAR
    candidates: list[str | os.PathLike[str]] = [bundled_font]
    font_env = os.getenv(env_name)
    if font_env:
        candidates.append(font_env)
    candidates.extend(linux_fonts)
    candidates.extend(windows_fonts)
    return _dedupe(candidates)


def get_cjk_font_path(*, bold: bool = False) -> str | None:
    for candidate in get_cjk_font_candidates(bold=bold):
        if candidate.exists():
            return str(candidate)
    return None


def iter_font_candidates(
    name: str | os.PathLike[str] | None = None,
    *,
    fallback: str | os.PathLike[str] | None = None,
    prefer_cjk: bool = False,
    bold: bool = False,
    extra: Sequence[str | os.PathLike[str]] = (),
) -> list[Path]:
    resource_dir = resolve_resource_dir()
    requested_name = _font_name(name)
    fallback_name = _font_name(fallback)
    treat_as_cjk = prefer_cjk or _is_cjk_font_request(name) or _is_cjk_font_request(fallback)

    candidates: list[str | os.PathLike[str]] = []
    if treat_as_cjk:
        candidates.extend(get_cjk_font_candidates(bold=bold))

    if requested_name:
        candidates.append(_resource_font_path(resource_dir, name))
    if fallback_name:
        candidates.append(_resource_font_path(resource_dir, fallback))
    for extra_candidate in extra:
        extra_name = _font_name(extra_candidate)
        if extra_name:
            candidates.append(_resource_font_path(resource_dir, extra_candidate))
        candidates.append(extra_candidate)

    if not treat_as_cjk:
        candidates.extend(get_cjk_font_candidates(bold=bold))

    candidates.extend(_WINDOWS_LATIN_FALLBACKS)

    if name:
        candidates.append(name)
    if fallback:
        candidates.append(fallback)

    return _dedupe(candidates)


def load_font(
    size: int,
    *,
    name: str | os.PathLike[str] | None = None,
    fallback: str | os.PathLike[str] | None = None,
    prefer_cjk: bool = False,
    bold: bool = False,
    extra: Sequence[str | os.PathLike[str]] = (),
) -> Any:
    from PIL import ImageFont

    for candidate in iter_font_candidates(
        name=name,
        fallback=fallback,
        prefer_cjk=prefer_cjk,
        bold=bold,
        extra=extra,
    ):
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return ImageFont.load_default()
