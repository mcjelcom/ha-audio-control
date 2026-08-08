"""Config-flow helpers: source resolution, port probing, and USB discovery.

These were the three least-covered areas of config_flow.py, and the first of
them is where today's CRITICAL bug lived: `_resolve_sources` handles the `sources`
mapping form used by five shipped profiles, which previously raised TypeError and
made those profiles impossible to add. The end-to-end flow tests cover the happy
path through it; these pin the branches directly, including the ones a profile
does not currently exercise.

The port helpers matter because they are the only thing standing between a typo
and a config entry that can never connect, and they are pure functions -- cheap to
test properly and easy to get subtly wrong (a bare `except OSError` that also
swallows TimeoutError, for instance).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import serial
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control import config_flow as cf
from custom_components.audio_control.const import DOMAIN

# Reuse the symbol config_flow itself resolved. HA 2025.x moved UsbServiceInfo to
# helpers.service_info.usb; importing it directly here would duplicate that
# version fallback and could drift from what the code under test actually uses.
UsbServiceInfo = cf.UsbServiceInfo


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


# ─── _resolve_sources ────────────────────────────────────────────────────────


def test_int_form_returns_count_and_no_names() -> None:
    """The common case: `sources: 8`."""
    assert cf._resolve_sources({"sources": 8}) == (8, {})


def test_missing_sources_defaults_to_six() -> None:
    """A profile with no `sources` key must not crash the flow."""
    assert cf._resolve_sources({}) == (6, {})


def test_mapping_form_returns_count_and_names() -> None:
    """The form that used to raise TypeError, e.g. NAD C 368 and Yamaha RX-A."""
    count, names = cf._resolve_sources(
        {"sources": {"count": 6, "names": {1: "Stream", 2: "Optical 1"}}}
    )
    assert count == 6
    assert names == {1: "Stream", 2: "Optical 1"}


def test_mapping_without_count_infers_from_names() -> None:
    """A names mapping and no count implies one source per name."""
    count, names = cf._resolve_sources(
        {"sources": {"names": {1: "CD", 2: "Tuner", 3: "Aux"}}}
    )
    assert count == 3
    assert len(names) == 3


def test_mapping_with_neither_count_nor_names_defaults_to_six() -> None:
    """An empty mapping must degrade, not produce a zero-source device."""
    assert cf._resolve_sources({"sources": {}}) == (6, {})


def test_string_keys_are_coerced_to_int() -> None:
    """YAML round-trips can produce string keys; zone/source lookups use ints."""
    _, names = cf._resolve_sources({"sources": {"names": {"1": "CD", "2": "TV"}}})
    assert names == {1: "CD", 2: "TV"}
    assert all(isinstance(k, int) for k in names)


def test_unexpected_type_falls_back_to_default() -> None:
    """A malformed profile must not raise from the flow."""
    assert cf._resolve_sources({"sources": "eight"}) == (6, {})


def test_count_wins_when_it_disagrees_with_names() -> None:
    """An explicit count is authoritative -- devices may have unnamed inputs.

    This is why the duplicate-`sources:` YAML keys mattered: the declared count
    was the value being silently discarded.
    """
    count, names = cf._resolve_sources(
        {"sources": {"count": 8, "names": {1: "CD", 2: "TV"}}}
    )
    assert count == 8
    assert len(names) == 2


# ─── _is_network_url ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        ("socket://192.168.1.50:4999", True),
        ("rfc2217://192.168.1.50:4999", True),
        ("/dev/ttyUSB0", False),
        ("demo", False),
        ("", False),
        # Not a supported scheme: must go down the serial path, not the TCP one.
        ("http://192.168.1.50", False),
    ],
)
def test_network_url_detection(port: str, expected: bool) -> None:
    assert cf._is_network_url(port) is expected


# ─── _test_port routing and error messages ───────────────────────────────────


def test_demo_port_needs_no_probe() -> None:
    """demo has no hardware, so neither prober should run."""
    with (
        patch.object(cf, "_test_serial_port") as ser,
        patch.object(cf, "_test_network_port") as net,
    ):
        assert cf._test_port("demo") is None
    ser.assert_not_called()
    net.assert_not_called()


def test_network_url_routes_to_the_tcp_prober() -> None:
    with (
        patch.object(cf, "_test_network_port", return_value=None) as net,
        patch.object(cf, "_test_serial_port") as ser,
    ):
        assert cf._test_port("socket://host:1") is None
    net.assert_called_once()
    ser.assert_not_called()


def test_tty_path_routes_to_the_serial_prober() -> None:
    with (
        patch.object(cf, "_test_serial_port", return_value=None) as ser,
        patch.object(cf, "_test_network_port") as net,
    ):
        assert cf._test_port("/dev/ttyUSB0") is None
    ser.assert_called_once()
    net.assert_not_called()


def test_permission_error_suggests_the_dialout_group() -> None:
    """The most common real failure on a fresh Linux install.

    A bare str(err) here would give "[Errno 13] Permission denied", which does
    not tell the user what to do about it.
    """
    with patch("serial.Serial", side_effect=PermissionError("denied")):
        msg = cf._test_serial_port("/dev/ttyUSB0")
    assert msg is not None
    assert "dialout" in msg


def test_serial_exception_is_reported() -> None:
    with patch("serial.Serial", side_effect=serial.SerialException("no such device")):
        msg = cf._test_serial_port("/dev/ttyNOPE")
    assert msg is not None
    assert "no such device" in msg


def test_successful_serial_probe_closes_the_port() -> None:
    """Leaving the probe's handle open would block the real connection."""
    handle = MagicMock()
    with patch("serial.Serial", return_value=handle):
        assert cf._test_serial_port("/dev/ttyUSB0") is None
    handle.close.assert_called_once()


