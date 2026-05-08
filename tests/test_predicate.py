"""Predicate evaluator unit tests.

Synthetic dumps. Size matches gba_play's writeable-block sum so the layout
sanity check passes.
"""

from __future__ import annotations

import pytest

from gamehackbench.lib.gba.predicate import DUMP_LAYOUT, evaluate

DUMP_SIZE = sum(size for _, _, size, _ in DUMP_LAYOUT)


def _empty_dump() -> bytearray:
    return bytearray(DUMP_SIZE)


def _ewram_offset() -> int:
    cursor = 0
    for name, _, size, _ in DUMP_LAYOUT:
        if name == "ewram":
            return cursor
        cursor += size
    raise AssertionError("ewram block missing from layout")


def test_8bit_equality_true() -> None:
    dump = _empty_dump()
    dump[_ewram_offset() + 0x26510] = 0xFF
    assert evaluate("0xH02226510=0xff", bytes(dump))  # mirror addr
    assert evaluate("0xH02026510=0xff", bytes(dump))  # canonical addr


def test_8bit_equality_false() -> None:
    dump = _empty_dump()
    assert not evaluate("0xH02226510=0xff", bytes(dump))


def test_inequality_ops() -> None:
    dump = _empty_dump()
    dump[_ewram_offset() + 0x100] = 0x42
    assert evaluate("0xH02000100!=0x00", bytes(dump))
    assert evaluate("0xH02000100>0x40", bytes(dump))
    assert evaluate("0xH02000100<0x50", bytes(dump))
    assert evaluate("0xH02000100>=0x42", bytes(dump))
    assert evaluate("0xH02000100<=0x42", bytes(dump))


def test_16bit_little_endian() -> None:
    dump = _empty_dump()
    off = _ewram_offset() + 0x200
    dump[off] = 0x34
    dump[off + 1] = 0x12
    assert evaluate("0x 02000200=0x1234", bytes(dump))


def test_32bit_money_value() -> None:
    """FireRed money at 0x022257BC, 4-byte little-endian."""
    dump = _empty_dump()
    off = _ewram_offset() + 0x257BC
    dump[off:off + 4] = (0x000F423F).to_bytes(4, "little")
    assert evaluate("0xX022257BC=0x000F423F", bytes(dump))
    assert evaluate("0xX022257BC=999999", bytes(dump))


def test_and_combinator() -> None:
    dump = _empty_dump()
    eo = _ewram_offset()
    dump[eo + 0x26510] = 0xFF
    dump[eo + 0x100] = 0x42
    assert evaluate("0xH02226510=0xff_0xH02000100=0x42", bytes(dump))
    assert not evaluate("0xH02226510=0xff_0xH02000100=0x00", bytes(dump))


def test_or_combinator() -> None:
    dump = _empty_dump()
    dump[_ewram_offset() + 0x26510] = 0xFF
    assert evaluate("0xH02226510=0xff S 0xH02000100=0x42", bytes(dump))
    assert not evaluate("0xH02000200=0x01 S 0xH02000100=0x42", bytes(dump))


def test_or_takes_lower_precedence_than_and() -> None:
    dump = _empty_dump()
    eo = _ewram_offset()
    dump[eo + 0x300] = 1
    dump[eo + 0x301] = 1
    # (a=1 AND b=1) OR (c=1 AND d=1) -> True since first group matches
    assert evaluate(
        "0xH02000300=0x01_0xH02000301=0x01 S 0xH02000302=0x01_0xH02000303=0x01",
        bytes(dump),
    )


def test_unknown_address_raises() -> None:
    dump = _empty_dump()
    with pytest.raises(ValueError):
        evaluate("0xH04000000=0x00", bytes(dump))
