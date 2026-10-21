"""JSON replies must be translated through the profile's response.mappings.

`JsonProtocolEngine.__init__` stored `response:` as `self._responses` but
`parse_response` never read it, so a `set_outputvol` / `set_muteoutput` /
`set_outputsource1` reply produced only `zone` and `raw_value` -- keys that
`_process_response` does not consume. On the RTI AD-810-100 / AD-46-100 / AD-1616
profile, volume, mute and source therefore only ever showed the optimistic UI
state, and changes made on a keypad or the unit itself never reached HA.

Reported in the HACS review of hacs/default#9954.
"""

from __future__ import annotations

from typing import Any

import pytest
from rs232_protocol import JsonProtocolEngine, create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles

RTI = "RTI AD-810-100 / AD-46-100"


def rti_profile() -> dict[str, Any]:
    return load_builtin_profiles()[RTI]


@pytest.fixture
def engine() -> JsonProtocolEngine:
    eng = create_engine(rti_profile())
    assert isinstance(eng, JsonProtocolEngine)
    return eng


@pytest.fixture
def conn() -> AsyncSerialConnection:
    return AsyncSerialConnection(
        port="demo", engine=create_engine(rti_profile()), demo_mode=True
    )


# ─── Engine: mapped keys are produced ─────────────────────────────────────────


def test_rti_profile_declares_mappings() -> None:
    """Guard the fixture: the shipped profile must actually carry the mappings."""
    mappings = rti_profile()["response"]["mappings"]
    assert {"set_outputvol", "set_muteoutput", "set_outputsource1"} <= set(mappings)


def test_volume_reply_maps_to_volume(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_outputvol","status":901,"value":[{"index":3,"value":42}]}'
    )
    assert r is not None
    assert r["zone"] == 3
    assert r["volume"] == 42


def test_mute_reply_maps_to_mute(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_muteoutput","status":901,"value":[{"index":5,"value":true}]}'
    )
    assert r is not None
    assert r["zone"] == 5
    assert r["mute"] is True


def test_source_reply_maps_to_source(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_outputsource1","status":200,"value":[{"index":2,"value":7}]}'
    )
    assert r is not None
    assert r["zone"] == 2
    assert r["source"] == 7


def test_numeric_string_is_coerced(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_outputvol","status":200,"value":[{"index":"4","value":"55"}]}'
    )
    assert r is not None
    assert r["zone"] == 4
    assert r["volume"] == 55


def test_bool_is_not_accepted_as_volume(engine: JsonProtocolEngine) -> None:
    """bool subclasses int; `true` must not become volume 1."""
    r = engine.parse_response(
        '{"type":"set_outputvol","status":200,"value":[{"index":1,"value":true}]}'
    )
    assert r is not None
    assert "volume" not in r


def test_non_bool_is_not_accepted_as_mute(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_muteoutput","status":200,"value":[{"index":1,"value":"yes"}]}'
    )
    assert r is not None
    assert "mute" not in r


def test_power_scalar_reply_maps(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response('{"type":"set_powerstate","status":200,"value":false}')
    assert r is not None
    assert r["power"] is False


def test_error_reply_is_not_mapped(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"set_outputvol","status":500,"value":[{"index":3,"value":42}]}'
    )
    assert r is not None
    assert r["error"] is True
    assert "volume" not in r


def test_unmapped_type_is_unchanged(engine: JsonProtocolEngine) -> None:
    r = engine.parse_response(
        '{"type":"get_unknown","status":200,"value":[{"index":3,"value":42}]}'
    )
    assert r is not None
    assert r["raw_value"] == 42
    assert "volume" not in r


def test_custom_zone_field() -> None:
    p = rti_profile()
    p["response"] = {
        "mappings": {"set_outputvol": {"zone_field": "out", "fields": {"volume": "v"}}}
    }
    eng = create_engine(p)
    r = eng.parse_response(
        '{"type":"set_outputvol","status":200,"value":[{"out":6,"v":9}]}'
    )
    assert r is not None
    assert r["zone"] == 6
    assert r["volume"] == 9


# ─── End to end: the reply lands in ZoneState ─────────────────────────────────


def test_keypad_volume_change_reaches_zone(conn: AsyncSerialConnection) -> None:
    conn._process_response(
        '{"type":"set_outputvol","status":901,"value":[{"index":3,"value":42}]}'
    )
    assert conn.zones[3].volume == 42


def test_keypad_mute_reaches_zone(conn: AsyncSerialConnection) -> None:
    conn._process_response(
        '{"type":"set_muteoutput","status":901,"value":[{"index":5,"value":true}]}'
    )
    assert conn.zones[5].mute is True


def test_keypad_source_reaches_zone(conn: AsyncSerialConnection) -> None:
    conn._process_response(
        '{"type":"set_outputsource1","status":901,"value":[{"index":2,"value":7}]}'
    )
    assert conn.zones[2].source == 7


def test_mapped_reply_leaves_other_zones_alone(conn: AsyncSerialConnection) -> None:
    before = conn.zones[4].volume
    conn._process_response(
        '{"type":"set_outputvol","status":901,"value":[{"index":3,"value":42}]}'
    )
    assert conn.zones[4].volume == before
