# mypy: ignore-errors
"""Generic Inspect AI scorer for GBA patch tasks.

The scorer applies the agent's xdelta3 patch (read from the default sandbox at
`/workspace/out/patch.xdelta`) to the ROM baked into the verifier sandbox at
`/roms/<rom_path>`, runs `gba_probe` for the locked frame count, SHA-1s the
resulting RW memory dump, and compares against the oracle pinned in `task.toml`.

Tasks that need different verification semantics (e.g. predicate-based or
multi-frame) should ship their own named scorer alongside this one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from gamehackbench.lib.gba.config import load_task_config


@scorer(metrics=[accuracy()])
def gba_ram_sha_scorer(task_dir: Path) -> Scorer:
    """Build a Scorer that grades a GBA patch task by RW-memory SHA-1.

    The scorer is pure config plumbing: everything task-specific (ROM filename,
    frame budget, oracle SHA-1) comes from `<task_dir>/task.toml`.
    """

    cfg = load_task_config(task_dir)
    rom_in_verifier = f"/roms/{cfg.rom_path}"
    frames = cfg.frames
    oracle_sha = cfg.oracle_sha1

    async def score(state: TaskState, target: Target) -> Score:
        try:
            patch = await sandbox().read_file("/workspace/out/patch.xdelta", text=False)
        except FileNotFoundError:
            return Score(value=INCORRECT, explanation="solver did not produce /workspace/out/patch.xdelta")
        if not isinstance(patch, bytes):
            patch = patch.encode("latin-1")

        await sandbox("verifier").write_file("/work/patch.xdelta", patch)

        cmd = [
            "sh",
            "-c",
            (
                "set -e; "
                f"xdelta3 -d -f -s {rom_in_verifier} /work/patch.xdelta /work/patched.gba; "
                f"gba_probe /work/patched.gba {frames} > /work/ram.bin"
            ),
        ]
        result = await sandbox("verifier").exec(cmd=cmd, timeout=180)
        if not result.success:
            return Score(
                value=INCORRECT,
                explanation=f"verifier exec failed (rc={result.returncode}): {result.stderr[-400:]}",
            )

        ram = await sandbox("verifier").read_file("/work/ram.bin", text=False)
        if not isinstance(ram, bytes):
            ram = ram.encode("latin-1")
        observed = hashlib.sha1(ram).hexdigest()

        if observed == oracle_sha:
            return Score(value=CORRECT, answer=observed, explanation=f"RAM SHA-1 matches oracle ({observed})")
        return Score(
            value=INCORRECT,
            answer=observed,
            explanation=f"RAM SHA-1 mismatch: observed={observed} oracle={oracle_sha}",
        )

    return score
