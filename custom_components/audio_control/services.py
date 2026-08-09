"""Service handlers for Audio Control integration.

All five services are registered unconditionally -- HA services are global, not
per-entry, and with several devices configured a registration-time gate would
have to be the union of every profile's capabilities anyway. Capability is
therefore checked per CALL, against both the profile's feature flag and the
presence of the underlying command:

- set_bass / set_treble: has_tone_controls AND bass_set / treble_set
- all_zones_off:         has_all_off       AND all_off
- group_mode_on/off:     has_group_mode    AND group_on / group_off

Checking the flag alone was not enough: ten of the 26 shipped profiles declare a
has_* flag with no matching command, so the call reached send_command, which
returned False and reported "command failed -- check device connection" for a
device that simply lacks the feature.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

try:
    # HA 2025.x moved target expansion out of helpers.service into
    # helpers.target. Importing only from helpers.service made the WHOLE
    # integration fail to load on 2026.8.1 with "cannot import name
    # async_extract_referenced_entity_ids" -- every entity went unavailable.
    # The local test harness pins HA 2024.12.5, where it still lives in
    # helpers.service, so the suite could not see this.
    from homeassistant.helpers.target import async_extract_referenced_entity_ids
except ImportError:  # pragma: no cover - depends on HA version
    # No `type: ignore` here: which branch type-checks depends on the installed
    # HA, so a blanket ignore is "unused" on one version and required on the
    # other. mypy resolves whichever path exists in the pinned harness.
    from homeassistant.helpers.service import (
        async_extract_referenced_entity_ids,
    )

from .const import DOMAIN
from .serial_manager import SerialManager

_LOGGER = logging.getLogger(__name__)

# Human-readable names for the profile feature flags used by global services.
# The flag name itself reached the user verbatim -- "This device does not support
# has_all_off." -- while the per-entity handlers already passed prose such as
# "tone controls".
_FEATURE_LABELS = {
    "has_all_off": "turning all zones off",
    "has_group_mode": "group mode",
    "has_tone_controls": "tone controls",
}

# Tone levels the devices accept, per the profiles' own step tables.
_TONE_LEVEL = vol.All(vol.Coerce(int), vol.In([-8, -6, -4, -2, 0, 2, 4, 6, 8]))

# Service schemas. `cv.TARGET_SERVICE_FIELDS` admits area_id / device_id /
# floor_id / label_id alongside entity_id: services.yaml advertises
# `target: entity:`, so the Actions UI renders all of those pickers, but a closed
# schema rejected every one with "extra keys not allowed". Picking an area -- the
# natural way to target "Kitchen" -- simply failed, as did `entity_id: all`.
# Annotated explicitly: mypy --strict cannot infer the key type through a `**`
# spread of TARGET_SERVICE_FIELDS, whose keys are vol.Marker objects.
_TONE_SCHEMA_DICT: dict[Any, Any] = {
    **cv.TARGET_SERVICE_FIELDS,
    vol.Required("level"): _TONE_LEVEL,
}

SERVICE_SET_BASS_SCHEMA = vol.Schema(_TONE_SCHEMA_DICT)
SERVICE_SET_TREBLE_SCHEMA = vol.Schema(_TONE_SCHEMA_DICT)

SERVICE_GROUP_MODE_ON_SCHEMA = vol.Schema(
    {
        vol.Required("source"): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
    }
)


def _get_manager_and_zone(
    hass: HomeAssistant, entity_id: str
) -> tuple[SerialManager | None, int | None]:
    """Resolve entity_id to its SerialManager and zone number."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if not entry or not entry.unique_id or not entry.config_entry_id:
        return None, None

    # unique_id format: ac_{entry_id}_zone_{N}
    if "_zone_" not in entry.unique_id:
        return None, None

    try:
        zone_num = int(entry.unique_id.rsplit("_zone_", 1)[1])
    except (ValueError, IndexError):
        return None, None

    # Get manager from config entry runtime_data
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry and hasattr(config_entry, "runtime_data"):
        manager = config_entry.runtime_data
        if isinstance(manager, SerialManager):
            return manager, zone_num

    return None, None


def _resolve_targets(hass: HomeAssistant, call: ServiceCall) -> list[str]:
    """Expand a service call's target into audio_control media_player entity ids.

    services.yaml advertises `target: entity:`, so the Actions UI renders area,
    device, floor and label pickers in addition to the entity picker. The
    handlers previously read `call.data["entity_id"]` directly, which meant every
    other picker -- and `entity_id: all` -- failed with "extra keys not allowed".

    async_extract_referenced_entity_ids does the expansion HA does for entity
    platform services, including `all`. The result is filtered to this
    integration's own media_player entities so that targeting a whole area
    containing unrelated players does not produce spurious not_valid_zone errors.
    """
    referenced = async_extract_referenced_entity_ids(hass, call, expand_group=True)
    candidates = referenced.referenced | referenced.indirectly_referenced
    registry = er.async_get(hass)
    ours = []
    for entity_id in candidates:
        entry = registry.async_get(entity_id)
        if entry and entry.platform == DOMAIN and entry.domain == "media_player":
            ours.append(entity_id)
    # An explicit entity target that is not ours must still reach the handler, so
    # it can raise not_valid_zone rather than being silently dropped.
    if not ours:
        return sorted(referenced.referenced)
    return sorted(ours)


