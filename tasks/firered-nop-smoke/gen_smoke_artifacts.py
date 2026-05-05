# mypy: ignore-errors
"""One-shot artifact generator for the firered-nop-smoke task.

Thin shim over `gamehackbench.lib.gba.artifacts.generate_artifacts`. Patch
parameters (offset, bytes, frames, oracle SHA-1) live in `task.toml` — edit
those, re-run this script, and commit the regenerated `solution/patch.xdelta`.

Run from this directory:
    uv run python gen_smoke_artifacts.py
"""

from __future__ import annotations

from pathlib import Path

from gamehackbench.lib.gba.artifacts import generate_artifacts

if __name__ == "__main__":
    generate_artifacts(Path(__file__).resolve().parent, write_solution=True)
