"""Tests for the SerialManager HA adapter layer.

Since SerialManager is a thin wrapper over AsyncSerialConnection that adds
HA-specific listener semantics (zone-filtered, no-arg callbacks), we test
those semantics here using the library directly.

The full HA integration test (with homeassistant.config_entries, entity setup,
etc.) requires pytest-homeassistant-custom-component and runs in the Docker
container — not locally.
"""

from __future__ import annotations

import pytest
from rs232_protocol import AsyncSerialConnection, ProtocolEngine, ZoneState

from .conftest import MONOPRICE_PROFILE


class _ZoneFilteredListenerAdapter:
    """Simulates SerialManager's zone-filtered listener pattern.

    SerialManager wraps the library's (zone, state) callbacks into HA's
    no-arg callbacks filtered by zone number. This class validates that logic.
    """

    def __init__(self, conn: AsyncSerialConnection) -> None:
        self._conn = conn
        self._listener_map: dict[tuple[int, object], object] = {}

    def register_listener(self, zone: int, callback_fn) -> None:
        """Register a zone-filtered listener (HA style)."""

        def _wrapper(_zone: int, _state: ZoneState) -> None:
            if _zone == zone:
                callback_fn()

        remove_fn = self._conn.add_listener(_wrapper)
        self._listener_map[(zone, callback_fn)] = remove_fn

    def unregister_listener(self, zone: int, callback_fn) -> None:
        """Unregister a listener."""
        key = (zone, callback_fn)
        remove_fn = self._listener_map.pop(key, None)
        if remove_fn:
            remove_fn()


@pytest.fixture
def conn() -> AsyncSerialConnection:
    """Create a demo-mode connection."""
    engine = ProtocolEngine(MONOPRICE_PROFILE)
    return AsyncSerialConnection(port="demo", engine=engine, demo_mode=True)


@pytest.fixture
def adapter(conn: AsyncSerialConnection) -> _ZoneFilteredListenerAdapter:
    """Create the listener adapter."""
    return _ZoneFilteredListenerAdapter(conn)


class TestZoneFilteredListeners:
    """Test the zone-filtered listener pattern (the core of SerialManager)."""

    def test_listener_called_for_matching_zone(
        self,
        conn: AsyncSerialConnection,
        adapter: _ZoneFilteredListenerAdapter,
    ) -> None:
        """Listener for zone 1 is called when zone 1 changes."""
        calls: list[bool] = []
        adapter.register_listener(1, lambda: calls.append(True))
        conn.set_zone_power(1, True)
        assert len(calls) == 1

    def test_listener_not_called_for_other_zone(
        self,
        conn: AsyncSerialConnection,
        adapter: _ZoneFilteredListenerAdapter,
    ) -> None:
        """Listener for zone 1 is NOT called when zone 2 changes."""
        calls: list[bool] = []
        adapter.register_listener(1, lambda: calls.append(True))
        conn.set_zone_power(2, True)
        assert len(calls) == 0

    def test_multiple_zone_listeners(
        self,
        conn: AsyncSerialConnection,
        adapter: _ZoneFilteredListenerAdapter,
    ) -> None:
        """Multiple listeners for different zones work independently."""
        calls_z1: list[bool] = []
        calls_z3: list[bool] = []
        adapter.register_listener(1, lambda: calls_z1.append(True))
        adapter.register_listener(3, lambda: calls_z3.append(True))

        conn.set_zone_power(1, True)
        assert len(calls_z1) == 1
        assert len(calls_z3) == 0

        conn.set_zone_power(3, True)
        assert len(calls_z1) == 1
        assert len(calls_z3) == 1

    def test_unregister_stops_notifications(
        self,
        conn: AsyncSerialConnection,
        adapter: _ZoneFilteredListenerAdapter,
    ) -> None:
        """Unregistered listener stops receiving notifications."""
        calls: list[bool] = []
        callback = lambda: calls.append(True)  # noqa: E731
        adapter.register_listener(2, callback)
        conn.set_zone_power(2, True)
        assert len(calls) == 1

        adapter.unregister_listener(2, callback)
        conn.set_zone_power(2, False)
        assert len(calls) == 1  # No new call


class TestConnectionDemoLifecycle:
    """Test demo connection lifecycle (SerialManager delegates these)."""

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self, conn: AsyncSerialConnection) -> None:
        """Connect in demo mode sets connected."""
        await conn.connect()
        assert conn.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected(
        self, conn: AsyncSerialConnection
    ) -> None:
        """Disconnect clears connected."""
        await conn.connect()
        await conn.disconnect()
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_send_command_demo(self, conn: AsyncSerialConnection) -> None:
        """Demo send always succeeds."""
        await conn.connect()
        result = await conn.send_command("power_on", zone=1)
        assert result is True

    def test_zones_initialized(self, conn: AsyncSerialConnection) -> None:
        """Zones are initialized from engine."""
        assert len(conn.zones) == 6
        for i in range(1, 7):
            assert isinstance(conn.zones[i], ZoneState)


class TestZoneMutation:
    """Test zone state mutation through the connection."""

    def test_power_on(self, conn: AsyncSerialConnection) -> None:
        """Power on updates zone state."""
        conn.set_zone_power(3, True)
        assert conn.zones[3].power is True

    def test_power_off_resets_volume(self, conn: AsyncSerialConnection) -> None:
        """Power off resets volume (non-inverted = 0)."""
        conn.zones[2].volume = 20
        conn.zones[2].mute = False
        conn.set_zone_power(2, False)
        assert conn.zones[2].power is False
        assert conn.zones[2].mute is True
        assert conn.zones[2].volume == 0

    def test_rollback(self, conn: AsyncSerialConnection) -> None:
        """Rollback restores previous state."""
        conn.zones[4].power = True
        conn.zones[4].mute = False
        conn.zones[4].volume = 15
        conn.set_zone_power(4, False)
        conn.rollback_zone_power(4, True, False, 15)
        assert conn.zones[4].power is True
        assert conn.zones[4].volume == 15
