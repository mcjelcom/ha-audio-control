"""Tests for BinaryProtocolEngine — hex-framed protocols."""

from __future__ import annotations

import pytest
from rs232_protocol import BinaryProtocolEngine, create_engine

# Minimal SpeakerCraft-like profile for testing
BINARY_PROFILE = {
    "protocol_type": "binary",
    "name": "Test Binary Device",
    "zones": 4,
    "sources": 6,
    "serial": {
        "baud_rate": 57600,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "command_delay_ms": 100,
    },
    "binary": {
        "start_byte": 0x55,
        "length_includes_start": True,
        "length_includes_checksum": False,
        "checksum": "mod256",
        "flow_control": "xon_xoff",
        "xon_byte": 0x11,
        "xoff_byte": 0x13,
    },
    "commands": {
        "power_on": {"opcode": 0xA0, "data": ["{zone}"]},
        "power_off": {"opcode": 0xA1, "data": ["{zone}"]},
        "volume_set": {
            "opcode": 0x57,
            "data": ["0x00", "0x00", "0x05", "{volume}", "{zone}"],
        },
        "source_set": {"opcode": 0xA3, "data": ["{zone}", "{source}"]},
        "status": {"opcode": 0x68, "data": ["{zone}"]},
    },
    "response": {
        "zone_status": {
            "opcode": 0x20,
            "fields": {
                "zone": {"offset": 0, "transform": "add1"},
                "power": {"offset": 2, "bit": 1},
                "mute": {"offset": 2, "bit": 0},
                "source": {"offset": 3, "transform": "add1"},
                "volume": {"offset": 4},
            },
        },
    },
    "volume": {"min": 0, "max": 80, "inverted": True},
    "features": {
        "has_tone_controls": False,
        "has_group_mode": False,
        "has_all_off": True,
        "unsolicited_updates": True,
    },
}


@pytest.fixture
def engine() -> BinaryProtocolEngine:
    """Create a test binary engine."""
    return BinaryProtocolEngine(BINARY_PROFILE)


class TestBinaryEngineProperties:
    """Test engine properties."""

    def test_baud_rate(self, engine: BinaryProtocolEngine) -> None:
        assert engine.baud_rate == 57600

    def test_num_zones(self, engine: BinaryProtocolEngine) -> None:
        assert engine.num_zones == 4

    def test_num_sources(self, engine: BinaryProtocolEngine) -> None:
        assert engine.num_sources == 6

    def test_volume_max(self, engine: BinaryProtocolEngine) -> None:
        assert engine.volume_max == 80

    def test_volume_inverted(self, engine: BinaryProtocolEngine) -> None:
        assert engine.volume_inverted is True

    def test_flow_control(self, engine: BinaryProtocolEngine) -> None:
        assert engine.flow_control == "xon_xoff"

    def test_xon_xoff_bytes(self, engine: BinaryProtocolEngine) -> None:
        assert engine.xon_byte == 0x11
        assert engine.xoff_byte == 0x13


class TestBinaryCommandFormatting:
    """Test command frame construction."""

    def test_power_on_zone_1(self, engine: BinaryProtocolEngine) -> None:
        """Zone 1 → wire byte 0x00 (0-indexed)."""
        cmd = engine.format_command("power_on", zone=1)
        assert cmd is not None
        assert cmd[0] == 0x55  # start byte
        assert cmd[2] == 0xA0  # opcode
        assert cmd[3] == 0x00  # zone 1 → 0-indexed = 0

    def test_power_off_zone_3(self, engine: BinaryProtocolEngine) -> None:
        cmd = engine.format_command("power_off", zone=3)
        assert cmd is not None
        assert cmd[2] == 0xA1  # opcode
        assert cmd[3] == 0x02  # zone 3 → 0-indexed = 2

    def test_volume_set(self, engine: BinaryProtocolEngine) -> None:
        cmd = engine.format_command("volume_set", zone=2, volume=40)
        assert cmd is not None
        assert cmd[2] == 0x57  # opcode
        assert cmd[5] == 0x05  # literal 0x05 from template
        assert cmd[6] == 40  # volume value (direct, not 0-indexed)
        assert cmd[7] == 0x01  # zone 2 → 0-indexed = 1

    def test_source_set(self, engine: BinaryProtocolEngine) -> None:
        cmd = engine.format_command("source_set", zone=1, source=3)
        assert cmd is not None
        assert cmd[2] == 0xA3  # opcode
        assert cmd[3] == 0x00  # zone 1 → 0
        assert cmd[4] == 0x02  # source 3 → 0-indexed = 2

    def test_undefined_command_returns_none(self, engine: BinaryProtocolEngine) -> None:
        assert engine.format_command("nonexistent") is None

    def test_checksum_present(self, engine: BinaryProtocolEngine) -> None:
        """Frame ends with a checksum byte."""
        cmd = engine.format_command("power_on", zone=1)
        assert cmd is not None
        # Verify checksum: (0x100 - sum(frame[:-1])) & 0xFF
        frame_without_checksum = cmd[:-1]
        expected = (0x100 - (sum(frame_without_checksum) % 256)) & 0xFF
        assert cmd[-1] == expected

    def test_frame_to_bytes_passthrough(self, engine: BinaryProtocolEngine) -> None:
        """bytes input passes through unchanged."""
        data = b"\x55\x04\xa0\x00\xab"
        assert engine.frame_to_bytes(data) == data


