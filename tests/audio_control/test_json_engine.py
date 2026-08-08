"""Tests for JsonProtocolEngine — JSON-over-serial protocols."""

from __future__ import annotations

import json

import pytest
from rs232_protocol import JsonProtocolEngine

JSON_PROFILE = {
    "protocol_type": "json",
    "name": "Test JSON Device",
    "zones": 6,
    "sources": 8,
    "serial": {
        "baud_rate": 9600,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "command_delay_ms": 50,
    },
    "json": {
        "delimiter": "\n",
        "login": {"username": "admin", "password": "secret"},
        "status_field": "status",
        "success_codes": [200, 901],
    },
    "commands": {
        "power_on": {"type": "set_powerstate", "value": True},
        "power_off": {"type": "set_powerstate", "value": False},
        "volume_set": {
            "type": "set_outputvol",
            "value_template": [{"index": "{zone}", "value": "{volume}"}],
        },
        "mute_on": {
            "type": "set_muteoutput",
            "value_template": [{"index": "{zone}", "value": True}],
        },
        "source_set": {
            "type": "set_outputsource1",
            "value_template": [{"index": "{zone}", "value": "{source}"}],
        },
    },
    "response": {},
    "volume": {"min": 0, "max": 100, "inverted": False},
    "features": {
        "has_tone_controls": False,
        "has_group_mode": True,
        "has_all_off": True,
        "unsolicited_updates": True,
    },
}


@pytest.fixture
def engine() -> JsonProtocolEngine:
    return JsonProtocolEngine(JSON_PROFILE)


class TestJsonEngineProperties:
    """Test properties."""

    def test_baud_rate(self, engine: JsonProtocolEngine) -> None:
        assert engine.baud_rate == 9600

    def test_num_zones(self, engine: JsonProtocolEngine) -> None:
        assert engine.num_zones == 6

    def test_volume_max(self, engine: JsonProtocolEngine) -> None:
        assert engine.volume_max == 100

    def test_volume_not_inverted(self, engine: JsonProtocolEngine) -> None:
        assert engine.volume_inverted is False

    def test_requires_login(self, engine: JsonProtocolEngine) -> None:
        assert engine.requires_login is True

    def test_delimiter(self, engine: JsonProtocolEngine) -> None:
        assert engine.delimiter == "\n"

    def test_has_unsolicited(self, engine: JsonProtocolEngine) -> None:
        assert engine.has_unsolicited_updates is True


class TestJsonCommandFormatting:
    """Test JSON command construction."""

    def test_power_on_literal_value(self, engine: JsonProtocolEngine) -> None:
        cmd = engine.format_command("power_on")
        assert cmd is not None
        obj = json.loads(cmd.decode("utf-8").strip())
        assert obj == {"type": "set_powerstate", "value": True}

    def test_power_off(self, engine: JsonProtocolEngine) -> None:
        cmd = engine.format_command("power_off")
        assert cmd is not None
        obj = json.loads(cmd.decode("utf-8").strip())
        assert obj["value"] is False

    def test_volume_set_template(self, engine: JsonProtocolEngine) -> None:
        cmd = engine.format_command("volume_set", zone=2, volume=75)
        assert cmd is not None
        obj = json.loads(cmd.decode("utf-8").strip())
        assert obj["type"] == "set_outputvol"
        assert obj["value"] == [{"index": 2, "value": 75}]

    def test_source_set_template(self, engine: JsonProtocolEngine) -> None:
        cmd = engine.format_command("source_set", zone=1, source=5)
        assert cmd is not None
        obj = json.loads(cmd.decode("utf-8").strip())
        assert obj["value"] == [{"index": 1, "value": 5}]

    def test_undefined_command(self, engine: JsonProtocolEngine) -> None:
        assert engine.format_command("nonexistent") is None

    def test_command_ends_with_delimiter(self, engine: JsonProtocolEngine) -> None:
        cmd = engine.format_command("power_on")
        assert cmd is not None
        assert cmd.endswith(b"\n")


