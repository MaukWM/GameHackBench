"""Typed loader for GBA task.toml files.

Every GBA task ships a `task.toml` with the same shape (id, ROM, frames,
oracle SHA-1, patch metadata). This module reads that file and returns a
validated `TaskConfig` so per-task code stops re-implementing the same toml
boilerplate and can rely on field types/conventions instead of dict gets.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class TaskConfig(BaseModel):
    """Validated view of a GBA task's task.toml."""

    id: str
    description: str = ""
    rom_path: str = Field(
        ...,
        description=(
            "ROM filename (relative). Convention: file lives at roms/<rom_path> on the "
            "host and at /roms/<rom_path> inside the verifier sandbox."
        ),
    )
    rom_sha1: str
    frames: int
    oracle_sha1: str
    patch_offset: int
    patch_bytes: bytes
    patch_format: str = "xdelta3"


def load_task_config(task_dir: Path) -> TaskConfig:
    """Read `<task_dir>/task.toml` and return a validated `TaskConfig`."""
    raw = tomllib.loads((task_dir / "task.toml").read_text())
    rom = raw["rom"]
    probe = raw["probe"]
    oracle = raw["oracle"]
    patch = raw["patch"]
    return TaskConfig(
        id=raw["id"],
        description=raw.get("description", ""),
        rom_path=rom["path"],
        rom_sha1=str(rom["sha1"]).lower(),
        frames=int(probe["frames"]),
        oracle_sha1=str(oracle["state_sha1"]).lower(),
        patch_offset=int(patch["offset"]),
        patch_bytes=bytes.fromhex(str(patch["bytes_hex"])),
        patch_format=str(patch.get("format", "xdelta3")),
    )
