"""Regressions for the 2026-11 multi-model code review of v2.0.3..v2.0.6.

Each test names the finding it pins down. Real AMC replies are from the X86i
capture (see test_amc_x86i_hardware_replies.py).
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

RTI = "RTI AD-810-100 / AD-46-100"
AMC = "AMC X86 / X86i"


def engine(name: str):
    return create_engine(load_builtin_profiles()[name])


# ─── J1: JSON multi-item reply must not mix zones ────────────────────────────


def test_json_multi_item_reply_keeps_zone_and_value_together() -> None:
    r = engine(RTI).parse_response(
        '{"type":"set_outputvol","status":901,'
        '"value":[{"index":1,"value":40},{"index":2,"value":70}]}'
    )
    assert r is not None
    # Before: zone 2 with volume 40 (zone 1's value written into zone 2).
    assert (r["zone"], r["volume"]) == (1, 40)


def test_json_all_zones_item_is_not_preferred() -> None:
    r = engine(RTI).parse_response(
        '{"type":"set_outputvol","status":901,'
        '"value":[{"index":0,"value":10},{"index":3,"value":55}]}'
    )
    assert r is not None
    assert (r["zone"], r["volume"]) == (3, 55)


def test_json_multi_item_end_to_end_writes_the_right_zone() -> None:
    conn = AsyncSerialConnection(port="demo", engine=engine(RTI), demo_mode=True)
    before = conn.zones[2].volume
    conn._process_response(
        '{"type":"set_outputvol","status":901,'
        '"value":[{"index":1,"value":40},{"index":2,"value":70}]}'
    )
    assert conn.zones[1].volume == 40
    assert conn.zones[2].volume == before


@pytest.mark.parametrize("bad_type", ["[1]", '{"a":1}'])
def test_json_unhashable_type_does_not_raise(bad_type: str) -> None:
    r = engine(RTI).parse_response(f'{{"type":{bad_type},"status":200,"value":true}}')
    assert r is not None


# ─── P1/P2 and reply prefix: AMC family profiles ─────────────────────────────


@pytest.mark.parametrize("name", [AMC, "AMC XO", "AMC XOir"])
def test_amc_family_records_bass_and_treble(name: str) -> None:
    r = engine(name).parse_response("ZN01,BASS+4,TREB-6")
    assert r is not None
    assert (r["bass"], r["treble"]) == (4, -6)


@pytest.mark.parametrize("name", [AMC, "AMC XO", "AMC XOir"])
def test_off_zone_does_not_record_source_zero(name: str) -> None:
    r = engine(name).parse_response("ZN01,SRC00,GRP0,VOL-62")
    assert r is not None
    assert r["power"] is False
    assert "source" not in r


def test_off_zone_keeps_last_real_source_end_to_end() -> None:
    conn = AsyncSerialConnection(port="demo", engine=engine(AMC), demo_mode=True)
    conn._process_response("ZN01,SRC03,GRP0,VOL-30")
    conn._process_response("ZN01,SRC00,GRP0,VOL-62")
    assert conn.zones[1].power is False
    assert conn.zones[1].source == 3


@pytest.mark.parametrize("name", [AMC, "AMC XO", "AMC XOir"])
def test_replies_with_z_fallback_prefix_parse(name: str) -> None:
    r = engine(name).parse_response("Z01,SRC03,GRP0,VOL-30")
    assert r is not None
    assert (r["zone"], r["source"], r["power"]) == (1, 3, True)


# ─── T1/T2: tone service over multi-zone targets ─────────────────────────────


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def _setup_amc(hass: HomeAssistant) -> list[str]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        title=AMC,
        data={"port": "demo", "device_profile": AMC, "num_zones": 6, "num_sources": 8},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "media_player"
    )


async def test_one_off_zone_does_not_block_the_others(hass: HomeAssistant) -> None:
    z1, z2 = (await _setup_amc(hass))[:2]
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": z2}, blocking=True
    )
    manager = next(iter(hass.config_entries.async_entries(DOMAIN))).runtime_data
    sent: list[tuple[str, int]] = []
    original = manager.async_send_command

    async def spy(command: str, **kw: object) -> bool:
        if command == "bass_set":
            sent.append((command, int(kw["zone"])))  # type: ignore[arg-type]
        return await original(command, **kw)

    manager.async_send_command = spy  # type: ignore[method-assign]
    # z1 (zone 1) is OFF and listed FIRST: it used to abort before zone 2.
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": [z1, z2], "level": 4}, blocking=True
        )
    assert excinfo.value.translation_key == "zone_off_tone"
    assert sent == [("bass_set", 2)], "the ON zone must still be commanded"


async def test_target_without_audio_control_zones_is_an_error(
    hass: HomeAssistant,
) -> None:
    await _setup_amc(hass)
    empty = ar.async_get(hass).async_create("Garage")
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"area_id": empty.id, "level": 4}, blocking=True
        )
    assert excinfo.value.translation_key == "no_target_zones"
