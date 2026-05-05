# mypy: ignore-errors
"""Inspect AI entrypoint for the firered-nop-smoke task.

End-to-end harness validation: stub solver copies a pre-baked xdelta3 patch into
the agent workspace; scorer applies that patch to the FireRed ROM inside the
verifier sandbox, runs gba_probe for a fixed frame count, and asserts that the
SHA-1 of the resulting RAM dump matches the locked oracle.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

TASK_DIR = Path(__file__).resolve().parents[3] / "tasks" / "firered-nop-smoke"
TASK_TOML = TASK_DIR / "task.toml"
SOLUTION_PATCH = TASK_DIR / "solution" / "patch.xdelta"
COMPOSE_FILE = TASK_DIR / "compose.yaml"


def _load_task_config() -> dict:
    with TASK_TOML.open("rb") as f:
        return tomllib.load(f)


@solver
def stub_patch_solver(local_patch: Path = SOLUTION_PATCH, dest: str = "/workspace/out/patch.xdelta") -> Solver:
    """Copies a pre-baked xdelta3 patch into the agent workspace.

    Stand-in for a real agent solver. Used to validate the harness pipeline before
    we have a model that can derive patches itself.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        contents = local_patch.read_bytes()
        await sandbox().write_file(dest, contents)
        return state

    return solve


@scorer(metrics=[accuracy()])
def gba_ram_sha_scorer() -> Scorer:
    """Apply the agent's xdelta3 patch in the verifier, run gba_probe, compare RAM SHA-1."""

    cfg = _load_task_config()
    frames = int(cfg["probe"]["frames"])
    oracle_sha = str(cfg["oracle"]["state_sha1"]).lower()

    async def score(state: TaskState, target: Target) -> Score:
        # 1. Read the patch the solver wrote in the default workspace (binary-safe).
        try:
            patch = await sandbox().read_file("/workspace/out/patch.xdelta", text=False)
        except FileNotFoundError:
            return Score(value=INCORRECT, explanation="solver did not produce /workspace/out/patch.xdelta")

        if not isinstance(patch, bytes):
            patch = patch.encode("latin-1")

        # 2. Hand the patch to the verifier service. (We do this even though compose has a
        #    shared volume; an explicit write_file keeps the scorer independent of the
        #    compose volume layout and is what the Inspect docs recommend.)
        await sandbox("verifier").write_file("/work/patch.xdelta", patch)

        # 3. Apply patch + run gba_probe to a file inside the verifier (stdout has a 10MB
        #    cap and we don't want to risk binary-decode round-trips).
        cmd = [
            "sh",
            "-c",
            (
                "set -e; "
                "xdelta3 -d -f -s /roms/firered.gba /work/patch.xdelta /work/patched.gba; "
                f"gba_probe /work/patched.gba {frames} > /work/ram.bin"
            ),
        ]
        result = await sandbox("verifier").exec(cmd=cmd, timeout=180)
        if not result.success:
            return Score(
                value=INCORRECT,
                explanation=f"verifier exec failed (rc={result.returncode}): {result.stderr[-400:]}",
            )

        # 4. Read RAM dump, compute SHA-1, compare.
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


@task
def firered_nop_smoke() -> Task:
    cfg = _load_task_config()
    instruction = (TASK_DIR / "instruction.md").read_text()

    return Task(
        dataset=[
            Sample(
                input=instruction,
                target=str(cfg["oracle"]["state_sha1"]),
                id=cfg["id"],
            )
        ],
        solver=[stub_patch_solver()],
        scorer=gba_ram_sha_scorer(),
        sandbox=("docker", str(COMPOSE_FILE)),
    )
