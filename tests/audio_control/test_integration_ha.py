"""Integration tests using pytest-homeassistant-custom-component.

These tests exercise the full HA lifecycle: config entry setup, entity creation,
state updates, and unload. They use real HA fixtures (hass, MockConfigEntry).
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_SET,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "audio_control"

# Minimal test profile (AMC-like)
TEST_PROFILE: dict[str, Any] = {
    "name": "Test Device",
    "manufacturer": "Test",
    "zones": 2,
    "sources": 4,
    "serial": {
        "baud_rate": 9600,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "command_prefix": "",
        "command_suffix": "\\r",
        "response_prefix": "",
        "response_terminator": "\\r",
        "command_delay_ms": 50,
    },
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PON",
        "power_off": "Z{zone:02d}POFF",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "volume_up": "Z{zone:02d}VU",
        "volume_down": "Z{zone:02d}VD",
        "mute_on": "Z{zone:02d}MUON",
        "mute_off": "Z{zone:02d}MUOFF",
        "source_set": "Z{zone:02d}SRC{source:02d}",
    },
    "response": {
        "status_pattern": (
            r"Z(?P<zone>\d{2}),"
            r"PWR(?P<power>\d),"
            r"SRC(?P<source>\d{2}),"
            r"VOL(?P<volume>\d{2}),"
            r"MUT(?P<mute>\d)"
        ),
        "error_response": "ERR",
        "mapping": {
            "power": {"field": "power", "type": "bool", "on_value": "1"},
            "mute": {"field": "mute", "type": "bool", "on_value": "1"},
            "volume": {"field": "volume", "type": "int"},
            "source": {"field": "source", "type": "int"},
        },
    },
    "volume": {"min": 0, "max": 30, "inverted": False},
    "features": {
        "has_tone_controls": False,
        "has_balance": False,
        "has_group_mode": False,
        "has_all_off": False,
        "unsolicited_updates": False,
    },
}


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Enable custom integrations for all tests in this module."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Device (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "baud_rate": 9600,
            "num_zones": 2,
            "num_sources": 4,
            "custom_profile": TEST_PROFILE,
        },
        options={
            "source_names": {1: "CD", 2: "TV", 3: "Vinyl", 4: "Bluetooth"},
            "zone_names": {1: "Living Room", 2: "Kitchen"},
        },
        unique_id="ac_demo",
    )


class TestIntegrationSetup:
    """Test config entry setup and teardown."""

    @pytest.mark.asyncio
    async def test_setup_entry_demo_mode(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that the integration sets up in demo mode."""
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert result is True
        assert mock_config_entry.state.value == "loaded"

    @pytest.mark.asyncio
    async def test_setup_creates_entities(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that zone entities are created."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Should have 2 zone entities
        states = hass.states.async_all(MP_DOMAIN)
        assert len(states) == 2

    @pytest.mark.asyncio
    async def test_entity_names(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that entity names include profile and zone names."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        states = hass.states.async_all(MP_DOMAIN)
        names = sorted(s.name for s in states)
        assert "Test Device Living Room" in names
        assert "Test Device Kitchen" in names

    @pytest.mark.asyncio
    async def test_initial_state_is_off(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that zones start in OFF state (demo mode)."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        states = hass.states.async_all(MP_DOMAIN)
        for state in states:
            assert state.state == MediaPlayerState.OFF

    @pytest.mark.asyncio
    async def test_unload_entry(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that unloading the entry works."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        assert result is True
        assert mock_config_entry.state.value == "not_loaded"


class TestEntityBehavior:
    """Test media player entity behavior."""

    @pytest.fixture(autouse=True)
    async def setup_entry(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        enable_custom_integrations: None,
    ) -> None:
        """Set up the integration for each test."""
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    @pytest.mark.asyncio
    async def test_turn_on(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test turning on a zone."""
        states = hass.states.async_all(MP_DOMAIN)
        entity_id = states[0].entity_id

        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == MediaPlayerState.ON

    @pytest.mark.asyncio
    async def test_turn_off(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test turning off a zone."""
        states = hass.states.async_all(MP_DOMAIN)
        entity_id = states[0].entity_id

        # Turn on first
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Now turn off
        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == MediaPlayerState.OFF

    @pytest.mark.asyncio
    async def test_source_list(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test that source list matches config."""
        states = hass.states.async_all(MP_DOMAIN)
        entity_id = states[0].entity_id
        state = hass.states.get(entity_id)
        assert state is not None
        source_list = state.attributes.get("source_list")
        assert source_list == ["CD", "TV", "Vinyl", "Bluetooth"]

    @pytest.mark.asyncio
    async def test_volume_set(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Test setting volume."""
        states = hass.states.async_all(MP_DOMAIN)
        entity_id = states[0].entity_id

        await hass.services.async_call(
            MP_DOMAIN,
            SERVICE_VOLUME_SET,
            {ATTR_ENTITY_ID: entity_id, "volume_level": 0.5},
            blocking=True,
        )
        await hass.async_block_till_done()
        # Demo mode: command succeeds but doesn't update state
        # (no serial response to parse), so we just verify no error
        state = hass.states.get(entity_id)
        assert state is not None
