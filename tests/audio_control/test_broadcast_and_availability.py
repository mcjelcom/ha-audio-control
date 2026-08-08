"""Global-service broadcast semantics, and availability after a mid-session drop.

Three defects, all of which only appear once something has already gone wrong --
which is exactly when the integration needs to behave predictably.

1. `_broadcast` raised HomeAssistantError from inside its `for manager in
   capable` loop. With two amplifiers configured, a failure on the first meant
   the second was never commanded at all. "All zones off" leaving half the house
   playing is worse than a clean error, because the error names one device while
   silently skipping the rest.

2. The same error surfaced the raw profile flag name -- "This device does not
   support has_all_off." The per-entity handlers already pass prose ("tone
   controls"), so this was also internally inconsistent.

3. Two of the six sites that clear `_connected` did not notify listeners.
   `AudioControlEntity.available` reads `manager.connected`, so entities kept
   reporting available=True and their last-known volume after the link dropped.
   HA only re-reads `available` when told to, so nothing self-corrected until the
   next successful poll.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import rs232_protocol.connection as conn_mod
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection

from custom_components.audio_control.const import DOMAIN

# Minimal profile with all_off support, used for both broadcast targets.
ALL_OFF_PROFILE: dict[str, Any] = {
    "name": "BroadcastTest",
    "zones": 2,
    "sources": 2,
    "serial": {"command_suffix": "\r", "response_terminator": "\r"},
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PON",
        "power_off": "Z{zone:02d}POFF",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "mute_on": "Z{zone:02d}MUON",
        "mute_off": "Z{zone:02d}MUOFF",
        "source_set": "Z{zone:02d}SRC{source:02d}",
        "all_off": "ZALLPWR00",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 62},
    "features": {"has_all_off": True, "has_tone_controls": False},
}

NO_ALL_OFF_PROFILE: dict[str, Any] = {
    **ALL_OFF_PROFILE,
    "name": "NoAllOff",
    "commands": {
        k: v for k, v in ALL_OFF_PROFILE["commands"].items() if k != "all_off"
    },
    "features": {"has_all_off": False, "has_tone_controls": False},
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def add_device(
    hass: HomeAssistant, suffix: str, profile: dict[str, Any]
) -> MockConfigEntry:
    """Add one demo-mode device so multiple can coexist in a single hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{profile['name']} {suffix} (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "num_zones": 2,
            "num_sources": 2,
            "custom_profile": profile,
        },
        unique_id=f"ac_demo_{suffix}",
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ─── Broadcast must reach every capable device ───────────────────────────────


async def test_all_zones_off_reaches_every_device(hass: HomeAssistant) -> None:
    """Both amplifiers must be commanded, not just the first."""
    a = await add_device(hass, "a", ALL_OFF_PROFILE)
    b = await add_device(hass, "b", ALL_OFF_PROFILE)

    send_a = AsyncMock(return_value=True)
    send_b = AsyncMock(return_value=True)
    with (
        patch.object(a.runtime_data, "async_send_command", new=send_a),
        patch.object(b.runtime_data, "async_send_command", new=send_b),
    ):
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)

    send_a.assert_awaited_once()
    send_b.assert_awaited_once()


async def test_failure_on_first_device_still_commands_the_second(
    hass: HomeAssistant,
) -> None:
    """The core regression: an early failure must not abort the broadcast.

    Raising mid-loop left later devices untouched, so "all zones off" could
    leave half the house playing while reporting a single-device error.
    """
    a = await add_device(hass, "a", ALL_OFF_PROFILE)
    b = await add_device(hass, "b", ALL_OFF_PROFILE)

    send_a = AsyncMock(return_value=False)  # device A rejects
    send_b = AsyncMock(return_value=True)
    with (
        patch.object(a.runtime_data, "async_send_command", new=send_a),
        patch.object(b.runtime_data, "async_send_command", new=send_b),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)

    send_b.assert_awaited_once(), "device B was skipped after A failed"


async def test_failure_is_still_reported(hass: HomeAssistant) -> None:
    """Completing the loop must not swallow the error.

    Without this, "keep going" could be implemented by ignoring failures --
    leaving the user with no signal that a device did not respond.
    """
    a = await add_device(hass, "a", ALL_OFF_PROFILE)
    with (
        patch.object(
            a.runtime_data, "async_send_command", new=AsyncMock(return_value=False)
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)


async def test_incapable_devices_are_skipped_not_failed(hass: HomeAssistant) -> None:
    """A device without all_off must be passed over, not reported as failing."""
    capable = await add_device(hass, "cap", ALL_OFF_PROFILE)
    incapable = await add_device(hass, "incap", NO_ALL_OFF_PROFILE)

    send_cap = AsyncMock(return_value=True)
    send_incap = AsyncMock(return_value=True)
    with (
        patch.object(capable.runtime_data, "async_send_command", new=send_cap),
        patch.object(incapable.runtime_data, "async_send_command", new=send_incap),
    ):
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)

    send_cap.assert_awaited_once()
    send_incap.assert_not_awaited()


