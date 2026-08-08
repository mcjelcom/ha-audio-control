"""Profile loader for serial/network audio devices.

No Home Assistant dependency. Pure filesystem + YAML logic.
"""

from __future__ import annotations

import glob
import logging
import os
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger(__name__)

# Built-in profiles directory (relative to this package)
BUILTIN_PROFILES_DIR = Path(__file__).parent / "profiles"


def load_builtin_profiles() -> dict[str, dict[str, Any]]:
    """Load all built-in device profiles.

    Returns dict mapping display name to profile data.
    """
    profiles: dict[str, dict[str, Any]] = {}
    for yaml_file in sorted(BUILTIN_PROFILES_DIR.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue  # Skip template files
        try:
            with open(yaml_file) as f:
                profile = yaml.safe_load(f)
            if profile and "name" in profile:
                profiles[profile["name"]] = profile
                profiles[profile["name"]]["_file"] = str(yaml_file)
        except Exception as err:
            _LOGGER.warning("Failed to load profile %s: %s", yaml_file, err)
    return profiles


def load_custom_profiles(custom_dir: str) -> dict[str, dict[str, Any]]:
    """Load user-defined custom profiles from a directory.

    Args:
        custom_dir: Path to directory containing custom YAML profiles.

    Returns dict mapping display name to profile data.
    """
    profiles: dict[str, dict[str, Any]] = {}
    if not os.path.isdir(custom_dir):
        return profiles

    for yaml_file in sorted(glob.glob(os.path.join(custom_dir, "*.yaml"))):
        try:
            with open(yaml_file) as f:
                profile = yaml.safe_load(f)
            if profile and "name" in profile:
                name = f"{profile['name']} (Custom)"
                profiles[name] = profile
                profiles[name]["_file"] = yaml_file
        except Exception as err:
            _LOGGER.warning("Failed to load custom profile %s: %s", yaml_file, err)
    return profiles


def load_all_profiles(
    custom_dir: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load all profiles (built-in + optional custom directory).

    Args:
        custom_dir: Optional path to custom profiles directory.
            If None, only built-in profiles are loaded.

    Returns dict mapping display name to profile data.
    """
    profiles = load_builtin_profiles()
    if custom_dir:
        profiles.update(load_custom_profiles(custom_dir))
    return profiles


def get_profile_choices(custom_dir: str | None = None) -> list[str]:
    """Get sorted list of profile names for UI selection."""
    profiles = load_all_profiles(custom_dir)
    return sorted(profiles.keys())
