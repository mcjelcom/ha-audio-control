"""Tests for the published automation blueprints (blueprints/ at the repo root).

Blueprints are YAML consumed by HA at runtime, so nothing else in the test
suite would catch a typo'd service name or a `!input` with no matching
definition. These tests validate them against HA's own blueprint schema and
check that every service they call actually exists in services.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.util.yaml import loader as hass_yaml

import custom_components.audio_control

BLUEPRINT_DIR = (
    Path(__file__).resolve().parents[2] / "blueprints" / "automation" / "audio_control"
)
# Derived from the installed package rather than hardcoded, so it survives the
# integration moving (it is now at custom_components/ for the HACS layout).
SERVICES_YAML = Path(custom_components.audio_control.__file__).parent / "services.yaml"

BLUEPRINT_FILES = sorted(BLUEPRINT_DIR.glob("*.yaml"))

# Representative inputs per blueprint, used to exercise !input substitution.
SAMPLE_INPUTS: dict[str, dict[str, Any]] = {
    "all_zones_off_at_time.yaml": {
        "off_time": "23:30:00",
        "weekdays": ["mon", "fri"],
    },
    "volume_limiter.yaml": {
        "zones": ["media_player.amc_x86_x86i_zone_1"],
        "max_volume": 0.75,
    },
    "zone_auto_off_when_idle.yaml": {
        "zone": "media_player.amc_x86_x86i_zone_1",
        "idle_minutes": 90,
    },
    "group_mode_toggle.yaml": {
        "toggle_entity": "input_boolean.party_mode",
        "group_source": 2,
    },
    "scheduled_zone_on.yaml": {
        "zone": "media_player.amc_x86_x86i_zone_1",
        "on_time": "07:00:00",
        "weekdays": ["mon"],
        "volume": 0.3,
        "source": "Source 2",
        "settle_delay": 1,
    },
    "tone_preset_on_source.yaml": {
        "zone": "media_player.amc_x86_x86i_zone_2",
        "trigger_source": "Source 3",
        "active_bass": 6,
        "active_treble": 0,
        "restore_bass": 0,
        "restore_treble": 0,
    },
}


def _load(path: Path) -> Blueprint:
    """Load and schema-validate a blueprint the way HA does."""
    return Blueprint(
        hass_yaml.load_yaml(str(path)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


def _iter_service_calls(obj: object) -> list[str]:
    """Collect every service/action call in a substituted automation config."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if (
                str(key) in {"service", "action"}
                and isinstance(value, str)
                and "." in value
            ):
                found.append(value)
            found.extend(_iter_service_calls(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_iter_service_calls(item))
    return found


def test_blueprints_exist() -> None:
    assert BLUEPRINT_FILES, "no blueprints found -- did the directory move?"


@pytest.mark.parametrize("path", BLUEPRINT_FILES, ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path) -> None:
    """Each blueprint passes HA's own schema and declares all its inputs.

    Blueprint() raises if a `!input` is referenced without a matching
    definition, which is the most likely hand-editing mistake.
    """
    blueprint = _load(path)
    assert blueprint.domain == "automation"
    assert blueprint.inputs, f"{path.name} declares no inputs"


@pytest.mark.parametrize("path", BLUEPRINT_FILES, ids=lambda p: p.name)
def test_blueprint_has_sample_inputs(path: Path) -> None:
    """Every blueprint is covered by SAMPLE_INPUTS, so new ones get tested."""
    assert path.name in SAMPLE_INPUTS, (
        f"add {path.name} to SAMPLE_INPUTS so substitution is exercised"
    )


@pytest.mark.parametrize("path", BLUEPRINT_FILES, ids=lambda p: p.name)
def test_blueprint_substitutes(path: Path) -> None:
    """Inputs substitute cleanly and produce a usable automation config."""
    blueprint = _load(path)
    inputs = BlueprintInputs(
        blueprint,
        {"use_blueprint": {"path": path.name, "input": SAMPLE_INPUTS[path.name]}},
    )
    inputs.validate()
    config = inputs.async_substitute()

    # HA normalizes singular trigger/action into the plural form.
    assert config.get("triggers") or config.get("trigger")
    assert config.get("actions") or config.get("action")


@pytest.mark.parametrize("path", BLUEPRINT_FILES, ids=lambda p: p.name)
def test_blueprint_calls_only_real_services(path: Path) -> None:
    """Guard against typos in audio_control.* service names.

    A misspelled service is invisible until the automation fires, so it is
    checked here against services.yaml rather than trusted.
    """
    known = set(hass_yaml.load_yaml(str(SERVICES_YAML)))

    blueprint = _load(path)
    inputs = BlueprintInputs(
        blueprint,
        {"use_blueprint": {"path": path.name, "input": SAMPLE_INPUTS[path.name]}},
    )
    inputs.validate()

    called = _iter_service_calls(inputs.async_substitute())
    assert called, f"{path.name} substitutes to no service calls"

    for call in called:
        domain, _, service = call.partition(".")
        if domain == "audio_control":
            assert service in known, (
                f"{path.name} calls unknown service audio_control.{service}; "
                f"services.yaml defines {sorted(known)}"
            )


@pytest.mark.parametrize("path", BLUEPRINT_FILES, ids=lambda p: p.name)
def test_source_url_points_at_this_public_file(path: Path) -> None:
    """Re-import in HA fetches source_url; it must be this public repo's file.

    The copies first shipped with the deploy repo pointed at that PRIVATE repo,
    so a public user's re-import would 404.
    """
    text = path.read_text(encoding="utf-8")
    want = (
        "https://github.com/mcjelcom/ha-audio-control/blob/main/"
        f"blueprints/automation/audio_control/{path.name}"
    )
    assert f"source_url: {want}" in text
