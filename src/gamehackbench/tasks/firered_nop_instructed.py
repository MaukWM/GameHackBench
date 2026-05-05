# mypy: ignore-errors
"""Inspect AI entrypoint for the firered-nop-instructed task.

Smoke #2: a real LLM agent (basic_agent + bash) reads the byte-level instruction,
operates on the ROM baked into /workspace/rom/firered.gba, and writes its own
xdelta3 patch to /workspace/out/patch.xdelta. The shared GBA scorer then applies
the patch in the verifier and grades it against the locked oracle.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import basic_agent
from inspect_ai.tool import bash

from gamehackbench.lib.gba.config import load_task_config
from gamehackbench.lib.gba.scorer import gba_ram_sha_scorer

TASK_DIR = Path(__file__).resolve().parents[3] / "tasks" / "firered-nop-instructed"
COMPOSE_FILE = TASK_DIR / "compose.yaml"


@task
def firered_nop_instructed() -> Task:
    cfg = load_task_config(TASK_DIR)
    instruction = (TASK_DIR / "instruction.md").read_text()
    return Task(
        dataset=[Sample(input=instruction, target=cfg.oracle_sha1, id=cfg.id)],
        solver=basic_agent(tools=[bash(timeout=180)], message_limit=15),
        scorer=gba_ram_sha_scorer(TASK_DIR),
        sandbox=("docker", str(COMPOSE_FILE)),
    )
