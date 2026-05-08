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
from gamehackbench.lib.gba.predicate import evaluate as evaluate_predicate


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _asset(repo_root: Path, rel: str) -> Path:
    """Resolve a task.toml asset path under <repo>/roms/. Fails loud if missing."""
    p = repo_root / "roms" / rel
    if not p.exists():
        sys.exit(f"missing asset {rel}: {p}")
    return p


def generate_artifacts(task_dir: Path, *, write_solution: bool = True) -> str:
    """Stage ROM, derive oracle, optionally emit the solution xdelta3 patch.

    Returns the derived oracle SHA-1 string.
    """

    cfg = load_task_config(task_dir)
    repo_root = task_dir.parents[1]
    rom_base = _asset(repo_root, cfg.rom_path)
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

    staged_rom = task_dir / "environment" / Path(cfg.rom_path).name
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


def stage_predicate_task(task_dir: Path) -> bool:
    """Stage ROM(+sav) for a predicate task and validate the reference solution.

    1. Validate the on-disk ROM SHA-1 against task.toml.
    2. Copy ROM (and sav, if configured) into `environment/` so the per-task
       Docker build context can `COPY` them (gitignored — copyrighted binary).
    3. Run `gba_play` against the reference `solution/input.txt`, dump RAM,
       and evaluate the task's predicate. Fails loudly if the reference
       solution doesn't satisfy the predicate (means either the predicate
       drifted, the input.txt is broken, or the determinism stack regressed).

    Returns True on success.
    """

    cfg = load_task_config(task_dir)
    if cfg.kind != "predicate":
        sys.exit(f"stage_predicate_task expected kind=predicate, got {cfg.kind}")

    repo_root = task_dir.parents[1]
    rom_base = _asset(repo_root, cfg.rom_path)
    play_bin = repo_root.parent / "tools" / "gba_probe" / "gba_play"
    if not play_bin.exists():
        sys.exit(f"missing gba_play binary: {play_bin} — run tools/gba_probe/build.sh first")

    rom = rom_base.read_bytes()
    rom_sha = _sha1(rom)
    print(f"base ROM: {rom_base} ({len(rom)} bytes, sha1={rom_sha})", file=sys.stderr)
    if rom_sha != cfg.rom_sha1:
        sys.exit(f"ROM sha1 mismatch: derived={rom_sha} pinned={cfg.rom_sha1}")

    env_dir = task_dir / "environment"
    env_dir.mkdir(exist_ok=True)
    staged_rom = env_dir / Path(cfg.rom_path).name
    if not staged_rom.exists() or staged_rom.read_bytes() != rom:
        shutil.copyfile(rom_base, staged_rom)
        print(f"staged ROM into {staged_rom}", file=sys.stderr)

    sav_base: Path | None = None
    if cfg.sav_path:
        sav_base = _asset(repo_root, cfg.sav_path)
        staged_sav = env_dir / Path(cfg.sav_path).name
        sav_bytes = sav_base.read_bytes()
        if not staged_sav.exists() or staged_sav.read_bytes() != sav_bytes:
            shutil.copyfile(sav_base, staged_sav)
            print(f"staged sav into {staged_sav}", file=sys.stderr)

    solution_input = task_dir / "solution" / "input.txt"
    if not solution_input.exists():
        sys.exit(f"missing reference solution: {solution_input}")

    work = task_dir / "_work"
    work.mkdir(exist_ok=True)
    ram_dump = work / "ram.bin"
    if ram_dump.exists():
        ram_dump.unlink()

    # gba_play auto-loads a sav next to the ROM (mGBA behaviour); the staged
    # sav in environment/ is for the in-container build context, not this
    # host-side validation run.
    cmd = [
        str(play_bin),
        "--rom", str(rom_base),
        "--frames", str(cfg.frames),
        "--input", str(solution_input),
        "--dump-ram", str(ram_dump),
    ]
    if cfg.runner_state:
        state_path = _asset(repo_root, cfg.runner_state)
        cmd += ["--state", str(state_path)]
    if cfg.runner_cheats:
        cheats_path = _asset(repo_root, cfg.runner_cheats)
        cmd += ["--cheats", str(cheats_path)]

    print(f"running: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, check=True, capture_output=True)
    print(proc.stderr.decode(errors="replace"), file=sys.stderr)

    ram = ram_dump.read_bytes()
    ok = evaluate_predicate(cfg.predicate_expr or "", ram)
    shutil.rmtree(work)

    if not ok:
        sys.exit(
            f"reference solution did not satisfy predicate: {cfg.predicate_expr} "
            f"— update solution/input.txt, the predicate, or investigate determinism regression"
        )
    print(f"predicate satisfied: {cfg.predicate_expr}")
    return True


def stage_pokes_task(task_dir: Path) -> bool:
    """Stage ROM + seed savestate for a pokes task and validate solution/pokes.txt.

    Pokes tasks differ from input-script predicate tasks: agent submits a
    list of byte writes; the verifier loads a pinned savestate (master+
    antidma active so cheat-style addresses are stable), applies the pokes
    via `gba_play --apply-pokes`, runs N frames, dumps RAM, and evaluates
    the predicate.

    1. Validate ROM SHA-1, copy ROM into environment/ for the build context.
    2. Copy the seed savestate from `<repo>/roms/<runner_state>` into
       environment/ — agents in the default service do NOT see this file
       (only the verifier mounts it), so the agent must derive the poke
       addresses from the ROM via RE.
    3. Run `gba_play` against the reference `solution/pokes.txt` with the
       seed state, dump RAM, evaluate the predicate. Fails loud on miss —
       same drift contract as `stage_predicate_task`.
    """

    cfg = load_task_config(task_dir)
    if cfg.kind != "predicate" or cfg.runner_artifact != "pokes":
        sys.exit(
            f"stage_pokes_task expected predicate+pokes task, got "
            f"kind={cfg.kind} artifact={cfg.runner_artifact}"
        )
    if not cfg.runner_state:
        sys.exit("pokes task requires runner.state in task.toml (path under roms/)")

    repo_root = task_dir.parents[1]
    rom_base = _asset(repo_root, cfg.rom_path)
    state_base = _asset(repo_root, cfg.runner_state)
    play_bin = repo_root.parent / "tools" / "gba_probe" / "gba_play"
    if not play_bin.exists():
        sys.exit(f"missing gba_play binary: {play_bin} — run tools/gba_probe/build.sh first")

    rom = rom_base.read_bytes()
    rom_sha = _sha1(rom)
    print(f"base ROM: {rom_base} ({len(rom)} bytes, sha1={rom_sha})", file=sys.stderr)
    if rom_sha != cfg.rom_sha1:
        sys.exit(f"ROM sha1 mismatch: derived={rom_sha} pinned={cfg.rom_sha1}")

    env_dir = task_dir / "environment"
    env_dir.mkdir(exist_ok=True)
    staged_rom = env_dir / Path(cfg.rom_path).name
    if not staged_rom.exists() or staged_rom.read_bytes() != rom:
        shutil.copyfile(rom_base, staged_rom)
        print(f"staged ROM into {staged_rom}", file=sys.stderr)
    staged_state = env_dir / Path(cfg.runner_state).name
    state_bytes = state_base.read_bytes()
    if not staged_state.exists() or staged_state.read_bytes() != state_bytes:
        shutil.copyfile(state_base, staged_state)
        print(f"staged seed state into {staged_state}", file=sys.stderr)

    solution_pokes = task_dir / "solution" / "pokes.txt"
    if not solution_pokes.exists():
        sys.exit(f"missing reference solution: {solution_pokes}")

    work = task_dir / "_work"
    work.mkdir(exist_ok=True)
    ram_dump = work / "ram.bin"
    if ram_dump.exists():
        ram_dump.unlink()

    cmd = [
        str(play_bin),
        "--rom", str(rom_base),
        "--frames", str(cfg.frames),
        "--state", str(state_base),
        "--apply-pokes", str(solution_pokes),
        "--dump-ram", str(ram_dump),
    ]
    print(f"running: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, check=True, capture_output=True)
    print(proc.stderr.decode(errors="replace"), file=sys.stderr)

    ram = ram_dump.read_bytes()
    ok = evaluate_predicate(cfg.predicate_expr or "", ram)
    shutil.rmtree(work)

    if not ok:
        sys.exit(
            f"reference solution did not satisfy predicate: {cfg.predicate_expr} "
            f"— update solution/pokes.txt, the predicate, the seed state, or "
            f"investigate determinism regression"
        )
    print(f"predicate satisfied: {cfg.predicate_expr}")
    return True
