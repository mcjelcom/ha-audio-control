"""Diagnostics support for Audio Control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LOGIN_PASSWORD, CONF_LOGIN_USERNAME
from .serial_manager import SerialManager

# Keys to redact from config entry data and options.
# `custom_profile` is included because a user-supplied profile may carry a
# `json.login` block, and device credentials must not appear in a diagnostics
# download that people routinely paste into public issue trackers.
TO_REDACT = {
    "port",
    "username",
    "password",
    CONF_LOGIN_USERNAME,
    CONF_LOGIN_PASSWORD,
    "custom_profile",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    manager: SerialManager = entry.runtime_data

    zone_states = {}
    for zone_num, state in manager.zones.items():
        zone_states[str(zone_num)] = {
            "power": state.power,
            "source": state.source,
            "volume": state.volume,
            "mute": state.mute,
            "bass": state.bass,
            "treble": state.treble,
            "balance": state.balance,
            "group": state.group,
        }

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        # Options were previously dumped unredacted, which would have leaked any
        # credential override stored there.
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "connection": {
            "connected": manager.connected,
            "demo_mode": manager.demo_mode,
        },
        "device": {
            "profile_name": entry.title,
            "zones": manager.engine.num_zones,
            "sources": manager.engine.num_sources,
            "baud_rate": manager.engine.baud_rate,
            "volume_max": manager.engine.volume_max,
            "volume_inverted": manager.engine.volume_inverted,
            "features": manager.engine.features,
        },
        "zone_states": zone_states,
    }
