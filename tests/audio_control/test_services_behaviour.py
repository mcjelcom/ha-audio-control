"""Behavioural tests for the audio_control services.

The pre-existing service tests called each service and asserted nothing ("no
error raised"), so they would pass with empty handler bodies. services.py sat at
51% coverage with every error branch dark. These tests assert what the device
actually receives and cover the failure paths a user can hit from the UI.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN

TONE_PROFILE: dict[str, Any] = {
    "name": "ToneCapable",
    "zones": 2,
    "sources": 4,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PWR01",
        "power_off": "Z{zone:02d}PWR00",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "mute_on": "Z{zone:02d}MUT01",
        "mute_off": "Z{zone:02d}MUT00",
        "source_set": "Z{zone:02d}SRC{source:02d}",
        "bass_set": "Z{zone:02d}BAS{sign}{level}",
        "treble_set": "Z{zone:02d}TRB{sign}{level}",
        "all_off": "ZALLOFF",
        "group_on": "ZALLGRP{source:02d}",
        "group_off": "ZALLGRP00",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 62, "inverted": True},
    "features": {
        "has_tone_controls": True,
        "has_group_mode": True,
        "has_all_off": True,
    },
}

# Same device, but without tone/group/all-off support.
NO_FEATURES_PROFILE: dict[str, Any] = {
    **TONE_PROFILE,
    "name": "NoFeatures",
    "features": {
        "has_tone_controls": False,
        "has_group_mode": False,
        "has_all_off": False,
    },
}


def make_entry(profile: dict[str, Any], unique: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"{profile['name']} (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "baud_rate": 9600,
            "num_zones": 2,
            "num_sources": 4,
            "custom_profile": profile,
        },
        options={
            "source_names": {1: "CD", 2: "TV", 3: "Vinyl", 4: "BT"},
            "zone_names": {1: "Living", 2: "Kitchen"},
        },
        unique_id=unique,
        version=3,
    )


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


@pytest.fixture
async def tone_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = make_entry(TONE_PROFILE, "ac_demo_tone")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def plain_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = make_entry(NO_FEATURES_PROFILE, "ac_demo_plain")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def zone_entity(hass: HomeAssistant, zone: int, entry_id: str | None = None) -> str:
    """Entity id for a zone, resolved via the registry's unique_id.

    Entity ids are slugified from "{profile} {zone name}" (e.g.
    media_player.tonecapable_living), so they cannot be derived from the zone
    number. The unique_id (ac_{entry}_zone_{n}) is the reliable key.
    """
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        if entity.platform != DOMAIN or entity.domain != "media_player":
            continue
        if entry_id and entity.config_entry_id != entry_id:
            continue
        if entity.unique_id.endswith(f"_zone_{zone}"):
            return entity.entity_id
    ids = [e.unique_id for e in registry.entities.values() if e.platform == DOMAIN]
    msg = f"no media_player for zone {zone}; unique_ids: {ids}"
    raise AssertionError(msg)


# ─── set_bass / set_treble send the right command ────────────────────────────


@pytest.mark.parametrize(
    ("service", "command"), [("set_bass", "bass_set"), ("set_treble", "treble_set")]
)
async def test_tone_service_sends_signed_level(
    hass: HomeAssistant,
    tone_entry: MockConfigEntry,
    service: str,
    command: str,
) -> None:
    """The SIGNED level must reach the engine, not a pre-mangled magnitude.

    services.py used to send abs(level) plus a separate sign kwarg, which made
    boost and cut identical on most profiles.
    """
    entity_id = zone_entity(hass, 1)
    manager = tone_entry.runtime_data
    with patch.object(
        manager, "async_send_command", new=AsyncMock(return_value=True)
    ) as send:
        await hass.services.async_call(
            DOMAIN, service, {"entity_id": entity_id, "level": -6}, blocking=True
        )
    send.assert_awaited_once()
    assert send.await_args is not None
    assert send.await_args.args[0] == command
    assert send.await_args.kwargs["level"] == -6


async def test_tone_service_rejects_unsupported_device(
    hass: HomeAssistant, plain_entry: MockConfigEntry
) -> None:
    """A device without tone controls must say so, not "check your connection".

    Previously the command was sent regardless, format_command returned None, and
    the user got command_failed -- which actively misdirects.
    """
    entity_id = zone_entity(hass, 1)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": entity_id, "level": 4}, blocking=True
        )
    assert err.value.translation_key == "feature_unsupported"


async def test_tone_service_rejects_unknown_entity(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """A non-audio_control entity_id must raise not_valid_zone."""
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_bass",
            {"entity_id": "media_player.not_ours", "level": 0},
            blocking=True,
        )
    assert err.value.translation_key == "not_valid_zone"


async def test_tone_service_raises_when_device_rejects(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """A NAK from the device must surface as command_failed."""
    entity_id = zone_entity(hass, 1)
    manager = tone_entry.runtime_data
    with (
        patch.object(manager, "async_send_command", new=AsyncMock(return_value=False)),
        pytest.raises(HomeAssistantError) as err,
    ):
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": entity_id, "level": 2}, blocking=True
        )
    assert err.value.translation_key == "command_failed"


async def test_tone_service_applies_to_multiple_entities(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """A list of entity_ids must each get a command."""
    ids = [zone_entity(hass, 1), zone_entity(hass, 2)]
    manager = tone_entry.runtime_data
    with patch.object(
        manager, "async_send_command", new=AsyncMock(return_value=True)
    ) as send:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": ids, "level": 0}, blocking=True
        )
    assert send.await_count == 2


# ─── Global services ─────────────────────────────────────────────────────────


async def test_all_zones_off_sends_all_off(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """Asserts the actual command, unlike the old "no error raised" test."""
    manager = tone_entry.runtime_data
    with patch.object(
        manager, "async_send_command", new=AsyncMock(return_value=True)
    ) as send:
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)
    send.assert_awaited_once()
    assert send.await_args is not None
    assert send.await_args.args[0] == "all_off"


async def test_group_mode_on_passes_source(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    manager = tone_entry.runtime_data
    with patch.object(
        manager, "async_send_command", new=AsyncMock(return_value=True)
    ) as send:
        await hass.services.async_call(
            DOMAIN, "group_mode_on", {"source": 3}, blocking=True
        )
    assert send.await_args is not None
    assert send.await_args.args[0] == "group_on"
    assert send.await_args.kwargs["source"] == 3


async def test_group_mode_off_sends_group_off(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    manager = tone_entry.runtime_data
    with patch.object(
        manager, "async_send_command", new=AsyncMock(return_value=True)
    ) as send:
        await hass.services.async_call(DOMAIN, "group_mode_off", {}, blocking=True)
    assert send.await_args is not None
    assert send.await_args.args[0] == "group_off"


async def test_global_service_skips_devices_without_the_feature(
    hass: HomeAssistant, plain_entry: MockConfigEntry
) -> None:
    """A device with has_all_off False must report feature_unsupported.

    Sending anyway produced a misleading command_failed.
    """
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)
    assert err.value.translation_key == "feature_unsupported"


async def test_global_service_reaches_every_capable_device(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """With two amplifiers configured, all_zones_off must silence BOTH.

    It previously picked whichever entry HA enumerated first, so one device kept
    playing and the ordering was unstable across restarts.
    """
    second = make_entry(TONE_PROFILE, "ac_demo_tone2")
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with (
        patch.object(
            tone_entry.runtime_data,
            "async_send_command",
            new=AsyncMock(return_value=True),
        ) as first_send,
        patch.object(
            second.runtime_data, "async_send_command", new=AsyncMock(return_value=True)
        ) as second_send,
    ):
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)

    first_send.assert_awaited_once()
    second_send.assert_awaited_once()


# ─── Registration / teardown ─────────────────────────────────────────────────


async def test_all_services_registered(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    for name in (
        "set_bass",
        "set_treble",
        "all_zones_off",
        "group_mode_on",
        "group_mode_off",
    ):
        assert hass.services.has_service(DOMAIN, name), f"{name} not registered"


async def test_level_out_of_range_is_rejected_by_schema(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """The schema restricts level to even values in -8..+8.

    Rejection happens before the handler runs, so no command reaches the device.
    """
    entity_id = zone_entity(hass, 1)
    manager = tone_entry.runtime_data
    with (
        patch.object(
            manager, "async_send_command", new=AsyncMock(return_value=True)
        ) as send,
        pytest.raises(vol.Invalid),
    ):
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": entity_id, "level": 99}, blocking=True
        )
    send.assert_not_awaited()


async def test_odd_level_is_rejected_by_schema(
    hass: HomeAssistant, tone_entry: MockConfigEntry
) -> None:
    """Only even steps are valid (-8, -6, -4, -2, 0, 2, 4, 6, 8)."""
    entity_id = zone_entity(hass, 1)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": entity_id, "level": 3}, blocking=True
        )
