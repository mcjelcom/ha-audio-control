"""Regression tests for the failure-recovery machinery in connection.py.

The uncovered third of connection.py was almost entirely recovery code -- the
only part of the file whose bugs are permanent rather than transient. A review
found four confirmed defects in it; all four were reproduced against the real
class before being fixed, and each test below fails on the pre-fix code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import pytest
import rs232_protocol.connection as conn_mod
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection

TEXT_PROFILE: dict[str, Any] = {
    "name": "Recovery",
    "zones": 2,
    "sources": 2,
    "serial": {
        "command_suffix": "\r",
        "response_terminator": "\r",
        "response_timeout_s": 0.05,
    },
    "commands": {
        "status": "?{zone}",
        "volume_set": "VS{zone}{volume:02d}",
        "volume_up": "VU{zone}",
        "volume_down": "VD{zone}",
        "power_on": "PO{zone}",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d)V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 38},
}


class StubWriter:
    """Minimal StreamWriter stand-in that records what was sent."""

    def __init__(self, *, close_error: Exception | None = None) -> None:
        self.written: list[bytes] = []
        self._close_error = close_error

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        if self._close_error:
            raise self._close_error

    async def wait_closed(self) -> None:
        return None


def make_conn(profile: dict[str, Any] | None = None) -> AsyncSerialConnection:
    return AsyncSerialConnection(
        port="socket://127.0.0.1:1",
        engine=create_engine(profile or TEXT_PROFILE),
        demo_mode=False,
    )


# ─── Bug 1: read loop spun forever on persistent engine errors ───────────────


async def test_persistent_engine_errors_break_read_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device whose frames always crash the engine must trigger a reconnect.

    consecutive_errors was reset right after read() rather than after a full
    successful iteration, so read-success -> reset -> raise -> increment meant
    the counter never passed 1. The `> 5` break was unreachable dead code and the
    loop spun at one traceback per second, forever, with no reconnect scheduled.
    """
    engine = create_engine(TEXT_PROFILE)

    def boom(_buf: bytes) -> tuple[list[bytes], bytes]:
        msg = "engine cannot parse this device"
        raise ValueError(msg)

    engine.extract_frames = boom  # type: ignore[method-assign]

    conn = AsyncSerialConnection(port="x", engine=engine, demo_mode=False)
    scheduled: list[int] = []
    conn._schedule_reconnect = lambda: scheduled.append(1)  # type: ignore[method-assign]

    class Reader:
        async def read(self, _n: int) -> bytes:
            await asyncio.sleep(0.001)
            return b"garbage\r"

    conn._reader = Reader()  # type: ignore[assignment]

    with caplog.at_level(logging.CRITICAL):  # suppress the expected tracebacks
        # Must terminate on its own. The 6 x 1s backoff sleeps dominate.
        await asyncio.wait_for(conn._read_loop(), timeout=20)

    assert scheduled, "no reconnect scheduled after persistent read errors"
    assert conn.connected is False


