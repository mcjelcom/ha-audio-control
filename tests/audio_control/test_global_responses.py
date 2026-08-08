"""Tests for global (device-wide) response handling in _process_response.

_process_response has a cyclomatic complexity of 23 and sits at 65% coverage --
high complexity plus low coverage is exactly where bugs survive. Of its five
global branches only all_off and mute_all_on had any test; mute_all_off,
group_off and group_on were entirely dark, and nothing verified that listeners
actually fire (the HA entities only update via that callback, so a missing
notification means the UI silently keeps stale state).
"""

from __future__ import annotations

from typing import Any

import pytest
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection

# Mirrors the shipped AMC profile's global patterns, which is where these
# responses come from on real hardware.
AMC_GLOBAL_PROFILE: dict[str, Any] = {
    "name": "AmcGlobals",
    "zones": 6,
    "sources": 8,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "commands": {
        "status": "ZN{zone:02d}STA00",
        "all_off": "ZALLPWR00",
        "group_on": "ZALLGRP{source:02d}",
        "group_off": "ZALLGRP00",
    },
    "response": {
        "status_pattern": (
            r"ZN(?P<zone>\d{2}),SRC(?P<source>\d{2}),GRP(?P<group>\d),"
            r"VOL-(?P<volume>\d{2})"
        ),
        "error_response": "?",
        "global_patterns": {
            "all_off": "ZALLOFF",
            "mute_all_on": "ZALLMON",
            "mute_all_off": "ZALLMOFF",
            "group_off": "GRPOFF",
            "group_on": r"GRPON,SRC(?P<source>\d{2})",
        },
        "mapping": {
            "power": {"field": "volume", "type": "threshold", "off_value": 62},
            "mute": {"field": "volume", "type": "equals", "mute_value": 62},
            "volume": {"field": "volume", "type": "int"},
            "source": {"field": "source", "type": "int"},
            "group": {"field": "group", "type": "bool", "on_value": "1"},
        },
    },
    "volume": {"min": 0, "max": 62, "inverted": True},
}


@pytest.fixture
def conn() -> AsyncSerialConnection:
    return AsyncSerialConnection(
        port="demo", engine=create_engine(AMC_GLOBAL_PROFILE), demo_mode=True
    )


def track(conn: AsyncSerialConnection) -> list[int]:
    """Record which zones get notified, so we can assert the UI is told."""
    notified: list[int] = []
    conn.add_listener(lambda zone, _state: notified.append(zone))
    return notified


# ─── Previously untested global branches ─────────────────────────────────────


def test_global_mute_all_off_clears_mute(conn: AsyncSerialConnection) -> None:
    """ZALLMOFF must unmute every zone.

    Untested branch: only the mute_all_ON path had coverage, so an inverted
    condition here would have left every zone muted with no way to recover
    except a per-zone command.
    """
    for zone in conn.zones.values():
        zone.mute = True
    conn._process_response("ZALLMOFF")
    assert all(z.mute is False for z in conn.zones.values())


def test_global_group_on_sets_group(conn: AsyncSerialConnection) -> None:
    """GRPON must set group=True on every zone."""
    for zone in conn.zones.values():
        zone.group = False
    conn._process_response("GRPON,SRC03")
    assert all(z.group is True for z in conn.zones.values())


def test_global_group_off_clears_group(conn: AsyncSerialConnection) -> None:
    """GRPOFF must clear group on every zone."""
    for zone in conn.zones.values():
        zone.group = True
    conn._process_response("GRPOFF")
    assert all(z.group is False for z in conn.zones.values())


# ─── Listeners must fire: the UI only updates through them ───────────────────


@pytest.mark.parametrize(
    "response",
    ["ZALLOFF", "ZALLMON", "ZALLMOFF", "GRPOFF", "GRPON,SRC01"],
)
def test_every_global_response_notifies_all_zones(
    conn: AsyncSerialConnection, response: str
) -> None:
    """A global change must notify every zone.

    Mutating zone state without notifying leaves HA showing stale values until
    the next 60s poll -- the user sees a control that "did nothing".
    """
    notified = track(conn)
    conn._process_response(response)
    assert set(notified) == set(conn.zones), (
        f"{response}: notified {sorted(set(notified))}, expected {sorted(conn.zones)}"
    )


