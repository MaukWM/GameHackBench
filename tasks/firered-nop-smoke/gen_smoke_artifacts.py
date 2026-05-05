# mypy: ignore-errors
"""One-shot artifact generator for the firered-nop-smoke task.

Picks a fixed offset deep in the ROM, writes a 2-byte Thumb NOP (mov r8, r8 = 0x46c0),
emits an xdelta3 patch, runs gba_probe over the patched ROM at fixed frame count, and
prints the oracle RAM SHA-1 to stdout. The chosen offset and oracle SHA are then
locked into task.toml.

Run from this directory:
    uv run python gen_smoke_artifacts.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
ROM_BASE = REPO_ROOT / "roms" / "firered.gba"
PROBE_BIN = REPO_ROOT.parent / "tools" / "gba_probe" / "gba_probe"

# Smoke-task constants. Frozen here, mirrored in task.toml.
# 0x204 is the entry-point target of the ARM branch at 0x000 (decoded from the FireRed
# header). Patching the first instruction guarantees execution diverges immediately
# and the RAM dump differs from baseline at any frame count > 0.
NOP_OFFSET = 0x204
NOP_BYTES = b"\xc0\x46"  # Thumb `mov r8, r8` (encoding 0x46C0, little-endian on disk).
FRAMES = 600


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=True, **kw)  # type: ignore[arg-type]


def main() -> int:
    if not ROM_BASE.exists():
        sys.exit(f"missing base ROM: {ROM_BASE}")
    if not PROBE_BIN.exists():
        sys.exit(f"missing gba_probe binary: {PROBE_BIN} — run tools/gba_probe/build.sh first")

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

    patch_out = THIS_DIR / "solution" / "patch.xdelta"
    patch_out.parent.mkdir(exist_ok=True)
    if patch_out.exists():
        patch_out.unlink()
    run(
        [
            "xdelta3",
            "-e",
            "-9",
            "-S",
            "djw",
            "-s",
            str(ROM_BASE),
            str(patched_rom),
            str(patch_out),
        ]
    )
    print(f"xdelta3 patch: {patch_out} ({patch_out.stat().st_size} bytes)", file=sys.stderr)

    # Verify round-trip: decode the patch onto the base, expect byte-identical patched ROM.
    decoded = work / "firered_decoded.gba"
    if decoded.exists():
        decoded.unlink()
    run(["xdelta3", "-d", "-s", str(ROM_BASE), str(patch_out), str(decoded)])
    if decoded.read_bytes() != patched_rom.read_bytes():
        sys.exit("xdelta3 round-trip mismatch")
    print("xdelta3 round-trip OK", file=sys.stderr)

    # Capture oracle RAM SHA via host gba_probe.
    proc = subprocess.run(
        [str(PROBE_BIN), str(patched_rom), str(FRAMES)],
        check=True,
        capture_output=True,
    )
    oracle = sha1(proc.stdout)
    print(proc.stderr.decode(errors="replace"), file=sys.stderr)

    # Stage the base ROM into environment/ so the verifier image build context can COPY it
    # (Docker won't follow symlinks across the context root, so a real copy is required).
    staged_rom = THIS_DIR / "environment" / "firered.gba"
    if not staged_rom.exists() or staged_rom.read_bytes() != ROM_BASE.read_bytes():
        shutil.copyfile(ROM_BASE, staged_rom)
        print(f"staged ROM into {staged_rom}", file=sys.stderr)

    # Tear down working copy of the patched ROM (gitignored anyway).
    shutil.rmtree(work)

    print(oracle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