async def test_error_counter_resets_after_a_good_iteration(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An intermittent glitch must not accumulate toward the break.

    Guards against over-correcting bug 1 by never resetting: a device with one
    bad frame every few reads would otherwise eventually disconnect itself.

    The error path sleeps 1s, so the loop's own backoff is patched out -- with it
    in place only a handful of iterations fit in a test-sized window and the
    reset would never be observed.
    """
    engine = create_engine(TEXT_PROFILE)
    calls = {"n": 0}
    real_extract = engine.extract_frames

    def flaky(buf: bytes) -> tuple[list[bytes], bytes]:
        calls["n"] += 1
        if calls["n"] % 3 == 0:  # one bad frame in three
            msg = "intermittent"
            raise ValueError(msg)
        return real_extract(buf)

    engine.extract_frames = flaky  # type: ignore[method-assign]
    conn = AsyncSerialConnection(port="x", engine=engine, demo_mode=False)
    scheduled: list[int] = []
    conn._schedule_reconnect = lambda: scheduled.append(1)  # type: ignore[method-assign]

    class Reader:
        async def read(self, _n: int) -> bytes:
            await asyncio.sleep(0)
            return b"Z1V20\r"

    conn._reader = Reader()  # type: ignore[assignment]

    real_sleep = asyncio.sleep
    monkeypatch.setattr(conn_mod.asyncio, "sleep", lambda _d: real_sleep(0))

    with caplog.at_level(logging.CRITICAL):
        task = asyncio.create_task(conn._read_loop())
        await real_sleep(0.2)
        task.cancel()
        # The loop catches CancelledError and breaks, but cancellation can also
        # land on an inner await (read(), the patched sleep) and propagate out of
        # the task. Both are correct shutdowns, so suppress it rather than
        # asserting on which one happened -- awaiting the task bare here made
        # this test fail intermittently under full-suite load.
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

    # Many more than 6 errors will have occurred, but never 6 in a row.
    assert calls["n"] > 20, f"loop barely ran ({calls['n']} iterations)"
    assert not scheduled, "intermittent errors should not force a reconnect"


# ─── Bug 3: half-open link mistaken for a successful reconnect ───────────────


async def test_reconnect_keeps_retrying_a_mute_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A port that opens but never replies is NOT a successful reconnect.

    _connected only means "the port opened". A status probe that times out is
    caught inside _wait_for_response, so it never reaches the handler that would
    clear _connected -- the reconnect loop therefore returned satisfied, leaving
    entities showing stale state, available=True, and no pending retry. This is
    the realistic socket:// case after a Wi-Fi drop or NAT timeout.
    """
    monkeypatch.setattr(conn_mod, "RECONNECT_DELAY_FAST", 0.02)
    conn = make_conn()
    opens: list[int] = []

    async def fake_open(**_kw: Any) -> tuple[Any, Any]:
        opens.append(1)
        return asyncio.StreamReader(), StubWriter()  # opens, never answers

    monkeypatch.setattr(
        conn_mod.serial_asyncio, "open_serial_connection", fake_open, raising=False
    )

    conn._schedule_reconnect()
    await asyncio.sleep(0.6)
    attempts = len(opens)
    await conn.disconnect()

    assert attempts > 1, f"gave up after {attempts} mute open(s)"
    assert conn._device_responded is False


async def test_reconnect_stops_when_device_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive case: a real reply ends the retry loop.

    Pairs with the test above so the fix cannot be "retry forever".
    """
    monkeypatch.setattr(conn_mod, "RECONNECT_DELAY_FAST", 0.02)
    conn = make_conn()
    opens: list[int] = []

    async def fake_open(**_kw: Any) -> tuple[Any, Any]:
        opens.append(1)
        reader = asyncio.StreamReader()
        # Feed a parseable status reply so the probe correlates.
        reader.feed_data(b"Z1V20\r" * 4)
        return reader, StubWriter()

    monkeypatch.setattr(
        conn_mod.serial_asyncio, "open_serial_connection", fake_open, raising=False
    )

    conn._schedule_reconnect()
    await asyncio.sleep(0.4)
    attempts = len(opens)
    await conn.disconnect()

    assert attempts == 1, f"kept retrying a live device ({attempts} opens)"


# ─── Bug 4: disconnect() leaked the transport when close() raised ────────────


async def test_disconnect_completes_when_close_raises() -> None:
    """An unplugged USB adapter makes close() raise; unload must still finish.

    close() sat outside the try, so OSError escaped disconnect() -> escaped
    async_unload_entry -> HA left the entry half-unloaded with _writer set and
    _connected True, and a reload stacked a second connection on the first.
    Unplug-during-reload is an ordinary user action.
    """
    conn = make_conn()
    conn._writer = StubWriter(close_error=OSError("device removed"))  # type: ignore[assignment]
    conn._connected = True

    await conn.disconnect()  # must not raise

    assert conn._writer is None
    assert conn._reader is None
    assert conn.connected is False


async def test_disconnect_is_idempotent() -> None:
    conn = make_conn()
    conn._writer = StubWriter()  # type: ignore[assignment]
    conn._connected = True
    await conn.disconnect()
    await conn.disconnect()  # must not raise
    assert conn._writer is None


# ─── Bug 2: retry re-sent relative commands ──────────────────────────────────


async def test_relative_command_is_never_retried() -> None:
    """volume_up must hit the wire exactly once even with retry_count set.

    Retries fire on "no correlated reply in time", but a device that acted on the
    command and merely replied slowly would receive it twice -- double-stepping
    the volume. send_command still returns False afterwards, so the caller rolls
    the UI back while the device sits two steps higher.

    19 of the 24 shipped profiles define volume_up/volume_down. No profile sets
    retry_count today, so this was latent -- a trap for the next profile author.
    """
    profile = {
        **TEXT_PROFILE,
        "serial": {**TEXT_PROFILE["serial"], "retry_count": 2},
    }
    conn = make_conn(profile)
    writer = StubWriter()
    conn._writer = writer  # type: ignore[assignment]
    conn._connected = True

    result = await conn.send_command("volume_up", zone=1)

    assert result is False  # nothing replied
    assert len(writer.written) == 1, (
        f"volume_up sent {len(writer.written)}x -- would double-step the volume"
    )


async def test_absolute_command_still_retries() -> None:
    """Idempotent commands SHOULD retry; the fix must not disable retry wholesale."""
    profile = {
        **TEXT_PROFILE,
        "serial": {**TEXT_PROFILE["serial"], "retry_count": 2},
    }
    conn = make_conn(profile)
    writer = StubWriter()
    conn._writer = writer  # type: ignore[assignment]
    conn._connected = True

    await conn.send_command("volume_set", zone=1, volume=20)

    assert len(writer.written) == 3, (
        f"volume_set sent {len(writer.written)}x, expected 1 + 2 retries"
    )


@pytest.mark.parametrize(
    "command", ["volume_up", "volume_down", "power_toggle", "mute_toggle"]
)
def test_relative_commands_are_all_declared(command: str) -> None:
    """The exclusion list must cover every relative command, not just volume."""
    assert command in conn_mod._NON_IDEMPOTENT_COMMANDS


# ─── Contract pins for the recovery machinery ────────────────────────────────


async def test_refresh_loop_exits_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 60s poll loop must stop on shutdown rather than outliving the entry."""
    monkeypatch.setattr(conn_mod, "STATE_REFRESH_INTERVAL", 0.01)
    conn = make_conn()
    conn._connected = True
    conn._writer = StubWriter()  # type: ignore[assignment]

    task = asyncio.create_task(conn._periodic_refresh())
    await asyncio.sleep(0.05)
    conn._shutting_down = True
    await asyncio.wait_for(task, timeout=2)  # must exit unaided


async def test_backoff_switches_from_fast_to_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fast retries (x10) then slow, so an off-by-one on the boundary is caught."""
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)  # do not actually wait

    monkeypatch.setattr(conn_mod.asyncio, "sleep", spy_sleep)

    async def always_fail(**_kw: Any) -> tuple[Any, Any]:
        msg = "unreachable"
        raise OSError(msg)

    monkeypatch.setattr(
        conn_mod.serial_asyncio, "open_serial_connection", always_fail, raising=False
    )

    conn = make_conn()
    task = asyncio.create_task(conn._reconnect_loop())
    await real_sleep(0.2)
    conn._shutting_down = True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    fast = conn_mod.RECONNECT_DELAY_FAST
    slow = conn_mod.RECONNECT_DELAY_SLOW
    reconnect_delays = [d for d in delays if d in (fast, slow)]
    assert reconnect_delays[:3] == [fast, fast, fast]
    if len(reconnect_delays) > conn_mod.MAX_FAST_RECONNECT_ATTEMPTS:
        assert reconnect_delays[conn_mod.MAX_FAST_RECONNECT_ATTEMPTS] == slow


async def test_duplicate_reconnects_create_one_task() -> None:
    """Concurrent schedule calls must not spawn competing reconnect loops."""
    conn = make_conn()
    for _ in range(5):
        conn._schedule_reconnect()
    task = conn._reconnect_task
    assert task is not None
    for _ in range(5):
        conn._schedule_reconnect()
    assert conn._reconnect_task is task
    await conn.disconnect()


async def test_shutdown_suppresses_reconnect() -> None:
    """No reconnect may be scheduled once shutting down (HA stop)."""
    conn = make_conn()
    conn._shutting_down = True
    conn._schedule_reconnect()
    assert conn._reconnect_task is None
