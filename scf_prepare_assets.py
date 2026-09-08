"""Fetch query-tool assets while building the deployment image."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if (Path(__file__).resolve().parent.parent / "overstats" / "__init__.py").exists() and Path(__file__).resolve().parent.name == "overstats":
    from overstats.src.modules.query_tool import ensure_query_tool_assets, load_query_tool
else:
    from src.modules.query_tool import ensure_query_tool_assets, load_query_tool


def main() -> None:
    config = load_query_tool()
    result = ensure_query_tool_assets(config)
    print(f"SCF resource preparation: {result}")
    if not result["checked"] or result["failed"]:
        raise RuntimeError("Resource preparation incomplete; refusing to build an empty/partial image")
    root = Path(__file__).resolve().parent
    total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    print(f"SCF packaged source/resources: {total / 1024 / 1024:.1f} MiB; allow additional temporary download space")


if __name__ == "__main__":
    main()
