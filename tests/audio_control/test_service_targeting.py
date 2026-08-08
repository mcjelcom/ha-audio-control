"""Tone services must accept every target services.yaml advertises.

`services.yaml` declares `target: entity:`, so the Actions UI renders area,
device, floor and label pickers alongside the entity picker. The schemas were
closed (`vol.Schema({"entity_id": cv.entity_ids, "level": ...})`), and
`hass.services.async_call` merges the target into service_data -- so every picker
except "entity" failed with `extra keys not allowed`, as did `entity_id: all`.

Picking an area is the natural way to target "Kitchen", so roughly half the
controls HA rendered for these actions were non-functional. Nothing in the suite
covered it because every existing test passes an explicit entity list.

Also covers the ICU issue in the wizard descriptions: the HA frontend parses
translated strings with intl-messageformat, where a bare `{zone:02d}` is a
malformed argument and `(?P<zone>...)` is read as an XML tag. Those two strings
are the only documentation for the hardest wizard steps, so a parse failure left
the user with no guidance at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN
from custom_components.audio_control.services import (
    SERVICE_SET_BASS_SCHEMA,
    SERVICE_SET_TREBLE_SCHEMA,
)

COMPONENT = Path("custom_components/audio_control")


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


# ─── Schemas accept what the UI can produce ──────────────────────────────────


@pytest.mark.parametrize("schema", [SERVICE_SET_BASS_SCHEMA, SERVICE_SET_TREBLE_SCHEMA])
@pytest.mark.parametrize(
    "target",
    [
        {"entity_id": ["media_player.amc_zone_1"]},
        {"entity_id": "media_player.amc_zone_1"},
        {"area_id": ["kitchen"]},
        {"area_id": "kitchen"},
        {"device_id": ["abc123"]},
        {"floor_id": ["ground"]},
        {"label_id": ["speakers"]},
        {"entity_id": "all"},
        # A combined target, which the UI can also produce.
        {"entity_id": ["media_player.a"], "area_id": ["kitchen"]},
    ],
)
def test_every_advertised_target_kind_validates(
    schema: vol.Schema, target: dict[str, Any]
) -> None:
    """Each of these previously raised "extra keys not allowed"."""
    schema({**target, "level": 4})


@pytest.mark.parametrize("schema", [SERVICE_SET_BASS_SCHEMA, SERVICE_SET_TREBLE_SCHEMA])
def test_level_is_still_validated(schema: vol.Schema) -> None:
    """Widening the target must not weaken the level check.

    The devices accept a fixed step table; an out-of-range value would format
    into a command the amplifier rejects.
    """
    schema({"entity_id": ["media_player.a"], "level": -8})
    for bad in (1, 3, 9, -9, 100):
        with pytest.raises(vol.Invalid):
            schema({"entity_id": ["media_player.a"], "level": bad})


@pytest.mark.parametrize("schema", [SERVICE_SET_BASS_SCHEMA, SERVICE_SET_TREBLE_SCHEMA])
def test_level_is_still_required(schema: vol.Schema) -> None:
    with pytest.raises(vol.Invalid):
        schema({"entity_id": ["media_player.a"]})


# ─── Area targeting reaches the right entities end to end ────────────────────

PROFILE: dict[str, Any] = {
    "name": "TargetTest",
    "zones": 2,
    "sources": 2,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PON",
        "power_off": "Z{zone:02d}POFF",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "mute_on": "Z{zone:02d}MUON",
        "mute_off": "Z{zone:02d}MUOFF",
        "source_set": "Z{zone:02d}SRC{source:02d}",
        "bass_set": "Z{zone:02d}BAS{level:+d}",
        "treble_set": "Z{zone:02d}TRB{level:+d}",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    "volume": {"min": 0, "max": 62},
    "features": {"has_tone_controls": True},
}


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TargetTest (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "num_zones": 2,
            "num_sources": 2,
            "custom_profile": PROFILE,
        },
        unique_id="ac_demo_target",
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_area_target_reaches_the_zone(hass: HomeAssistant) -> None:
    """The core regression: an area target used to be rejected outright."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    zone_1 = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_1")
    )

    area = ar.async_get(hass).async_create("Kitchen")
    registry.async_update_entity(zone_1.entity_id, area_id=area.id)

    # Demo mode ACKs, so a resolved target must not raise.
    await hass.services.async_call(
        DOMAIN, "set_bass", {"area_id": area.id, "level": 4}, blocking=True
    )


async def test_device_target_reaches_the_zone(hass: HomeAssistant) -> None:
    """A device target must expand to that device's zone entities."""
    entry = await setup_entry(hass)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    await hass.services.async_call(
        DOMAIN, "set_treble", {"device_id": device.id, "level": -2}, blocking=True
    )


async def test_explicit_entity_target_still_works(hass: HomeAssistant) -> None:
    """The path every existing test uses must be unaffected."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    zone_1 = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_1")
    )
    await hass.services.async_call(
        DOMAIN, "set_bass", {"entity_id": zone_1.entity_id, "level": 0}, blocking=True
    )


async def test_area_with_no_matching_entities_does_not_crash(
    hass: HomeAssistant,
) -> None:
    """An empty area must fail cleanly, not with a traceback."""
    from homeassistant.exceptions import HomeAssistantError

    await setup_entry(hass)
    empty = ar.async_get(hass).async_create("Empty Room")
    # Either a clean HomeAssistantError or a no-op is acceptable; a raw
    # exception type other than HomeAssistantError is not.
    try:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"area_id": empty.id, "level": 4}, blocking=True
        )
    except HomeAssistantError:
        pass


# ─── Wizard descriptions must survive the frontend's ICU parser ──────────────


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((COMPONENT / name).read_text())
    return data


@pytest.mark.parametrize("filename", ["strings.json", "translations/en.json"])
def test_no_config_description_contains_icu_hostile_syntax(filename: str) -> None:
    """The frontend parses these with intl-messageformat, not str.format.

    Two failure modes shipped: a bare `{zone:02d}` is a MALFORMED_ARGUMENT (the
    colon starts a format spec ICU cannot parse), and `(?P<zone>\\d{2})` throws
    UNCLOSED_TAG because `<zone>` reads as an XML tag. Both strings were the sole
    documentation for the hardest wizard steps, so the user saw nothing.

    Exception messages are exempt: HA renders those with Python str.format.
    """
    steps = load(filename)["config"]["step"]
    offenders = {}
    for step_name, step in steps.items():
        text = step.get("description", "")
        # A brace group is only ICU-safe if it names a placeholder the flow
        # supplies; anything with a colon or non-identifier content is not.
        braces = re.findall(r"\{([^}]*)\}", text)
        bad_braces = [b for b in braces if not b.replace("_", "").isalnum()]
        # `<word>` is parsed as a tag.
        has_tag = bool(re.search(r"<[A-Za-z]", text))
        if bad_braces or has_tag:
            offenders[step_name] = {"braces": bad_braces, "tag": has_tag}
    assert not offenders, f"ICU-hostile descriptions: {offenders}"


def test_wizard_steps_still_document_their_fields() -> None:
    """Removing the braces must not remove the guidance.

    An empty description would technically pass the ICU check while leaving the
    user just as stranded, so assert the substance is still there.
    """
    steps = load("strings.json")["config"]["step"]
    commands = steps["custom_commands"]["description"].lower()
    for word in ("zone", "source", "volume"):
        assert word in commands, f"custom_commands no longer mentions {word}"
    response = steps["custom_response"]["description"].lower()
    for word in ("regular expression", "zone", "power", "mute"):
        assert word in response, f"custom_response no longer mentions {word}"
