"""Zone-prefix detection must recover from a missed first reply.

Found on a real AMC X86i (haac-tw, 2026-11-06 rollout): the first `status`
probe (prefix `ZN`) timed out at boot, connect() switched to the fallback `Z`,
and the X86i answers `?` to every `*Z01STA00`. Detection was only ever re-run
by the reconnect loop, which a `?` reply never triggers -- the port stays open
and the device keeps "answering" -- so every command failed with "Check the
device connection" until the config entry was reloaded.

The fake amplifier reproduces the captured traffic (TX `*Z01STA00\r` -> RX
`?\r`; `ZN` -> `#ZN01,SRC..,GRP0,VOL-..\r`). The tests drive the REAL connect()
and periodic refresh against the SHIPPED AMC X86 profile, which sends each
status once (no retry_count).
"""

from __future__ import annotations

import asyncio
import copy
import re
from typing import Any

import pytest
from rs232_protocol import connection as connection_module
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles

STATUS = re.compile(rb"^\*(ZN|Z)(\d{2})STA00\r$")
TIMEOUT = 0.1  # response_timeout_s for the test profile
# Longer than a whole connect(), so the refresh loop never probes while
# connect() is still probing -- as in production (60 s refresh).
REFRESH = 1.0


class FakeX86i:
    """StreamWriter stand-in that answers like the real amplifier."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        *,
        drop_first: int = 0,
        slow_writes: int = 0,
        slow_delay: float = 0.0,
    ) -> None:
        self.reader = reader
        self.drop = drop_first
        self.slow_writes = slow_writes
        self.slow_delay = slow_delay
        self.written: list[bytes] = []

    @staticmethod
    def reply_for(data: bytes) -> bytes:
        m = STATUS.match(data)
        if m and m.group(1) == b"ZN":
            return b"#ZN" + m.group(2) + b",SRC01,GRP0,VOL-30\r"
        return b"?\r"  # what the X86i says to `Z` commands

    def write(self, data: bytes) -> None:
        self.written.append(data)
        if self.drop:
            self.drop -= 1  # a missed reply: noise, amp still settling, ...
            return
        reply = self.reply_for(data)
        if self.slow_writes:
            # Amp still booting: the reply arrives after the integration gave up.
            self.slow_writes -= 1
            asyncio.get_running_loop().call_later(
                self.slow_delay, self.reader.feed_data, reply
            )
        else:
            self.reader.feed_data(reply)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def fast_amc_profile() -> dict[str, Any]:
    """The shipped profile, with its delays shortened for the test."""
    profile = copy.deepcopy(load_builtin_profiles()["AMC X86 / X86i"])
    assert "retry_count" not in profile["serial"]  # the field case: no resend
    profile["serial"]["command_delay_ms"] = 5
    profile["serial"]["response_timeout_s"] = TIMEOUT
    return profile


@pytest.fixture
def amp_factory(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the serial layer. Set `kwargs` before connect(); read `amp` after."""
    holder: dict[str, Any] = {"kwargs": {}}

    class FakeSerialAsyncio:
        @staticmethod
        async def open_serial_connection(
            **_: Any,
        ) -> tuple[asyncio.StreamReader, FakeX86i]:
            reader = asyncio.StreamReader()
            amp = FakeX86i(reader, **holder["kwargs"])
            holder["amp"] = amp
            return reader, amp

    monkeypatch.setattr(connection_module, "serial_asyncio", FakeSerialAsyncio)
    monkeypatch.setattr(connection_module, "STATE_REFRESH_INTERVAL", REFRESH)
    return holder


async def connect() -> AsyncSerialConnection:
    conn = AsyncSerialConnection(
        port="/dev/ttyUSB0", engine=create_engine(fast_amc_profile()), demo_mode=False
    )
    await conn.connect()
    return conn


async def wait_until_zone1_known(conn: AsyncSerialConnection, budget: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while loop.time() < deadline:
        if conn.zones[1].power_known:
            return True
        await asyncio.sleep(0.02)
    return conn.zones[1].power_known


async def wait_until_prefix_confirmed(
    conn: AsyncSerialConnection, budget: float
) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while loop.time() < deadline:
        if not conn._zone_prefix_unconfirmed():
            return True
        await asyncio.sleep(0.02)
    return not conn._zone_prefix_unconfirmed()


async def test_missed_first_reply_recovers_correct_prefix(
    amp_factory: dict[str, Any],
) -> None:
    """The field case: one missed `ZN` reply must not strand the amp on `Z`.

    Fails on the old code, which stayed on `Z` (`*Z01STA00` -> `?` forever).
    """
    amp_factory["kwargs"] = {"drop_first": 1}
    conn = await connect()
    try:
        amp: FakeX86i = amp_factory["amp"]
        assert amp.written[:2] == [b"*ZN01STA00\r", b"*Z01STA00\r"]  # as on haac-tw
        assert not conn.zones[1].power_known  # connect() alone did not recover
        assert await wait_until_zone1_known(conn, 3 * REFRESH), (
            f"zone 1 never got a status reply; last writes: {amp.written[-3:]}"
        )
        assert await conn.send_command("status", zone=2) is True
        assert amp.written[-1].startswith(b"*ZN02")
    finally:
        await conn.disconnect()


async def test_late_reply_does_not_lock_the_wrong_prefix(
    amp_factory: dict[str, Any],
) -> None:
    """A slow amp's late `ZN` reply, landing during the `Z` probe, must not lock `Z`.

    The status pattern accepts both `ZN01` and `Z01`, so a late reply parses as
    a success for whichever probe is waiting. Locking on it recreates the
    original dead end permanently (a locked prefix is never re-probed).
    """
    amp_factory["kwargs"] = {"slow_writes": 2, "slow_delay": TIMEOUT * 1.5}
    conn = await connect()
    try:
        amp: FakeX86i = amp_factory["amp"]
        # The late reply still updates zone 1's state, so "zone 1 known" is not
        # enough; wait for detection itself to settle.
        assert await wait_until_prefix_confirmed(conn, 4 * REFRESH)
        assert await conn.send_command("status", zone=3) is True
        assert amp.written[-1].startswith(b"*ZN03")
    finally:
        await conn.disconnect()


async def test_locked_prefix_survives_missed_replies(
    amp_factory: dict[str, Any],
) -> None:
    """Guard (passes before and after the fix): a confirmed prefix is kept."""
    conn = await connect()
    try:
        amp: FakeX86i = amp_factory["amp"]
        assert await wait_until_zone1_known(conn, 1.0)
        amp.drop = 2
        assert await conn._probe_zone_prefix() is False  # both replies missed
        amp.drop = 0
        assert await conn.send_command("status", zone=1) is True
        assert amp.written[-1].startswith(b"*ZN01")
        assert not any(w.startswith(b"*Z0") for w in amp.written)
    finally:
        await conn.disconnect()
