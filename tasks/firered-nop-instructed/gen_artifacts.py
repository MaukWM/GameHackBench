# mypy: ignore-errors
"""One-shot artifact generator for the firered-nop-instructed task.

Differences vs firered-nop-smoke's generator:
- No solution/patch.xdelta is produced — the agent emits its own patch at runtime.
- The base ROM is staged into environment/firered.gba so BOTH the default and the
  verifier Dockerfiles can COPY it into their build contexts.
- Re-derives the oracle SHA-1 from the locked NOP and prints it; this is asserted
  to match the value pinned in task.toml so the task stays self-consistent if
  someone tweaks frame count or NOP bytes.

Run from this directory:
    uv run python gen_artifacts.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
ROM_BASE = REPO_ROOT / "roms" / "firered.gba"
PROBE_BIN = REPO_ROOT.parent / "tools" / "gba_probe" / "gba_probe"
TASK_TOML = THIS_DIR / "task.toml"

# Locked patch parameters — must match instruction.md and task.toml.
NOP_OFFSET = 0x204
NOP_BYTES = b"\xc0\x46"  # Thumb `mov r8, r8`
FRAMES = 600


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def main() -> int:
    if not ROM_BASE.exists():
        sys.exit(f"missing base ROM: {ROM_BASE}")
    if not PROBE_BIN.exists():
        sys.exit(f"missing gba_probe binary: {PROBE_BIN} — run tools/gba_probe/build.sh first")

    cfg = tomllib.loads(TASK_TOML.read_text())
    pinned_oracle = str(cfg["oracle"]["state_sha1"]).lower()
    pinned_frames = int(cfg["probe"]["frames"])
    if pinned_frames != FRAMES:
        sys.exit(f"task.toml frames ({pinned_frames}) != generator FRAMES ({FRAMES})")

    rom = ROM_BASE.read_bytes()
    print(f"base ROM: {ROM_BASE} ({len(rom)} bytes, sha1={sha1(rom)})", file=sys.stderr)

    patched = bytearray(rom)
    original = bytes(patched[NOP_OFFSET : NOP_OFFSET + 2])
    patched[NOP_OFFSET : NOP_OFFSET + 2] = NOP_BYTES
    print(
        f"patched offset 0x{NOP_OFFSET:x}: {original.hex()} -> {NOP_BYTES.hex()}",
        file=sys.stderr,
    )

    work = THIS_DIR / "_work"
    work.mkdir(exist_ok=True)
    patched_rom = work / "firered_patched.gba"
    patched_rom.write_bytes(bytes(patched))

    proc = subprocess.run(
        [str(PROBE_BIN), str(patched_rom), str(FRAMES)],
        check=True,
        capture_output=True,
    )
    oracle = sha1(proc.stdout)
    print(proc.stderr.decode(errors="replace"), file=sys.stderr)

    # Stage the base ROM into environment/ for BOTH Dockerfiles to COPY.
    staged_rom = THIS_DIR / "environment" / "firered.gba"
    if not staged_rom.exists() or staged_rom.read_bytes() != ROM_BASE.read_bytes():
        shutil.copyfile(ROM_BASE, staged_rom)
        print(f"staged ROM into {staged_rom}", file=sys.stderr)

    shutil.rmtree(work)

    if oracle != pinned_oracle:
        sys.exit(
            f"oracle SHA-1 mismatch: derived={oracle} pinned={pinned_oracle} "
            f"— update task.toml or investigate determinism regression"
        )

    print(oracle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
