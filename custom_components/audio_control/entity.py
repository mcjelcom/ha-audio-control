"""Base entity for Audio Control integration.

All platform entities inherit from this to share device_info and common attributes.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .serial_manager import SerialManager


class AudioControlEntity(Entity):
    """Base class for Audio Control entities.

    Provides shared device_info, availability, and common attributes.
    """

    # The modern HA pattern: HA composes the displayed name as
    # "<device name> <entity name>", so each entity sets only its own part.
    # Previously this was False with _attr_name = f"{profile_name} {zone_name}",
    # which stuttered on the device page -- every row under a device already
    # titled "AMC X86 / X86i" read "AMC X86 / X86i Zone 1".
    #
    # Entity IDs are deliberately UNCHANGED: each subclass supplies
    # suggested_object_id so the registry keeps producing
    # media_player.amc_x86_x86i_zone_1. Without that, adopting has_entity_name
    # would rename every entity to media_player.<device_slug>_zone_1 and break
    # users' dashboards and automations on upgrade.
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SerialManager, profile_name: str) -> None:
        """Initialize base entity."""
        self._manager = manager
        self._profile_name = profile_name
        # Slug the entity id would have had under the old naming scheme.
        self._legacy_object_id: str | None = None

    @property
    def suggested_object_id(self) -> str | None:
        """Preserve the pre-has_entity_name entity id.

        HA only consults this when the entity is first registered, so existing
        installs keep their ids regardless; it protects NEW installs from getting
        different ids to old ones, which would make dashboards non-portable and
        documentation wrong.
        """
        return self._legacy_object_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info shared by all entities of this device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._manager.entry_id)},
            name=self._profile_name,
            manufacturer="Audio Control",
            model=self._profile_name,
        )

    @property
    def available(self) -> bool:
        """Return True if device is connected."""
        return self._manager.connected
