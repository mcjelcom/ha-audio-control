"""Which MediaPlayerEntityFeature flags each real profile advertises.

These run against the *shipped* profiles rather than a synthetic one, because the
bugs they cover were both mismatches between a profile's real capabilities and
what the entity claimed:

  * `volume_max > 0` hid the volume slider and mute on the NAD C 368, whose scale
    is -80..0 dB. Nothing in the UI could change its volume.
  * VOLUME_STEP was advertised whenever a volume range existed, so the Xantech
    MRC-88 (volume_set, no volume_up/volume_down) rendered +/- buttons that sent
    nothing.

A wrong feature flag is a silent failure -- HA renders a control that does not
work, or omits one that would. There is no log line and no exception, so only an
assertion on the flags catches it.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

F = MediaPlayerEntityFeature


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def builtin(display_name: str) -> dict[str, Any]:
    """Fetch a shipped profile by its display name, as the config flow does."""
    profiles = load_builtin_profiles()
    assert display_name in profiles, sorted(profiles)
    return profiles[display_name]


async def setup_profile(hass: HomeAssistant, display_name: str) -> MockConfigEntry:
    """Set up a config entry for a shipped profile in demo mode.

    Goes through async_setup_entry rather than instantiating the entity directly,
    so the num_zones/num_sources plumbing and the profile lookup are exercised
    too -- the config_flow `sources` crash lived in exactly that seam.
    """
    profile = builtin(display_name)
    raw_sources = profile.get("sources", 6)
    num_sources = (
        raw_sources if isinstance(raw_sources, int) else raw_sources.get("count", 6)
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{display_name} (Demo)",
        data={
            "port": "demo",
            "device_profile": display_name,
            "num_zones": profile.get("zones", 1),
            "num_sources": num_sources,
        },
        unique_id=f"ac_demo_{display_name}",
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def features_of(hass: HomeAssistant, zone: int = 1) -> MediaPlayerEntityFeature:
    """Supported-features flags for a zone's media_player entity."""
    registry = er.async_get(hass)
    for ent in registry.entities.values():
        if (
            ent.platform == DOMAIN
            and ent.domain == "media_player"
            and ent.unique_id.endswith(f"_zone_{zone}")
        ):
            state = hass.states.get(ent.entity_id)
            assert state is not None
            return MediaPlayerEntityFeature(state.attributes["supported_features"])
    msg = f"no media_player entity for zone {zone}"
    raise AssertionError(msg)


# ─── dB scales: span, not max ────────────────────────────────────────────────


async def test_negative_db_scale_still_offers_volume(hass: HomeAssistant) -> None:
    """NAD C 368 runs -80..0 dB, so volume_max is 0 -- but volume works fine.

    This is the regression: gating on `volume_max > 0` evaluated False here and
    stripped VOLUME_SET and VOLUME_MUTE from a device that supports both.
    """
    await setup_profile(hass, "NAD C 368 / C 388")
    features = features_of(hass)
    assert features & F.VOLUME_SET
    assert features & F.VOLUME_MUTE
    assert features & F.VOLUME_STEP


async def test_straddling_db_scale_offers_volume(hass: HomeAssistant) -> None:
    """Yamaha RX-A spans -80..+16, i.e. max > 0 -- the case that always worked.

    Pairs with the NAD test so a fix that only special-cases negatives is caught.
    """
    await setup_profile(hass, "Yamaha RX-A / RX-V Series")
    assert features_of(hass) & F.VOLUME_SET


async def test_plain_scale_offers_volume(hass: HomeAssistant) -> None:
    """The ordinary 0..62 case must be unaffected by the gate change."""
    await setup_profile(hass, "AMC X86 / X86i")
    features = features_of(hass)
    assert features & F.VOLUME_SET
    assert features & F.VOLUME_STEP
    assert features & F.VOLUME_MUTE


# ─── VOLUME_STEP requires real relative commands ─────────────────────────────


async def test_no_step_commands_means_no_step_buttons(hass: HomeAssistant) -> None:
    """Xantech MRC-88 has volume_set but no volume_up/volume_down.

    Advertising VOLUME_STEP put +/- buttons in the UI that silently did nothing:
    send_command returns False for an unknown command, and the entity only logged
    a warning. The slider worked; the buttons did not.
    """
    await setup_profile(hass, "Xantech MRC-88")
    features = features_of(hass)
    assert features & F.VOLUME_SET, "slider should still be offered"
    assert not features & F.VOLUME_STEP, "MRC-88 has no volume_up/volume_down"


async def test_sibling_profile_with_step_commands_keeps_them(
    hass: HomeAssistant,
) -> None:
    """Xantech MX88 does define volume_up/down, so it must keep VOLUME_STEP.

    Guards against fixing the MRC-88 by dropping VOLUME_STEP for the whole
    Xantech family.
    """
    await setup_profile(hass, "Xantech MX88 / MX88a")
    assert features_of(hass) & F.VOLUME_STEP


# ─── Genuinely volume-less devices ───────────────────────────────────────────


@pytest.mark.parametrize(
    "display_name",
    ["AMC XAi", "AMC XGi", "Rotel RCD-1572 CD Player", "Rotel Michi M8 / S5"],
)
async def test_volumeless_devices_offer_no_volume(
    hass: HomeAssistant, display_name: str
) -> None:
    """Power amps and transports have no volume; min == max == 0 for all four.

    This is the case the original `volume_max > 0` gate was written for, and it
    must keep working -- a volume slider on a fixed-gain power amp is worse than
    no slider, since it looks functional.
    """
    await setup_profile(hass, display_name)
    features = features_of(hass)
    assert not features & F.VOLUME_SET
    assert not features & F.VOLUME_STEP
    assert not features & F.VOLUME_MUTE


# ─── Profile-wide invariant ──────────────────────────────────────────────────


def test_every_profile_with_a_volume_span_can_set_volume() -> None:
    """A non-zero span must come with volume_set, or the slider is a no-op.

    Checked across all shipped profiles rather than per-device: this is the
    invariant the entity gate relies on, and a future profile that declares a
    range without the command would reintroduce dead controls.
    """
    offenders = []
    for name, profile in load_builtin_profiles().items():
        engine = create_engine(profile)
        if engine.volume_max - engine.volume_min > 0 and not engine.has_command(
            "volume_set"
        ):
            offenders.append(name)
    assert not offenders, f"volume range but no volume_set: {offenders}"


def test_every_profile_declaring_step_commands_declares_both() -> None:
    """volume_up without volume_down (or vice versa) yields one dead button."""
    offenders = [
        name
        for name, profile in load_builtin_profiles().items()
        if (engine := create_engine(profile))
        and engine.has_command("volume_up") != engine.has_command("volume_down")
    ]
    assert not offenders, f"only one of volume_up/volume_down: {offenders}"
