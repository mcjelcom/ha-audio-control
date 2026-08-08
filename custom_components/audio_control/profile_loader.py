"""Profile loader - delegates to rs232_protocol library.

Adds HA-specific convention: custom profiles live in {config_dir}/audio_control/.
"""

from __future__ import annotations

import os
from typing import Any

from .rs232_protocol import (
    load_all_profiles as _load_all_profiles,
)
from .rs232_protocol import (
    load_builtin_profiles,
)

__all__ = [
    "get_profile_choices",
    "load_all_profiles",
    "load_builtin_profiles",
]

_CUSTOM_SUBDIR = "audio_control"


def _custom_dir(config_dir: str) -> str:
    """Return the HA-convention custom profiles directory path."""
    return os.path.join(config_dir, _CUSTOM_SUBDIR)


def load_all_profiles(config_dir: str) -> dict[str, dict[str, Any]]:
    """Load all profiles (built-in from library + custom from config dir)."""
    return _load_all_profiles(_custom_dir(config_dir))


def get_profile_choices(config_dir: str) -> list[str]:
    """Get sorted list of profile names for the config flow dropdown."""
    profiles = load_all_profiles(config_dir)
    return sorted(profiles.keys())
