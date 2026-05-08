# mypy: ignore-errors
"""Inspect AI scorers for GBA tasks.

Two scorers, both verifier-driven:

* `gba_ram_sha_scorer` — applies an xdelta3 patch in the verifier, runs
  `gba_probe`, and compares the resulting RAM SHA-1 to a pinned oracle.
* `gba_predicate_scorer` — stages the agent's `input.txt` (or other artifact)
  in the verifier, runs `gba_play`, copies the RAM dump back to the host,
  and evaluates an rcheevos-subset predicate from `task.toml`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from gamehackbench.lib.gba.config import load_task_config
from gamehackbench.lib.gba.predicate import evaluate as evaluate_predicate


@scorer(metrics=[accuracy()])
def gba_ram_sha_scorer(task_dir: Path) -> Scorer:
    """Build a Scorer that grades a GBA patch task by RW-memory SHA-1.

    The scorer is pure config plumbing: everything task-specific (ROM filename,
    frame budget, oracle SHA-1) comes from `<task_dir>/task.toml`.
    """

    cfg = load_task_config(task_dir)
    rom_in_verifier = f"/roms/{Path(cfg.rom_path).name}"
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


@scorer(metrics=[accuracy()])
def gba_predicate_scorer(task_dir: Path) -> Scorer:
    """Build a Scorer that grades a GBA task by rcheevos-subset predicate.

    Expects the agent to write a `gba_play` input script at
    `/workspace/out/input.txt`. The verifier runs `gba_play` against the
    pinned ROM (and, if configured, .sav / state / cheats), dumps RAM, and
    returns it; the scorer evaluates the predicate against that dump on the
    Inspect host.
    """

    cfg = load_task_config(task_dir)
    if cfg.kind != "predicate":
        raise ValueError(f"gba_predicate_scorer requires a predicate task; got kind={cfg.kind}")

    rom_in_verifier = f"/roms/{Path(cfg.rom_path).name}"
    frames = cfg.frames
    predicate_expr = cfg.predicate_expr
    explanation = cfg.predicate_explanation
    artifact = cfg.runner_artifact
    # Pokes-task seed state is staged into /roms inside the verifier image
    # under its basename; runner.state in task.toml uses the host-side
    # `firered/foo.ss0` path so the host artifact generator can find it.
    state_in_verifier = f"/roms/{Path(cfg.runner_state).name}" if cfg.runner_state else None

    if artifact == "input":
        agent_input_path = cfg.runner_agent_input or "/work/agent_input.txt"
        runner_flag = "--input"
        artifact_local = "/workspace/out/input.txt"
    else:
        agent_input_path = cfg.runner_agent_pokes or "/work/agent_pokes.txt"
        runner_flag = "--apply-pokes"
        artifact_local = "/workspace/out/pokes.txt"

    extra_args = ""
    if state_in_verifier:
        extra_args += f" --state {state_in_verifier}"
    if cfg.runner_cheats:
        extra_args += f" --cheats /roms/{cfg.runner_cheats}"

    async def score(state: TaskState, target: Target) -> Score:
        try:
            agent_input = await sandbox().read_file(artifact_local, text=True)
        except FileNotFoundError:
            return Score(value=INCORRECT, explanation=f"solver did not produce {artifact_local}")
        if isinstance(agent_input, bytes):
            agent_input = agent_input.decode("utf-8", errors="replace")

        await sandbox("verifier").write_file(agent_input_path, agent_input)

        cmd = [
            "sh",
            "-c",
            (
                "set -e; "
                f"gba_play --rom {rom_in_verifier} --frames {frames} "
                f"{runner_flag} {agent_input_path}{extra_args} "
                "--dump-ram /work/ram.bin >/dev/null"
            ),
        ]
        result = await sandbox("verifier").exec(cmd=cmd, timeout=180)
        if not result.success:
            return Score(
                value=INCORRECT,
                explanation=f"gba_play exec failed (rc={result.returncode}): {result.stderr[-400:]}",
            )

        ram = await sandbox("verifier").read_file("/work/ram.bin", text=False)
        if not isinstance(ram, bytes):
            ram = ram.encode("latin-1")

        try:
            ok = evaluate_predicate(predicate_expr, ram)
        except ValueError as exc:
            return Score(value=INCORRECT, explanation=f"predicate evaluation error: {exc}")

        if ok:
            return Score(
                value=CORRECT,
                answer="predicate held",
                explanation=f"{predicate_expr}  ({explanation})" if explanation else predicate_expr,
            )
        return Score(
            value=INCORRECT,
            answer="predicate failed",
            explanation=f"predicate did not hold: {predicate_expr}",
        )

    return score
