"""Volume conversion tests, including dB scales with a negative floor.

Regression cover for a bug the previous 368 tests all missed: ProtocolEngine
carried a near-duplicate of the base class's volume conversion that assumed a
0..max scale. On the NAD C 368 (-80..0 dB) every requested level mapped to 0 dB
-- full volume -- so asking for 10% would blast the amplifier. Yamaha (-80..16)
could never reach its lower half, and reverse conversion returned -5.0, outside
the 0.0-1.0 range Home Assistant accepts.

The tests are written against real bundled profiles rather than synthetic ones,
so a profile whose scale is later edited is covered automatically.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from rs232_protocol import create_engine
from rs232_protocol.base import BaseProtocolEngine
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR

# Derived from the installed package rather than hardcoded, so the path
# survives the library moving (it is now vendored in the integration).
PROFILE_DIR = BUILTIN_PROFILES_DIR

HA_LEVELS = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)


def load_profile(stem: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((PROFILE_DIR / f"{stem}.yaml").read_text())
    return data


def all_profiles() -> list[tuple[str, dict[str, Any]]]:
    """Every bundled profile except the custom-device template."""
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if data and not str(data.get("name", "")).startswith("My Custom"):
            out.append((path.stem, data))
    return out


PROFILES = all_profiles()
PROFILE_IDS = [stem for stem, _ in PROFILES]


# ─── dB scales (the actual bug) ──────────────────────────────────────────────


def test_nad_db_scale_spans_full_range() -> None:
    """NAD is -80..0 dB: 0.0 must be the floor, not the ceiling.

    Before the fix every level returned 0 (= 0 dB = maximum volume).
    """
    engine = create_engine(load_profile("nad_c368"))
    assert engine.volume_min == -80
    assert engine.volume_max == 0
    assert engine.ha_volume_to_device(0.0) == -80
    assert engine.ha_volume_to_device(0.5) == -40
    assert engine.ha_volume_to_device(1.0) == 0


def test_nad_quiet_request_is_not_full_volume() -> None:
    """The dangerous case stated plainly: a quiet request must stay quiet."""
    engine = create_engine(load_profile("nad_c368"))
    quiet = engine.ha_volume_to_device(0.1)
    loud = engine.ha_volume_to_device(1.0)
    assert quiet < loud
    assert quiet <= -60


def test_yamaha_asymmetric_db_scale() -> None:
    """Yamaha spans -80..16, so the midpoint is negative, not max/2."""
    engine = create_engine(load_profile("yamaha_rx_a"))
    assert engine.volume_min == -80
    assert engine.volume_max == 16
    assert engine.ha_volume_to_device(0.0) == -80
    assert engine.ha_volume_to_device(1.0) == 16
    assert engine.ha_volume_to_device(0.5) == -32


def test_reverse_conversion_stays_normalized() -> None:
    """device_volume_to_ha must never leave 0.0-1.0; HA rejects out-of-range.

    Previously NAD/Yamaha floors produced values like -5.0.
    """
    for stem in ("nad_c368", "yamaha_rx_a"):
        engine = create_engine(load_profile(stem))
        for device_value in (engine.volume_min, 0, engine.volume_max):
            result = engine.device_volume_to_ha(device_value)
            assert 0.0 <= result <= 1.0, f"{stem}: {device_value} -> {result}"


# ─── Standard 0..max scales must be unaffected ───────────────────────────────


def test_inverted_scale_unchanged() -> None:
    """AMC is inverted 0..62 (62 = silent). Guards against regressing the fix."""
    engine = create_engine(load_profile("amc_x86"))
    assert engine.volume_min == 0
    assert engine.ha_volume_to_device(0.0) == 62
    assert engine.ha_volume_to_device(0.5) == 31
    assert engine.ha_volume_to_device(1.0) == 0


def test_normal_scale_unchanged() -> None:
    """Monoprice is non-inverted 0..38."""
    engine = create_engine(load_profile("monoprice_6zone"))
    assert engine.ha_volume_to_device(0.0) == 0
    assert engine.ha_volume_to_device(0.5) == 19
    assert engine.ha_volume_to_device(1.0) == 38


def test_volume_min_defaults_to_zero() -> None:
    """A profile with no explicit volume.min keeps the plain 0..max behaviour."""
    profile = {
        "name": "T",
        "zones": 1,
        "sources": 1,
        "commands": {"status": "S"},
        "volume": {"max": 100},
    }
    assert create_engine(profile).volume_min == 0


# ─── Properties hold for every bundled profile ───────────────────────────────


@pytest.mark.parametrize(("stem", "profile"), PROFILES, ids=PROFILE_IDS)
def test_device_value_within_declared_range(stem: str, profile: dict[str, Any]) -> None:
    """Converted values must land inside the device's own min..max."""
    engine = create_engine(profile)
    for level in HA_LEVELS:
        value = engine.ha_volume_to_device(level)
        assert engine.volume_min <= value <= engine.volume_max, (
            f"{stem}: ha={level} -> {value} outside "
            f"[{engine.volume_min}, {engine.volume_max}]"
        )


