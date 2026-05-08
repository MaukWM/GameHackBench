"""Minimal rcheevos-subset predicate evaluator for GBA tasks.

Why a subset and not the real library: predicates we need today are simple
byte-level invariants ("badge byte at 0x02226510 == 0xFF", possibly with AND
across a few addresses). Vendoring rcheevos + cffi pulls in ~5K LOC of C
plus a build step inside the verifier container, for one bit of evaluator
logic. The subset below covers what we use; if a future task needs delta
values, hit counts, or alt-groups we'll vendor the real thing.

DSL atoms supported (all rcheevos-compatible):

    0xH<addr>   8-bit  read at GBA bus address <addr>
    0x <addr>   16-bit read (note the literal space)
    0xX<addr>   32-bit read

    <atom> <op> <value>     where <op> in =, !=, <, <=, >, >=
    <cond> _ <cond>         AND   (all conds in a group must hold)
    <cond> S <cond>         OR    (alt-group: any group must hold)

Numeric literals: hex (`0x...`) or decimal.

Memory layout: dump produced by `gba_play --dump-ram` is a flat blob of
writeable mGBA memory blocks in fixed order. We resolve bus addresses by
masking with each block's GBA bus range; a hit on the EWRAM mirror at
0x02xxxxxx with addr beyond 0x02040000 is folded back via mod-0x40000 the
way the real GBA hardware mirrors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Order MUST match `gba_play.dump_ram` output (writeable blocks, mGBA block
# manifest order). If gba_play's dump order ever changes, fix it here too.
DUMP_LAYOUT: tuple[tuple[str, int, int, int], ...] = (
    # name,    bus_base,   size,     mirror_mask (0 = no mirror)
    ("ewram",  0x02000000, 0x40000,  0x00FFFFFF),  # EWRAM mirrors every 256KB across 0x02xxxxxx
    ("iwram",  0x03000000, 0x8000,   0x00FFFFFF),  # IWRAM mirrors every 32KB across 0x03xxxxxx
    ("pal",    0x05000000, 0x400,    0x00FFFFFF),
    ("vram",   0x06000000, 0x18000,  0),
    ("oam",    0x07000000, 0x400,    0x00FFFFFF),
    ("flash",  0x0E000000, 0x20000,  0),
)


@dataclass(frozen=True)
class _Block:
    name: str
    base: int
    size: int
    offset_in_dump: int
    mirror_mask: int


def _layout(dump_size: int) -> list[_Block]:
    blocks: list[_Block] = []
    cursor = 0
    for name, base, size, mirror_mask in DUMP_LAYOUT:
        blocks.append(_Block(name, base, size, cursor, mirror_mask))
        cursor += size
    if cursor != dump_size:
        raise ValueError(
            f"dump size {dump_size} does not match expected layout sum {cursor}"
        )
    return blocks


def _peek(dump: bytes, blocks: list[_Block], bus_addr: int, width: int) -> int:
    """Read `width` bytes (1/2/4) at GBA bus address. Little-endian."""
    for blk in blocks:
        # Try direct hit
        if blk.base <= bus_addr < blk.base + blk.size:
            off = blk.offset_in_dump + (bus_addr - blk.base)
            return int.from_bytes(dump[off:off + width], "little")
        # Mirror hit (e.g. EWRAM at 0x02226510 -> 0x02026510)
        if blk.mirror_mask:
            region = (bus_addr & ~blk.mirror_mask) | (blk.base & ~blk.mirror_mask)
            if region == (blk.base & ~blk.mirror_mask):
                off_in_block = (bus_addr - blk.base) % blk.size
                if 0 <= off_in_block < blk.size:
                    high_match = (bus_addr & ~blk.mirror_mask) == (blk.base & ~blk.mirror_mask)
                    if high_match:
                        off = blk.offset_in_dump + off_in_block
                        return int.from_bytes(dump[off:off + width], "little")
    raise ValueError(f"bus address 0x{bus_addr:08x} not in any known block")


_ATOM = re.compile(
    r"""
    0x(?P<sz>[HX\ ])
    (?P<addr>[0-9a-fA-F]+)
    \s*
    (?P<op>=|!=|<=|>=|<|>)
    \s*
    (?P<val>0x[0-9a-fA-F]+|\d+)
    """,
    re.VERBOSE,
)


_OPS = {
    "=":  lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


_WIDTH = {"H": 1, " ": 2, "X": 4}


def _parse_int(s: str) -> int:
    return int(s, 16) if s.lower().startswith("0x") else int(s, 10)


def _eval_atom(atom: str, dump: bytes, blocks: list[_Block]) -> bool:
    m = _ATOM.fullmatch(atom.strip())
    if not m:
        raise ValueError(f"could not parse atom: {atom!r}")
    width = _WIDTH[m["sz"]]
    addr = int(m["addr"], 16)
    expected = _parse_int(m["val"])
    actual = _peek(dump, blocks, addr, width)
    return _OPS[m["op"]](actual, expected)


def evaluate(predicate: str, dump: bytes) -> bool:
    """Return True iff the rcheevos-subset `predicate` holds against `dump`.

    OR has lower precedence than AND, matching rcheevos semantics:
    `A_B S C_D` means `(A AND B) OR (C AND D)`.
    """
    blocks = _layout(len(dump))
    return any(
        all(_eval_atom(a, dump, blocks) for a in alt.split("_") if a.strip())
        for alt in predicate.split("S")
    )
