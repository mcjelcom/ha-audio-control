"""Audio Control integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)

from .const import CONF_DEVICE_PROFILE, CONF_LOGIN_PASSWORD, CONF_LOGIN_USERNAME
from .dashboard_writer import async_write_dashboard
from .profile_loader import load_all_profiles
from .rs232_protocol import AuthenticationError, create_engine
from .serial_manager import SerialManager
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.BINARY_SENSOR]

type AudioControlConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: AudioControlConfigEntry
) -> bool:
    """Set up Audio Control from a config entry."""
    profile_name = entry.data.get(CONF_DEVICE_PROFILE, "")
    port = entry.data.get("port", "demo")

    # Load the profile — either from library or inline custom
    if profile_name == "__custom__":
        profile = entry.data.get("custom_profile")
        if not profile:
            _LOGGER.error("Custom profile data missing from config entry")
            return False
    else:
        profiles = await hass.async_add_executor_job(
            load_all_profiles, hass.config.config_dir
        )
        profile = profiles.get(profile_name)
        if not profile:
            _LOGGER.error("Profile '%s' not found", profile_name)
            return False

    # Apply any credential override before building the engine. Profiles ship
    # vendor defaults (RTI is admin/admin); a user who changed their device
    # password needs a way to supply the real one without editing the profile.
    profile = _apply_credential_override(profile, entry)

    # Create protocol engine and serial manager. Building the engine compiles the
    # profile's regexes, so a malformed profile raises here -- most plausibly a
    # hand-written YAML in {config}/audio_control/, which bypasses the config
    # flow's validation entirely because the loader only parses YAML. Previously
    # that escaped as a raw re.error out of async_setup_entry, which HA reports
    # as an unexplained traceback. ConfigEntryError marks the entry as failed
    # with a readable message and, unlike ConfigEntryNotReady, does not retry
    # forever on a fault that cannot fix itself.
    # Report the profile's own name rather than the "__custom__" sentinel, which
    # means nothing to the person reading the error.
    label = profile.get("name") or profile_name or "unknown"
    try:
        engine = create_engine(profile)
    except Exception as err:
        _LOGGER.error("Profile '%s' is not usable: %s", label, err)
        msg = f"Device profile '{label}' is invalid: {err}"
        raise ConfigEntryError(msg) from err

    manager = SerialManager(hass, port, engine, entry.entry_id)
    try:
        await manager.async_connect()
    except AuthenticationError as err:
        # Bad credentials cannot fix themselves, so retrying is pointless -- and
        # AuthenticationError previously fell into the generic handler below and
        # became ConfigEntryNotReady, which made HA retry the same wrong password
        # with backoff forever. That is precisely what the exception exists to
        # prevent. ConfigEntryAuthFailed instead triggers the reauth flow and
        # shows the user a "reconfigure credentials" prompt.
        await manager.async_disconnect()
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        # Release any partially-created reader/writer and background tasks, then
        # raise ConfigEntryNotReady so HA retries with backoff instead of leaving
        # the entry dead until a manual reload. Network bridges (socket://) are
        # commonly unreachable for a moment at HA startup.
        await manager.async_disconnect()
        msg = f"Could not connect to {port}"
        raise ConfigEntryNotReady(msg) from err

    entry.runtime_data = manager

    # Listen for options updates (zone/source name changes)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    # Must come after platform setup -- entities only exist in the registry once
    # the media_player platform has been forwarded. Reading the live registry
    # here avoids the .storage flush delay (10s running / 180s at startup) that
    # makes the boot-time generator race against HA.
    await async_write_dashboard(hass, entry)

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: AudioControlConfigEntry
) -> None:
    """Handle options update — reload integration to apply name changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: AudioControlConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_disconnect()
        await async_unload_services(hass)
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: AudioControlConfigEntry
) -> None:
    """Clean up when a config entry is removed.

    Currently no persistent data to clean, but this hook ensures proper
    lifecycle handling if we add stored state in the future.
    """
    _LOGGER.debug("Removed Audio Control entry: %s", entry.title)


def _apply_credential_override(
    profile: dict[str, Any], entry: ConfigEntry
) -> dict[str, Any]:
    """Return the profile with `json.login` replaced by entry-option credentials.

    Only applies to profiles that already declare a login block. Copies the
    nested dicts so the shared in-memory profile cache is not mutated -- other
    entries using the same profile must not inherit these credentials.
    """
    username = entry.options.get(CONF_LOGIN_USERNAME)
    password = entry.options.get(CONF_LOGIN_PASSWORD)
    if not username and not password:
        return profile

    json_cfg = profile.get("json")
    if not isinstance(json_cfg, dict) or "login" not in json_cfg:
        return profile

    login = dict(json_cfg["login"])
    if username:
        login["username"] = username
    if password:
        login["password"] = password

    merged = dict(profile)
    merged["json"] = {**json_cfg, "login": login}
    return merged


_UNIQUE_ID_PREFIX_MAP = (("rs232mz_", "ac_"), ("rs232a_", "ac_"))


def _to_current_prefix(unique_id: str | None) -> str | None:
    """Return unique_id rewritten to the ac_ prefix, or None if unchanged."""
    if not unique_id:
        return None
    for old, new in _UNIQUE_ID_PREFIX_MAP:
        if unique_id.startswith(old):
            return unique_id.replace(old, new, 1)
    return None


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate a config entry (and its entities) to the current version.

    Version history:
    - 1: Initial (may have rs232mz_ or rs232a_ unique IDs)
    - 2: Standardized on rs232a_ prefix, added binary_sensor platform
    - 3: Renamed domain to audio_control, unique IDs use ac_ prefix
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    # A downgrade (entry newer than this code understands) must not be treated as
    # a successful migration -- HA would then set up an entry with an unknown
    # schema. Refuse it.
    if config_entry.version > 3:
        _LOGGER.error(
            "Cannot downgrade Audio Control entry from version %d to 3",
            config_entry.version,
        )
        return False

    if config_entry.version == 3:
        return True

    _LOGGER.info(
        "Migrating Audio Control entry '%s' from version %d to 3",
        config_entry.title,
        config_entry.version,
    )

    # Config entry unique_id.
    new_entry_uid = _to_current_prefix(config_entry.unique_id)
    hass.config_entries.async_update_entry(
        config_entry,
        unique_id=new_entry_uid or config_entry.unique_id,
        version=3,
    )
    if new_entry_uid:
        _LOGGER.info(
            "Migrated entry unique_id: %s -> %s",
            config_entry.unique_id,
            new_entry_uid,
        )

    # Entity registry unique_ids. Rewriting only the config entry left every
    # entity orphaned under its old rs232mz_/rs232a_ id, producing duplicate
    # entities and breaking automations/dashboards bound to the old ids.
    @callback
    def _migrate_entity(entity: er.RegistryEntry) -> dict[str, str] | None:
        new_uid = _to_current_prefix(entity.unique_id)
        return {"new_unique_id": new_uid} if new_uid else None

    await er.async_migrate_entries(hass, config_entry.entry_id, _migrate_entity)

    return True
