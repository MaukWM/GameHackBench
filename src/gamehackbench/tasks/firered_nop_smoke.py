# mypy: ignore-errors
"""Inspect AI entrypoint for the firered-nop-smoke task.

End-to-end harness validation: stub solver copies a pre-baked xdelta3 patch into
the agent workspace; the shared GBA scorer applies that patch in the verifier
sandbox, runs gba_probe, and asserts the resulting RAM SHA-1 matches the locked
oracle pinned in task.toml.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

from gamehackbench.lib.gba.config import load_task_config
from gamehackbench.lib.gba.scorer import gba_ram_sha_scorer

TASK_DIR = Path(__file__).resolve().parents[3] / "tasks" / "firered-nop-smoke"
SOLUTION_PATCH = TASK_DIR / "solution" / "patch.xdelta"
COMPOSE_FILE = TASK_DIR / "compose.yaml"


@solver
def stub_patch_solver(
    local_patch: Path = SOLUTION_PATCH,
    dest: str = "/workspace/out/patch.xdelta",
) -> Solver:
    """Copies a pre-baked xdelta3 patch into the agent workspace.

    Stand-in for a real agent solver. Used to validate the harness pipeline before
    we have a model that can derive patches itself.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().write_file(dest, local_patch.read_bytes())
        return state

    return solve


@task
def firered_nop_smoke() -> Task:
    cfg = load_task_config(TASK_DIR)
    instruction = (TASK_DIR / "instruction.md").read_text()
    return Task(
        dataset=[Sample(input=instruction, target=cfg.oracle_sha1, id=cfg.id)],
        solver=[stub_patch_solver()],
        scorer=gba_ram_sha_scorer(TASK_DIR),
        sandbox=("docker", str(COMPOSE_FILE)),
    )
