"""A fresh demo device must start at a sane, silent volume on every profile.

`ZoneState.volume` defaults to 0, which is a raw *device* value -- and its
meaning depends entirely on the profile's scale:

  AMC X86i      0..62 inverted -> raw 0 = 100% volume
  NAD C 368   -80..0  dB       -> raw 0 =   0 dB = 100% volume
  Yamaha      -80..16 dB       -> raw 0 =   0 dB =  83% volume
  Monoprice     0..38          -> raw 0 = silent (the only intuitive case)

On real hardware this self-corrects at the first status poll, which is why it
went unnoticed. Demo mode has no device to poll, so the wrong value is what the
user sees and keeps -- a demo of an AMC or NAD opens showing full volume.

Beyond looking wrong, it is a footgun: someone demoing a profile, then switching
that same entry to real hardware, has a UI already reading 100%.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

# Profiles whose raw 0 does NOT mean silence, i.e. every scale that is inverted
# or has a negative floor.
NON_ZERO_FLOOR_PROFILES = [
    "AMC X86 / X86i",
    "AMC X1616e",
    "AMC XO",
    "AMC XOir",
    "NAD C 368 / C 388",
    "Yamaha RX-A / RX-V Series",
]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def add_demo(hass: HomeAssistant, profile_name: str) -> Any:
    """Add a profile in demo mode through the real config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_profile": profile_name, CONF_PORT: "demo"},
    )
    await hass.async_block_till_done()
    assert result["type"].value == "create_entry", result
    assert result["result"].state is ConfigEntryState.LOADED
    return result["result"]


def zone_entity_ids(hass: HomeAssistant, entry_id: str) -> list[str]:
    registry = er.async_get(hass)
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry_id)
        if e.domain == "media_player"
    )


# ─── Initial demo volume must be silent, not maximum ─────────────────────────


@pytest.mark.parametrize("profile_name", NON_ZERO_FLOOR_PROFILES)
async def test_demo_does_not_start_at_full_volume(
    hass: HomeAssistant, profile_name: str
) -> None:
    """The regression: raw 0 read as 100% on inverted and dB scales."""
    entry = await add_demo(hass, profile_name)
    engine = create_engine(load_builtin_profiles()[profile_name])
    for zone in entry.runtime_data.zones.values():
        ha = engine.device_volume_to_ha(zone.volume)
        assert ha < 0.5, (
            f"{profile_name} demo opens at {ha:.0%} volume (raw {zone.volume})"
        )


@pytest.mark.parametrize("profile_name", sorted(load_builtin_profiles()))
async def test_every_demo_profile_starts_silent_and_off(
    hass: HomeAssistant, profile_name: str
) -> None:
    """Across all profiles: powered off, and at the quiet end of the scale.

    Uses the engine's own conversion rather than comparing raw numbers, since
    "quiet" is 0 on some scales and volume_max on inverted ones.
    """
    entry = await add_demo(hass, profile_name)
    engine = create_engine(load_builtin_profiles()[profile_name])
    span = engine.volume_max - engine.volume_min

    for num, zone in entry.runtime_data.zones.items():
        assert zone.power is False, f"{profile_name} zone {num} starts on"
        assert zone.mute is False, f"{profile_name} zone {num} starts muted"
        assert engine.volume_min <= zone.volume <= engine.volume_max, (
            f"{profile_name} zone {num} raw {zone.volume} outside "
            f"{engine.volume_min}..{engine.volume_max}"
        )
        if span > 0:
            ha = engine.device_volume_to_ha(zone.volume)
            assert ha == 0.0, f"{profile_name} zone {num} starts at {ha:.0%}"


async def test_source_defaults_to_a_valid_source(hass: HomeAssistant) -> None:
    """Source 1 must be in range; source 0 would render as "Source 0"."""
    entry = await add_demo(hass, "AMC X86 / X86i")
    engine = create_engine(load_builtin_profiles()["AMC X86 / X86i"])
    for zone in entry.runtime_data.zones.values():
        assert 1 <= zone.source <= engine.num_sources


# ─── Demo mode is fully controllable ─────────────────────────────────────────


async def test_demo_volume_round_trips_through_the_ui(hass: HomeAssistant) -> None:
    """Setting a level in demo mode must read back as that level.

    The point of demo mode is exercising the UI, so a set/read round trip is the
    core contract. Real hardware self-heals via polling; demo mode has no poll,
    so the optimistic value must be internally consistent on its own.
    """
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await add_demo(hass, "AMC X86 / X86i")
    eid = zone_entity_ids(hass, entry.entry_id)[0]

    # Power on first: MediaPlayerEntity.state_attributes returns early for an
    # OFF entity, so volume_level is absent by design until the zone is on.
    await hass.services.async_call(
        MP_DOMAIN, "turn_on", {"entity_id": eid}, blocking=True
    )
    await hass.async_block_till_done()

    for level in (0.0, 0.25, 0.5, 0.75, 1.0):
        await hass.services.async_call(
            MP_DOMAIN,
            "volume_set",
            {"entity_id": eid, "volume_level": level},
            blocking=True,
        )
        await hass.async_block_till_done()
        state = hass.states.get(eid)
        assert state is not None
        # Round trip is exact to the device's step resolution (1/62 here).
        assert abs(state.attributes["volume_level"] - level) <= 1 / 62, (
            f"set {level} read back {state.attributes['volume_level']}"
        )


async def test_demo_power_and_source_are_controllable(hass: HomeAssistant) -> None:
    """Power and source select must work with no device attached."""
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await add_demo(hass, "AMC X86 / X86i")
    eid = zone_entity_ids(hass, entry.entry_id)[0]

    await hass.services.async_call(
        MP_DOMAIN, "turn_on", {"entity_id": eid}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "on"

    await hass.services.async_call(
        MP_DOMAIN,
        "select_source",
        {"entity_id": eid, "source": "Source 3"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(eid).attributes["source"] == "Source 3"

    await hass.services.async_call(
        MP_DOMAIN, "turn_off", {"entity_id": eid}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "off"


async def test_demo_zones_are_independent(hass: HomeAssistant) -> None:
    """Changing one zone must not disturb another.

    A shared mutable default (one ZoneState reused across zones) would make all
    six move together -- invisible on a single-zone profile.
    """
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await add_demo(hass, "AMC X86 / X86i")
    ids = zone_entity_ids(hass, entry.entry_id)
    assert len(ids) >= 2

    await hass.services.async_call(
        MP_DOMAIN, "turn_on", {"entity_id": ids[0]}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(ids[0]).state == "on"
    assert hass.states.get(ids[1]).state == "off", "zones share state"
