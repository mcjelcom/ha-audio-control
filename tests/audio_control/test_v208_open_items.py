"""v2.0.8: the five open items left after the 2026-11 review.

A  RTI set_powerstate (no zone) -> device-wide power, not dropped
B  RTI get_outputvol (status poll) reply mapped
C  AMC XOir absolute tone encoding (manual v3.3: 00-12, 22-32)  [UNVERIFIED on hw]
D  per-profile tone levels: odd steps for Monoprice/Xantech, -12..+12 for XOir
E  "zone is off" tone check only once power is actually KNOWN
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.models import ZoneState
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

RTI = "RTI AD-810-100 / AD-46-100"
AMC = "AMC X86 / X86i"


def engine(name: str):
    return create_engine(load_builtin_profiles()[name])


def mx88() -> str:
    return next(k for k in load_builtin_profiles() if "MX88" in k)


def monoprice_31028() -> str:
    return next(
        k for k, p in load_builtin_profiles().items() if "31028" in str(p.get("models"))
    )


# ─── A ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("power", [True, False])
def test_rti_device_power_reaches_every_zone(power: bool) -> None:
    conn = AsyncSerialConnection(port="demo", engine=engine(RTI), demo_mode=True)
    for z in conn.zones.values():
        z.power = not power
    conn._process_response(
        f'{{"type":"set_powerstate","status":901,"value":{str(power).lower()}}}'
    )
    assert all(z.power is power for z in conn.zones.values())
    assert all(z.power_known for z in conn.zones.values())


def test_rti_device_power_is_a_global_event() -> None:
    r = engine(RTI).parse_response(
        '{"type":"set_powerstate","status":200,"value":true}'
    )
    assert r is not None
    assert r["global"] == "power"
    assert "zone" not in r


# ─── B ───────────────────────────────────────────────────────────────────────


def test_rti_status_poll_reply_sets_volume() -> None:
    conn = AsyncSerialConnection(port="demo", engine=engine(RTI), demo_mode=True)
    conn._process_response(
        '{"type":"get_outputvol","status":200,"value":[{"index":4,"value":33}]}'
    )
    assert conn.zones[4].volume == 33


# ─── C ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "wire"),
    [(0, "00"), (4, "04"), (12, "12"), (-2, "22"), (-7, "27"), (-12, "32")],
)
def test_xoir_encodes_absolute_levels(level: int, wire: str) -> None:
    e = engine("AMC XOir")
    assert e.format_command("bass_set", zone=1, level=level) == f"*ZN01BAS{wire}\r"
    assert e.format_command("treble_set", zone=1, level=level) == f"*ZN01TRB{wire}\r"


@pytest.mark.parametrize(("reply", "bass"), [("22", -2), ("32", -12), ("04", 4)])
def test_xoir_decodes_absolute_levels(reply: str, bass: int) -> None:
    r = engine("AMC XOir").parse_response(f"ZN01,BASS{reply},TREB00")
    assert r is not None
    assert r["bass"] == bass


def test_signed_replies_unaffected_by_negative_base() -> None:
    """A device answering "+4"/"-6" must decode as before."""
    r = engine("AMC XOir").parse_response("ZN01,BASS+4,TREB-6")
    assert r is not None
    assert (r["bass"], r["treble"]) == (4, -6)


def test_x86_encoding_unchanged() -> None:
    assert engine(AMC).format_command("bass_set", zone=1, level=-4) == "*ZN01BAS-4\r"


# ─── D ───────────────────────────────────────────────────────────────────────


def test_offset_profiles_declare_every_step() -> None:
    for name in (mx88(), monoprice_31028()):
        assert engine(name).tone_levels == tuple(range(-7, 8)), name


def test_odd_level_encodes_on_offset_profile() -> None:
    e = engine(mx88())
    assert e.format_command("bass_set", zone=1, level=-7) is not None
    assert "BS00" in str(e.format_command("bass_set", zone=1, level=-7))
    assert "BS12" in str(e.format_command("bass_set", zone=1, level=5))


def test_xoir_levels_skip_minus_one() -> None:
    levels = engine("AMC XOir").tone_levels
    assert levels is not None
    assert -1 not in levels
    assert (min(levels), max(levels)) == (-12, 12)


# ─── E ───────────────────────────────────────────────────────────────────────


def test_power_starts_unknown_on_real_connections() -> None:
    assert ZoneState().power_known is False
    conn = AsyncSerialConnection(port="x", engine=engine(AMC), demo_mode=False)
    assert not any(z.power_known for z in conn.zones.values())


def test_status_reply_makes_power_known() -> None:
    conn = AsyncSerialConnection(port="x", engine=engine(AMC), demo_mode=False)
    conn._process_response("ZN01,SRC00,GRP0,VOL-62")
    assert conn.zones[1].power_known
    assert conn.zones[1].power is False


def test_demo_state_is_known_from_the_start() -> None:
    conn = AsyncSerialConnection(port="demo", engine=engine(AMC), demo_mode=True)
    assert all(z.power_known for z in conn.zones.values())


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def _setup(hass: HomeAssistant, name: str) -> tuple[str, object]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        title=name,
        data={"port": "demo", "device_profile": name, "num_zones": 6, "num_sources": 8},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    eid = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "media_player"
    )[0]
    return eid, entry.runtime_data


async def test_unknown_power_does_not_block_tone(hass: HomeAssistant) -> None:
    eid, manager = await _setup(hass, AMC)
    manager.zones[1].power_known = False  # type: ignore[attr-defined]  # never polled
    await hass.services.async_call(
        DOMAIN, "set_bass", {"entity_id": eid, "level": 4}, blocking=True
    )


async def test_known_off_zone_still_blocked(hass: HomeAssistant) -> None:
    eid, _ = await _setup(hass, AMC)
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": eid, "level": 4}, blocking=True
        )
    assert excinfo.value.translation_key == "zone_off_tone"


async def test_odd_level_accepted_on_offset_profile(hass: HomeAssistant) -> None:
    eid, _ = await _setup(hass, mx88())
    await hass.services.async_call(
        DOMAIN, "set_bass", {"entity_id": eid, "level": -7}, blocking=True
    )
