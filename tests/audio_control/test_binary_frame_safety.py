"""BinaryProtocolEngine._resolve_data_byte — the frame-safety guards.

Every branch here exists to stop a malformed byte reaching a device. The comments
in the source record what each one prevented: silently masking with `& 0xFF`
turned volume=-1 into 0xFF (full attenuation on an inverted scale) and volume=300
into 44, and a zone of 0 became -1, which `bytes()` rejects with a ValueError
that escaped format_command entirely.

binary_engine.py was the least-covered module at 87%, and much of the gap was
these guards plus the accessors. A guard with no test is indistinguishable from
one that was removed, so they are pinned individually here -- the observable
contract is "return None rather than build a bad frame", which format_command
turns into a refusal instead of a wire write.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from rs232_protocol import create_engine
from rs232_protocol.binary_engine import BinaryProtocolEngine

BASE: dict[str, Any] = {
    "name": "FrameSafety",
    "protocol_type": "binary",
    "zones": 6,
    "sources": 6,
    "serial": {
        "baud_rate": 57600,
        "data_bits": 8,
        "parity": "even",
        "stop_bits": 2,
        "command_delay_ms": 250,
    },
    "binary": {"start_byte": 0x55, "checksum": "mod256"},
    "commands": {
        "volume_set": {"opcode": "0x15", "data": ["{zone}", "{volume}"]},
        "literal_hex": {"opcode": "0x01", "data": ["0xFF", "0x00"]},
        "literal_dec": {"opcode": "0x02", "data": ["7", "42"]},
        "bogus_template": {"opcode": "0x03", "data": ["not_a_template"]},
        "bass_set": {"opcode": "0x04", "data": ["{zone}", "{level}"]},
    },
    "response": {"mapping": {}},
    "volume": {"min": 0, "max": 38},
}


def engine(**overrides: Any) -> BinaryProtocolEngine:
    profile = {**BASE, **overrides}
    built = create_engine(profile)
    assert isinstance(built, BinaryProtocolEngine)
    return built


# ─── Serial accessors read from the profile ──────────────────────────────────


def test_serial_accessors_reflect_the_profile() -> None:
    """Wrong parity or stop bits corrupts every byte on the wire.

    These are plain property reads, but an inverted mapping would be invisible in
    tests that only ever use the 8N1 default.
    """
    e = engine()
    assert e.baud_rate == 57600
    assert e.data_bits == 8
    assert e.parity == "E"
    assert e.stop_bits == 2
    assert e.command_delay == 0.25


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("none", "N"), ("even", "E"), ("odd", "O"), ("NONE", "N"), ("nonsense", "N")],
)
def test_parity_words_map_to_pyserial_letters(declared: str, expected: str) -> None:
    """pyserial wants N/E/O; profiles spell it out. Unknown falls back to N."""
    e = engine(serial={**BASE["serial"], "parity": declared})
    assert e.parity == expected


def test_serial_defaults_apply_when_unspecified() -> None:
    """A minimal profile must still produce a usable port configuration."""
    e = engine(serial={})
    assert e.data_bits == 8
    assert e.parity == "N"
    assert e.stop_bits == 1
    assert e.command_delay == 0.1


# ─── Literal data bytes ──────────────────────────────────────────────────────


def test_hex_literals_are_emitted_verbatim() -> None:
    frame = engine().format_command("literal_hex")
    assert frame is not None
    assert frame[2:5] == bytes([0x01, 0xFF, 0x00])


def test_decimal_literals_are_emitted_verbatim() -> None:
    frame = engine().format_command("literal_dec")
    assert frame is not None
    assert frame[2:5] == bytes([0x02, 7, 42])


def test_unrecognised_template_refuses_the_frame(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unknown template must not silently become 0x00.

    A zero byte is a legal value everywhere, so substituting one would send a
    plausible-but-wrong command rather than failing.
    """
    with caplog.at_level(logging.WARNING):
        assert engine().format_command("bogus_template") is None
    assert any("not_a_template" in r.getMessage() for r in caplog.records)


# ─── Range guards: refuse rather than wrap ───────────────────────────────────


@pytest.mark.parametrize("volume", [-1, 256, 300, 1000])
def test_out_of_range_volume_refuses_the_frame(volume: int) -> None:
    """The regression the source comment records.

    Masking with & 0xFF turned -1 into 0xFF -- full attenuation on an inverted
    scale, i.e. the loudest possible setting on some devices -- and 300 into 44.
    """
    assert engine().format_command("volume_set", zone=1, volume=volume) is None


@pytest.mark.parametrize("volume", [0, 1, 38, 255])
def test_in_range_volume_builds_a_frame(volume: int) -> None:
    """The guard must not reject legal values."""
    frame = engine().format_command("volume_set", zone=1, volume=volume)
    assert frame is not None
    assert frame[4] == volume


def test_zone_is_zero_indexed_on_the_wire() -> None:
    """Zone 1 becomes 0x00; the profile numbering is 1-based."""
    frame = engine().format_command("volume_set", zone=1, volume=20)
    assert frame is not None
    assert frame[3] == 0x00


