"""AMC XCDie — a fixed-width binary transport with no length byte.

Source: "APPENDIX 5: RS-232 Protocol Specifications for XCDie", XCDie MANUAL.pdf
(amchome.com/files/). Protocol Ver 1.0, RS232C UART, 9600bps, 8 data bits.

Every frame is exactly three bytes: `55 <cmd> AA`. The manual states the format
as "CD Play  55_20_AA" with "_" denoting a blank space, and lists 25 opcodes plus
a `55 FF AA` Read Status command with a 17-entry status table.

Two things made this the first profile of its shape:

  1. No length byte. BinaryProtocolEngine._build_frame_header unconditionally
     inserted one, so the engine produced `55 03 FA AE AA` where the device
     wants `55 FA AA` -- a length byte AND a mod256 checksum the XCDie never
     asked for. `checksum: none` already existed; omitting the length did not.
  2. It is a transport, not a zone device. There is no volume, no source in the
     audio sense, and no power -- only play/pause/stop/track and an input
     selector (CD/USB/SD/24192).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR

from custom_components.audio_control.const import DOMAIN

PROFILE_NAME = "AMC XCDie CD Player"
F = MediaPlayerEntityFeature


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def profile() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (BUILTIN_PROFILES_DIR / "amc_xcdie.yaml").read_text()
    )
    return data


def engine() -> Any:
    return create_engine(profile())


# ─── Frames are exactly three bytes, as printed ──────────────────────────────


@pytest.mark.parametrize(
    ("command", "opcode"),
    [
        # Opcodes transcribed from the appendix table.
        ("play", 0xFA),
        ("pause", 0xFB),
        ("stop", 0x21),
        ("next_track", 0xF3),
        ("prev_track", 0xF2),
        ("status", 0xFF),
    ],
)
def test_frame_is_start_opcode_end(command: str, opcode: int) -> None:
    """`55 <cmd> AA` with nothing in between.

    Pre-fix the engine emitted `55 03 FA AE AA`: an injected length byte and a
    mod256 checksum the XCDie protocol does not define. The device would reject
    every frame.
    """
    frame = engine().format_command(command)
    assert frame == bytes([0x55, opcode, 0xAA]), (
        f"{command}: got {frame.hex(' ').upper() if frame else None}, "
        f"want 55 {opcode:02X} AA"
    )


def test_every_command_frame_is_exactly_three_bytes() -> None:
    """No command may grow the frame -- the width is fixed by the protocol."""
    e = engine()
    for name in profile()["commands"]:
        frame = e.format_command(name)
        assert frame is not None, f"{name} did not format"
        assert len(frame) == 3, f"{name}: {len(frame)} bytes, want 3"
        assert frame[0] == 0x55
        assert frame[2] == 0xAA


def test_no_checksum_byte_is_appended() -> None:
    """The appendix defines no checksum; appending one corrupts the frame."""
    assert profile()["binary"].get("checksum") == "none"


def test_input_select_commands_match_the_manual() -> None:
    """CD=F6, USB=F7, SD=F8, 24192=F9 from the appendix table."""
    e = engine()
    for source, opcode in ((1, 0xF6), (2, 0xF7), (3, 0xF8), (4, 0xF9)):
        frame = e.format_command(f"source_{source}")
        assert frame == bytes([0x55, opcode, 0xAA]), f"source {source}"


def test_serial_params_match_the_manual() -> None:
    """ "RS232C UART / 9600bps / Data 8bit"."""
    e = engine()
    assert e.baud_rate == 9600
    assert e.data_bits == 8


# ─── Status replies decode against the manual's table ────────────────────────


@pytest.mark.parametrize(
    ("code", "expect_power", "expect_source"),
    [
        # Status Code table: 2x = CD, 3x = USB, 4x = SD, 50 = 24192.
        (0x21, True, 1),  # CD PLAY
        (0x22, True, 1),  # CD PAUSE
        (0x23, True, 1),  # CD STOP
        (0x31, True, 2),  # USB PLAY
        (0x33, True, 2),  # USB STOP
        (0x41, True, 3),  # SD PLAY
        (0x45, True, 3),  # SD RANDOM
        (0x50, True, 4),  # 24192
    ],
)
def test_status_codes_map_to_the_documented_source(
    code: int, expect_power: bool, expect_source: int
) -> None:
    """The high nibble encodes the active input, per the manual's table."""
    parsed = engine().parse_response(bytes([0x55, code, 0xAA]))
    assert parsed is not None, f"status {code:02X} did not parse"
    assert parsed.get("source") == expect_source
    assert parsed.get("power") is expect_power