class TestBinaryResponseParsing:
    """Test response frame parsing."""

    def test_parse_zone_status(self, engine: BinaryProtocolEngine) -> None:
        """Parse a zone status response with bit fields."""
        # opcode 0x20, payload: zone=0, unknown=0, flags=0x02 (power on, not muted), source=2, volume=30
        frame = bytes([0x55, 0x08, 0x20, 0x00, 0x00, 0x02, 0x02, 0x30, 0x00])
        result = engine.parse_response(frame)
        assert result is not None
        assert result["zone"] == 1  # 0 + 1 (add1 transform)
        assert result["power"] is True  # bit 1 of 0x02
        assert result["mute"] is False  # bit 0 of 0x02
        assert result["source"] == 3  # 2 + 1 (add1 transform)

    def test_parse_unknown_opcode(self, engine: BinaryProtocolEngine) -> None:
        frame = bytes([0x55, 0x04, 0xFF, 0x00, 0x00])
        assert engine.parse_response(frame) is None

    def test_parse_too_short(self, engine: BinaryProtocolEngine) -> None:
        assert engine.parse_response(b"\x55\x02") is None

    def test_parse_wrong_start_byte(self, engine: BinaryProtocolEngine) -> None:
        assert engine.parse_response(b"\xaa\x04\x20\x00\x00") is None


class TestBinaryFrameExtraction:
    """Test extract_frames for binary protocols."""

    def test_extract_single_frame(self, engine: BinaryProtocolEngine) -> None:
        # Frame: 55 04 A0 00 [checksum]
        frame_data = bytes([0x55, 0x04, 0xA0, 0x00])
        checksum = (0x100 - (sum(frame_data) % 256)) & 0xFF
        buffer = frame_data + bytes([checksum])
        frames, remaining = engine.extract_frames(buffer)
        assert len(frames) == 1
        assert remaining == b""

    def test_extract_skips_xon_xoff(self, engine: BinaryProtocolEngine) -> None:
        """XON/XOFF bytes before a frame are skipped."""
        frame_data = bytes([0x55, 0x04, 0xA0, 0x00])
        checksum = (0x100 - (sum(frame_data) % 256)) & 0xFF
        buffer = bytes([0x11, 0x13]) + frame_data + bytes([checksum])
        frames, _remaining = engine.extract_frames(buffer)
        assert len(frames) == 1

    def test_incomplete_frame_remains(self, engine: BinaryProtocolEngine) -> None:
        """Incomplete frame stays in buffer."""
        buffer = bytes([0x55, 0x08, 0x20])  # length says 8 but only 3 bytes
        frames, remaining = engine.extract_frames(buffer)
        assert len(frames) == 0
        assert remaining == buffer


class TestBinaryVolumeConversion:
    """Test volume conversion for inverted binary devices."""

    def test_ha_to_device_max(self, engine: BinaryProtocolEngine) -> None:
        """1.0 HA = 0 device (loudest, inverted)."""
        assert engine.ha_volume_to_device(1.0) == 0

    def test_ha_to_device_min(self, engine: BinaryProtocolEngine) -> None:
        """0.0 HA = 80 device (mute, inverted)."""
        assert engine.ha_volume_to_device(0.0) == 80

    def test_device_to_ha_roundtrip(self, engine: BinaryProtocolEngine) -> None:
        for ha_vol in [0.0, 0.25, 0.5, 0.75, 1.0]:
            device_val = engine.ha_volume_to_device(ha_vol)
            back = engine.device_volume_to_ha(device_val)
            assert abs(back - ha_vol) < 0.02


