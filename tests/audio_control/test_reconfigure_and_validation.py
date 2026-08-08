"""Reconfigure flow port entry, and validation of the custom-wizard regex.

Two independent defects, both in the config flow:

1. Reconfigure rendered the port field as `vol.In(discovered_ports + ["demo"])`,
   while initial setup rendered it as free-text `str`. A `socket://host:port`
   entry is not in the discovered list, so its OWN current value failed schema
   validation -- the form could not be submitted at all, even unchanged. Network
   transports are a supported, documented configuration.

2. The custom-device wizard accepts `status_pattern` as free text and never
   compiles it. `create_engine()` compiles it at setup time and sits OUTSIDE the
   try/except in async_setup_entry, so a typo'd regex raises `re.error` on every
   load attempt. The entry cannot be loaded to be fixed, and reconfigure only
   edits the port -- so the only recovery is deleting and re-adding the device.
   Validating at submit time, where the user can still see the field, turns a
   dead entry into an inline error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN

SOCKET_PORT = "socket://192.168.1.50:4999"
DISCOVERED = ["/dev/ttyUSB0", "/dev/ttyUSB1"]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


@pytest.fixture
def mock_ports() -> Any:
    """Serial discovery returns only real tty devices, never socket:// URLs."""
    with patch(
        "custom_components.audio_control.config_flow._list_serial_ports",
        return_value=list(DISCOVERED),
    ):
        yield


@pytest.fixture
def port_opens() -> Any:
    """_test_port returns None on success (no error message)."""
    with patch(
        "custom_components.audio_control.config_flow._test_port", return_value=None
    ):
        yield


def network_entry() -> MockConfigEntry:
    """An entry already configured against a network-attached serial bridge."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="AMC X86 / X86i",
        unique_id=f"ac_{SOCKET_PORT}",
        data={"port": SOCKET_PORT, "device_profile": "AMC X86 / X86i"},
        version=3,
    )


# ─── Reconfigure must accept network ports ───────────────────────────────────


async def test_reconfigure_accepts_socket_url(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """A socket:// port must be submittable, matching the initial setup step."""
    entry = network_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_PORT: "socket://192.168.1.99:4999"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["port"] == "socket://192.168.1.99:4999"


async def test_reconfigure_can_resubmit_its_own_current_value(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """The sharpest form of the bug: the pre-filled default was itself invalid.

    vol.In() rejected the value the form had just rendered as the default, so a
    user opening Reconfigure on a network entry could not submit the form even
    without editing anything.
    """
    entry = network_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PORT: SOCKET_PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_accepts_rfc2217_url(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """rfc2217:// is the other documented network scheme."""
    entry = network_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_PORT: "rfc2217://192.168.1.50:4999"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["port"] == "rfc2217://192.168.1.50:4999"


async def test_reconfigure_still_accepts_a_tty_path(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """The ordinary local-serial case must keep working."""
    entry = network_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PORT: "/dev/ttyUSB1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["port"] == "/dev/ttyUSB1"


async def test_reconfigure_still_reports_an_unopenable_port(
    hass: HomeAssistant, mock_ports: Any
) -> None:
    """Dropping vol.In must not drop validation -- _test_port still gates.

    Without this, "accept any string" would be indistinguishable from "accept
    anything without checking", and a typo'd port would produce a dead entry.
    """
    entry = network_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.audio_control.config_flow._test_port",
        return_value="could not open port",
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PORT: "/dev/ttyNOPE"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_to_demo_skips_the_port_check(
    hass: HomeAssistant, mock_ports: Any
) -> None:
    """demo has no hardware to open, so it must bypass _test_port."""
    entry = network_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.audio_control.config_flow._test_port",
        return_value="should not be called",
    ) as test_port:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PORT: "demo"}
        )
    test_port.assert_not_called()
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["port"] == "demo"


# ─── Custom wizard must reject an uncompilable regex ─────────────────────────


