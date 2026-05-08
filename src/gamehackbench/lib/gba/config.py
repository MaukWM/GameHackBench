"""Typed loader for GBA task.toml files.

GBA tasks come in two flavors today:

1. **RAM-SHA tasks** (e.g. firered-nop-smoke): agent submits an xdelta3
   patch; verifier applies, runs gba_probe, scores by SHA-1 of the RAM dump
   against a pinned oracle.
2. **Predicate tasks** (e.g. firered-all-badges):
   agent submits an artifact (input.txt, patch, etc.); verifier runs
   gba_play and scores by evaluating an rcheevos-subset predicate against
   the RAM dump.

Both kinds share `[rom]` and `[probe]`. RAM-SHA adds `[oracle]` + `[patch]`;
predicate adds `[predicate]` and optionally `[runner]`. The loader validates
which sections are present and returns a `TaskConfig` with the matching
optional fields populated.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class TaskConfig(BaseModel):
    """Validated view of a GBA task's task.toml."""

    id: str
    description: str = ""
    kind: Literal["ram_sha", "predicate"]
    rom_path: str = Field(
        ...,
        description=(
            "ROM filename (relative). Convention: file lives at roms/<rom_path> on the "
            "host and at /roms/<rom_path> inside the verifier sandbox."
        ),
    )
    rom_sha1: str
    sav_path: str | None = None  # baked into the verifier image alongside the ROM
    frames: int

    # ram_sha-only
    oracle_sha1: str | None = None
    patch_offset: int | None = None
    patch_bytes: bytes | None = None
    patch_format: str = "xdelta3"

    # predicate-only
    predicate_expr: str | None = None
    predicate_explanation: str = ""
    # Which artifact the agent submits — "input" (gba_play scripted button
    # input) or "pokes" (RAM byte writes applied after state load). Default
    # "input" preserves the existing overworld-smoke contract.
    runner_artifact: Literal["input", "pokes"] = "input"
    runner_agent_input: str | None = None
    runner_agent_pokes: str | None = None
    runner_state: str | None = None
    runner_cheats: str | None = None
    # Verifier-side budget for the verify-pokes Inspect tool (cap on how many
    # times the agent may call the verifier during solve). Only consulted by
    # pokes tasks; predicate scoring is unaffected.
    verify_budget: int = 8


def load_task_config(task_dir: Path) -> TaskConfig:
    """Read `<task_dir>/task.toml` and return a validated `TaskConfig`."""
    raw = tomllib.loads((task_dir / "task.toml").read_text())
    rom = raw["rom"]
    probe = raw["probe"]

    has_oracle = "oracle" in raw and "patch" in raw
    has_predicate = "predicate" in raw
    if has_oracle == has_predicate:
        raise ValueError(
            f"task.toml in {task_dir} must define exactly one of [oracle]+[patch] or [predicate]"
        )

    base = {
        "id": raw["id"],
        "description": raw.get("description", ""),
        "rom_path": rom["path"],
        "rom_sha1": str(rom["sha1"]).lower(),
        "sav_path": rom.get("sav"),
        "frames": int(probe["frames"]),
    }

    if has_oracle:
        oracle = raw["oracle"]
        patch = raw["patch"]
        return TaskConfig(
            **base,
            kind="ram_sha",
            oracle_sha1=str(oracle["state_sha1"]).lower(),
            patch_offset=int(patch["offset"]),
            patch_bytes=bytes.fromhex(str(patch["bytes_hex"])),
            patch_format=str(patch.get("format", "xdelta3")),
        )

    pred = raw["predicate"]
    runner = raw.get("runner", {})
    artifact = str(runner.get("artifact", "input")).lower()
    if artifact not in ("input", "pokes"):
        raise ValueError(f"runner.artifact must be 'input' or 'pokes', got {artifact!r}")
    return TaskConfig(
        **base,
        kind="predicate",
        predicate_expr=str(pred["expr"]),
        predicate_explanation=str(pred.get("explanation", "")),
        runner_artifact=artifact,  # type: ignore[arg-type]
        runner_agent_input=runner.get("agent_input"),
        runner_agent_pokes=runner.get("agent_pokes"),
        runner_state=runner.get("state"),
        runner_cheats=runner.get("cheats"),
        verify_budget=int(runner.get("verify_budget", 8)),
    )