class TestJsonLogin:
    """Test authentication handling."""

    def test_format_login(self, engine: JsonProtocolEngine) -> None:
        login_cmd = engine.format_login()
        obj = json.loads(login_cmd.decode("utf-8").strip())
        assert obj == {"type": "login", "username": "admin", "password": "secret"}

    def test_not_logged_in_initially(self, engine: JsonProtocolEngine) -> None:
        assert engine.logged_in is False

    def test_mark_logged_in(self, engine: JsonProtocolEngine) -> None:
        engine.mark_logged_in()
        assert engine.logged_in is True


class TestJsonResponseParsing:
    """Test JSON response parsing."""

    def test_parse_success_response(self, engine: JsonProtocolEngine) -> None:
        data = '{"type":"set_powerstate","status":200,"value":true}'
        result = engine.parse_response(data)
        assert result is not None
        assert result["type"] == "set_powerstate"
        assert result["status"] == 200
        assert result["power"] is True
        assert "error" not in result

    def test_parse_error_response(self, engine: JsonProtocolEngine) -> None:
        data = '{"type":"set_powerstate","status":401}'
        result = engine.parse_response(data)
        assert result is not None
        assert result["error"] is True

    def test_parse_broadcast(self, engine: JsonProtocolEngine) -> None:
        data = '{"type":"set_outputvol","status":901,"value":[{"index":3,"value":50}]}'
        result = engine.parse_response(data)
        assert result is not None
        assert result["status"] == 901
        assert result["zone"] == 3
        assert result["raw_value"] == 50

    def test_parse_login_success(self, engine: JsonProtocolEngine) -> None:
        data = '{"type":"login","status":200}'
        result = engine.parse_response(data)
        assert result is not None
        assert result.get("login_success") is True
        assert engine.logged_in is True

    def test_parse_login_failed(self, engine: JsonProtocolEngine) -> None:
        data = '{"type":"login","status":400}'
        result = engine.parse_response(data)
        assert result is not None
        assert result.get("error") is True

    def test_parse_invalid_json(self, engine: JsonProtocolEngine) -> None:
        assert engine.parse_response("not json at all") is None

    def test_parse_empty(self, engine: JsonProtocolEngine) -> None:
        assert engine.parse_response("") is None
        assert engine.parse_response(b"") is None


class TestJsonFrameExtraction:
    """Test newline-delimited frame extraction."""

    def test_single_frame(self, engine: JsonProtocolEngine) -> None:
        buffer = b'{"type":"test","status":200}\n'
        frames, remaining = engine.extract_frames(buffer)
        assert len(frames) == 1
        assert remaining == b""

    def test_multiple_frames(self, engine: JsonProtocolEngine) -> None:
        buffer = b'{"a":1}\n{"b":2}\n'
        frames, _remaining = engine.extract_frames(buffer)
        assert len(frames) == 2

    def test_incomplete_frame_remains(self, engine: JsonProtocolEngine) -> None:
        buffer = b'{"type":"test","status":200}\n{"partial'
        frames, remaining = engine.extract_frames(buffer)
        assert len(frames) == 1
        assert remaining == b'{"partial'

    def test_empty_buffer(self, engine: JsonProtocolEngine) -> None:
        frames, remaining = engine.extract_frames(b"")
        assert frames == []
        assert remaining == b""


class TestJsonVolumeConversion:
    """Test volume conversion (non-inverted, 0-100)."""

    def test_ha_to_device(self, engine: JsonProtocolEngine) -> None:
        assert engine.ha_volume_to_device(0.0) == 0
        assert engine.ha_volume_to_device(0.5) == 50
        assert engine.ha_volume_to_device(1.0) == 100

    def test_device_to_ha(self, engine: JsonProtocolEngine) -> None:
        assert engine.device_volume_to_ha(0) == 0.0
        assert engine.device_volume_to_ha(50) == 0.5
        assert engine.device_volume_to_ha(100) == 1.0
