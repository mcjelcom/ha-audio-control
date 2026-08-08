"""Tests for AsyncSerialConnection — the library's connection manager."""

from __future__ import annotations

import pytest
from rs232_protocol import AsyncSerialConnection, ProtocolEngine, ZoneState


class TestDemoMode:
    """Test demo mode (no real serial port)."""

    @pytest.fixture
    def conn(self, monoprice_engine: ProtocolEngine) -> AsyncSerialConnection:
        return AsyncSerialConnection(
            port="demo", engine=monoprice_engine, demo_mode=True
        )

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self, conn: AsyncSerialConnection) -> None:
        """Demo connect immediately sets connected."""
        await conn.connect()
        assert conn.connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, conn: AsyncSerialConnection) -> None:
        """Demo disconnect cleans up."""
        await conn.connect()
        await conn.disconnect()
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_send_command_succeeds(self, conn: AsyncSerialConnection) -> None:
        """Demo send always returns True."""
        await conn.connect()
        result = await conn.send_command("power_on", zone=1)
        assert result is True

    def test_zones_initialized(self, conn: AsyncSerialConnection) -> None:
        """Zones are initialized from engine num_zones."""
        assert len(conn.zones) == 6
        for i in range(1, 7):
            assert i in conn.zones
            assert isinstance(conn.zones[i], ZoneState)

    @pytest.mark.asyncio
    async def test_listener_notified_on_connect(
        self, conn: AsyncSerialConnection
    ) -> None:
        """Listeners are notified for all zones on connect."""
        notifications: list[int] = []

        def on_zone(zone: int, state: ZoneState) -> None:
            notifications.append(zone)

        conn.add_listener(on_zone)
        await conn.connect()
        assert sorted(notifications) == [1, 2, 3, 4, 5, 6]


class TestZoneStateMutation:
    """Test zone state changes."""

    @pytest.fixture
    def conn(self, monoprice_engine: ProtocolEngine) -> AsyncSerialConnection:
        return AsyncSerialConnection(
            port="demo", engine=monoprice_engine, demo_mode=True
        )

    def test_set_zone_power_on(self, conn: AsyncSerialConnection) -> None:
        """Power on updates zone state."""
        conn.set_zone_power(1, True)
        assert conn.zones[1].power is True

    def test_set_zone_power_off_resets_volume(
        self, monoprice_engine: ProtocolEngine
    ) -> None:
        """Power off resets volume to 0 (non-inverted profile)."""
        conn = AsyncSerialConnection(
            port="demo", engine=monoprice_engine, demo_mode=True
        )
        conn.zones[1].power = True
        conn.zones[1].volume = 20
        conn.set_zone_power(1, False)
        assert conn.zones[1].power is False
        assert conn.zones[1].mute is True
        assert conn.zones[1].volume == 0  # Non-inverted: 0 = silent

    def test_set_zone_power_off_inverted(self, amc_engine: ProtocolEngine) -> None:
        """Power off with inverted volume resets to max (62)."""
        conn = AsyncSerialConnection(port="demo", engine=amc_engine, demo_mode=True)
        conn.zones[1].power = True
        conn.zones[1].volume = 20
        conn.set_zone_power(1, False)
        assert conn.zones[1].volume == 62  # Inverted: 62 = mute

    def test_rollback_zone_power(self, conn: AsyncSerialConnection) -> None:
        """Rollback restores previous state."""
        conn.zones[2].power = True
        conn.zones[2].mute = False
        conn.zones[2].volume = 15
        conn.set_zone_power(2, False)  # Optimistic off
        conn.rollback_zone_power(2, True, False, 15)  # Rollback
        assert conn.zones[2].power is True
        assert conn.zones[2].mute is False
        assert conn.zones[2].volume == 15


class TestListenerManagement:
    """Test add/remove listeners."""

    @pytest.fixture
    def conn(self, monoprice_engine: ProtocolEngine) -> AsyncSerialConnection:
        return AsyncSerialConnection(
            port="demo", engine=monoprice_engine, demo_mode=True
        )

    def test_add_and_remove_listener(self, conn: AsyncSerialConnection) -> None:
        """Listener can be added and removed."""
        calls: list[int] = []

        def on_zone(zone: int, state: ZoneState) -> None:
            calls.append(zone)

        remove = conn.add_listener(on_zone)
        conn.set_zone_power(1, True)
        assert 1 in calls

        calls.clear()
        remove()
        conn.set_zone_power(2, True)
        assert calls == []

    def test_multiple_listeners(self, conn: AsyncSerialConnection) -> None:
        """Multiple listeners all get notified."""
        calls_a: list[int] = []
        calls_b: list[int] = []

        conn.add_listener(lambda z, s: calls_a.append(z))
        conn.add_listener(lambda z, s: calls_b.append(z))

        conn.set_zone_power(3, True)
        assert 3 in calls_a
        assert 3 in calls_b

    def test_listener_exception_doesnt_break_others(
        self, conn: AsyncSerialConnection
    ) -> None:
        """A failing listener doesn't prevent others from being called."""
        calls: list[int] = []

        def bad_listener(zone: int, state: ZoneState) -> None:
            raise RuntimeError("oops")

        def good_listener(zone: int, state: ZoneState) -> None:
            calls.append(zone)

        conn.add_listener(bad_listener)
        conn.add_listener(good_listener)
        conn.set_zone_power(1, True)
        assert 1 in calls


class TestResponseProcessing:
    """Test response processing logic in the connection."""

    @pytest.fixture
    def conn(self, amc_engine: ProtocolEngine) -> AsyncSerialConnection:
        return AsyncSerialConnection(port="demo", engine=amc_engine, demo_mode=True)

    def test_process_status_response(self, conn: AsyncSerialConnection) -> None:
        """Status response updates zone state."""
        conn._process_response("ZN03,SRC05,GRP0,VOL-25")
        assert conn.zones[3].source == 5
        assert conn.zones[3].volume == 25

    def test_process_global_all_off(self, conn: AsyncSerialConnection) -> None:
        """Global all-off sets all zones power=False."""
        for z in conn.zones.values():
            z.power = True
        conn._process_response("ZALLOFF")
        for z in conn.zones.values():
            assert z.power is False
            assert z.mute is True

    def test_process_global_mute_on(self, conn: AsyncSerialConnection) -> None:
        """Global mute sets all zones mute=True."""
        for z in conn.zones.values():
            z.mute = False
        conn._process_response("ZALLMON")
        for z in conn.zones.values():
            assert z.mute is True

    def test_process_error(self, conn: AsyncSerialConnection) -> None:
        """Error response enqueues __ERROR__."""
        conn._process_response("?")
        msg = conn._response_queue.get_nowait()
        assert msg == "__ERROR__"

    def test_process_unknown_response(self, conn: AsyncSerialConnection) -> None:
        """Unknown response is enqueued raw."""
        conn._process_response("SOMETHING_WEIRD")
        msg = conn._response_queue.get_nowait()
        assert msg == "SOMETHING_WEIRD"

    def test_zone_listener_notified(self, conn: AsyncSerialConnection) -> None:
        """Zone state change notifies listeners."""
        notifications: list[int] = []
        conn.add_listener(lambda z, s: notifications.append(z))
        conn._process_response("ZN02,SRC04,GRP1,VOL-10")
        assert 2 in notifications