@pytest.mark.parametrize(("stem", "profile"), PROFILES, ids=PROFILE_IDS)
def test_round_trip_is_stable(stem: str, profile: dict[str, Any]) -> None:
    """ha -> device -> ha returns approximately the original level.

    Tolerance accounts for quantisation on coarse scales (Yamaha has 16 steps).
    """
    engine = create_engine(profile)
    if engine.volume_max == engine.volume_min:
        pytest.skip(f"{stem} has no volume range")
    for level in HA_LEVELS:
        device = engine.ha_volume_to_device(level)
        restored = engine.device_volume_to_ha(device)
        assert abs(restored - level) < 0.06, (
            f"{stem}: {level} -> {device} -> {restored}"
        )


@pytest.mark.parametrize(("stem", "profile"), PROFILES, ids=PROFILE_IDS)
def test_monotonic(stem: str, profile: dict[str, Any]) -> None:
    """Louder requests must never produce a quieter device value.

    Catches sign errors on inverted and negative-floor scales alike.
    """
    engine = create_engine(profile)
    if engine.volume_max == engine.volume_min:
        pytest.skip(f"{stem} has no volume range")
    values = [engine.ha_volume_to_device(level) for level in HA_LEVELS]
    if engine.volume_inverted:
        assert values == sorted(values, reverse=True), f"{stem}: {values}"
    else:
        assert values == sorted(values), f"{stem}: {values}"


@pytest.mark.parametrize(("stem", "profile"), PROFILES, ids=PROFILE_IDS)
def test_out_of_range_device_value_is_clamped(
    stem: str, profile: dict[str, Any]
) -> None:
    """Devices sometimes report values outside their documented range."""
    engine = create_engine(profile)
    for probe in (engine.volume_min - 50, engine.volume_max + 50):
        result = engine.device_volume_to_ha(probe)
        assert 0.0 <= result <= 1.0, f"{stem}: {probe} -> {result}"


# ─── The structural cause ────────────────────────────────────────────────────


def test_engines_do_not_override_volume_conversion() -> None:
    """Conversion must live only on the base class.

    The bug was a duplicated implementation in ProtocolEngine that drifted from
    the base version. This asserts the duplication does not come back.
    """
    from rs232_protocol.binary_engine import BinaryProtocolEngine
    from rs232_protocol.json_engine import JsonProtocolEngine
    from rs232_protocol.protocol_engine import ProtocolEngine

    for cls in (ProtocolEngine, BinaryProtocolEngine, JsonProtocolEngine):
        for method in ("ha_volume_to_device", "device_volume_to_ha"):
            assert method not in vars(cls), (
                f"{cls.__name__} overrides {method}; conversion must stay on "
                "BaseProtocolEngine so all engines share one implementation"
            )


def test_base_uses_decimal_rounding() -> None:
    """Banker's rounding at a .5 boundary, not float round()."""
    profile = {
        "name": "T",
        "zones": 1,
        "sources": 1,
        "commands": {"status": "S"},
        "volume": {"max": 10, "inverted": True},
    }
    engine = create_engine(profile)
    assert isinstance(engine, BaseProtocolEngine)
    # 1.0 - 0.55 = 0.45 exactly in Decimal -> 4.5 -> ROUND_HALF_EVEN -> 4
    assert engine.ha_volume_to_device(0.55) == 4