# ─── Entity surface: a transport, not a zone ─────────────────────────────────


async def setup_xcdie(hass: HomeAssistant) -> Any:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_profile": PROFILE_NAME, CONF_PORT: "demo"},
    )
    await hass.async_block_till_done()
    assert result["type"].value == "create_entry", result
    assert result["result"].state is ConfigEntryState.LOADED
    return result["result"]


def features_of(hass: HomeAssistant, entry_id: str) -> MediaPlayerEntityFeature:
    registry = er.async_get(hass)
    ent = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry_id)
        if e.domain == "media_player"
    )
    state = hass.states.get(ent.entity_id)
    assert state is not None
    return MediaPlayerEntityFeature(state.attributes["supported_features"])


async def test_transport_controls_are_offered(hass: HomeAssistant) -> None:
    """Play/pause/stop/next/prev all exist in the appendix."""
    entry = await setup_xcdie(hass)
    features = features_of(hass, entry.entry_id)
    assert features & F.PLAY
    assert features & F.PAUSE
    assert features & F.STOP
    assert features & F.NEXT_TRACK
    assert features & F.PREVIOUS_TRACK


async def test_audio_controls_are_not_offered(hass: HomeAssistant) -> None:
    """A CD transport has no volume, mute, or power over serial.

    Advertising any of them would give controls that fail silently, which is the
    failure mode the feature gates were rebuilt to prevent.
    """
    entry = await setup_xcdie(hass)
    features = features_of(hass, entry.entry_id)
    assert not features & F.VOLUME_SET
    assert not features & F.VOLUME_STEP
    assert not features & F.VOLUME_MUTE
    assert not features & F.TURN_ON
    assert not features & F.TURN_OFF


async def test_four_inputs_are_selectable(hass: HomeAssistant) -> None:
    """CD / USB / SD / 24192 are the documented media inputs."""
    entry = await setup_xcdie(hass)
    assert features_of(hass, entry.entry_id) & F.SELECT_SOURCE
    registry = er.async_get(hass)
    ent = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player"
    )
    state = hass.states.get(ent.entity_id)
    assert state is not None
    assert state.attributes["source_list"] == ["CD", "USB", "SD", "24192"]


# ─── The library change this profile required ────────────────────────────────


def test_length_byte_can_be_omitted() -> None:
    """`has_length_byte: false` must suppress the length byte entirely.

    Guards the new binary-engine option directly, independent of the XCDie
    profile, so a regression is attributed to the engine rather than the YAML.
    """
    prof: dict[str, Any] = {
        "name": "probe",
        "protocol_type": "binary",
        "zones": 1,
        "sources": 1,
        "binary": {
            "start_byte": 0x55,
            "end_byte": 0xAA,
            "checksum": "none",
            "escape_byte": None,
            "has_length_byte": False,
        },
        "commands": {"ping": {"opcode": "0x20"}},
        "response": {"mapping": {}},
        "volume": {"min": 0, "max": 0},
        "serial": {"baud_rate": 9600},
    }
    assert create_engine(prof).format_command("ping") == bytes([0x55, 0x20, 0xAA])


def test_length_byte_is_still_present_by_default() -> None:
    """Existing binary profiles must be unaffected by the new option.

    Russound RNET and SpeakerCraft MZC both rely on the length byte; defaulting
    the new flag to False would silently break them.
    """
    prof: dict[str, Any] = {
        "name": "probe",
        "protocol_type": "binary",
        "zones": 1,
        "sources": 1,
        "binary": {"start_byte": 0x55, "checksum": "none"},
        "commands": {"ping": {"opcode": "0x20"}},
        "response": {"mapping": {}},
        "volume": {"min": 0, "max": 0},
        "serial": {"baud_rate": 9600},
    }
    frame = create_engine(prof).format_command("ping")
    assert frame is not None
    # start, length, opcode. length_includes_start also defaults True, so the
    # count is start(1) + length(1) + payload(1) = 3, not the payload alone.
    assert frame[:3] == bytes([0x55, 0x03, 0x20])
