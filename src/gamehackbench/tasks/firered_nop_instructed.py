# mypy: ignore-errors
"""Inspect AI entrypoint for the firered-nop-instructed task.

Smoke #2: a real LLM agent (basic_agent + bash) reads the byte-level instruction,
operates on the ROM baked into /workspace/rom/firered.gba, and writes its own
xdelta3 patch to /workspace/out/patch.xdelta. The scorer is identical to smoke #1:
apply the agent's patch in the verifier sandbox, run gba_probe, compare RAM SHA-1
against the locked oracle.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState, basic_agent
from inspect_ai.tool import bash
from inspect_ai.util import sandbox

TASK_DIR = Path(__file__).resolve().parents[3] / "tasks" / "firered-nop-instructed"
TASK_TOML = TASK_DIR / "task.toml"
COMPOSE_FILE = TASK_DIR / "compose.yaml"


def _load_task_config() -> dict:
    with TASK_TOML.open("rb") as f:
        return tomllib.load(f)


@scorer(metrics=[accuracy()])
def gba_ram_sha_scorer() -> Scorer:
    """Apply the agent's xdelta3 patch in the verifier, run gba_probe, compare RAM SHA-1."""

    cfg = _load_task_config()
    frames = int(cfg["probe"]["frames"])
    oracle_sha = str(cfg["oracle"]["state_sha1"]).lower()

    async def score(state: TaskState, target: Target) -> Score:
        try:
            patch = await sandbox().read_file("/workspace/out/patch.xdelta", text=False)
        except FileNotFoundError:
            return Score(value=INCORRECT, explanation="agent did not produce /workspace/out/patch.xdelta")

        if not isinstance(patch, bytes):
            patch = patch.encode("latin-1")

        await sandbox("verifier").write_file("/work/patch.xdelta", patch)

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

        ram = await sandbox("verifier").read_file("/work/ram.bin", text=False)
        if not isinstance(ram, bytes):
            ram = ram.encode("latin-1")
        observed = hashlib.sha1(ram).hexdigest()

        if observed == oracle_sha:
            return Score(value=CORRECT, answer=observed,
                         explanation=f"RAM SHA-1 matches oracle ({observed})")
        return Score(
            value=INCORRECT,
            answer=observed,
            explanation=f"RAM SHA-1 mismatch: observed={observed} oracle={oracle_sha}",
        )

    return score


@task
def firered_nop_instructed() -> Task:
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
        solver=basic_agent(
            tools=[bash(timeout=180)],
            message_limit=15,
        ),
        scorer=gba_ram_sha_scorer(),
        sandbox=("docker", str(COMPOSE_FILE)),
    )
