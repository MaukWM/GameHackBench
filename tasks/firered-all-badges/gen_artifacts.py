# mypy: ignore-errors
"""Artifact generator for firered-all-badges.

Pokes task — no ROM patching, no input.txt. Stages ROM + the pinned seed
savestate into the verifier build context, then runs gba_play with the
reference solution/pokes.txt against the seed state and asserts the
predicate fires. Drift here means either the predicate, solution, the
seed state, or the determinism stack regressed.

Run from this directory:
    uv run python gen_artifacts.py
"""

from __future__ import annotations

from pathlib import Path

from gamehackbench.lib.gba.artifacts import stage_pokes_task

if __name__ == "__main__":
    stage_pokes_task(Path(__file__).resolve().parent)
