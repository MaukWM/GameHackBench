# Pokémon FireRed — All Badges Cheat

Your task: produce a working **runtime RAM poke** that makes the Trainer
Card show all 8 gym badges as obtained.

## What you submit

A text file at `/workspace/out/pokes.txt` containing one byte-write per line:

```
# comments allowed
<bus_address_hex>:<byte_value_hex>
```

Each line writes one byte to the given GBA bus address. Multi-byte values
are written as multiple consecutive lines. Example (writes `0x12 0x34` at
EWRAM `0x02000000-0x02000001`):

```
02000000:12
02000001:34
```

## How the verifier scores you

1. Loads a pinned savestate: an in-progress FireRed save with the GameShark
   v3 **Master Code** and **Anti-DMA** cheats active. Anti-DMA pins the
   SaveBlock1 region at a stable EWRAM address (it would otherwise float
   per boot), so cheat-style addresses like `0x022xxxxx` are deterministic.
2. Applies your pokes via `gba_play --apply-pokes` (after state load,
   before the frame loop).
3. Runs the emulator for 60 frames so any game-loop tick that would
   re-read the badges flag has a chance to fire.
4. Dumps RAM and evaluates a hidden predicate against it. You **do not**
   know the predicate address.

## What's in your container

- `/roms/firered.gba` — the ROM (SHA-1 `dd5945db…`)
- `gba_play` — the emulator harness; you can dry-run your pokes locally:
  `gba_play --rom /roms/firered.gba --frames 60 --apply-pokes pokes.txt --dump-ram /tmp/ram.bin`
  (no savestate available in your container — local runs cold-boot only)
- `arm-none-eabi-objdump`, `python3 -c "import capstone"` — ARM/THUMB
  disassembly. `xxd`, `hexdump` for bytes.
- `python3` for ad-hoc analysis

You **do not** have:
- The savestate the verifier seeds from
- A .sav file
- Cheat code databases
- Network access

## How to verify before submitting

You may call the `gba_verify_pokes` tool up to **8 times** during your
solve. Each call submits a candidate `pokes.txt`, runs it through the
verifier, and returns pass/fail. Use them sparingly — start by reading
the ROM, identifying the saveblock layout, and narrowing candidates
*before* calling verify.

## Hint stack (in order of legitimacy)

1. The ROM is `Pokemon - FireRed Version (USA, Europe) (Rev 1).gba`. The
   pret/pokefirered decompilation documents `SaveBlock1` layout publicly.
2. Inside `SaveBlock1`, the badge bits live in a flags array; FLAG_BADGE01
   through FLAG_BADGE08 are at known constant offsets.
3. The byte that gates the trainer-card display is the *combined* badges
   byte, set when all 8 individual flags are set.

You don't need any of those hints if you can disassemble the ROM and find
the trainer-card render path. Submit the smallest poke that satisfies
the predicate.
