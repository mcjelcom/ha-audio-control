"""Tests for the Audio Control config flow.

Covers: user step, custom wizard (4 steps), reconfigure, options flow,
abort on duplicate, and error handling.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "audio_control"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Enable custom integrations."""


@pytest.fixture
def mock_serial_ports() -> Any:
    """Mock serial port discovery to return predictable ports."""
    with patch(
        "custom_components.audio_control.config_flow._list_serial_ports",
        return_value=["/dev/ttyUSB0", "/dev/ttyUSB1"],
    ):
        yield


@pytest.fixture
def mock_serial_test_ok() -> Any:
    """Mock serial port test to always succeed."""
    with patch(
        "custom_components.audio_control.config_flow._test_port",
        return_value=None,
    ):
        yield


@pytest.fixture
def mock_serial_test_fail() -> Any:
    """Mock serial port test to fail."""
    with patch(
        "custom_components.audio_control.config_flow._test_port",
        return_value="Permission denied for /dev/ttyUSB0",
    ):
        yield


class TestUserStep:
    """Test the initial user step (profile + port selection)."""

    @pytest.mark.asyncio
    async def test_form_shown(
        self, hass: HomeAssistant, mock_serial_ports: Any
    ) -> None:
        """Test that the form is shown on first access."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_create_entry_with_builtin_profile(
        self,
        hass: HomeAssistant,
        mock_serial_ports: Any,
        mock_serial_test_ok: Any,
    ) -> None:
        """Test successful entry creation with a built-in profile."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": "AMC X86 / X86i",
                "port": "/dev/ttyUSB0",
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "AMC X86 / X86i"
        assert result["data"]["port"] == "/dev/ttyUSB0"
        assert result["data"]["device_profile"] == "AMC X86 / X86i"
        assert result["data"]["num_zones"] == 6
        assert result["data"]["num_sources"] == 8
        assert result["data"]["baud_rate"] == 38400

    @pytest.mark.asyncio
    async def test_create_entry_demo_mode(
        self, hass: HomeAssistant, mock_serial_ports: Any
    ) -> None:
        """Test entry creation in demo mode (no serial port test)."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": "AMC X86 / X86i",
                "port": "demo",
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "AMC X86 / X86i (Demo)"
        assert result["data"]["port"] == "demo"

    @pytest.mark.asyncio
    async def test_error_cannot_connect(
        self,
        hass: HomeAssistant,
        mock_serial_ports: Any,
        mock_serial_test_fail: Any,
    ) -> None:
        """Test error shown when serial port test fails."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": "AMC X86 / X86i",
                "port": "/dev/ttyUSB0",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_abort_already_configured(
        self,
        hass: HomeAssistant,
        mock_serial_ports: Any,
        mock_serial_test_ok: Any,
    ) -> None:
        """Test abort when same port is already configured."""
        # Create an existing entry
        existing = MockConfigEntry(
            domain=DOMAIN,
            unique_id="ac_/dev/ttyUSB0",
            data={"port": "/dev/ttyUSB0"},
        )
        existing.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": "AMC X86 / X86i",
                "port": "/dev/ttyUSB0",
            },
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


class TestCustomWizard:
    """Test the 4-step custom device wizard."""

    @pytest.mark.asyncio
    async def test_custom_wizard_full_flow(
        self, hass: HomeAssistant, mock_serial_ports: Any
    ) -> None:
        """Test complete custom device wizard from start to entry creation."""
        # Step 1: User selects custom device
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": ">> Custom Device (define via UI)",
                "port": "demo",
            },
        )
        # Should advance to custom_basic
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_basic"

        # Step 2: Basic info
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_name": "My Amp",
                "zones": 4,
                "sources": 6,
                "baud_rate": 9600,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_serial"

        # Step 3: Serial framing
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "command_prefix": "*",
                "command_suffix": "\\r",
                "response_prefix": "#",
                "response_terminator": "\\r",
                "command_delay_ms": 200,
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_commands"

        # Step 4: Commands
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "status": "Z{zone:02d}STA",
                "power_on": "Z{zone:02d}PON",
                "power_off": "Z{zone:02d}POFF",
                "volume_set": "Z{zone:02d}VOL{volume:02d}",
                "volume_up": "Z{zone:02d}VU",
                "volume_down": "Z{zone:02d}VD",
                "mute_on": "Z{zone:02d}MU1",
                "mute_off": "Z{zone:02d}MU0",
                "source_set": "Z{zone:02d}SRC{source:02d}",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "custom_response"

        # Step 5: Response parsing → creates entry
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "status_pattern": r"Z(?P<zone>\d{2}) PWR(?P<power>\d) SRC(?P<source>\d{2}) VOL(?P<volume>\d{2}) MUT(?P<mute>\d)",
                "volume_min": 0,
                "volume_max": 50,
                "volume_inverted": False,
                "error_response": "ERR",
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "My Amp (Demo)"
        assert result["data"]["device_profile"] == "__custom__"
        assert result["data"]["num_zones"] == 4
        assert result["data"]["num_sources"] == 6
        assert result["data"]["custom_profile"]["serial"]["baud_rate"] == 9600
        assert result["data"]["custom_profile"]["serial"]["command_prefix"] == "*"


