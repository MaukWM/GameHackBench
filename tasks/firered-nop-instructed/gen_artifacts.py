# mypy: ignore-errors
"""One-shot artifact generator for the firered-nop-instructed task.

Thin shim over `gamehackbench.lib.gba.artifacts.generate_artifacts`. The agent
generates its own patch at runtime, so `write_solution=False` skips the
xdelta3 encode + round-trip step and only stages the ROM and re-derives the
oracle (asserted against `task.toml`).

Run from this directory:
    uv run python gen_artifacts.py
"""

from __future__ import annotations

from pathlib import Path

from gamehackbench.lib.gba.artifacts import generate_artifacts

if __name__ == "__main__":
    generate_artifacts(Path(__file__).resolve().parent, write_solution=False)