def test_zone_zero_refuses_rather_than_underflowing() -> None:
    """Zone 0 would map to -1, which bytes() rejects with a raw ValueError.

    Refusing here keeps that failure inside format_command as a None, which
    send_command reports as a failed command.
    """
    assert engine().format_command("volume_set", zone=0, volume=20) is None


@pytest.mark.parametrize("value", ["loud", None, [1], {"a": 1}])
def test_non_numeric_parameter_refuses_the_frame(
    value: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A service call carrying a string must not crash the engine."""
    with caplog.at_level(logging.WARNING):
        assert engine().format_command("volume_set", zone=1, volume=value) is None


def test_missing_parameter_refuses_the_frame() -> None:
    """An omitted kwarg must refuse, not default to 0.

    This test previously asserted the opposite -- that a missing `volume`
    resolved to 0 and still built a frame. A review showed why that was wrong: 0
    is the LOUDEST value on an inverted scale, so a dropped parameter produced a
    valid, checksummed frame commanding maximum volume. On SpeakerCraft MZC
    (inverted, max 80) `volume_set` with no volume emitted
    `55 08 57 00 00 05 00 00 47`, which device_volume_to_ha reads back as 1.0.

    The text engine already failed closed on the identical mistake, which is what
    established the intended contract.
    """
    e = engine()
    assert e.format_command("volume_set", zone=1) is None, "missing volume"
    assert e.format_command("volume_set", volume=20) is None, "missing zone"
    # Both present: builds normally.
    assert e.format_command("volume_set", zone=1, volume=20) is not None


def test_explicit_zero_is_still_accepted() -> None:
    """Refusing a MISSING kwarg must not refuse a deliberate 0.

    The two were previously indistinguishable; the fix must separate them rather
    than reject both.
    """
    frame = engine().format_command("volume_set", zone=1, volume=0)
    assert frame is not None
    assert frame[4] == 0


# ─── Signed tone values ──────────────────────────────────────────────────────


def test_signed_tone_uses_twos_complement_without_a_bias() -> None:
    """Profiles with no declared bias encode tone as two's complement."""
    frame = engine().format_command("bass_set", zone=1, level=-8)
    assert frame is not None
    assert frame[4] == (-8 & 0xFF)


@pytest.mark.parametrize("level", [-129, 128, 500])
def test_out_of_range_signed_tone_refuses_the_frame(level: int) -> None:
    """Beyond a signed byte, refuse rather than truncate."""
    assert engine().format_command("bass_set", zone=1, level=level) is None


def test_biased_tone_encoding_is_the_inverse_of_decoding() -> None:
    """A profile declaring `transform: bias` must encode with the same bias.

    Russound RNET offset-encodes tone as +10 (0x00..0x14). Encode and decode
    reading the bias from the same place is what stops them drifting apart.
    """
    e = engine(
        response={
            "mapping": {},
            "zone_status": {
                "opcode": "0x20",
                "fields": {"bass": {"offset": 0, "transform": "bias", "bias": 10}},
            },
        }
    )
    frame = e.format_command("bass_set", zone=1, level=0)
    assert frame is not None
    assert frame[4] == 10, "level 0 should encode as the bias itself"

    frame = e.format_command("bass_set", zone=1, level=-10)
    assert frame is not None
    assert frame[4] == 0, "level -10 should encode as 0"


def test_biased_tone_out_of_byte_range_refuses() -> None:
    """A bias that pushes the value past 0xFF must not wrap."""
    e = engine(
        response={
            "mapping": {},
            "zone_status": {
                "opcode": "0x20",
                "fields": {"bass": {"offset": 0, "transform": "bias", "bias": 250}},
            },
        }
    )
    assert e.format_command("bass_set", zone=1, level=20) is None


# ─── Checksums ───────────────────────────────────────────────────────────────


def test_xor_checksum_is_supported() -> None:
    """SpeakerCraft-style XOR, distinct from mod256."""
    e = engine(binary={"start_byte": 0x55, "checksum": "xor"})
    frame = e.format_command("literal_dec")
    assert frame is not None
    expected = 0
    for byte in frame[:-1]:
        expected ^= byte
    assert frame[-1] == expected


def test_unknown_checksum_warns_and_disables(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo must be visible, not silently disable frame validation.

    "mdo256" would otherwise be indistinguishable from the documented
    `checksum: none`.
    """
    with caplog.at_level(logging.WARNING):
        e = engine(binary={"start_byte": 0x55, "checksum": "mdo256"})
    assert any("mdo256" in r.getMessage() for r in caplog.records)
    frame = e.format_command("literal_dec")
    assert frame is not None
    # No checksum appended: start, length, opcode, 2 data bytes.
    assert len(frame) == 5


def test_checksum_none_is_silent() -> None:
    """Intentionally disabling validation must not warn."""
    e = engine(binary={"start_byte": 0x55, "checksum": "none"})
    frame = e.format_command("literal_dec")
    assert frame is not None
    assert len(frame) == 5


def test_unknown_command_returns_none() -> None:
    """Nothing to format, so no frame -- send_command reports failure."""
    assert engine().format_command("no_such_command") is None