class TestReconfigureFlow:
    """Test the reconfigure flow (change serial port)."""

    @pytest.mark.asyncio
    async def test_reconfigure_changes_port(
        self,
        hass: HomeAssistant,
        mock_serial_ports: Any,
        mock_serial_test_ok: Any,
    ) -> None:
        """Test successful port change via reconfigure."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="AMC X86 / X86i",
            unique_id="ac_/dev/ttyUSB0",
            data={
                "port": "/dev/ttyUSB0",
                "device_profile": "AMC X86 / X86i",
                "baud_rate": 38400,
                "num_zones": 6,
                "num_sources": 8,
            },
            version=2,
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"port": "/dev/ttyUSB1"},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["port"] == "/dev/ttyUSB1"

    @pytest.mark.asyncio
    async def test_reconfigure_error_on_bad_port(
        self,
        hass: HomeAssistant,
        mock_serial_ports: Any,
        mock_serial_test_fail: Any,
    ) -> None:
        """Test error shown when new port can't be opened."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            unique_id="ac_/dev/ttyUSB0",
            data={"port": "/dev/ttyUSB0", "device_profile": "AMC X86 / X86i"},
            version=2,
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"port": "/dev/ttyUSB1"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


class TestOptionsFlow:
    """Test the options flow (rename zones/sources)."""

    @pytest.mark.asyncio
    async def test_options_flow_renames(
        self, hass: HomeAssistant, enable_custom_integrations: None
    ) -> None:
        """Test renaming zones and sources via options flow."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Test",
            unique_id="ac_demo",
            data={
                "port": "demo",
                "device_profile": "__custom__",
                "baud_rate": 9600,
                "num_zones": 2,
                "num_sources": 2,
                "custom_profile": {
                    "name": "Test",
                    "zones": 2,
                    "sources": 2,
                    "serial": {
                        "baud_rate": 9600,
                        "data_bits": 8,
                        "parity": "none",
                        "stop_bits": 1,
                        "command_delay_ms": 50,
                        "command_prefix": "",
                        "command_suffix": "\\r",
                        "response_prefix": "",
                        "response_terminator": "\\r",
                    },
                    "commands": {
                        "status": "S{zone}",
                        "power_on": "P{zone}1",
                        "power_off": "P{zone}0",
                        "volume_set": "V{zone}{volume}",
                        "mute_on": "M{zone}1",
                        "mute_off": "M{zone}0",
                        "source_set": "I{zone}{source}",
                    },
                    "response": {
                        "status_pattern": "(?P<zone>\\d)(?P<power>\\d)(?P<volume>\\d{2})(?P<mute>\\d)(?P<source>\\d)",
                        "error_response": "?",
                        "mapping": {
                            "power": {
                                "field": "power",
                                "type": "bool",
                                "on_value": "1",
                            },
                            "mute": {"field": "mute", "type": "bool", "on_value": "1"},
                            "volume": {"field": "volume", "type": "int"},
                            "source": {"field": "source", "type": "int"},
                        },
                    },
                    "volume": {"min": 0, "max": 30, "inverted": False},
                    "features": {
                        "has_tone_controls": False,
                        "has_group_mode": False,
                        "has_all_off": False,
                        "has_balance": False,
                        "unsolicited_updates": False,
                    },
                },
            },
            options={
                "source_names": {1: "Source 1", 2: "Source 2"},
                "zone_names": {1: "Zone 1", 2: "Zone 2"},
            },
            version=2,
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "zone_1": "Living Room",
                "zone_2": "Kitchen",
                "source_1": "Turntable",
                "source_2": "TV",
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["zone_names"] == {1: "Living Room", 2: "Kitchen"}
        assert entry.options["source_names"] == {1: "Turntable", 2: "TV"}
