"""Add every shipped profile through the real config flow in demo mode.

`demo` is a first-class port value: connect() marks itself connected without
opening hardware and send_command() returns True, so the whole entity layer runs
without an amplifier. That makes it possible to exercise all 23 profiles through
the actual UI flow -- not just the one AMC X86i that happens to be wired up.

This is the coverage the hardware test could not provide. haac-tw validated one
profile deeply against real serial; this validates the other 22 broadly. The
CRITICAL `sources` crash is the motivating case: five profiles raised TypeError
on Submit and could never be added, and the earlier tests called
`_resolve_sources` directly rather than going through `async_step_user` ->
`async_create_entry` -> `async_setup_entry` the way a user does.

Note `unique_id` is `f"ac_{port}"`, so only one `demo` entry can exist at a time;
each test therefore sets up and tears down its own.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

# The five that raised TypeError on Submit before ce4a883: their `sources` key is
# a mapping rather than an int.
MAPPING_FORM_PROFILES = [
    "Marantz PM7000N / SR Series",
    "Monoprice 31028 (Commercial 70V)",
    "NAD C 368 / C 388",
    "Rotel RA-1572 / RA-1592",
    "Yamaha RX-A / RX-V Series",
]

ALL_PROFILES = sorted(load_builtin_profiles())


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def add_via_flow(hass: HomeAssistant, profile_name: str) -> dict[str, Any]:
    """Add a profile exactly as the UI does: user step, then Submit."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM, result
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_profile": profile_name, CONF_PORT: "demo"},
    )
    await hass.async_block_till_done()
    return result  # type: ignore[no-any-return]


# ─── The five that could never be added ──────────────────────────────────────


@pytest.mark.parametrize("profile_name", MAPPING_FORM_PROFILES)
async def test_mapping_form_profile_can_be_added(
    hass: HomeAssistant, profile_name: str
) -> None:
    """Each of these raised TypeError on Submit before the fix.

    Goes through the real flow rather than calling _resolve_sources directly, so
    it covers the entry-creation seam where the crash actually happened.
    """
    result = await add_via_flow(hass, profile_name)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["data"]["device_profile"] == profile_name
    assert result["data"]["port"] == "demo"
    assert result["data"]["num_sources"] > 0


@pytest.mark.parametrize("profile_name", MAPPING_FORM_PROFILES)
async def test_mapping_form_profile_seeds_real_source_names(
    hass: HomeAssistant, profile_name: str
) -> None:
    """The mapping form carries names, which must reach the entry options.

    Falling back to "Source 1..N" would be a silent regression: the entry would
    load, so only the dropdown contents would reveal the loss.
    """
    result = await add_via_flow(hass, profile_name)
    names = result["options"]["source_names"]
    assert names, "no source names seeded"
    assert not all(v.startswith("Source ") for v in names.values()), (
        f"{profile_name} fell back to generic names: {names}"
    )


# ─── Every profile, end to end ───────────────────────────────────────────────


@pytest.mark.parametrize("profile_name", ALL_PROFILES)
async def test_every_profile_sets_up_in_demo_mode(
    hass: HomeAssistant, profile_name: str
) -> None:
    """All 23 profiles must add, load, and register their zone entities.

    Broad rather than deep: it would catch a profile whose regex fails to
    compile, whose zone count is wrong, or which raises during setup -- none of
    which the single-profile hardware test could reach.
    """
    result = await add_via_flow(hass, profile_name)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result

    # Assert on the state itself. ConfigEntryState.recoverable describes whether
    # a FAILED state is retryable, so it is True for LOADED too -- checking it
    # here would have passed for a broken entry as readily as a working one.
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED, (
        f"{profile_name} did not load: {entry.state}"
    )

    engine = create_engine(load_builtin_profiles()[profile_name])
    registry = er.async_get(hass)
    zones = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player"
    ]
    assert len(zones) == engine.num_zones, (
        f"{profile_name}: {len(zones)} entities for {engine.num_zones} zones"
    )

    # The connection sensor must report connected: demo mode is healthy by
    # definition, and a False here would mean connect() did not take the demo
    # branch.
    sensors = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "binary_sensor"
    ]
    assert len(sensors) == 1
    state = hass.states.get(sensors[0].entity_id)
    assert state is not None
    assert state.state == "on", f"{profile_name}: connection sensor {state.state}"


async def test_demo_port_is_unique(hass: HomeAssistant) -> None:
    """unique_id is f"ac_{port}", so a second demo entry must abort.

    Documents why the tests above each add exactly one entry.
    """
    first = await add_via_flow(hass, "AMC X86 / X86i")
    assert first["type"] is FlowResultType.CREATE_ENTRY

    second = await add_via_flow(hass, "Monoprice 6-Zone")
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"


# ─── Commands succeed in demo mode, so optimistic state persists ─────────────


async def test_commands_apply_optimistically_in_demo_mode(
    hass: HomeAssistant,
) -> None:
    """send_command returns True in demo mode, so state must stick.

    This is the same path the real amp exercised (turn_on 62->30, volume_up
    30->29 on the AMC's inverted scale); demo mode confirms the entity logic
    without hardware, using the same profile.
    """
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    result = await add_via_flow(hass, "AMC X86 / X86i")
    manager = result["result"].runtime_data
    registry = er.async_get(hass)
    eid = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, result["result"].entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_1")
    )

    await hass.services.async_call(
        MP_DOMAIN, "turn_on", {"entity_id": eid}, blocking=True
    )
    assert manager.zones[1].power is True

    # AMC is inverted, so louder means a LOWER device value -- matching the
    # 30 -> 29 observed on real hardware.
    manager.zones[1].volume = 30
    await hass.services.async_call(
        MP_DOMAIN, "volume_up", {"entity_id": eid}, blocking=True
    )
    assert manager.zones[1].volume == 29

    await hass.services.async_call(
        MP_DOMAIN, "volume_down", {"entity_id": eid}, blocking=True
    )
    assert manager.zones[1].volume == 30

    await hass.services.async_call(
        MP_DOMAIN, "turn_off", {"entity_id": eid}, blocking=True
    )
    assert manager.zones[1].power is False
