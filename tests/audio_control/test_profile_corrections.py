"""Regression tests for profile corrections found by documentation research.

Each fix here came from an authoritative source (manufacturer manual or the
vendor protocol spec, cross-checked against open-source drivers tested on real
hardware), not from inference.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR, load_builtin_profiles


def load(stem: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (BUILTIN_PROFILES_DIR / f"{stem}.yaml").read_text()
    )
    return data


# ─── Monoprice 31028 ─────────────────────────────────────────────────────────
# Source: Monoprice manual 31028_Manual_180731.pdf


def test_31028_parses_single_digit_volume() -> None:
    """Volume is not zero-padded in responses.

    The manual's own example is "#6ZS VO8 PO1 MU0 IS0+". A \\d{2} pattern made
    every single-digit volume fail to parse at all (returned None), so any zone
    below volume 10 reported nothing.
    """
    engine = create_engine(load("monoprice_31028"))
    result = engine.parse_response("6ZS VO8 PO1 MU0 IS0")
    assert result is not None
    assert result["volume"] == 8
    assert result["zone"] == 6


def test_31028_still_parses_two_digit_volume() -> None:
    """The relaxed pattern must not break the padded form."""
    engine = create_engine(load("monoprice_31028"))
    result = engine.parse_response("1ZS VO38 PO1 MU0 IS1")
    assert result is not None
    assert result["volume"] == 38


def test_31028_has_two_bus_line_sources() -> None:
    """The 31028 has a per-zone BUS/LINE selector, not numbered inputs.

    Also guards against the duplicate top-level `sources:` key that previously
    made YAML silently drop the count.
    """
    engine = create_engine(load("monoprice_31028"))
    assert engine.num_sources == 2


def test_31028_uses_input_select_command() -> None:
    """Input select is IS0/IS1, not the invented SS command."""
    engine = create_engine(load("monoprice_31028"))
    # Single-digit zone (unlike the unit-prefixed 10761), so zone 1 -> "!1IS...".
    assert engine.format_command("source_set", zone=1, source=1) == "!1IS1+"
    assert engine.format_command("source_set", zone=3, source=0) == "!3IS0+"


def test_31028_bass_offset_encoded() -> None:
    """Wire 0-14 with flat at 7; boost and cut must differ."""
    engine = create_engine(load("monoprice_31028"))
    assert engine.format_command("bass_set", zone=1, level=-7) == "!1BS00+"
    assert engine.format_command("bass_set", zone=1, level=0) == "!1BS07+"
    assert engine.format_command("bass_set", zone=1, level=7) == "!1BS14+"


def test_31028_documents_2db_step() -> None:
    """31028 is 2 dB/step, unlike the 10761/Xantech 1 dB/step.

    Same 0-14 range and same flat value of 7, so the distinction is easy to lose
    and is recorded explicitly in the profile.
    """
    profile = load("monoprice_31028")
    assert profile.get("tone_step_db") == 2


# ─── Russound CAV6.6: fabricated ASCII profile removed ───────────────────────


def test_no_ascii_cav66_profile() -> None:
    """The ASCII "Russound CAV6.6" profile must not come back.

    The CAV6.6 speaks binary RNET only (0xF0-framed, 0xF7-terminated). The old
    profile sent ASCII like "F1 B Z1 08" -- literally the letter 'F' (0x46), not
    the 0xF0 framing byte -- and no such command exists in the RNET spec. It
    could never have controlled the hardware.
    """
    assert not (BUILTIN_PROFILES_DIR / "russound_cav66.yaml").exists()
    names = set(load_builtin_profiles())
    assert "Russound CAV6.6" not in names


def test_cav66_models_covered_by_rnet_profile() -> None:
    """Users with a CAV6.6 must still find their device."""
    profile = load("russound_rnet")
    assert "CAV6.6" in profile["models"]
    assert "CAA66" in profile["models"]


# ─── RNET tone encoding: offset +10, not two's complement ────────────────────
# Source: Russound RNET Protocol & Specifications v1.00.4 §8.4-8.5, corroborated
# by aiorussound (bass_raw - 10) and rnet-pi (value += 10).


@pytest.mark.parametrize(("level", "wire"), [(-10, 0x00), (0, 0x0A), (10, 0x14)])
def test_rnet_tone_transmits_biased_byte(level: int, wire: int) -> None:
    """Spec: 0x00 = -10, 0x0A = flat, 0x14 = +10.

    Two's complement sent 0xF6 for -10, which the device would read as +246.
    """
    engine = create_engine(load("russound_rnet"))
    cmd = engine.format_command("bass_set", zone=1, level=level)
    assert isinstance(cmd, bytes)
    # Layout is ... level, checksum, end_byte
    assert cmd[-3] == wire


@pytest.mark.parametrize(("wire", "level"), [(0x00, -10), (0x0A, 0), (0x14, 10)])
def test_rnet_tone_decodes_biased_byte(wire: int, level: int) -> None:
    """Decoding must mirror transmit; `transform: signed` read flat as +10."""
    engine = create_engine(load("russound_rnet"))
    # zone_status opcode 0x06; payload starts at data[3]; bass at payload 23
    frame = bytearray([0xF0, 0x20, 0x06] + [0x00] * 30)
    frame[3 + 23] = wire
    body = bytes(frame)
    checksum = (sum(body) + len(body)) & 0x7F
    result = engine.parse_response(body + bytes([checksum]) + b"\xf7")
    assert result is not None
    assert result["bass"] == level


def test_rnet_tone_round_trips() -> None:
    """Encode then decode returns the original level for the whole range."""
    engine = create_engine(load("russound_rnet"))
    for level in range(-10, 11):
        cmd = engine.format_command("bass_set", zone=1, level=level)
        assert isinstance(cmd, bytes)
        wire = cmd[-3]
        frame = bytearray([0xF0, 0x20, 0x06] + [0x00] * 30)
        frame[3 + 23] = wire
        body = bytes(frame)
        checksum = (sum(body) + len(body)) & 0x7F
        result = engine.parse_response(body + bytes([checksum]) + b"\xf7")
        assert result is not None
        assert result["bass"] == level, f"{level} -> 0x{wire:02X} -> {result['bass']}"


# ─── All bass-capable profiles distinguish boost from cut ─────────────────────


def test_every_bass_profile_distinguishes_boost_from_cut() -> None:
    """No profile may send identical bytes for +8 and -8.

    This was true of 8 of 12 profiles before the tone work; it is the property
    the whole exercise was about, asserted once over every shipped profile.
    """
    identical = []
    for path in sorted(BUILTIN_PROFILES_DIR.glob("*.yaml")):
        profile = yaml.safe_load(path.read_text())
        if not (profile.get("commands") or {}).get("bass_set"):
            continue
        engine = create_engine(profile)
        boost = engine.format_command("bass_set", zone=1, level=8)
        cut = engine.format_command("bass_set", zone=1, level=-8)
        if boost == cut:
            identical.append(path.stem)
    assert not identical, f"boost == cut on: {identical}"
