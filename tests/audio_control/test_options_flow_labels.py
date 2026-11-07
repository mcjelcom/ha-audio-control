"""Every field on the rename (options) form must have a friendly label.

The options form builds its fields at runtime -- `zone_1`..`zone_N` and
`source_1`..`source_N` -- but strings.json only labelled the two credential
fields. HA falls back to the raw key for an unlabelled field, so users renaming
their zones saw `zone_1`, `source_1` instead of "Zone 1 name". Nothing warns:
the form works, it just looks broken (found on a live HA while taking docs
screenshots, 2026-11-02).

The test renders the real form for every built-in profile, plus the largest
custom-wizard device, and checks each field key has a label in BOTH strings.json
and translations/en.json (en.json is what HA actually serves).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.config_flow import (
    CUSTOM_SOURCE_CHOICES,
    CUSTOM_ZONE_CHOICES,
    LABELLED_MAX,
    _resolve_sources,
)
from custom_components.audio_control.const import DOMAIN

COMPONENT = Path("custom_components/audio_control")
LABEL_FILES = {
    "strings.json": COMPONENT / "strings.json",
    "en.json": COMPONENT / "translations" / "en.json",
}

PROFILES = load_builtin_profiles()

# The custom-device wizard's largest choices, read from the wizard itself so that
# raising them without adding labels fails here.
CUSTOM_MAX_ZONES = max(CUSTOM_ZONE_CHOICES)
CUSTOM_MAX_SOURCES = max(CUSTOM_SOURCE_CHOICES)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def option_labels(path: Path) -> dict[str, str]:
    """The `data` labels of the options flow's init step."""
    data: dict[str, Any] = json.loads(path.read_text())
    labels: dict[str, str] = data["options"]["step"]["init"]["data"]
    return labels


async def form_field_keys(
    hass: HomeAssistant, profile_name: str, zones: int, sources: int
) -> list[str]:
    """Open the real options form and return its field keys."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        unique_id=f"ac_labels_{zones}_{sources}",
        data={
            "port": "demo",
            "device_profile": profile_name,
            "num_zones": zones,
            "num_sources": sources,
        },
        version=3,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    keys = [str(marker.schema) for marker in result["data_schema"].schema]
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    return keys


def assert_labelled(keys: list[str]) -> None:
    for file_name, path in LABEL_FILES.items():
        labels = option_labels(path)
        missing = [k for k in keys if k not in labels]
        assert not missing, f"{file_name}: no label for {missing}"
        raw = [k for k in keys if labels[k] == k]
        assert not raw, f"{file_name}: label is just the key for {raw}"


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
async def test_every_profile_form_field_is_labelled(
    hass: HomeAssistant, profile_name: str
) -> None:
    """The form a user of each shipped profile sees has no raw field names."""
    profile = PROFILES[profile_name]
    sources, _ = _resolve_sources(profile)
    keys = await form_field_keys(
        hass, profile_name, int(profile.get("zones", 6)), sources
    )
    assert any(k.startswith("zone_") for k in keys)
    assert_labelled(keys)


async def test_largest_custom_device_form_is_labelled(hass: HomeAssistant) -> None:
    """A custom-wizard device can have more zones than any shipped profile."""
    keys = await form_field_keys(
        hass, "__custom__", CUSTOM_MAX_ZONES, CUSTOM_MAX_SOURCES
    )
    assert_labelled(keys)


def test_label_files_agree() -> None:
    """A label fixed in only one file would not reach users (or hassfest)."""
    labels = [option_labels(p) for p in LABEL_FILES.values()]
    assert labels[0] == labels[1]


@pytest.mark.parametrize("path", LABEL_FILES.values(), ids=LABEL_FILES.keys())
def test_labels_cover_one_to_labelled_max(path: Path) -> None:
    """User YAML profiles have no size limit, so labels cover a generous range.

    Every reviewer of the first version (labels 1..16, the largest built-in
    profile) pointed out that a user profile in config/audio_control/ could
    exceed it and show raw keys again. The range must be gap-free: one missing
    index would show a single raw `zone_N` in an otherwise friendly form.
    """
    labels = option_labels(path)
    for kind in ("zone", "source"):
        indices = sorted(
            int(k.removeprefix(f"{kind}_")) for k in labels if k.startswith(f"{kind}_")
        )
        assert indices == list(range(1, LABELLED_MAX + 1)), kind
    largest = max(
        max(int(p.get("zones", 6)), _resolve_sources(p)[0]) for p in PROFILES.values()
    )
    assert max(CUSTOM_ZONE_CHOICES + CUSTOM_SOURCE_CHOICES + [largest]) <= LABELLED_MAX
