# mypy: ignore-errors
"""Shared artifact generator for GBA patch tasks.

Each task directory has a thin `gen_artifacts.py` that does:

    from gamehackbench.lib.gba.artifacts import generate_artifacts
    generate_artifacts(Path(__file__).resolve().parent, write_solution=...)

This module owns the heavy lifting:

1. Validate inputs exist (base ROM, host `gba_probe` binary).
2. Verify the on-disk ROM SHA-1 matches the value pinned in `task.toml`.
3. Apply the locked patch in-memory and write the patched ROM to a scratch dir.
4. Optionally encode an `xdelta3` patch into `solution/patch.xdelta` and
   round-trip-decode it as a sanity check (skipped for tasks where the agent
   produces the patch itself).
5. Stage the base ROM into `environment/<rom_path>` so the per-task Docker
   build context can `COPY` it (gitignored — copyrighted binary).
6. Run `gba_probe` over the patched ROM at the locked frame count and assert
   that the derived oracle SHA-1 matches the value pinned in `task.toml`.

A drift in step 6 means either the task config was edited deliberately
(re-pin) or the determinism stack regressed (bug — investigate).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from gamehackbench.lib.gba.config import load_task_config


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def generate_artifacts(task_dir: Path, *, write_solution: bool = True) -> str:
    """Stage ROM, derive oracle, optionally emit the solution xdelta3 patch.

    Returns the derived oracle SHA-1 string.
    """

    cfg = load_task_config(task_dir)
    repo_root = task_dir.parents[1]
    rom_base = repo_root / "roms" / cfg.rom_path
    probe_bin = repo_root.parent / "tools" / "gba_probe" / "gba_probe"

    if not rom_base.exists():
        sys.exit(f"missing base ROM: {rom_base}")
    if not probe_bin.exists():
        sys.exit(f"missing gba_probe binary: {probe_bin} — run tools/gba_probe/build.sh first")

    rom = rom_base.read_bytes()
    rom_sha = _sha1(rom)
    print(f"base ROM: {rom_base} ({len(rom)} bytes, sha1={rom_sha})", file=sys.stderr)
    if rom_sha != cfg.rom_sha1:
        sys.exit(f"ROM sha1 mismatch: derived={rom_sha} pinned={cfg.rom_sha1}")

    patched = bytearray(rom)
    n = len(cfg.patch_bytes)
    original = bytes(patched[cfg.patch_offset : cfg.patch_offset + n])
    patched[cfg.patch_offset : cfg.patch_offset + n] = cfg.patch_bytes
    print(
        f"patched offset 0x{cfg.patch_offset:x}: {original.hex()} -> {cfg.patch_bytes.hex()}",
        file=sys.stderr,
    )

    work = task_dir / "_work"
    work.mkdir(exist_ok=True)
    patched_rom = work / f"{rom_base.stem}_patched{rom_base.suffix}"
    patched_rom.write_bytes(bytes(patched))

    if write_solution:
        solution_dir = task_dir / "solution"
        solution_dir.mkdir(exist_ok=True)
        patch_out = solution_dir / "patch.xdelta"
        if patch_out.exists():
            patch_out.unlink()
        subprocess.run(
            ["xdelta3", "-e", "-9", "-S", "djw", "-s", str(rom_base), str(patched_rom), str(patch_out)],
            check=True,
        )
        print(f"xdelta3 patch: {patch_out} ({patch_out.stat().st_size} bytes)", file=sys.stderr)

        decoded = work / "decoded.gba"
        if decoded.exists():
            decoded.unlink()
        subprocess.run(
            ["xdelta3", "-d", "-s", str(rom_base), str(patch_out), str(decoded)],
            check=True,
        )
        if decoded.read_bytes() != patched_rom.read_bytes():
            sys.exit("xdelta3 round-trip mismatch")
        print("xdelta3 round-trip OK", file=sys.stderr)

    proc = subprocess.run(
        [str(probe_bin), str(patched_rom), str(cfg.frames)],
        check=True,
        capture_output=True,
    )
    oracle = _sha1(proc.stdout)
    print(proc.stderr.decode(errors="replace"), file=sys.stderr)

    staged_rom = task_dir / "environment" / cfg.rom_path
    if not staged_rom.exists() or staged_rom.read_bytes() != rom:
        shutil.copyfile(rom_base, staged_rom)
        print(f"staged ROM into {staged_rom}", file=sys.stderr)

    shutil.rmtree(work)

    if oracle != cfg.oracle_sha1:
        sys.exit(
            f"oracle SHA-1 mismatch: derived={oracle} pinned={cfg.oracle_sha1} "
            f"— update task.toml or investigate determinism regression"
        )

    print(oracle)
    return oracle
