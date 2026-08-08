"""A capability needs BOTH the profile flag and the underlying command.

The media_player power/volume/mute flags were hardened to gate on
`engine.has_command(...)`, but three other paths still trusted the profile's
`has_*` flag alone: the tone services, the global broadcast, and the transport /
source-select feature bits.

Ten of the 26 shipped profiles declare a flag with no matching command:

  has_tone_controls, no bass_set : NAD C 368, RTI AD-810-100, Rotel RSP-1576,
                                   SpeakerCraft MZC, Xantech ZPR68-10
  has_group_mode,   no group_on  : RTI AD-810-100, Russound RNET
  has_balance,      no balance_set: AMC X1616e, Rotel RA-1572, Rotel RSP-1576,
                                    Russound RNET, Xantech MRC-88, Xantech MX88

The consequence was a misleading error, not a silent one: the flag gate passed,
format_command returned None, send_command returned False, and the user was told
"Failed to send set_bass for zone 1. Check device connection." on a device that
has no tone control at all. The `_broadcast` comment even claimed feature
filtering existed to avoid exactly that, which the code did not achieve.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

# (flag, command it implies) for every flag the code acts on.
FLAG_COMMANDS = [
    ("has_tone_controls", "bass_set"),
    ("has_tone_controls", "treble_set"),
    ("has_group_mode", "group_on"),
    ("has_group_mode", "group_off"),
    ("has_all_off", "all_off"),
    ("has_transport", "play"),
]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def source_count(profile: dict[str, Any]) -> int:
    raw = profile.get("sources", 6)
    if isinstance(raw, int):
        return raw
    return int(raw.get("count") or len(raw.get("names") or {}) or 6)


# ─── Every advertised control must be performable ────────────────────────────


def test_no_profile_advertises_source_select_it_cannot_perform() -> None:
    """SELECT_SOURCE requires source_set OR a full set of discrete opcodes.

    Gating on `num_sources > 1` alone gave the AMC XCDie a completely dead
    dropdown: four media inputs, but its opcodes are discrete (source_1..4) and
    async_select_source only ever sent `source_set`.
    """
    offenders = []
    for name, profile in load_builtin_profiles().items():
        engine = create_engine(profile)
        count = source_count(profile)
        if count <= 1:
            continue
        has_generic = engine.has_command("source_set")
        has_discrete = all(
            engine.has_command(f"source_{i}") for i in range(1, count + 1)
        )
        if not (has_generic or has_discrete):
            offenders.append(name)
    assert not offenders, f"multi-source profiles with no way to switch: {offenders}"


def test_transport_flag_implies_transport_commands() -> None:
    """has_transport must come with the commands the flag turns into buttons."""
    offenders = {}
    for name, profile in load_builtin_profiles().items():
        engine = create_engine(profile)
        if not engine.features.get("has_transport"):
            continue
        missing = [
            c
            for c in ("play", "pause", "stop", "next_track", "prev_track")
            if not engine.has_command(c)
        ]
        if missing:
            offenders[name] = missing
    assert not offenders, f"has_transport without commands: {offenders}"


@pytest.mark.parametrize(("flag", "command"), FLAG_COMMANDS)
def test_flag_command_mismatches_are_known(flag: str, command: str) -> None:
    """Records which profiles are inconsistent, without failing the build.

    These mismatches are in the shipped YAML and fixing every one needs the
    vendor manuals. The code now gates on flag AND command, so a mismatch is
    harmless -- the feature is simply not offered. This test exists so the list
    cannot GROW unnoticed: a new profile adding a flag without its command
    changes the count and fails here.
    """
    inconsistent = sorted(
        name
        for name, profile in load_builtin_profiles().items()
        if (engine := create_engine(profile))
        and engine.features.get(flag)
        and not engine.has_command(command)
    )
    # Snapshot taken after the review; shrinking this is an improvement, growing
    # it means a new profile introduced a fresh inconsistency.
    known = {
        ("has_tone_controls", "bass_set"): 5,
        ("has_tone_controls", "treble_set"): 5,
        ("has_group_mode", "group_on"): 2,
        ("has_group_mode", "group_off"): 2,
        ("has_all_off", "all_off"): 0,
        ("has_transport", "play"): 0,
    }
    assert len(inconsistent) <= known[(flag, command)], (
        f"new {flag}/{command} mismatch introduced: {inconsistent}"
    )


# ─── The service gate now reports the right error ────────────────────────────


async def setup_profile(hass: HomeAssistant, display_name: str) -> MockConfigEntry:
    profile = load_builtin_profiles()[display_name]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{display_name} (Demo)",
        data={
            "port": "demo",
            "device_profile": display_name,
            "num_zones": profile.get("zones", 1),
            "num_sources": source_count(profile),
        },
        unique_id="ac_demo",
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def zone_entity(hass: HomeAssistant, entry_id: str) -> str:
    registry = er.async_get(hass)
    return next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry_id)
        if e.domain == "media_player" and e.unique_id.endswith("_zone_1")
    )


async def test_tone_service_reports_unsupported_not_connection_failure(
    hass: HomeAssistant,
) -> None:
    """The core regression.

    NAD C 368 declares has_tone_controls but has no bass_set. The user used to be
    told to "check device connection" for a capability the device never had.
    """
    entry = await setup_profile(hass, "NAD C 368 / C 388")
    eid = zone_entity(hass, entry.entry_id)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "set_bass", {"entity_id": eid, "level": 4}, blocking=True
        )
    message = str(excinfo.value).lower()
    assert "does not support" in message, f"got {message!r}"
    assert "connection" not in message, "still blaming the connection"


async def test_tone_service_still_works_where_supported(hass: HomeAssistant) -> None:
    """The gate must not block devices that genuinely have tone control.

    Without this, "reject everything" would pass the test above.
    """
    entry = await setup_profile(hass, "AMC X86 / X86i")
    eid = zone_entity(hass, entry.entry_id)
    # Demo mode ACKs, so a supported call must not raise.
    await hass.services.async_call(
        DOMAIN, "set_bass", {"entity_id": eid, "level": 4}, blocking=True
    )


async def test_group_broadcast_skips_flag_only_devices(hass: HomeAssistant) -> None:
    """Russound RNET sets has_group_mode but defines no group_on.

    It used to pass the broadcast's "capable" filter and then fail with
    command_failed -- the exact misleading error the filter's comment said it
    prevented.
    """
    await setup_profile(hass, "Russound CAV / CAS / MCA (RNET)")
    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN, "group_mode_on", {"source": 1}, blocking=True
        )
    message = str(excinfo.value).lower()
    assert "does not support" in message, f"got {message!r}"


async def test_xcdie_source_select_uses_discrete_opcodes(hass: HomeAssistant) -> None:
    """End to end: the XCDie dropdown must now actually switch inputs."""
    entry = await setup_profile(hass, "AMC XCDie CD Player")
    eid = zone_entity(hass, entry.entry_id)
    state = hass.states.get(eid)
    assert state is not None
    features = F(state.attributes["supported_features"])
    assert features & F.SELECT_SOURCE

    # Demo mode ACKs every command, so a working path does not raise.
    for label in state.attributes["source_list"]:
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": eid, "source": label},
            blocking=True,
        )
