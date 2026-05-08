# Cheat seed for `firered-all-badges`

Single libretro `.cht` file: oracle cheat + the GS v3 preamble it requires.
Source for the active cheat: libretro-database `cht/Nintendo - Game Boy
Advance/Pokemon - FireRed Version (USA, Europe) (Rev 1).cht`.

## Files

- **`cheat.cht`** — 3 codes:
  - `cheat0` Master Code (FireRed US Rev 1) — handshake / decryption seed
  - `cheat1` Anti DMA — disables the per-boot RAM-base randomization so
    fixed addresses resolve correctly
  - `cheat2` Have All Badges — `00226510 000000FF`, the actual oracle

All three enabled.

## Pipeline

`cheat_to_predicate.py` runs `gba_probe` twice against this single file:
once with `cheat2` enabled (target), once with `cheat2` toggled off in
memory (baseline). Diff between the two RAM dumps → rcheevos predicate.

```bash
GBA_PROBE=path/to/gba_probe \
python3 local_scripts/cheat_to_predicate.py \
  --rom roms/firered/firered.gba \
  --frames 1800 \
  --cheats tasks/firered-all-badges/cheats/cheat.cht \
  --target-cheat "Have All Badges" \
  --intersect 3
```

The agent never reads this file. Lives in the task repo only so the
predicate is regeneratable from the cheat source, not magic numbers.
