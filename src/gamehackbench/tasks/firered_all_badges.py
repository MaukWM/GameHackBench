# mypy: ignore-errors
"""Inspect AI entrypoint for the firered-all-badges task.

RAM-poke task: agent reverses the FireRed ROM to find the byte that gates
"all 8 badges" and submits a poke list. No reference state in the agent
container; verifier seeds from a pinned savestate (master + anti-DMA
cheats active so SaveBlock1 lives at a stable EWRAM address).

Solver = `basic_agent` with `bash` + `gba_verify_pokes`. Agent gets up to
N verify calls (config-driven, default 8). Final scoring reads
`/workspace/out/pokes.txt` and re-runs through the predicate scorer.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import basic_agent
from inspect_ai.tool import bash

from gamehackbench.lib.gba.config import load_task_config
from gamehackbench.lib.gba.scorer import gba_predicate_scorer
from gamehackbench.lib.gba.verify_tool import gba_verify_pokes

TASK_DIR = Path(__file__).resolve().parents[3] / "tasks" / "firered-all-badges"
COMPOSE_FILE = TASK_DIR / "compose.yaml"


@task
def firered_all_badges() -> Task:
    cfg = load_task_config(TASK_DIR)
    instruction = (TASK_DIR / "instruction.md").read_text()
    return Task(
        dataset=[Sample(input=instruction, target=cfg.predicate_expr or "", id=cfg.id)],
        solver=basic_agent(
            tools=[bash(timeout=180), gba_verify_pokes(TASK_DIR)],
            message_limit=40,
        ),
        scorer=gba_predicate_scorer(TASK_DIR),
        sandbox=("docker", str(COMPOSE_FILE)),
    )
