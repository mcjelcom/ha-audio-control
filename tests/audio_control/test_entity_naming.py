"""has_entity_name is adopted WITHOUT renaming anything.

`_attr_has_entity_name = False` plus `_attr_name = f"{profile} {zone}"` made every
row on the device page repeat the device's own title: under a device already
called "AMC X86 / X86i", the entities read "AMC X86 / X86i Zone 1" and "AMC X86 /
X86i Connection".

The modern pattern is has_entity_name = True with the entity naming only its own
part, letting HA compose "<device> <entity>". Done naively that RENAMES every
entity -- HA derives the object id from the device slug plus the entity name, so
`media_player.amc_x86_x86i_zone_1` would become something else and break users'
dashboards, automations and the shipped dashboard YAML.

`suggested_object_id` avoids that. I captured the entity ids and friendly names
before the change and compared after: both are byte-identical, so this is a
device-page presentation fix with no migration and no breakage.

One thing that had to be discovered rather than assumed: HA PREFIXES the device
slug onto suggested_object_id, so returning the old full name
("AMC X86 / X86i Zone 1") produced the doubled
`media_player.amc_x86_x86i_amc_x86_x86i_zone_1`. The suggestion must be the
entity-only part.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN

# Captured from the tree BEFORE the change, with the AMC X86 profile in demo mode.
EXPECTED: dict[str, str] = {
    "binary_sensor.amc_x86_x86i_connection": "AMC X86 / X86i Connection",
    "media_player.amc_x86_x86i_zone_1": "AMC X86 / X86i Zone 1",
    "media_player.amc_x86_x86i_zone_2": "AMC X86 / X86i Zone 2",
    "media_player.amc_x86_x86i_zone_3": "AMC X86 / X86i Zone 3",
    "media_player.amc_x86_x86i_zone_4": "AMC X86 / X86i Zone 4",
    "media_player.amc_x86_x86i_zone_5": "AMC X86 / X86i Zone 5",
    "media_player.amc_x86_x86i_zone_6": "AMC X86 / X86i Zone 6",
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def setup_amc(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AMC X86 / X86i (Demo)",
        unique_id="ac_demo",
        data={
            "port": "demo",
            "device_profile": "AMC X86 / X86i",
            "num_zones": 6,
            "num_sources": 8,
        },
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ─── Nothing the user can see or reference may change ────────────────────────


async def test_entity_ids_are_unchanged(hass: HomeAssistant) -> None:
    """The whole point: adopt the pattern without breaking references.

    These ids appear in users' dashboards and automations, and in the dashboard
    YAML this integration generates. A rename would silently break all of them.
    """
    entry = await setup_amc(hass)
    registry = er.async_get(hass)
    actual = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert actual == set(EXPECTED), (
        f"entity ids changed\n  added:   {sorted(actual - set(EXPECTED))}\n"
        f"  removed: {sorted(set(EXPECTED) - actual)}"
    )


async def test_friendly_names_are_unchanged(hass: HomeAssistant) -> None:
    """HA must compose the same displayed name it produced before.

    Guards the composition specifically: with has_entity_name the name is
    device + entity, so a wrong `_attr_name` shows up here rather than in the id.
    """
    await setup_amc(hass)
    for entity_id, expected_name in EXPECTED.items():
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} missing"
        assert state.attributes.get("friendly_name") == expected_name


async def test_object_id_is_not_doubled(hass: HomeAssistant) -> None:
    """Regression guard for the mistake I made first time.

    Returning the old FULL name from suggested_object_id gave
    `media_player.amc_x86_x86i_amc_x86_x86i_zone_1`, because HA prefixes the
    device slug itself. The suggestion must be the entity-only part.
    """
    entry = await setup_amc(hass)
    registry = er.async_get(hass)
    for e in er.async_entries_for_config_entry(registry, entry.entry_id):
        object_id = e.entity_id.split(".", 1)[1]
        assert "amc_x86_x86i_amc_x86_x86i" not in object_id, (
            f"device slug appears twice in {e.entity_id}"
        )


# ─── The stutter itself is gone ──────────────────────────────────────────────


async def test_entity_name_no_longer_repeats_the_device_name(
    hass: HomeAssistant,
) -> None:
    """On the device page HA shows `_attr_name` alone, so it must be short.

    This is the actual defect: the entity's own name used to include the profile,
    so every row under "AMC X86 / X86i" read "AMC X86 / X86i Zone 1".
    """
    entry = await setup_amc(hass)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    device_name = device.name
    assert device_name == "AMC X86 / X86i"

    component_names = []
    for entity_id in EXPECTED:
        domain = entity_id.split(".", 1)[0]
        entity = hass.data["entity_components"][domain].get_entity(entity_id)
        assert entity is not None
        component_names.append(entity.name)

    for name in component_names:
        assert isinstance(name, str)
        assert device_name not in name, (
            f"entity name {name!r} still repeats the device name"
        )


async def test_has_entity_name_is_enabled(hass: HomeAssistant) -> None:
    """The flag itself, since everything above depends on it.

    With it False, HA uses `_attr_name` verbatim and the short names would become
    the whole friendly name ("Zone 1"), losing the device context.
    """
    await setup_amc(hass)
    entity = hass.data["entity_components"]["media_player"].get_entity(
        "media_player.amc_x86_x86i_zone_1"
    )
    assert entity is not None
    assert entity.has_entity_name is True


# ─── Renamed zones and other profiles ────────────────────────────────────────


async def test_custom_zone_names_flow_through(hass: HomeAssistant) -> None:
    """A renamed zone must appear in both the id and the composed name."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AMC X86 / X86i (Demo)",
        unique_id="ac_demo_named",
        data={
            "port": "demo",
            "device_profile": "AMC X86 / X86i",
            "num_zones": 2,
            "num_sources": 8,
        },
        options={"zone_names": {1: "Kitchen", 2: "Patio"}},
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("media_player.amc_x86_x86i_kitchen")
    assert state is not None, "renamed zone did not produce the expected id"
    assert state.attributes.get("friendly_name") == "AMC X86 / X86i Kitchen"