async def test_no_capable_device_message_is_human_readable(
    hass: HomeAssistant,
) -> None:
    """The error must not leak the raw profile flag name.

    "This device does not support has_all_off." is developer text. The
    per-entity handlers already pass prose such as "tone controls", so this was
    inconsistent as well as unfriendly.
    """
    await add_device(hass, "incap", NO_ALL_OFF_PROFILE)
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(DOMAIN, "all_zones_off", {}, blocking=True)

    placeholders = excinfo.value.translation_placeholders or {}
    feature = placeholders.get("feature", "")
    assert "has_" not in feature, f"raw flag name leaked: {feature!r}"
    assert feature, "no feature placeholder supplied"


# ─── Availability must follow a mid-session link drop ────────────────────────


def make_conn(notified: list[int]) -> AsyncSerialConnection:
    """A live-looking connection recording every zone notification.

    The library-level API is add_listener(cb) with cb(zone, state); the zone
    filtering that HA entities rely on lives in SerialManager.register_listener.
    """
    conn = AsyncSerialConnection(
        port="socket://127.0.0.1:1",
        engine=create_engine(ALL_OFF_PROFILE),
        demo_mode=False,
    )
    conn._connected = True
    conn.add_listener(lambda zone, _state: notified.append(zone))
    return conn


class Writer:
    """StreamWriter stub whose drain() fails, as a dropped socket does."""

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        msg = "connection reset by peer"
        raise OSError(msg)

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


async def test_send_failure_notifies_listeners(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OSError on send clears _connected, so entities must be told.

    AudioControlEntity.available reads manager.connected, but HA only re-reads it
    when a state write is requested. Without the notify, every entity kept
    showing available=True and its last-known volume after the link dropped.
    """
    notified: list[int] = []
    conn = make_conn(notified)
    conn._writer = Writer()  # type: ignore[assignment]
    monkeypatch.setattr(conn, "_schedule_reconnect", lambda: None)

    result = await conn.send_command("volume_set", zone=1, volume=20)

    assert result is False
    assert conn.connected is False
    assert notified, "listeners were not notified when the link dropped"
    # Every zone must be refreshed, not just the one that was being commanded:
    # a dropped link makes the whole device unavailable.
    assert set(notified) == {1, 2}


async def test_persistent_read_errors_notify_listeners(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The consecutive-error bail-out path must notify too.

    The OSError branch of the read loop already did; the generic
    >5-consecutive-errors branch next to it did not, so a device whose frames
    always crash the engine went unavailable internally but stayed "available"
    in the UI.
    """
    notified: list[int] = []
    engine = create_engine(ALL_OFF_PROFILE)

    def boom(_buf: bytes) -> tuple[list[bytes], bytes]:
        msg = "engine cannot parse this device"
        raise ValueError(msg)

    engine.extract_frames = boom  # type: ignore[method-assign]
    conn = AsyncSerialConnection(port="x", engine=engine, demo_mode=False)
    conn._connected = True
    conn.add_listener(lambda zone, _state: notified.append(zone))
    monkeypatch.setattr(conn, "_schedule_reconnect", lambda: None)

    class Reader:
        async def read(self, _n: int) -> bytes:
            await asyncio.sleep(0)
            return b"garbage\r"

    conn._reader = Reader()  # type: ignore[assignment]

    # The error path sleeps 1s per iteration; six of those would dominate the
    # test, so the loop's own backoff is patched out.
    real_sleep = asyncio.sleep
    monkeypatch.setattr(conn_mod.asyncio, "sleep", lambda _d: real_sleep(0))

    with caplog.at_level(logging.CRITICAL):  # suppress the expected tracebacks
        await asyncio.wait_for(conn._read_loop(), timeout=10)

    assert conn.connected is False
    assert notified, "listeners were not notified after persistent read errors"


# ─── The zone-1 assumption the connection sensor depends on ──────────────────


def test_zone_one_always_exists() -> None:
    """AudioControlConnectionSensor registers its listener against zone 1.

    SerialManager's listener API is zone-filtered with no connection-level
    channel, so the sensor picks zone 1. That relies on zone 1 existing for every
    profile -- pinned here because the sensor would silently stop updating if it
    ever did not, with no error anywhere.
    """
    from rs232_protocol.profile_loader import load_builtin_profiles

    for name, profile in load_builtin_profiles().items():
        conn = AsyncSerialConnection(
            port="demo", engine=create_engine(profile), demo_mode=True
        )
        assert 1 in conn.zones, f"{name} has no zone 1"


async def test_connection_drop_notifies_zone_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the assumption: drops must reach zone 1 specifically.

    _notify_all() covers every zone today. A future change that notified only
    the zone being commanded would leave the connection sensor stuck on "on".
    """
    notified: list[int] = []
    conn = make_conn(notified)
    conn._writer = Writer()  # type: ignore[assignment]
    monkeypatch.setattr(conn, "_schedule_reconnect", lambda: None)

    # Command zone 2, so a zone-scoped notification would not include zone 1.
    await conn.send_command("volume_set", zone=2, volume=20)

    assert 1 in notified, "connection sensor's zone would not have been updated"