async def run_custom_wizard(hass: HomeAssistant, status_pattern: str) -> dict[str, Any]:
    """Drive the custom-device wizard to the response step and submit a pattern."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "device_profile": ">> Custom Device (define via UI)",
            CONF_PORT: "demo",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_name": "Wizard Test", "zones": 2, "sources": 2},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "command_prefix": "",
            "command_suffix": "\\r",
            "response_prefix": "",
            "response_terminator": "\\r",
            "command_delay_ms": 100,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "status": "Z{zone:02d}STA",
            "power_on": "Z{zone:02d}PON",
            "power_off": "Z{zone:02d}POFF",
            "volume_set": "Z{zone:02d}VOL{volume:02d}",
            "mute_on": "Z{zone:02d}MUON",
            "mute_off": "Z{zone:02d}MUOFF",
            "source_set": "Z{zone:02d}SRC{source:02d}",
        },
    )
    return await hass.config_entries.flow.async_configure(  # type: ignore[no-any-return]
        result["flow_id"],
        user_input={
            "status_pattern": status_pattern,
            "volume_min": 0,
            "volume_max": 38,
            "volume_inverted": False,
            "error_response": "?",
        },
    )


async def test_unterminated_group_is_rejected_at_submit(
    hass: HomeAssistant, mock_ports: Any
) -> None:
    """An unclosed group is the most likely hand-typed regex mistake.

    Must come back as an inline form error, not an entry that raises re.error on
    every load thereafter.
    """
    result = await run_custom_wizard(hass, r"Z(?P<zone>\d{2}")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_response"
    assert result["errors"] == {"status_pattern": "invalid_regex"}


@pytest.mark.parametrize(
    "pattern",
    [
        r"Z(?P<zone>\d{2}",  # unterminated group
        r"Z(?P<zone>\d)[0-9",  # unterminated character class
        r"Z(?P<zone>\d)**",  # nothing to repeat
        r"Z(?P<zone>\d)(?P<zone>\d)",  # duplicate group name
    ],
)
async def test_uncompilable_patterns_are_all_rejected(
    hass: HomeAssistant, mock_ports: Any, pattern: str
) -> None:
    """Every re.error variant must be caught, not just missing parens."""
    result = await run_custom_wizard(hass, pattern)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"status_pattern": "invalid_regex"}


async def test_valid_pattern_still_creates_the_entry(
    hass: HomeAssistant, mock_ports: Any
) -> None:
    """The guard must not reject legitimate patterns.

    Without this, "reject everything" would pass the tests above.
    """
    result = await run_custom_wizard(
        hass, r"Z(?P<zone>\d{2}) PWR(?P<power>\d) VOL(?P<volume>\d{2})"
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    profile = result["data"]["custom_profile"]
    assert profile["response"]["status_pattern"].startswith("Z(?P<zone>")


async def test_rejected_pattern_can_be_corrected_in_place(
    hass: HomeAssistant, mock_ports: Any
) -> None:
    """After the error the user must be able to fix the field and continue.

    A validation error that dead-ends the flow would be little better than the
    un-loadable entry it replaced.
    """
    result = await run_custom_wizard(hass, r"Z(?P<zone>\d{2}")
    assert result["errors"] == {"status_pattern": "invalid_regex"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "status_pattern": r"Z(?P<zone>\d{2}) VOL(?P<volume>\d{2})",
            "volume_min": 0,
            "volume_max": 38,
            "volume_inverted": False,
            "error_response": "?",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


# ─── The unique_id must follow the port ──────────────────────────────────────


async def test_reconfigure_updates_the_unique_id(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """unique_id IS the port and is the only duplicate guard.

    Updating `data` without it left the entry claiming its old port, so the SAME
    physical port could be added again -- two managers opening one serial link.
    """
    entry = network_entry()
    entry.add_to_hass(hass)
    assert entry.unique_id == f"ac_{SOCKET_PORT}"

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PORT: "/dev/ttyUSB1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["port"] == "/dev/ttyUSB1"
    assert entry.unique_id == "ac_/dev/ttyUSB1", "unique_id did not follow the port"


async def test_reconfigure_onto_another_entrys_port_is_refused(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """Moving entry A onto entry B's port must abort, not create a conflict.

    Previously unchecked in this direction: both entries would then drive the
    same device.
    """
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Other",
        unique_id="ac_/dev/ttyUSB0",
        data={"port": "/dev/ttyUSB0", "device_profile": "AMC X86 / X86i"},
        version=3,
    )
    other.add_to_hass(hass)

    entry = network_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PORT: "/dev/ttyUSB0"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["port"] == SOCKET_PORT, "port should be unchanged"


async def test_resubmitting_the_same_port_is_not_a_conflict(
    hass: HomeAssistant, mock_ports: Any, port_opens: Any
) -> None:
    """An unchanged port must not collide with the entry's own unique_id."""
    entry = network_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PORT: SOCKET_PORT}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


# ─── USB discovery matchers must be able to match ────────────────────────────


def test_usb_description_patterns_are_lowercase() -> None:
    """HA lowercases the device NAME but not the pattern before fnmatch.

    homeassistant/components/usb/_fnmatch_lower does
    `fnmatch(name.lower(), pattern)`, so "*RS232*" could never match and the FTDI
    matchers never fired. Every one of core's own usb description patterns is
    lowercase.
    """
    import json
    from pathlib import Path

    manifest = json.loads(
        Path("custom_components/audio_control/manifest.json").read_text()
    )
    for matcher in manifest.get("usb", []):
        pattern = matcher.get("description")
        if pattern is None:
            continue
        assert pattern == pattern.lower(), f"{pattern!r} can never match"


def test_usb_matchers_all_filter_by_description() -> None:
    """A bare VID/PID matcher claims every adapter using that chip.

    10C4:EA60 (SiLabs CP2102) is claimed by homeassistant_sky_connect, zha and
    zwave_js -- offering "Audio Control" for a Zigbee stick is a poor first
    impression, and 1A86:7523 (CH340) is equally generic. Both were dropped in
    favour of description-filtered matchers.
    """
    import json
    from pathlib import Path

    manifest = json.loads(
        Path("custom_components/audio_control/manifest.json").read_text()
    )
    unfiltered = [
        f"{m['vid']}:{m['pid']}"
        for m in manifest.get("usb", [])
        if "description" not in m
    ]
    assert not unfiltered, f"matchers with no description filter: {unfiltered}"