@pytest.mark.parametrize(
    ("profile", "zones", "expected_id"),
    [
        ("AMC XIA100e / XIA150e", 1, "media_player.amc_xia100e_xia150e_zone_1"),
        ("AMC XCDie CD Player", 1, "media_player.amc_xcdie_cd_player_zone_1"),
        ("Monoprice 6-Zone", 6, "media_player.monoprice_6_zone_zone_1"),
    ],
)
async def test_other_profiles_keep_their_id_shape(
    hass: HomeAssistant, profile: str, zones: int, expected_id: str
) -> None:
    """The id scheme must hold across profiles, not just the AMC X86.

    The shipped dashboard YAML hardcodes ids of exactly this shape, so a change
    here would silently break it.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{profile} (Demo)",
        unique_id=f"ac_demo_{profile}",
        data={
            "port": "demo",
            "device_profile": profile,
            "num_zones": zones,
            "num_sources": 4,
        },
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(expected_id) is not None, f"{expected_id} not created"


async def test_connection_sensor_keeps_its_diagnostic_category(
    hass: HomeAssistant,
) -> None:
    """Unrelated to naming, but easy to disturb when editing this class."""
    entry = await setup_amc(hass)
    registry = er.async_get(hass)
    sensor = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "binary_sensor"
    )
    assert sensor.entity_category is not None
    assert sensor.entity_category.value == "diagnostic"


def test_dashboard_generator_expects_the_same_id_shape() -> None:
    """dashboard_writer parses the zone number out of the unique_id.

    Naming changes must not disturb the unique_id, which is the dashboard
    generator's input -- it is independent of the entity id but lives in the same
    code path.
    """
    from custom_components.audio_control.dashboard_writer import _zone_number

    assert _zone_number("ac_01ABC_zone_3") == 3
    assert _zone_number("ac_01ABC_connection") is None
