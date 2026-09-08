"""Opt-in SCF entry point. Ordinary deployments continue to use run.py."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile


def prepare_runtime(source: Path, temporary_parent: Path, *, link_resources: bool = False) -> Path:
    """Prepare a private runtime; optionally link immutable image resources.

    Preserve the lower-case overstats package layout expected by resource paths.
    SQLite data, tests, git history and local generated output are not deployed.
    Linked files are read-only on SCF; cache writers must replace atomically.
    """
    workspace = Path(tempfile.mkdtemp(prefix="overstats-scf-", dir=temporary_parent))
    target = workspace / "overstats"
    target.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sqlite*", "*.db", ".git")
    try:
        for name in ("src", "config", "res"):
            if (source / name).is_dir():
                if name == "res" and link_resources:
                    # Writable directory tree, immutable image-backed resource files.
                    # Atomic cache replacements remain private to this instance.
                    shutil.copytree(source / name, target / name, ignore=ignore,
                                    copy_function=lambda src, dst: os.symlink(src, dst))
                else:
                    shutil.copytree(source / name, target / name, ignore=ignore)
        for name in ("run.py", "__init__.py"):
            shutil.copy2(source / name, target / name)
    except Exception:
        shutil.rmtree(workspace)
        raise
    return target


def main() -> None:
    cos_names = ("OVERSTATS_ACCOUNTS_COS_REGION", "OVERSTATS_ACCOUNTS_COS_BUCKET", "OVERSTATS_ACCOUNTS_COS_KEY")
    use_cos = any(name in os.environ for name in cos_names)
    if use_cos:
        if not all(os.environ.get(name, "").strip() for name in cos_names):
            raise ValueError("All three OVERSTATS_ACCOUNTS_COS_* settings are required")
    else:
        for name in ("OVERSTATS_DASHEN_ROLE_ID", "OVERSTATS_DASHEN_TOKEN"):
            if not os.environ.get(name, "").strip():
                raise ValueError(f"SCF requires {name} or a COS account pool")
        if int(os.environ["OVERSTATS_DASHEN_ROLE_ID"]) <= 0:
            raise ValueError("OVERSTATS_DASHEN_ROLE_ID must be positive")
    os.environ["OVERSTATS_API_HOST"] = "0.0.0.0"
    os.environ["OVERSTATS_API_PORT"] = "9000"
    os.environ["OVERSTATS_ENABLE_DATABASE_WRITE"] = "false"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["OVERSTATS_SCF_FROZEN_QUERY_TOOL"] = "1"
    runtime = prepare_runtime(Path(__file__).resolve().parent, Path(tempfile.gettempdir()), link_resources=True)
    os.chdir(runtime.parent)
    if use_cos:
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve().with_name("scf_cos_gateway.py"))])
    # Replace bootstrap so all imports and __file__ paths refer to writable files.
    os.execv(sys.executable, [sys.executable, "-m", "overstats.run"])


if __name__ == "__main__":
    main()
