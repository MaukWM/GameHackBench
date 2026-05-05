# GameHackBench

Benchmark for agents that patch old console binaries to enable cheats, verified inside containers via emulator memory state.

## Development

```bash
uv sync
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest
```

## Running tasks (Inspect AI)

Smoke #1 — harness pipeline only (no real model needed, stub solver copies the locked patch into the workspace):

```bash
uv run inspect eval src/gamehackbench/tasks/firered_nop_smoke.py --model mockllm/model
```

Smoke #2 — real agent following byte-level instructions (`OPENAI_API_KEY` must be set):

```bash
uv run inspect eval src/gamehackbench/tasks/firered_nop_instructed.py --model openai/gpt-5.5
```

Both expect Docker running locally and the substrate base image already built — see `base-images/gba/`.

## Inspecting eval runs

Every eval writes a `.eval` log to `logs/` at the repo root. Browse them in the local web viewer:

```bash
uv run inspect view                            # opens http://127.0.0.1:7575, lists all runs
uv run inspect view --log-dir logs/            # explicit log dir (must run from repo root, or pass abs path)
```

In the viewer, pick a run → sample → tabs:

- **Transcript** — model reasoning summary + tool calls + tool outputs, in order
- **Messages** — raw `ChatMessage` tree (system / user / assistant / tool)
- **Scoring** — scorer output (`CORRECT` / `INCORRECT`, observed vs oracle SHA, explanation)
- **Metadata** / **JSON** — token counts, model params, full sample dict

Tail-follow a run live in the terminal instead of the browser:

```bash
uv run inspect eval ... --display conversation
```

Plain JSON dump (for grep / scripts):

```bash
uv run inspect log dump logs/<file>.eval | jq '.samples[0].messages'
```

## Regenerating task artifacts

Each task ships with a one-shot generator that produces its locked artifacts (xdelta3 patch + oracle RAM SHA-1). The committed `solution/patch.xdelta` and the `oracle.state_sha1` field in `task.toml` are derived from this script. Re-run if you change the patch offset, NOP bytes, or frame budget.

Prerequisite: the host-side `gba_probe` binary must exist at `../tools/gba_probe/gba_probe` (build it with `tools/gba_probe/build.sh` from the sibling research repo). And the task's base ROM must be present at `roms/<rom>.gba`.

```bash
cd tasks/firered-nop-smoke
uv run python gen_smoke_artifacts.py

cd tasks/firered-nop-instructed
uv run python gen_artifacts.py
```

The script:

1. Reads `roms/firered.gba`, applies the locked patch (Thumb NOP `c0 46` at ROM offset `0x204`).
2. (smoke #1 only) Encodes `xdelta3` diff → `solution/patch.xdelta` (committed). Smoke #2 has no committed solution — the agent generates its own patch at runtime.
3. Round-trip decodes the patch and asserts byte-equality with the in-memory patched ROM.
4. Stages a copy of the base ROM at `environment/firered.gba` so the Docker image build context can `COPY` it in (gitignored).
5. Runs `gba_probe` over the patched ROM at the locked frame count and prints the SHA-1 of the RAM dump (the oracle).

The printed SHA-1 should match `[oracle].state_sha1` in `task.toml`. If it doesn't, either the patch parameters changed (update `task.toml`) or something in the determinism stack regressed (bug — investigate before committing).

## Repo layout

```
GameHackBench/
├── base-images/gba/                          # gamehackbench/gba-base substrate image (mGBA + gba_probe)
├── src/gamehackbench/tasks/                  # Inspect @task / @solver / @scorer modules, one per task
├── tasks/<task-id>/                          # task spec (task.toml, instruction.md, compose.yaml,
│                                             #   environment/Dockerfile.*, solution/, gen_*_artifacts.py)
└── roms/                                     # base ROMs (gitignored — copyrighted binaries)
```
