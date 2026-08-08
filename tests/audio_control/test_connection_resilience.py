"""Regression tests for SEC-004..011: connection resilience.

These cover the failure modes that leave the integration permanently broken
rather than merely erroring once -- the class of bug the previous suite could not
see, because every test ran in demo mode where send_command always returns True.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection

TEXT_PROFILE: dict[str, Any] = {
    "name": "T",
    "zones": 6,
    "sources": 6,
    "serial": {"command_suffix": "\r", "response_terminator": "\r"},
    "commands": {"status": "?{zone}", "power_on": "P{zone}"},
    "response": {
        "status_pattern": r"Z(?P<zone>\d)V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 38},
}

AMC_PREFIX_PROFILE: dict[str, Any] = {
    "name": "AmcLike",
    "zones": 6,
    "sources": 8,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "zone_prefix": "ZN",
    "zone_prefix_fallback": "Z",
    "commands": {"status": "{zp}{zone:02d}STA00"},
    "response": {
        "status_pattern": r"ZN(?P<zone>\d{2}),VOL-(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 62, "inverted": True},
}


def make_conn(profile: dict[str, Any]) -> AsyncSerialConnection:
    return AsyncSerialConnection(
        port="socket://127.0.0.1:1", engine=create_engine(profile), demo_mode=False
    )


class StubWriter:
    """Minimal StreamWriter stand-in."""

    def __init__(self, *, drain_error: Exception | None = None) -> None:
        self.written: list[bytes] = []
        self.closed = False
        self._drain_error = drain_error

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        if self._drain_error:
            raise self._drain_error

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


# ─── SEC-007: only parsed responses may confirm a command ────────────────────


async def test_unparsed_line_does_not_confirm_command() -> None:
    """A boot banner / noise line must not satisfy a pending command.

    Accepting it as an ACK is what locked the wrong zone prefix in permanently.
    """
    conn = make_conn(TEXT_PROFILE)
    conn._writer = StubWriter()  # type: ignore[assignment]
    conn._connected = True

    # Queue only an unparseable line, then let the wait time out.
    conn._response_queue.put_nowait("BOOTING v1.2")
    result = await conn._wait_for_response("status", expected_zone=1)
    assert result is False


async def test_parsed_matching_zone_confirms() -> None:
    """The positive case still works -- guards against over-tightening."""
    conn = make_conn(TEXT_PROFILE)
    conn._writer = StubWriter()  # type: ignore[assignment]
    conn._connected = True

    conn._response_queue.put_nowait("Z1V20")
    assert await conn._wait_for_response("status", expected_zone=1) is True


async def test_error_sentinel_fails_fast() -> None:
    conn = make_conn(TEXT_PROFILE)
    conn._response_queue.put_nowait("__ERROR__")
    assert await conn._wait_for_response("status", expected_zone=1) is False


# ─── SEC-011: the wait timeout is a total budget, not per-message ────────────


async def test_timeout_is_total_not_per_message() -> None:
    """A chatty device must not extend the wait indefinitely.

    Previously the timeout reset on every arrival, so max_mismatches messages
    could hold _command_lock for 10x response_timeout.
    """
    conn = make_conn(TEXT_PROFILE)
    conn._writer = StubWriter()  # type: ignore[assignment]
    conn._connected = True

    # Feed a steady stream of responses for the WRONG zone.
    async def flood() -> None:
        for _ in range(50):
            await conn._response_queue.put("Z5V20")
            await asyncio.sleep(0.01)

    flood_task = asyncio.create_task(flood())
    loop = asyncio.get_running_loop()
    start = loop.time()
    result = await conn._wait_for_response("status", expected_zone=1)
    elapsed = loop.time() - start
    flood_task.cancel()

    assert result is False
    # response_timeout defaults to 1.5s; must not approach 10 * 1.5 = 15s.
    assert elapsed < 4.0, f"held the lock for {elapsed:.1f}s"


# ─── SEC-007: zone-prefix detection stays retryable ──────────────────────────


def test_prefix_switch_swaps_rather_than_discards() -> None:
    """Both candidates are retained so detection can be retried.

    Discarding the fallback made a transient first-probe timeout permanently
    strand the device on the wrong prefix.
    """
    engine = create_engine(AMC_PREFIX_PROFILE)
    assert engine.has_zone_prefix_fallback

    assert engine.switch_to_fallback_prefix() is True
    assert engine.format_command("status", zone=1) == "*Z01STA00\r"
    # The original candidate is still available, not thrown away.
    assert engine.has_zone_prefix_fallback

    assert engine.switch_to_fallback_prefix() is True
    assert engine.format_command("status", zone=1) == "*ZN01STA00\r"


def test_prefix_detection_can_be_reset() -> None:
    """A locked-in prefix can be re-detected on reconnect."""
    engine = create_engine(AMC_PREFIX_PROFILE)
    engine.lock_zone_prefix()
    assert engine.has_zone_prefix_fallback is False

    engine.reset_zone_prefix_detection()
    assert engine.has_zone_prefix_fallback is True


# ─── SEC-005: a failed connect must not leak tasks ───────────────────────────


async def test_failed_handshake_releases_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tasks and the writer are released when the handshake raises.

    HA awaits connect() before assigning runtime_data, so on a raise it has no
    manager and never calls disconnect() -- previously leaking two tasks and an
    fd per setup retry.
    """
    conn = make_conn(TEXT_PROFILE)
    writer = StubWriter(drain_error=OSError("half-open"))

    async def fake_open(**_kw: Any) -> tuple[Any, Any]:
        return asyncio.StreamReader(), writer

    import rs232_protocol.connection as conn_mod

    monkeypatch.setattr(
        conn_mod.serial_asyncio, "open_serial_connection", fake_open, raising=False
    )
    # Force the handshake to blow up after the tasks exist.
    monkeypatch.setattr(
        conn, "send_command", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x"))
    )

    with pytest.raises(RuntimeError):
        await conn.connect()

    assert conn._read_task is None
    assert conn._refresh_task is None
    assert conn._writer is None
    assert conn.connected is False
    # Crucially, reconnection is still possible.
    assert conn._shutting_down is False