@pytest.mark.parametrize(
    "port", ["socket://192.168.1.50", "socket://:4999", "socket://"]
)
def test_network_url_missing_host_or_port_is_rejected(port: str) -> None:
    """An incomplete URL must be reported as malformed, not dialled."""
    with patch("socket.create_connection") as connect:
        msg = cf._test_network_port(port)
    assert msg is not None
    assert "Invalid URL format" in msg
    connect.assert_not_called()


def test_network_timeout_is_distinguished_from_refusal() -> None:
    """A silently-dropped SYN and an active refusal need different advice.

    TimeoutError is an OSError subclass, so the timeout branch must be listed
    first -- otherwise every timeout reports as a generic connection failure.
    """
    with patch("socket.create_connection", side_effect=TimeoutError):
        msg = cf._test_network_port("socket://192.168.1.50:4999")
    assert msg is not None
    assert "timed out" in msg


def test_network_refusal_is_reported() -> None:
    with patch(
        "socket.create_connection", side_effect=ConnectionRefusedError("refused")
    ):
        msg = cf._test_network_port("socket://192.168.1.50:4999")
    assert msg is not None
    assert "Cannot connect" in msg


def test_successful_network_probe_closes_the_socket() -> None:
    """A leaked socket can hold the bridge's single TCP slot open."""
    sock = MagicMock()
    with patch("socket.create_connection", return_value=sock):
        assert cf._test_network_port("socket://192.168.1.50:4999") is None
    sock.close.assert_called_once()


# ─── _list_serial_ports ──────────────────────────────────────────────────────


def test_port_list_is_sorted_and_deduplicated() -> None:
    """comports() and the glob patterns overlap, so duplicates are expected."""
    info = MagicMock()
    info.device = "/dev/ttyUSB0"
    with (
        patch("serial.tools.list_ports.comports", return_value=[info]),
        patch(
            "custom_components.audio_control.config_flow.glob.glob",
            side_effect=lambda pattern: ["/dev/ttyUSB0"] if "ttyUSB" in pattern else [],
        ),
    ):
        ports = cf._list_serial_ports()
    assert ports == ["/dev/ttyUSB0"]


def test_port_list_merges_both_discovery_sources() -> None:
    info = MagicMock()
    info.device = "/dev/ttyACM0"
    with (
        patch("serial.tools.list_ports.comports", return_value=[info]),
        patch(
            "custom_components.audio_control.config_flow.glob.glob",
            side_effect=lambda pattern: ["/dev/ttyUSB1"] if "ttyUSB" in pattern else [],
        ),
    ):
        ports = cf._list_serial_ports()
    assert ports == ["/dev/ttyACM0", "/dev/ttyUSB1"]


# ─── The two port-failure policies differ by design ──────────────────────────


