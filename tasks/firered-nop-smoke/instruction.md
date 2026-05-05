# firered-nop-smoke

Smoke-test task for GameHackBench. Validates the patch → verify pipeline.

## Goal

Produce an `xdelta3` patch at `/workspace/out/patch.xdelta` such that, when applied
to the Pokémon FireRed (USA, Europe) Rev 1 ROM (SHA-1
`dd5945db9b930750cb39d00c84da8571feebf417`), the resulting ROM run for 600 frames
in mGBA produces a RW-memory SHA-1 of:

```
74d47f2fad70f5882b3b7bb0e4f777d0247cd7a0
```

## Reference solution

Patch the byte at ROM offset `0x204` with the 2-byte Thumb NOP `c0 46`
(`mov r8, r8`). 0x204 is the entry-point target of the ARM branch instruction at
ROM offset `0x000`.

## Note

This is a harness-validation task, not an agent-capability task. The shipped solver
stub copies `solution/patch.xdelta` into the workspace verbatim — replace with a
real solver to exercise actual cheat-discovery work.