# ─── SEC-010: listener list mutation during notify ───────────────────────────


def test_self_unregistering_listener_does_not_skip_others() -> None:
    """A callback that removes itself must not cause the next one to be skipped."""
    conn = make_conn(TEXT_PROFILE)
    called: list[str] = []

    def cb1(_z: int, _s: Any) -> None:
        called.append("cb1")
        remove1()

    def cb2(_z: int, _s: Any) -> None:
        called.append("cb2")

    remove1 = conn.add_listener(cb1)
    conn.add_listener(cb2)

    conn.notify_zone(1)
    assert called == ["cb1", "cb2"], f"listener skipped: {called}"


def test_remove_listener_is_idempotent() -> None:
    """Calling the remover twice must not raise ValueError."""
    conn = make_conn(TEXT_PROFILE)
    remove = conn.add_listener(lambda _z, _s: None)
    remove()
    remove()  # must not raise


# ─── SEC-004: malformed device data must not escape as a traceback ───────────


def test_json_engine_tolerates_non_numeric_zone_index() -> None:
    """A string/None "index" must not raise TypeError out of parse_response."""
    profile = {
        "name": "J",
        "protocol_type": "json",
        "zones": 8,
        "sources": 8,
        "commands": {
            "status": {"type": "get_outputvol", "value": [{"index": "{zone}"}]}
        },
        "response": {},
        "volume": {"min": 0, "max": 100},
    }
    engine = create_engine(profile)
    for bad in (
        '{"type":"x","status":200,"value":[{"index":"1"}]}',
        '{"type":"x","status":200,"value":[{"index":null}]}',
        '{"type":"x","status":200,"value":[{"index":{}}]}',
    ):
        engine.parse_response(bad)  # must not raise


# ─── SEC-009: out-of-range parameters refuse rather than wrap ────────────────


def test_binary_out_of_range_volume_refuses() -> None:
    """volume=-1 previously became 0xFF (full attenuation on an inverted scale)."""
    profile = {
        "name": "B",
        "protocol_type": "binary",
        "zones": 4,
        "sources": 4,
        "commands": {"volume_set": {"opcode": "0x57", "data": ["{volume}", "{zone}"]}},
        "binary": {"start_byte": 0x55, "checksum": "mod256"},
        "volume": {"min": 0, "max": 80},
    }
    engine = create_engine(profile)
    assert engine.format_command("volume_set", zone=1, volume=-1) is None
    assert engine.format_command("volume_set", zone=1, volume=300) is None
    assert engine.format_command("volume_set", zone=1, volume=40) is not None


def test_binary_zone_zero_refuses() -> None:
    """zone=0 maps to -1, which bytes() rejected with an escaping ValueError."""
    profile = {
        "name": "B",
        "protocol_type": "binary",
        "zones": 4,
        "sources": 4,
        "commands": {"power_on": {"opcode": "0xA0", "data": ["{zone}"]}},
        "binary": {"start_byte": 0x55, "checksum": "mod256"},
    }
    engine = create_engine(profile)
    assert engine.format_command("power_on", zone=0) is None
    assert engine.format_command("power_on", zone=1) is not None


def test_binary_signed_tone_encodes_twos_complement() -> None:
    """Tone values are genuinely signed and must encode, not be rejected."""
    profile = {
        "name": "B",
        "protocol_type": "binary",
        "zones": 6,
        "sources": 6,
        "commands": {"bass_set": {"opcode": "0x20", "data": ["{zone}", "{level}"]}},
        "binary": {"start_byte": 0xF0, "end_byte": 0xF7, "checksum": "rnet"},
    }
    engine = create_engine(profile)
    cut = engine.format_command("bass_set", zone=1, level=-8)
    boost = engine.format_command("bass_set", zone=1, level=8)
    assert cut is not None
    assert boost is not None
    assert cut != boost
    assert 0xF8 in cut  # -8 as two's complement
