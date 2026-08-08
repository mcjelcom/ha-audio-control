"""Regression tests for tone-control encoding and error-response handling.

Both bugs were found in code review and confirmed against the real library:

- Tone: services.py pre-applied abs()+sign, so set_bass(-8) and set_bass(+8)
  produced byte-identical commands on 8 of 12 profiles -- bass/treble cut was
  impossible. Encoding now lives in the engine, per template style.
- error_response: the Monoprice profile sets error_response: "", and the guard
  `line == error_response` classified every blank line as a device error,
  triggering spurious optimistic-state rollback on the most-used profile.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR

# Derived from the installed package rather than hardcoded, so the path
# survives the library moving (it is now vendored in the integration).
PROFILE_DIR = BUILTIN_PROFILES_DIR


def load(stem: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((PROFILE_DIR / f"{stem}.yaml").read_text())
    return data


def bass_profiles() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if (data.get("commands") or {}).get("bass_set"):
            out.append((path.stem, data))
    return out


BASS_PROFILES = bass_profiles()
BASS_IDS = [stem for stem, _ in BASS_PROFILES]


# ─── Tone sign encoding ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("stem", "profile"), BASS_PROFILES, ids=BASS_IDS)
def test_bass_cut_differs_from_boost(stem: str, profile: dict[str, Any]) -> None:
    """set_bass(-8) and set_bass(+8) must produce different wire commands.

    A profile whose template genuinely cannot express a sign (no {sign}, no
    offset) is exempt -- but it must be flagged so the gap is visible, not
    silently accepted.
    """
    engine = create_engine(profile)
    boost = engine.format_command("bass_set", zone=1, level=8)
    cut = engine.format_command("bass_set", zone=1, level=-8)
    assert boost is not None
    assert cut is not None

    template = profile["commands"]["bass_set"]
    can_sign = "{sign}" in str(template) or "{level:+d}" in str(template)
    mapping = (profile.get("response", {}).get("mapping", {}) or {}).get("bass", {})
    has_offset = mapping.get("offset") is not None
    # Binary profiles encode tone as a biased byte declared in the response
    # fields (RNET: bias 10), which is a valid sign encoding too.
    has_bias = any(
        isinstance(cfg, dict)
        and isinstance(cfg.get("fields"), dict)
        and any(
            isinstance(f, dict) and f.get("transform") == "bias"
            for f in cfg["fields"].values()
        )
        for cfg in (profile.get("response") or {}).values()
    )

    if can_sign or has_offset or has_bias:
        assert boost != cut, f"{stem}: boost and cut are identical ({boost!r})"
    else:
        pytest.skip(f"{stem} template cannot encode a sign; needs a profile offset")


@pytest.mark.parametrize(("stem", "profile"), BASS_PROFILES, ids=BASS_IDS)
def test_bass_wire_value_never_malformed(stem: str, profile: dict[str, Any]) -> None:
    """No level in -8..+8 may render a stray minus in an unsigned field.

    Offset-encoded templates use {level:02d}; a negative value there produces
    e.g. 'BS-1', a malformed command. Values must be clamped into wire range.
    """
    engine = create_engine(profile)
    template = str(profile["commands"]["bass_set"])
    signed_template = "{sign}" in template or "{level:+d}" in template

    for level in range(-8, 9):
        cmd = engine.format_command("bass_set", zone=1, level=level)
        assert cmd is not None
        if isinstance(cmd, str) and not signed_template:
            # Strip the fixed command scaffolding; no '-' should remain.
            assert "-" not in cmd, f"{stem}: level={level} -> {cmd!r}"


def test_amc_sign_style() -> None:
    """AMC uses {sign}{level}: explicit sign, magnitude follows."""
    engine = create_engine(load("amc_x86"))
    assert engine.format_command("bass_set", zone=1, level=6) == "*ZN01BAS+6\r"
    assert engine.format_command("bass_set", zone=1, level=-6) == "*ZN01BAS-6\r"
    assert engine.format_command("bass_set", zone=1, level=0) == "*ZN01BAS+0\r"


def test_monoprice_offset_style() -> None:
    """Monoprice offset -7: level 0 -> wire 07 (flat), +7 -> 14, -7 -> 00."""
    engine = create_engine(load("monoprice_6zone"))
    assert engine.format_command("bass_set", zone=1, level=0) == "<11BS07\r"
    assert engine.format_command("bass_set", zone=1, level=7) == "<11BS14\r"
    assert engine.format_command("bass_set", zone=1, level=-7) == "<11BS00\r"
    # Out-of-range clamps to the endpoints rather than emitting a bad value.
    assert engine.format_command("bass_set", zone=1, level=8) == "<11BS14\r"
    assert engine.format_command("bass_set", zone=1, level=-8) == "<11BS00\r"


def test_rti_signed_format_style() -> None:
    """RTI uses {level:+d}: Python renders the sign itself."""
    engine = create_engine(load("rti_ad4x"))
    boost = engine.format_command("bass_set", zone=1, level=8)
    cut = engine.format_command("bass_set", zone=1, level=-8)
    assert "+8" in boost
    assert "-8" in cut


# ─── error_response ──────────────────────────────────────────────────────────


def test_empty_error_response_does_not_flag_blank_lines() -> None:
    """Monoprice error_response is "": a blank line must not be an error.

    Before the fix this returned {'error': True}, rolling back optimistic state
    for accepted commands.
    """
    engine = create_engine(load("monoprice_6zone"))
    assert engine.error_response == ""
    assert engine.parse_response("") is None
    assert engine.parse_response("   ") is None


def test_real_error_token_still_detected() -> None:
    """A profile with a real error token still flags it."""
    engine = create_engine(load("amc_x86"))
    token = engine.error_response
    assert token  # AMC uses "?"
    result = engine.parse_response(token)
    assert result == {"error": True}


def test_valid_status_never_misread_as_error() -> None:
    """A normal status line is parsed, not treated as an error."""
    engine = create_engine(load("monoprice_6zone"))
    # >11 PA=00 power=01 mute=00 dt=00 vol=20 treb=07 bass=07 bal=10 src=01
    line = ">11000100002007071001"
    result = engine.parse_response(line)
    assert result is not None
    assert "error" not in result
    assert result.get("zone") == 1