def test_all_off_sets_both_power_and_mute(conn: AsyncSerialConnection) -> None:
    """all_off is documented to imply muted, not just powered down."""
    for zone in conn.zones.values():
        zone.power = True
        zone.mute = False
    conn._process_response("ZALLOFF")
    for zone in conn.zones.values():
        assert zone.power is False
        assert zone.mute is True


# ─── Global responses are still enqueued for command correlation ─────────────


def test_global_response_is_enqueued(conn: AsyncSerialConnection) -> None:
    """A pending all_off command waits on the queue; the reply must reach it."""
    assert conn._response_queue.empty()
    conn._process_response("ZALLOFF")
    assert not conn._response_queue.empty()


def test_error_response_enqueues_sentinel(conn: AsyncSerialConnection) -> None:
    conn._process_response("?")
    assert conn._response_queue.get_nowait() == "__ERROR__"


def test_unparseable_response_is_enqueued_verbatim(
    conn: AsyncSerialConnection,
) -> None:
    """Unknown lines still wake a waiter, but as themselves -- not as an ACK.

    _wait_for_response treats an unparsed line as a mismatch (SEC-007), so it
    must reach the queue without being turned into a success sentinel.
    """
    conn._process_response("SOME BANNER v1.2")
    assert conn._response_queue.get_nowait() == "SOME BANNER v1.2"


# ─── Zone-specific responses ─────────────────────────────────────────────────


def test_zone_response_updates_only_that_zone(conn: AsyncSerialConnection) -> None:
    """A status frame for zone 3 must not disturb the others."""
    for zone in conn.zones.values():
        zone.volume = 10
    conn._process_response("ZN03,SRC05,GRP0,VOL-25")
    assert conn.zones[3].volume == 25
    assert conn.zones[3].source == 5
    assert all(conn.zones[z].volume == 10 for z in conn.zones if z != 3)


def test_zone_response_notifies_only_that_zone(
    conn: AsyncSerialConnection,
) -> None:
    notified = track(conn)
    conn._process_response("ZN02,SRC01,GRP0,VOL-30")
    assert notified == [2]


def test_out_of_range_zone_is_ignored(conn: AsyncSerialConnection) -> None:
    """A response for a zone the device does not have must not raise.

    The Monoprice zone_offset can also produce a negative zone from a malformed
    frame, so this guard is load-bearing.
    """
    notified = track(conn)
    conn._process_response("ZN99,SRC01,GRP0,VOL-30")  # zone 99 does not exist
    assert notified == []


def test_zone_zero_is_ignored(conn: AsyncSerialConnection) -> None:
    """Zones are 1-based, so a frame for zone 0 must change nothing.

    Compares against a snapshot rather than a hardcoded default, so this does not
    break if ZoneState's field defaults change.
    """
    before = {z: (s.source, s.volume, s.power) for z, s in conn.zones.items()}
    notified = track(conn)
    conn._process_response("ZN00,SRC07,GRP0,VOL-30")
    after = {z: (s.source, s.volume, s.power) for z, s in conn.zones.items()}
    assert after == before
    assert notified == []


# ─── Listener robustness ─────────────────────────────────────────────────────


def test_raising_listener_does_not_stop_others(
    conn: AsyncSerialConnection,
) -> None:
    """One bad entity callback must not prevent the rest from updating.

    Without this the read loop would also be at risk, since _process_response
    runs inside it.
    """
    calls: list[str] = []

    def bad(_zone: int, _state: Any) -> None:
        calls.append("bad")
        msg = "entity blew up"
        raise RuntimeError(msg)

    def good(_zone: int, _state: Any) -> None:
        calls.append("good")

    conn.add_listener(bad)
    conn.add_listener(good)
    conn._process_response("ZN01,SRC01,GRP0,VOL-30")  # must not raise
    assert "good" in calls