def _get_all_managers(hass: HomeAssistant) -> list[SerialManager]:
    """All loaded SerialManagers, for global (device-wide) commands.

    Global services carry no target, so with multiple amplifiers configured we
    apply the command to every one rather than an arbitrary first entry -- which
    previously silenced only whichever device HA enumerated first, unstably
    across restarts.
    """
    managers: list[SerialManager] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        manager = getattr(entry, "runtime_data", None)
        if isinstance(manager, SerialManager):
            managers.append(manager)
    return managers


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for Audio Control.

    Guards against double-registration on reload.
    """
    if hass.services.has_service(DOMAIN, "set_bass"):
        return

    async def handle_set_bass(call: ServiceCall) -> None:
        """Handle set_bass service."""
        level = int(call.data["level"])
        entity_ids = _resolve_targets(hass, call)

        for entity_id in entity_ids:
            manager, zone_num = _get_manager_and_zone(hass, entity_id)
            if not manager or zone_num is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="not_valid_zone",
                    translation_placeholders={"entity_id": entity_id},
                )
            # Both the flag AND the command must be present. Ten of the 26
            # profiles declare has_tone_controls / has_group_mode / has_balance
            # without the matching command, so a flag-only gate let the call
            # through to send_command, which returned False and surfaced
            # "command failed -- check device connection" for a device that
            # simply has no tone control.
            if not (
                manager.engine.features.get("has_tone_controls")
                and manager.engine.has_command("bass_set")
            ):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="feature_unsupported",
                    translation_placeholders={"feature": "tone controls"},
                )
            # Pass the signed level through; the protocol engine encodes it for
            # the profile's template style (sign+magnitude, :+d, or offset).
            success = await manager.async_send_command(
                "bass_set", zone=zone_num, level=level
            )
            if not success:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={
                        "command": "set_bass",
                        "zone": str(zone_num),
                    },
                )

    async def handle_set_treble(call: ServiceCall) -> None:
        """Handle set_treble service."""
        level = int(call.data["level"])
        entity_ids = _resolve_targets(hass, call)

        for entity_id in entity_ids:
            manager, zone_num = _get_manager_and_zone(hass, entity_id)
            if not manager or zone_num is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="not_valid_zone",
                    translation_placeholders={"entity_id": entity_id},
                )
            # Both the flag AND the command must be present. Ten of the 26
            # profiles declare has_tone_controls / has_group_mode / has_balance
            # without the matching command, so a flag-only gate let the call
            # through to send_command, which returned False and surfaced
            # "command failed -- check device connection" for a device that
            # simply has no tone control.
            if not (
                manager.engine.features.get("has_tone_controls")
                and manager.engine.has_command("treble_set")
            ):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="feature_unsupported",
                    translation_placeholders={"feature": "tone controls"},
                )
            success = await manager.async_send_command(
                "treble_set", zone=zone_num, level=level
            )
            if not success:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={
                        "command": "set_treble",
                        "zone": str(zone_num),
                    },
                )

    async def _broadcast(command: str, feature: str, **kwargs: object) -> None:
        """Send a global command to every loaded device that supports it."""
        managers = _get_all_managers(hass)
        if not managers:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="integration_unavailable",
            )
        # Only devices whose profile advertises the feature AND defines the
        # command. Filtering on the flag alone did not achieve what the comment
        # claimed: RTI AD-810 and Russound RNET both set has_group_mode without
        # group_on/group_off, so they passed the filter and then produced exactly
        # the misleading "command failed" this was meant to avoid.
        capable = [
            m
            for m in managers
            if m.engine.features.get(feature) and m.engine.has_command(command)
        ]
        if not capable:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="feature_unsupported",
                translation_placeholders={
                    "feature": _FEATURE_LABELS.get(feature, feature)
                },
            )
        # Command every capable device before reporting, then raise once. Raising
        # from inside the loop meant a failure on the first amplifier left the
        # rest untouched -- "all zones off" could leave half the house playing
        # while naming only one device in the error.
        failed = [
            manager
            for manager in capable
            if not await manager.async_send_command(command, **kwargs)
        ]
        if failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={
                    "command": command,
                    "zone": f"all ({len(failed)} of {len(capable)} devices)",
                },
            )

    async def handle_all_zones_off(_call: ServiceCall) -> None:
        """Handle all_zones_off service (all devices with all-off support)."""
        await _broadcast("all_off", "has_all_off")

    async def handle_group_mode_on(call: ServiceCall) -> None:
        """Handle group_mode_on service (all devices with group support)."""
        await _broadcast("group_on", "has_group_mode", source=int(call.data["source"]))

    async def handle_group_mode_off(_call: ServiceCall) -> None:
        """Handle group_mode_off service (all devices with group support)."""
        await _broadcast("group_off", "has_group_mode")

    hass.services.async_register(
        DOMAIN, "set_bass", handle_set_bass, schema=SERVICE_SET_BASS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_treble", handle_set_treble, schema=SERVICE_SET_TREBLE_SCHEMA
    )
    hass.services.async_register(DOMAIN, "all_zones_off", handle_all_zones_off)
    hass.services.async_register(
        DOMAIN,
        "group_mode_on",
        handle_group_mode_on,
        schema=SERVICE_GROUP_MODE_ON_SCHEMA,
    )
    hass.services.async_register(DOMAIN, "group_mode_off", handle_group_mode_off)


_SERVICES = (
    "set_bass",
    "set_treble",
    "all_zones_off",
    "group_mode_on",
    "group_mode_off",
)


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services when the last config entry is removed."""
    if not hass.config_entries.async_entries(DOMAIN):
        for service in _SERVICES:
            hass.services.async_remove(DOMAIN, service)
