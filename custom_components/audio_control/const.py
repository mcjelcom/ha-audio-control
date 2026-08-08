"""Constants for the Audio Control integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "audio_control"

CONF_DEVICE_PROFILE: Final = "device_profile"
CONF_BAUD_RATE: Final = "baud_rate"
CONF_NUM_ZONES: Final = "num_zones"
CONF_NUM_SOURCES: Final = "num_sources"
CONF_SOURCE_NAMES: Final = "source_names"
CONF_ZONE_NAMES: Final = "zone_names"
# Optional per-entry credential override for profiles whose `json.login` block
# ships vendor defaults (e.g. RTI admin/admin). Stored in entry options so a
# user who hardened their device password can still connect.
CONF_LOGIN_USERNAME: Final = "login_username"
CONF_LOGIN_PASSWORD: Final = "login_password"

DEMO_PORT: Final = "demo"
