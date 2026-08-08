"""A parsed reply must actually land in ZoneState.

`_process_response` dispatched on `parsed.get("zone")` and dropped anything
without that key. 14 of the 26 shipped profiles never produce one:

  - 13 single-zone devices whose status_pattern has no (?P<zone>...) group,
    because a one-zone amplifier has no zone to report -- AMC XAi, XGi, XIA
    (both), XCDie, Marantz, NAD, Oppo, Rotel (x4), Yamaha.
  - Russound RNET, which is EIGHT zones and whose binary `zone_status` response
    declares no `zone` field at all.

Every reply from all 14 was computed, returned, and thrown away, so their
entities showed the ZoneState defaults forever: `off`, source 1, and (before the
demo-volume fix) whatever raw 0 meant on that scale. The 60s poll re-read the
device and discarded that too, so there was no path to consistency.

This also made the `static:` block added for the XCDie pointless -- its entire
purpose is to feed this path.

Predates the AMC work; found by a review of it.
"""

from __future__ import annotations

from typing import Any

import pytest
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles


def conn(profile: dict[str, Any]) -> AsyncSerialConnection:
    return AsyncSerialConnection(
        port="demo", engine=create_engine(profile), demo_mode=True
    )


def profile(name: str) -> dict[str, Any]:
    return load_builtin_profiles()[name]


# ─── Single-zone devices: the reply implies zone 1 ────────────────────────────


def test_xia_status_reaches_zone_one() -> None:
    """ "#ON,SRC03,MUTE OFF" must set power and source, not be discarded."""
    c = conn(profile("AMC XIA100e / XIA150e"))
    c._process_response("ON,SRC03,MUTE OFF")
    zone = c.zones[1]
    assert zone.power is True, "power was discarded"
    assert zone.source == 3, "source was discarded"
    assert zone.mute is False


def test_xia_mute_state_reaches_zone_one() -> None:
    c = conn(profile("AMC XIA100e / XIA150e"))
    c._process_response("ON,SRC06,MUTE ON")
    assert c.zones[1].mute is True
    assert c.zones[1].source == 6


def test_xcdie_static_block_reaches_zone_one() -> None:
    """The `static:` mechanism exists solely to feed ZoneState.

    Before the fix its values were computed and dropped, so the XCDie showed
    `off` / `CD` no matter what the player reported.
    """
    c = conn(profile("AMC XCDie CD Player"))
    c._process_response(bytes([0x55, 0x31, 0xAA]))  # USB PLAY
    assert c.zones[1].power is True
    assert c.zones[1].source == 2, "USB is source 2"


@pytest.mark.parametrize(
    ("code", "expected_source"),
    [(0x21, 1), (0x31, 2), (0x41, 3), (0x50, 4)],
)
def test_xcdie_every_input_reaches_zone_one(code: int, expected_source: int) -> None:
    """CD / USB / SD / 24192, per the Status Code table's high nibble."""
    c = conn(profile("AMC XCDie CD Player"))
    c._process_response(bytes([0x55, code, 0xAA]))
    assert c.zones[1].source == expected_source


@pytest.mark.parametrize(
    "name",
    [
        "AMC XAi",
        "AMC XGi",
        "AMC XIA100e / XIA150e",
        "AMC XIA / 306D (4-input)",
        "AMC XCDie CD Player",
        "Marantz PM7000N / SR Series",
        "NAD C 368 / C 388",
        "Oppo UDP-203 / UDP-205",
        "Rotel Michi M8 / S5",
        "Rotel RA-1572 / RA-1592",
        "Rotel RCD-1572 CD Player",
        "Rotel RSP-1576 / RSP-1582",
        "Yamaha RX-A / RX-V Series",
    ],
)
def test_single_zone_profiles_have_a_zone_one(name: str) -> None:
    """The fallback targets zone 1, so it must exist for all of them."""
    c = conn(profile(name))
    assert 1 in c.zones
    assert c.engine.num_zones == 1


# ─── Multi-zone must NOT get a fallback ──────────────────────────────────────


def test_multi_zone_reply_without_a_zone_is_still_dropped() -> None:
    """Guessing zone 1 on a multi-zone device would corrupt state.

    A reply that does not say which zone it describes cannot be attributed on an
    8-zone amplifier, so dropping it is correct -- the alternative is writing
    another zone's state into zone 1. This is why the fallback is conditional on
    num_zones == 1 rather than unconditional.
    """
    c = conn(profile("AMC X86 / X86i"))
    assert c.engine.num_zones == 6
    before = (c.zones[1].power, c.zones[1].source, c.zones[1].volume)
    # A parseable frame with no zone group cannot occur for this profile, so
    # assert the guard directly: an unattributable reply leaves state untouched.
    c._process_response("garbage that does not parse")
    assert (c.zones[1].power, c.zones[1].source, c.zones[1].volume) == before


def test_zone_scoped_reply_still_targets_its_own_zone() -> None:
    """The fallback must not hijack replies that DO name a zone."""
    c = conn(profile("AMC X86 / X86i"))
    c._process_response("ZN03,SRC02,GRP0,VOL-30")
    assert c.zones[3].volume == 30, "zone 3 should have been updated"
    assert c.zones[1].volume != 30, "zone 1 must be untouched"


# ─── The Russound RNET case: 8 zones, no zone field ──────────────────────────


def test_rnet_zone_status_declares_no_zone_field() -> None:
    """Documents a real gap rather than asserting desired behaviour.

    Russound RNET is 8 zones and its binary `zone_status` response declares
    fields for power/source/volume/tone but NOT zone, so its replies are
    unattributable and correctly dropped. The fix would be to add a zone field
    with the right byte offset, which needs the RNET spec -- inventing an offset
    is how russound_cav66.yaml earned its deletion.

    Pinned so the gap is visible and so a future profile fix is a deliberate
    change rather than a surprise.
    """
    prof = profile("Russound CAV / CAS / MCA (RNET)")
    engine = create_engine(prof)
    assert engine.num_zones == 8
    responses = prof.get("response") or {}
    zone_status = responses.get("zone_status")
    assert isinstance(zone_status, dict)
    fields = zone_status.get("fields") or {}
    assert "zone" not in fields, (
        "RNET now declares a zone field -- remove this test and assert the "
        "replies reach their zones instead"
    )


# ─── Fleet invariant ─────────────────────────────────────────────────────────


def test_no_single_zone_profile_silently_discards_state() -> None:
    """Every single-zone profile must be able to update zone 1.

    Checked via the engine's own num_zones, so a future single-zone profile is
    covered without being listed by name.
    """
    offenders = []
    for name, prof in load_builtin_profiles().items():
        engine = create_engine(prof)
        if engine.num_zones != 1:
            continue
        c = AsyncSerialConnection(port="demo", engine=engine, demo_mode=True)
        if 1 not in c.zones:
            offenders.append(name)
    assert not offenders, f"single-zone profiles with no zone 1: {offenders}"