class TestFactory:
    """Test create_engine factory selects correct engine."""

    def test_binary_type(self) -> None:
        engine = create_engine(BINARY_PROFILE)
        assert isinstance(engine, BinaryProtocolEngine)

    def test_text_type_default(self) -> None:
        from rs232_protocol import ProtocolEngine

        text_profile = {
            "name": "Test",
            "zones": 2,
            "sources": 2,
            "serial": {},
            "commands": {"power_on": "PON"},
            "response": {},
            "volume": {},
            "features": {},
        }
        engine = create_engine(text_profile)
        assert isinstance(engine, ProtocolEngine)

    def test_json_type(self) -> None:
        from rs232_protocol import JsonProtocolEngine

        json_profile = {
            "protocol_type": "json",
            "name": "Test",
            "zones": 1,
            "sources": 1,
            "serial": {},
            "json": {"delimiter": "\n"},
            "commands": {"power_on": {"type": "set_power", "value": True}},
            "response": {},
            "volume": {},
            "features": {},
        }
        engine = create_engine(json_profile)
        assert isinstance(engine, JsonProtocolEngine)


# ─── RNET End-Byte Delimited Framing ────────────────────────────────────────

RNET_PROFILE = {
    "protocol_type": "binary",
    "name": "RNET Test",
    "zones": 6,
    "sources": 6,
    "serial": {"baud_rate": 19200, "command_delay_ms": 100},
    "binary": {
        "start_byte": 0xF0,
        "end_byte": 0xF7,
        "escape_byte": 0xF1,
        "length_includes_start": False,
        "length_includes_checksum": False,
        "checksum": "rnet",
    },
    "commands": {
        "power_on": {"opcode": 0x05, "data": ["{zone}", "0x01"]},
        "power_off": {"opcode": 0x05, "data": ["{zone}", "0x00"]},
        "status": {"opcode": 0x07, "data": ["{zone}"]},
        # Raw {volume} byte so a value equal to the end byte (0xF7) exercises
        # transmit-side escaping.
        "volume_set": {"opcode": 0x15, "data": ["0x00", "{volume}", "{zone}"]},
    },
    "response": {},
    "volume": {"min": 0, "max": 50, "inverted": False},
    "features": {"unsolicited_updates": True},
}


@pytest.fixture
def rnet_engine() -> BinaryProtocolEngine:
    """Create an RNET-style engine with end-byte framing."""
    return BinaryProtocolEngine(RNET_PROFILE)


def rnet_checksum(body: bytes) -> int:
    """RNET checksum: (sum + count) & 0x7F, matching the engine."""
    return (sum(body) + len(body)) & 0x7F


def rnet_frame(*body_after_start: int) -> bytes:
    """Build a well-formed RNET frame: F0 <body> <checksum> F7.

    The extractor validates the checksum, so tests must build valid frames --
    arbitrary byte sequences are indistinguishable from line noise and are
    (correctly) dropped.
    """
    body = bytes([0xF0, *body_after_start])
    return body + bytes([rnet_checksum(body)]) + b"\xf7"


