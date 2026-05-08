# mypy: ignore-errors
"""Inspect AI tool: gba_verify_pokes — agent-callable verifier for pokes tasks.

Why a tool and not just the scorer: pokes tasks reward iterative RE. A
one-shot blind submission is brutal — the agent should be able to test a
candidate `pokes.txt`, learn pass/fail, refine, and resubmit. To stop
trivial brute-force across EWRAM, calls are budget-capped (default 8 per
solve).

The tool runs the same machinery as `gba_predicate_scorer`'s pokes branch:
write candidate to verifier sandbox → `gba_play --state <seed> --apply-pokes
<candidate> --frames N --dump-ram` → evaluate predicate. It returns a
human-readable string the model can reason over plus the remaining budget.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox

from gamehackbench.lib.gba.config import load_task_config
from gamehackbench.lib.gba.predicate import evaluate as evaluate_predicate


@tool
def gba_verify_pokes(task_dir: Path) -> Tool:
    """Build the verify-pokes tool for a specific task.

    Closure captures the per-task budget and verifier args. Inspect AI runs
    one solver per Sample, so the closure-local counter is per-sample and
    resets between runs (correct semantics).
    """
    cfg = load_task_config(task_dir)
    if cfg.kind != "predicate" or cfg.runner_artifact != "pokes":
        raise ValueError(
            f"gba_verify_pokes requires predicate+pokes task; "
            f"got kind={cfg.kind} artifact={cfg.runner_artifact}"
        )

    rom_in_verifier = f"/roms/{cfg.rom_path}"
    frames = cfg.frames
    predicate_expr = cfg.predicate_expr or ""
    state_path = f"/roms/{Path(cfg.runner_state).name}" if cfg.runner_state else None
    pokes_path_in_verifier = cfg.runner_agent_pokes or "/work/agent_pokes.txt"
    budget_total = cfg.verify_budget

    # Per-Sample counter. The Inspect AI runtime instantiates a fresh tool
    # per Sample via the @tool factory, so this list is private to one solve.
    used = [0]

    async def execute(pokes: str) -> str:
        """Verify a candidate poke list against the hidden predicate.

        Args:
            pokes: Contents of the candidate `pokes.txt`. One byte-write
                per line, format `<bus_addr_hex>:<byte_hex>`. Comments
                with `#` and blank lines are allowed.

        Returns:
            One-line pass/fail diagnostic plus remaining budget. On pass,
            the agent should still write the same content to
            `/workspace/out/pokes.txt` for the final scorer to pick up.
        """
        if used[0] >= budget_total:
            return (
                f"verify-budget exhausted ({used[0]}/{budget_total} calls used). "
                f"Submit your best candidate to /workspace/out/pokes.txt; "
                f"the final scorer will run anyway."
            )
        used[0] += 1
        remaining = budget_total - used[0]

        await sandbox("verifier").write_file(pokes_path_in_verifier, pokes)

        cmd_parts = [
            f"gba_play --rom {rom_in_verifier} --frames {frames}",
            f"--apply-pokes {pokes_path_in_verifier}",
        ]
        if state_path:
            cmd_parts.append(f"--state {state_path}")
        cmd_parts.append("--dump-ram /work/ram.bin")
        cmd = ["sh", "-c", "set -e; " + " ".join(cmd_parts) + " >/dev/null"]
        result = await sandbox("verifier").exec(cmd=cmd, timeout=120)
        if not result.success:
            return (
                f"verify call {used[0]}/{budget_total}: gba_play failed "
                f"(rc={result.returncode}). stderr tail: {result.stderr[-300:]} "
                f"({remaining} calls remaining)"
            )

        ram = await sandbox("verifier").read_file("/work/ram.bin", text=False)
        if not isinstance(ram, bytes):
            ram = ram.encode("latin-1")
        try:
            ok = evaluate_predicate(predicate_expr, ram)
        except ValueError as exc:
            return (
                f"verify call {used[0]}/{budget_total}: predicate eval error: {exc} "
                f"({remaining} calls remaining)"
            )
        verdict = "PASS" if ok else "FAIL"
        return (
            f"verify call {used[0]}/{budget_total}: {verdict} "
            f"({remaining} calls remaining)"
        )

    return execute
