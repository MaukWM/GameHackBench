# firered-nop-instructed

You are running inside a Linux sandbox. The base ROM `firered.gba` (Pokémon FireRed
(USA, Europe) Rev 1, SHA-1 `dd5945db9b930750cb39d00c84da8571feebf417`) is already
present at `/workspace/rom/firered.gba`. `xdelta3` and `python3` are installed.

## Goal

Produce an `xdelta3` patch at `/workspace/out/patch.xdelta` such that, when applied
to the base ROM, the bytes at ROM offset `0x204` are replaced with the 2-byte
sequence `c0 46` (a Thumb `mov r8, r8` NOP). All other bytes must be unchanged.

A grader will:

1. Apply your patch to `/workspace/rom/firered.gba` with `xdelta3 -d -f -s ...`.
2. Run a deterministic emulator probe on the patched ROM for 600 frames.
3. Compare the SHA-1 of the resulting RW memory dump against a fixed oracle.

## Suggested approach

```bash
# 1. Copy the base ROM somewhere writable.
cp /workspace/rom/firered.gba /tmp/patched.gba

# 2. Overwrite the 2 bytes at offset 0x204 (516 decimal) with c0 46.
python3 -c "p=open('/tmp/patched.gba','r+b'); p.seek(0x204); p.write(b'\xc0\x46'); p.close()"

# 3. Encode the diff as an xdelta3 patch.
mkdir -p /workspace/out
xdelta3 -e -9 -S djw -f -s /workspace/rom/firered.gba /tmp/patched.gba /workspace/out/patch.xdelta

# 4. Sanity-check round-trip.
xdelta3 -d -f -s /workspace/rom/firered.gba /workspace/out/patch.xdelta /tmp/roundtrip.gba
cmp /tmp/patched.gba /tmp/roundtrip.gba && echo OK
```

When `/workspace/out/patch.xdelta` is in place, call `submit` with a short note
(e.g. `done`). The grader does not read your submitted text — it reads the file.