class TestRnetFrameExtraction:
    """Test end-byte delimited frame extraction (RNET 0xF0/0xF7)."""

    def test_simple_frame(self, rnet_engine: BinaryProtocolEngine) -> None:
        """Complete frame between F0 and F7."""
        frame = rnet_frame(0x01, 0x02, 0x03)
        frames, remaining = rnet_engine.extract_frames(frame)
        assert len(frames) == 1
        assert frames[0] == frame
        assert remaining == b""

    def test_two_frames(self, rnet_engine: BinaryProtocolEngine) -> None:
        """Two consecutive frames."""
        frame1 = rnet_frame(0x0A, 0x0B)
        frame2 = rnet_frame(0x0C, 0x0D, 0x0E)
        frames, remaining = rnet_engine.extract_frames(frame1 + frame2)
        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2
        assert remaining == b""

    def test_escape_sequence(self, rnet_engine: BinaryProtocolEngine) -> None:
        """Escape byte (0xF1) followed by inverted byte is decoded.

        To carry 0xF7 in the body, the sender emits 0xF1 then (~0xF7 & 0xFF) =
        0x08; the receiver inverts it back. The checksum is computed over the
        DECODED bytes, so it is derived from the post-escape payload.
        """
        decoded_body = bytes([0xF0, 0x01, 0xF7, 0x02])
        checksum = rnet_checksum(decoded_body)
        # Wire form escapes the 0xF7 in the body; the checksum byte here (0x62)
        # is not itself a framing byte, so it needs no escaping.
        wire = bytes([0xF0, 0x01, 0xF1, 0x08, 0x02, checksum, 0xF7])
        frames, _remaining = rnet_engine.extract_frames(wire)
        assert len(frames) == 1
        assert frames[0] == decoded_body + bytes([checksum]) + b"\xf7"

    def test_bad_checksum_frame_is_dropped(
        self, rnet_engine: BinaryProtocolEngine
    ) -> None:
        """A frame whose checksum does not match is discarded, not applied.

        Regression: the end-delimited extractor previously performed no checksum
        validation at all (the length-based one did), so RS232 line noise wrote
        corrupt volume/source values straight into zone state.
        """
        good = rnet_frame(0x02, 0x07, 0x00)
        corrupt = bytearray(good)
        corrupt[2] ^= 0xFF  # flip a body byte, leave the checksum stale

        assert len(rnet_engine.extract_frames(good)[0]) == 1
        assert rnet_engine.extract_frames(bytes(corrupt))[0] == []

    def test_command_round_trips_through_extractor(
        self, rnet_engine: BinaryProtocolEngine
    ) -> None:
        """A formatted command must be parseable by the same engine.

        Regression: format_command omitted the 0xF7 terminator, so every
        Russound command was malformed on the wire and the engine could not
        parse its own output.
        """
        cmd = rnet_engine.format_command("power_on", zone=1)
        assert isinstance(cmd, bytes)
        assert cmd[-1] == 0xF7, "frame must be terminated by the end byte"

        frames, remaining = rnet_engine.extract_frames(cmd)
        assert len(frames) == 1
        assert remaining == b""

    def test_body_byte_colliding_with_end_byte_is_escaped(
        self, rnet_engine: BinaryProtocolEngine
    ) -> None:
        """A payload value equal to the end byte must not terminate the frame.

        Regression: escaping was implemented on receive only, so a body byte of
        0xF7 was transmitted raw and truncated the command at the device.
        """
        cmd = rnet_engine.format_command("volume_set", zone=1, volume=0xF7)
        assert isinstance(cmd, bytes)
        # Only the final byte may be 0xF7.
        assert 0xF7 not in cmd[1:-1], f"unescaped end byte in body: {cmd.hex(' ')}"
        # And it must survive the round trip.
        frames, _ = rnet_engine.extract_frames(cmd)
        assert len(frames) == 1

    def test_incomplete_frame_no_end_byte(
        self, rnet_engine: BinaryProtocolEngine
    ) -> None:
        """Incomplete frame (no end byte yet) stays in buffer."""
        buffer = bytes([0xF0, 0x01, 0x02, 0x03])
        frames, remaining = rnet_engine.extract_frames(buffer)
        assert len(frames) == 0
        assert remaining == buffer

    def test_incomplete_escape_at_end(self, rnet_engine: BinaryProtocolEngine) -> None:
        """Escape byte at very end of buffer — wait for next byte."""
        buffer = bytes([0xF0, 0x01, 0xF1])
        frames, remaining = rnet_engine.extract_frames(buffer)
        assert len(frames) == 0
        assert remaining == buffer

    def test_garbage_before_start(self, rnet_engine: BinaryProtocolEngine) -> None:
        """Bytes before start byte are skipped."""
        frame = rnet_frame(0x01)
        buffer = bytes([0xAA, 0xBB, 0xCC]) + frame
        frames, _remaining = rnet_engine.extract_frames(buffer)
        assert len(frames) == 1
        assert frames[0] == frame

    def test_rnet_checksum_algorithm(self) -> None:
        """Verify RNET checksum: (sum + count) & 0x7F."""
        from rs232_protocol.binary_engine import _checksum_rnet

        data = bytes([0xF0, 0x01, 0x02, 0x03])
        expected = (0xF0 + 0x01 + 0x02 + 0x03 + 4) & 0x7F
        assert _checksum_rnet(data) == expected

    def test_rnet_command_format(self, rnet_engine: BinaryProtocolEngine) -> None:
        """RNET power_on command builds correctly."""
        cmd = rnet_engine.format_command("power_on", zone=1)
        assert cmd is not None
        assert cmd[0] == 0xF0  # start byte
        assert cmd[2] == 0x05  # opcode
        assert cmd[3] == 0x00  # zone 1 → 0-indexed
        assert cmd[4] == 0x01  # power on value
