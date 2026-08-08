"""Tests for the media_player entity: optimistic state and rollback.

Every command updates HA state immediately then reverts if the device NAKs.
media_player.py sat at 68% coverage with the rollback branches for volume, mute
and source entirely untested -- only power had any direct test, and that called
the manager helper rather than going through the entity. A wrong-variable capture
(reading state AFTER mutating it) would desync HA from the hardware permanently
with no error surfaced, which is exactly the class of bug these cover.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    DOMAIN as MP_DOMAIN,
)
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_PLAY,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import DOMAIN

PROFILE: dict[str, Any] = {
    "name": "RollbackTest",
    "zones": 2,
    "sources": 3,
    "serial": {"command_prefix": "*", "command_suffix": "\r"},
    "commands": {
        "status": "Z{zone:02d}STA",
        "power_on": "Z{zone:02d}PWR01",
        "power_off": "Z{zone:02d}PWR00",
        "volume_set": "Z{zone:02d}VOL{volume:02d}",
        "volume_up": "Z{zone:02d}VOLUP",
        "volume_down": "Z{zone:02d}VOLDN",
        "mute_on": "Z{zone:02d}MUT01",
        "mute_off": "Z{zone:02d}MUT00",
        "source_set": "Z{zone:02d}SRC{source:02d}",
    },
    "response": {
        "status_pattern": r"Z(?P<zone>\d{2})V(?P<volume>\d{2})",
        "mapping": {"volume": {"field": "volume", "type": "int"}},
    },
    # Non-inverted 0..62 keeps the arithmetic easy to assert.
    "volume": {"min": 0, "max": 62, "inverted": False},
    "features": {"has_tone_controls": False},
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    cfg = MockConfigEntry(
        domain=DOMAIN,
        title="RollbackTest (Demo)",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "baud_rate": 9600,
            "num_zones": 2,
            "num_sources": 3,
            "custom_profile": PROFILE,
        },
        options={
            "source_names": {1: "CD", 2: "TV", 3: "Vinyl"},
            "zone_names": {1: "Living", 2: "Kitchen"},
        },
        unique_id="ac_demo_rollback",
        version=3,
    )
    cfg.add_to_hass(hass)
    await hass.config_entries.async_setup(cfg.entry_id)
    await hass.async_block_till_done()
    return cfg


def zone_entity(hass: HomeAssistant, zone: int) -> str:
    """Entity id for a zone, via the registry unique_id (ac_{entry}_zone_{n})."""
    registry = er.async_get(hass)
    for ent in registry.entities.values():
        if (
            ent.platform == DOMAIN
            and ent.domain == "media_player"
            and ent.unique_id.endswith(f"_zone_{zone}")
        ):
            return ent.entity_id
    msg = f"no media_player for zone {zone}"
    raise AssertionError(msg)


async def call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(MP_DOMAIN, service, data, blocking=True)


def nak(entry: MockConfigEntry) -> Any:
    """Patch the manager so every command is rejected by the device."""
    return patch.object(
        entry.runtime_data, "async_send_command", new=AsyncMock(return_value=False)
    )


def ack(entry: MockConfigEntry) -> Any:
    return patch.object(
        entry.runtime_data, "async_send_command", new=AsyncMock(return_value=True)
    )


# ─── Volume ──────────────────────────────────────────────────────────────────


async def test_volume_set_applies_on_success(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(hass, SERVICE_VOLUME_SET, **{ATTR_ENTITY_ID: eid}, volume_level=0.5)
    # 0.5 of 0..62 non-inverted = 31
    assert entry.runtime_data.zones[1].volume == 31


async def test_volume_set_rolls_back_on_nak(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A rejected volume must revert to the PREVIOUS value, not stay applied."""
    zone = entry.runtime_data.zones[1]
    zone.volume = 20
    eid = zone_entity(hass, 1)
    with nak(entry):
        await call(hass, SERVICE_VOLUME_SET, **{ATTR_ENTITY_ID: eid}, volume_level=0.9)
    assert zone.volume == 20, "volume did not roll back"


