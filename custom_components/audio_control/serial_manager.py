"""Home Assistant adapter for the serial/network connection.

Wraps AsyncSerialConnection from the library with HA-specific lifecycle methods
(async_connect/async_disconnect) and zone-filtered listener semantics.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEMO_PORT
from .rs232_protocol import (
    AsyncSerialConnection,
    BaseProtocolEngine,
    ZoneState,
)

__all__ = ["SerialManager"]


class SerialManager:
    """HA-specific wrapper around AsyncSerialConnection.

    Provides the same interface the integration expects while delegating
    all protocol and I/O logic to the library.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        port: str,
        engine: BaseProtocolEngine,
        entry_id: str,
    ) -> None:
        """Initialize the serial manager."""
        self.hass = hass
        self._entry_id = entry_id
        self._listener_map: dict[
            tuple[int, Callable[[], None]], Callable[[], None]
        ] = {}
        self._connection = AsyncSerialConnection(
            port=port,
            engine=engine,
            demo_mode=(port == DEMO_PORT),
        )

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connection.connected

    @property
    def zones(self) -> dict[int, ZoneState]:
        """Return zone state dict."""
        return self._connection.zones

    @property
    def engine(self) -> BaseProtocolEngine:
        """Return the protocol engine."""
        return self._connection.engine

    @property
    def entry_id(self) -> str:
        """Return the config entry ID."""
        return self._entry_id

    @property
    def demo_mode(self) -> bool:
        """Return whether running in demo mode (no real serial port)."""
        return self._connection.demo_mode

    # --- Zone State Mutation ------------------------------------------------

    def set_zone_power(self, zone: int, power: bool) -> None:
        """Optimistic power state update."""
        self._connection.set_zone_power(zone, power)

    def rollback_zone_power(
        self, zone: int, prev_power: bool, prev_mute: bool, prev_vol: int
    ) -> None:
        """Rollback a failed power state change."""
        self._connection.rollback_zone_power(zone, prev_power, prev_mute, prev_vol)

    # --- Listeners ----------------------------------------------------------

    def register_listener(self, zone: int, callback_fn: Callable[[], None]) -> None:
        """Register a zone state change listener (HA-style: no args).

        The library uses (zone, state) callbacks; this adapter filters by zone
        and calls the HA-style no-arg callback only for the registered zone.
        """

        def _wrapper(_zone: int, _state: ZoneState) -> None:
            if _zone == zone:
                callback_fn()

        remove_fn = self._connection.add_listener(_wrapper)
        self._listener_map[(zone, callback_fn)] = remove_fn

    def unregister_listener(self, zone: int, callback_fn: Callable[[], None]) -> None:
        """Unregister a listener."""
        key = (zone, callback_fn)
        remove_fn = self._listener_map.pop(key, None)
        if remove_fn:
            remove_fn()

    def notify_zone_update(self, zone: int) -> None:
        """Notify listeners of a zone state change (for optimistic updates)."""
        self._connection.notify_zone(zone)

    # --- Connection Lifecycle -----------------------------------------------

    async def async_connect(self) -> None:
        """Open serial connection."""
        await self._connection.connect()

    async def async_disconnect(self) -> None:
        """Close serial connection."""
        await self._connection.disconnect()

    # --- Commands -----------------------------------------------------------

    async def async_send_command(self, command_name: str, **kwargs: Any) -> bool:
        """Send a command to the device."""
        return await self._connection.send_command(command_name, **kwargs)
