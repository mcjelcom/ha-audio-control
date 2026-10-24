"""Binary sensor platform for Audio Control - connection status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

try:
    # HA 2026.x defines it in binary_sensor.const and no longer exports it from
    # the package (still importable there, but not a public name).
    from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
except ImportError:  # pragma: no cover - older HA
    from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined]
        BinarySensorDeviceClass,
    )

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudioControlConfigEntry
from .entity import AudioControlEntity
from .serial_manager import SerialManager

# Connection state is read-only; no parallel update concern but be explicit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AudioControlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up connection status binary sensor."""
    manager: SerialManager = entry.runtime_data
    profile_name = entry.title.removesuffix(" (Demo)")

    async_add_entities([AudioControlConnectionSensor(manager, profile_name)])


class AudioControlConnectionSensor(AudioControlEntity, BinarySensorEntity):
    """Binary sensor showing device connection status.

    ON = connected, OFF = disconnected.
    Provides history graph of connection stability.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: SerialManager, profile_name: str) -> None:
        """Initialize connection sensor."""
        super().__init__(manager, profile_name)
        self._attr_unique_id = f"ac_{manager.entry_id}_connection"
        self._attr_name = "Connection"
        self._legacy_object_id = "Connection"

    @property
    def is_on(self) -> bool:
        """Return True if connection is active."""
        return self._manager.connected

    @property
    def available(self) -> bool:
        """Connection sensor is always available (it reports the connection state)."""
        return True

    async def async_added_to_hass(self) -> None:
        """Register for connection state changes.

        Registered against zone 1 because SerialManager's listener API is
        zone-filtered and there is no connection-level channel. That is sound
        rather than arbitrary: zone 1 always exists (zones are built as
        range(1, num_zones + 1) and num_zones >= 1), and every connect/disconnect
        transition calls _notify_all(), which covers all zones. Worth knowing if
        the notification model ever changes -- a connection event that notified
        only some zones would silently stop updating this sensor.
        """
        self._manager.register_listener(1, self._connection_changed)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister listener."""
        self._manager.unregister_listener(1, self._connection_changed)

    @callback
    def _connection_changed(self) -> None:
        """Handle connection state change."""
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        """Return extra attributes."""
        return {
            "serial_port": "demo" if self._manager.demo_mode else "(configured)",
            "demo_mode": self._manager.demo_mode,
        }
