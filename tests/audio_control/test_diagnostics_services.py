"""Tests for diagnostics, binary_sensor, and services platforms.

Uses real HA fixtures via pytest-homeassistant-custom-component.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.binary_sensor import DOMAIN as BS_DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "audio_control"

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
        "bass_set": "Z{zone:02d}BAS{sign}{level}",
        "treble_set": "Z{zone:02d}TRB{sign}{level}",
        "all_off": "ALLOFF",
        "group_on": "GRP{source:02d}",
        "group_off": "GRPOFF",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2}),PWR(?P<power>\d),SRC(?P<source>\d{2}),VOL(?P<volume>\d{2}),MUT(?P<mute>\d)",
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
        "has_tone_controls": True,
        "has_balance": False,
        "has_group_mode": True,
        "has_all_off": True,
        "unsolicited_updates": False,
    },
}


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Enable custom integrations."""


@pytest.fixture
async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Set up integration with test profile."""
    entry = MockConfigEntry(
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
            "source_names": {1: "CD", 2: "TV", 3: "Vinyl", 4: "BT"},
            "zone_names": {1: "Living", 2: "Kitchen"},
        },
        unique_id="ac_demo_test",
        version=2,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


class TestBinarySensor:
    """Test the connection status binary sensor."""

    @pytest.mark.asyncio
    async def test_connection_sensor_created(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """Binary sensor entity is created."""
        states = hass.states.async_all(BS_DOMAIN)
        assert len(states) == 1
        assert "connection" in states[0].entity_id

    @pytest.mark.asyncio
    async def test_connection_sensor_on_in_demo(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """Connection sensor is ON in demo mode (always connected)."""
        states = hass.states.async_all(BS_DOMAIN)
        assert states[0].state == "on"

    @pytest.mark.asyncio
    async def test_connection_sensor_attributes(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """Sensor has diagnostic attributes."""
        states = hass.states.async_all(BS_DOMAIN)
        attrs = states[0].attributes
        assert attrs["demo_mode"] is True
        assert "device_class" in attrs


class TestDiagnostics:
    """Test the diagnostics platform."""

    @pytest.mark.asyncio
    async def test_diagnostics_output(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """Diagnostics returns expected structure."""
        from custom_components.audio_control.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        result = await async_get_config_entry_diagnostics(hass, setup_entry)

        # Check structure
        assert "config_entry" in result
        assert "options" in result
        assert "connection" in result
        assert "device" in result
        assert "zone_states" in result

        # Port is redacted
        assert result["config_entry"]["port"] == "**REDACTED**"

        # Connection info
        assert result["connection"]["connected"] is True
        assert result["connection"]["demo_mode"] is True

        # Device info
        assert result["device"]["zones"] == 2
        assert result["device"]["sources"] == 4
        assert result["device"]["baud_rate"] == 9600

        # Zone states (2 zones)
        assert "1" in result["zone_states"]
        assert "2" in result["zone_states"]
        assert "power" in result["zone_states"]["1"]
        assert "volume" in result["zone_states"]["1"]


class TestServices:
    """Test custom service calls."""

    @pytest.mark.asyncio
    async def test_all_zones_off(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """all_zones_off service executes without error."""
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)
        # Demo mode: command always succeeds, no error raised

    @pytest.mark.asyncio
    async def test_group_mode_on(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """group_mode_on service executes with source parameter."""
        await hass.services.async_call(
            DOMAIN, "group_mode_on", {"source": 2}, blocking=True
        )

    @pytest.mark.asyncio
    async def test_group_mode_off(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """group_mode_off service executes."""
        await hass.services.async_call(DOMAIN, "group_mode_off", {}, blocking=True)

    @pytest.mark.asyncio
    async def test_services_registered(
        self, hass: HomeAssistant, setup_entry: MockConfigEntry
    ) -> None:
        """All 5 services are registered."""
        assert hass.services.has_service(DOMAIN, "set_bass")
        assert hass.services.has_service(DOMAIN, "set_treble")
        assert hass.services.has_service(DOMAIN, "all_zones_off")
        assert hass.services.has_service(DOMAIN, "group_mode_on")
        assert hass.services.has_service(DOMAIN, "group_mode_off")
