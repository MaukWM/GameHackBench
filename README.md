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

End-to-end smoke task (no real model needed — uses a stub solver that copies the locked patch into the workspace):

```bash
uv run inspect eval src/gamehackbench/tasks/firered_nop_smoke.py --model mockllm/model
```

Expects Docker running locally and the substrate base image already built — see `base-images/gba/`.

## Regenerating task artifacts

Each task ships with a one-shot generator that produces its locked artifacts (xdelta3 patch + oracle RAM SHA-1). The committed `solution/patch.xdelta` and the `oracle.state_sha1` field in `task.toml` are derived from this script. Re-run if you change the patch offset, NOP bytes, or frame budget.

Prerequisite: the host-side `gba_probe` binary must exist at `../tools/gba_probe/gba_probe` (build it with `tools/gba_probe/build.sh` from the sibling research repo). And the task's base ROM must be present at `roms/<rom>.gba`.

```bash
cd tasks/firered-nop-smoke
uv run python gen_smoke_artifacts.py
```

The script:

1. Reads `roms/firered.gba`, applies the locked patch (Thumb NOP `c0 46` at ROM offset `0x204`).
2. Encodes `xdelta3` diff → `solution/patch.xdelta` (committed).
3. Round-trip decodes the patch and asserts byte-equality with the in-memory patched ROM.
4. Stages a copy of the base ROM at `environment/firered.gba` so the verifier Docker image build context can `COPY` it in (gitignored).
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