async def test_unloadable_profile_blocks_submission(hass: HomeAssistant) -> None:
    """A profile that vanishes between listing and submission must error cleanly.

    The name has to be in the dropdown for the schema to accept it, so the
    profile dict is emptied only on the SECOND load -- the one that resolves the
    submitted name. Patching it empty from the start makes voluptuous reject the
    value first, and line 182 is never reached.
    """
    real_profiles = cf.load_all_profiles(hass.config.config_dir)
    calls = {"n": 0}

    def vanishing(config_dir: str) -> dict[str, Any]:
        calls["n"] += 1
        return real_profiles if calls["n"] == 1 else {}

    with (
        patch.object(cf, "_list_serial_ports", return_value=["/dev/ttyUSB0"]),
        patch.object(cf, "load_all_profiles", side_effect=vanishing),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": "AMC X86 / X86i",
                CONF_PORT: "/dev/ttyUSB0",
            },
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_profile"}


async def test_custom_wizard_warns_but_proceeds_on_a_bad_port(
    hass: HomeAssistant,
) -> None:
    """Deliberate asymmetry with the profile path, pinned so it stays deliberate.

    The profile path blocks on cannot_connect. The custom wizard only warns: the
    user has already invested five steps defining the device, and discarding that
    because the amp is unplugged would be worse than creating an entry that
    retries via ConfigEntryNotReady.
    """
    with (
        patch.object(cf, "_list_serial_ports", return_value=["/dev/ttyUSB0"]),
        patch.object(cf, "_test_port", return_value="could not open port"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_profile": ">> Custom Device (define via UI)",
                CONF_PORT: "/dev/ttyUSB0",
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"device_name": "Wizard", "zones": 2, "sources": 2},
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
                "volume_min": 0,
                "volume_max": 38,
                "volume_inverted": False,
                "error_response": "?",
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["port"] == "/dev/ttyUSB0"


# ─── USB discovery ───────────────────────────────────────────────────────────


def usb_info(device: str = "/dev/ttyUSB0") -> UsbServiceInfo:
    return UsbServiceInfo(
        device=device,
        vid="0403",
        pid="6001",
        serial_number="A1",
        manufacturer="FTDI",
        description="USB Serial",
    )


async def test_usb_discovery_offers_the_discovered_port(hass: HomeAssistant) -> None:
    """Discovery should pre-fill the port so the user need not type it."""
    with patch.object(cf, "_list_serial_ports", return_value=["/dev/ttyUSB0"]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "usb"}, data=usb_info()
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_default = result["data_schema"]({"device_profile": "AMC X86 / X86i"})
    assert schema_default[CONF_PORT] == "/dev/ttyUSB0"


async def test_usb_discovery_aborts_for_an_already_configured_port(
    hass: HomeAssistant,
) -> None:
    """Re-plugging a configured adapter must not offer a duplicate entry."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ac_/dev/ttyUSB0",
        data={"port": "/dev/ttyUSB0", "device_profile": "AMC X86 / X86i"},
        version=3,
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "usb"}, data=usb_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_usb_discovery_sets_the_title_placeholder(hass: HomeAssistant) -> None:
    """The port appears in the discovery card, so the user knows which adapter."""
    with patch.object(cf, "_list_serial_ports", return_value=["/dev/ttyUSB1"]):
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "usb"}, data=usb_info("/dev/ttyUSB1")
        )
    flows = hass.config_entries.flow.async_progress()
    assert flows
    assert flows[0]["context"]["title_placeholders"] == {"port": "/dev/ttyUSB1"}


def test_probe_patches_actually_take_effect() -> None:
    """Guards the patch targets the tests above depend on.

    `serial` and `socket` are imported INSIDE the probe helpers (deliberately --
    HA discourages heavy imports at config_flow module scope), so the patch
    target is the source module, not `cf`. Patching `cf.serial` raises
    AttributeError today, but if someone later hoists the import to module scope
    both spellings would work and the distinction would go unnoticed. This
    asserts the patch genuinely intercepts the call rather than passing through
    to real hardware.
    """
    sentinel = MagicMock(side_effect=PermissionError("patched"))
    with patch("serial.Serial", sentinel):
        assert cf._test_serial_port("/dev/ttyPATCHED") is not None
    sentinel.assert_called_once()
