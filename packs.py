"""Manage optional resource packs: python packs.py --help."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    # Loading by file avoids src.__init__, which imports the HTTP server.
    runpy.run_path(
        str(Path(__file__).resolve().parent / "src" / "modules" / "ow_guess" / "packs.py"),
        run_name="__main__",
    )
