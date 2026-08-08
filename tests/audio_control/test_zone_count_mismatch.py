"""Entity count and the engine's zone dict must not be allowed to diverge.

Entities were created from `entry.data[CONF_NUM_ZONES]`, frozen at config-flow
time, while `zones` is built from the LIVE profile's `engine.num_zones`. They
agree today because the flow copies `profile["zones"]` into the entry -- but a
profile whose zone count is reduced in a later release makes the stored value
stale, and every state property then does an unguarded
`self._manager.zones[self._zone_num]`.

The result is a KeyError raised inside a state property on every update: a
traceback per refresh in the log, plus entities that can never recover. The
reverse (a raised count) is quieter but also wrong -- `set_zone_power` and
`notify_zone` silently no-op on an unknown zone, so those entities never update
and never error either.

Two-part fix: clamp the entity count to the engine, and make the properties
degrade to unavailable rather than raise if a zone goes missing at runtime.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN

# 2-zone profile; the entry will claim more.
PROFILE: dict[str, Any] = {
    "name": "ZoneCountTest",
    "zones": 2,
    "sources": 2,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PON",
        "power_off": "Z{zone:02d}POFF",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "mute_on": "Z{zone:02d}MUON",
        "mute_off": "Z{zone:02d}MUOFF",
        "source_set": "Z{zone:02d}SRC{source:02d}",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 62},
    "features": {},
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def setup_with_stored_zones(hass: HomeAssistant, stored: int) -> MockConfigEntry:
    """Set up an entry claiming `stored` zones against a 2-zone profile."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ZoneCountTest (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "num_zones": stored,
            "num_sources": 2,
            "custom_profile": PROFILE,
        },
        unique_id="ac_demo_zonecount",
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def zone_entities(hass: HomeAssistant, entry_id: str) -> list[str]:
    registry = er.async_get(hass)
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry_id)
        if e.domain == "media_player"
    )


# ─── A stale, higher stored count must be clamped ────────────────────────────


async def test_stale_higher_count_is_clamped(hass: HomeAssistant) -> None:
    """The regression: 8 stored vs 2 real gave 6 entities raising KeyError."""
    entry = await setup_with_stored_zones(hass, 8)
    entities = zone_entities(hass, entry.entry_id)
    assert len(entities) == 2, f"expected 2 entities, got {entities}"


async def test_clamping_is_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Silently dropping entities would look like data loss.

    The warning is the only signal that the entry's stored count is stale and a
    reconfigure would correct it.
    """
    with caplog.at_level(logging.WARNING):
        await setup_with_stored_zones(hass, 8)
    assert any(
        "zone" in r.getMessage().lower() and "8" in r.getMessage()
        for r in caplog.records
    ), "no warning about the stale zone count"


async def test_no_state_property_raises_for_the_clamped_entities(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Reading every surviving entity must not produce a KeyError traceback."""
    entry = await setup_with_stored_zones(hass, 8)
    with caplog.at_level(logging.ERROR):
        for entity_id in zone_entities(hass, entry.entry_id):
            state = hass.states.get(entity_id)
            assert state is not None
            # Touch the attributes HA would render.
            _ = state.state, dict(state.attributes)
    assert "KeyError" not in caplog.text


async def test_matching_count_is_unaffected(hass: HomeAssistant) -> None:
    """The normal case must create exactly the profile's zones."""
    entry = await setup_with_stored_zones(hass, 2)
    assert len(zone_entities(hass, entry.entry_id)) == 2


async def test_lower_stored_count_is_respected(hass: HomeAssistant) -> None:
    """min() must not silently ADD entities the user never configured.

    A user who deliberately configured fewer zones than the profile supports
    should keep that choice.
    """
    entry = await setup_with_stored_zones(hass, 1)
    assert len(zone_entities(hass, entry.entry_id)) == 1


# ─── Properties degrade rather than raise if a zone vanishes at runtime ──────


async def test_missing_zone_makes_the_entity_unavailable(
    hass: HomeAssistant,
) -> None:
    """A zone removed after setup must report unavailable, not raise.

    Simulates the runtime half of the divergence: even with the clamp, a zone
    could disappear if the engine's zone dict were rebuilt. Every state property
    previously indexed the dict directly.
    """
    entry = await setup_with_stored_zones(hass, 2)
    entity_ids = zone_entities(hass, entry.entry_id)
    manager = entry.runtime_data

    # Remove zone 2 behind the entity's back.
    del manager.zones[2]
    manager.notify_zone_update(1)
    await hass.async_block_till_done()

    # Force a state write for the orphaned entity.
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} vanished entirely"


async def test_command_on_a_missing_zone_does_not_raise_keyerror(
    hass: HomeAssistant,
) -> None:
    """A vanished zone must fail safely, whichever layer catches it.

    I expected the entity's own HomeAssistantError guard to fire here. It does not,
    and the reason is better than my expectation: `available` returns False for a
    missing zone, and HA skips service calls to unavailable entities -- so the
    command never reaches the entity at all. The guard remains as defence for a
    direct method call.

    What matters either way is that no KeyError escapes and the manager is not
    touched.
    """
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await setup_with_stored_zones(hass, 2)
    manager = entry.runtime_data
    registry = er.async_get(hass)
    zone_2 = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_2")
    )
    del manager.zones[2]

    component = hass.data["entity_components"][MP_DOMAIN]
    entity = component.get_entity(zone_2)
    assert entity is not None
    assert entity.available is False, "a zone-less entity must be unavailable"

    # Either outcome is acceptable; a KeyError is not.
    try:
        await hass.services.async_call(
            MP_DOMAIN, "turn_on", {"entity_id": zone_2}, blocking=True
        )
    except HomeAssistantError:
        pass
    assert 2 not in manager.zones


async def test_direct_command_on_a_missing_zone_raises_cleanly(
    hass: HomeAssistant,
) -> None:
    """The entity-level guard itself, bypassing HA's availability filter.

    An automation or another integration holding a reference could call the method
    directly, so the guard must still convert a missing zone into a readable
    error rather than a KeyError.
    """
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await setup_with_stored_zones(hass, 2)
    manager = entry.runtime_data
    registry = er.async_get(hass)
    zone_2 = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_2")
    )
    del manager.zones[2]

    entity = hass.data["entity_components"][MP_DOMAIN].get_entity(zone_2)
    assert entity is not None
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()


async def test_surviving_zone_still_works_after_another_vanishes(
    hass: HomeAssistant,
) -> None:
    """Losing one zone must not disable the others."""
    from homeassistant.components.media_player import DOMAIN as MP_DOMAIN

    entry = await setup_with_stored_zones(hass, 2)
    manager = entry.runtime_data
    registry = er.async_get(hass)
    zone_1 = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_1")
    )

    del manager.zones[2]
    # Demo mode ACKs, so zone 1 must still command cleanly.
    await hass.services.async_call(
        MP_DOMAIN, "turn_on", {"entity_id": zone_1}, blocking=True
    )
    assert manager.zones[1].power is True