async def test_volume_set_rollback_restores_exact_prior_value(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Guards against capturing the prior value AFTER mutating it.

    If prev were read post-assignment, rollback would restore the NEW value and
    the bug would be invisible -- state would look "applied" despite the NAK.
    """
    zone = entry.runtime_data.zones[1]
    for original in (0, 7, 31, 62):
        zone.volume = original
        eid = zone_entity(hass, 1)
        with nak(entry):
            await call(
                hass, SERVICE_VOLUME_SET, **{ATTR_ENTITY_ID: eid}, volume_level=0.25
            )
        assert zone.volume == original, f"expected {original}, got {zone.volume}"


async def test_volume_set_sends_device_scaled_value(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The command must carry the DEVICE value, not the 0.0-1.0 HA level."""
    eid = zone_entity(hass, 1)
    with ack(entry) as send:
        await call(hass, SERVICE_VOLUME_SET, **{ATTR_ENTITY_ID: eid}, volume_level=1.0)
    assert send.await_args is not None
    assert send.await_args.kwargs["volume"] == 62


# ─── Mute ────────────────────────────────────────────────────────────────────


async def test_mute_applies_on_success(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    zone = entry.runtime_data.zones[1]
    zone.mute = False
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(
            hass, SERVICE_VOLUME_MUTE, **{ATTR_ENTITY_ID: eid}, is_volume_muted=True
        )
    assert zone.mute is True


@pytest.mark.parametrize("original", [True, False])
async def test_mute_rolls_back_on_nak(
    hass: HomeAssistant, entry: MockConfigEntry, original: bool
) -> None:
    """Rollback must restore the prior mute state in both directions."""
    zone = entry.runtime_data.zones[1]
    zone.mute = original
    eid = zone_entity(hass, 1)
    with nak(entry):
        await call(
            hass,
            SERVICE_VOLUME_MUTE,
            **{ATTR_ENTITY_ID: eid},
            is_volume_muted=not original,
        )
    assert zone.mute is original


async def test_mute_sends_correct_command(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    eid = zone_entity(hass, 1)
    with ack(entry) as send:
        await call(
            hass, SERVICE_VOLUME_MUTE, **{ATTR_ENTITY_ID: eid}, is_volume_muted=True
        )
    assert send.await_args is not None
    assert send.await_args.args[0] == "mute_on"

    with ack(entry) as send:
        await call(
            hass, SERVICE_VOLUME_MUTE, **{ATTR_ENTITY_ID: eid}, is_volume_muted=False
        )
    assert send.await_args is not None
    assert send.await_args.args[0] == "mute_off"


# ─── Source select ───────────────────────────────────────────────────────────


async def test_source_select_applies_on_success(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    zone = entry.runtime_data.zones[1]
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(hass, "select_source", **{ATTR_ENTITY_ID: eid}, source="TV")
    assert zone.source == 2  # TV is source 2


async def test_source_select_rolls_back_on_nak(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A rejected source must revert AND surface an error.

    This previously only asserted the rollback, because the entity logged a
    warning and returned. A review pointed out that an automation calling
    select_source then saw success regardless -- nothing in the UI or the trace
    indicated the device had refused. It now raises, so the rollback and the
    error are asserted together.
    """
    zone = entry.runtime_data.zones[1]
    zone.source = 1
    eid = zone_entity(hass, 1)
    with nak(entry), pytest.raises(HomeAssistantError):
        await call(hass, "select_source", **{ATTR_ENTITY_ID: eid}, source="Vinyl")
    assert zone.source == 1, "source did not roll back"


async def test_source_select_is_case_insensitive(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    zone = entry.runtime_data.zones[1]
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(hass, "select_source", **{ATTR_ENTITY_ID: eid}, source="tv")
    assert zone.source == 2


async def test_unknown_source_sends_nothing_and_raises(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An unrecognised name must send nothing, change nothing, and raise.

    Silently ignoring it left the caller unable to tell a typo from a success.
    """
    zone = entry.runtime_data.zones[1]
    zone.source = 1
    eid = zone_entity(hass, 1)
    with ack(entry) as send, pytest.raises(HomeAssistantError) as excinfo:
        await call(hass, "select_source", **{ATTR_ENTITY_ID: eid}, source="Turntable")
    send.assert_not_awaited()
    assert zone.source == 1
    # The message must list what IS available, or the user cannot self-correct.
    placeholders = excinfo.value.translation_placeholders or {}
    assert "CD" in placeholders.get("available", "")


async def test_synthesised_source_label_is_selectable(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """ "Source N" labels that source_list offers must actually work.

    source_list synthesises "Source N" for any index without a configured name,
    but async_select_source only searched the names dict -- so those entries
    matched nothing and silently did nothing, while HA left the dropdown showing
    the new value. Every label the UI offers must be resolvable.
    """
    entry.runtime_data.zones[1].source = 1
    eid = zone_entity(hass, 1)
    state = hass.states.get(eid)
    assert state is not None
    for label in state.attributes["source_list"]:
        with ack(entry) as send:
            await call(hass, "select_source", **{ATTR_ENTITY_ID: eid}, source=label)
        send.assert_awaited(), f"label {label!r} from source_list sent nothing"


# ─── Power ───────────────────────────────────────────────────────────────────


async def test_turn_on_applies_on_success(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    zone = entry.runtime_data.zones[1]
    zone.power = False
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(hass, SERVICE_TURN_ON, **{ATTR_ENTITY_ID: eid})
    assert zone.power is True


async def test_turn_off_rolls_back_on_nak(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Power rollback must restore power, mute AND volume together.

    Turning off sets mute and drives volume to the silent end, so all three have
    to be restored or the zone shows as on-but-silent.
    """
    zone = entry.runtime_data.zones[1]
    zone.power, zone.mute, zone.volume = True, False, 25
    eid = zone_entity(hass, 1)
    with nak(entry):
        await call(hass, SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: eid})
    assert zone.power is True
    assert zone.mute is False
    assert zone.volume == 25


# ─── Volume step: documented gap ─────────────────────────────────────────────


async def test_volume_up_sends_command(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    eid = zone_entity(hass, 1)
    with ack(entry) as send:
        await call(hass, "volume_up", **{ATTR_ENTITY_ID: eid})
    assert send.await_args is not None
    assert send.await_args.args[0] == "volume_up"


async def test_volume_step_updates_local_state(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """volume_up/down must move local state like every other command path.

    They previously sent the command and mutated nothing. Because VOLUME_STEP is
    declared, HA calls the override rather than its own volume_level +/- fallback,
    so the slider showed the stale level until the next 60s poll -- pressing +/-
    repeatedly looked like nothing happened, then the level jumped.
    """
    zone = entry.runtime_data.zones[1]
    zone.volume = 30
    eid = zone_entity(hass, 1)
    # Non-inverted profile: louder means a higher device value.
    with ack(entry):
        await call(hass, "volume_up", **{ATTR_ENTITY_ID: eid})
    assert zone.volume == 31

    with ack(entry):
        await call(hass, "volume_down", **{ATTR_ENTITY_ID: eid})
    assert zone.volume == 30


async def test_volume_step_rolls_back_on_nak(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A rejected step must revert, not leave the UI one step out of sync."""
    zone = entry.runtime_data.zones[1]
    zone.volume = 30
    eid = zone_entity(hass, 1)
    with nak(entry):
        await call(hass, "volume_up", **{ATTR_ENTITY_ID: eid})
    assert zone.volume == 30


async def test_volume_step_clamps_at_scale_ends(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Stepping past either rail must stay in range, not produce an invalid value."""
    zone = entry.runtime_data.zones[1]
    eid = zone_entity(hass, 1)

    zone.volume = 62  # max
    with ack(entry):
        await call(hass, "volume_up", **{ATTR_ENTITY_ID: eid})
    assert zone.volume == 62

    zone.volume = 0  # min
    with ack(entry):
        await call(hass, "volume_down", **{ATTR_ENTITY_ID: eid})
    assert zone.volume == 0


# ─── Entity surface ──────────────────────────────────────────────────────────


async def test_entities_created_per_zone(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    zones = [
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "media_player"
    ]
    assert len(zones) == 2


async def test_source_list_reflects_configured_names(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The UI dropdown must show the user's names, not "Source N"."""
    state = hass.states.get(zone_entity(hass, 1))
    assert state is not None
    assert state.attributes["source_list"] == ["CD", "TV", "Vinyl"]


async def test_state_reflects_zone_power(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    eid = zone_entity(hass, 1)
    with ack(entry):
        await call(hass, SERVICE_TURN_ON, **{ATTR_ENTITY_ID: eid})
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == STATE_ON

    with ack(entry):
        await call(hass, SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: eid})
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == STATE_OFF


async def test_unsupported_feature_not_advertised(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """This profile has no play/pause commands, so PLAY must not be offered."""
    state = hass.states.get(zone_entity(hass, 1))
    assert state is not None
    features = state.attributes["supported_features"]
    assert not features & MediaPlayerEntityFeature.PLAY
    assert features & MediaPlayerEntityFeature.VOLUME_SET
    assert features & MediaPlayerEntityFeature.SELECT_SOURCE


async def test_play_service_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Calling an unsupported service must be rejected, not silently ignored."""
    eid = zone_entity(hass, 1)
    with pytest.raises(HomeAssistantError):
        await call(hass, SERVICE_MEDIA_PLAY, **{ATTR_ENTITY_ID: eid})
