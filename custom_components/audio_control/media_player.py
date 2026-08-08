"""Media player platform for Audio Control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (  # type: ignore[attr-defined]
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AudioControlConfigEntry
from .const import (
    CONF_NUM_SOURCES,
    CONF_NUM_ZONES,
    CONF_SOURCE_NAMES,
    CONF_ZONE_NAMES,
    DOMAIN,
)
from .entity import AudioControlEntity
from .rs232_protocol import ZoneState
from .serial_manager import SerialManager

_LOGGER = logging.getLogger(__name__)

# Serial communication is sequential (command_lock); disable parallel platform updates
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AudioControlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up media player entities from a config entry."""
    manager = entry.runtime_data
    # Clamp to what the engine actually built. CONF_NUM_ZONES is frozen into the
    # entry at config-flow time while the zones dict comes from the live profile,
    # so a profile whose zone count is REDUCED in a later release leaves entities
    # indexing keys that no longer exist -- and every state property does an
    # unguarded self._manager.zones[self._zone_num], so each update raises
    # KeyError, spamming the log and leaving broken entities. Clamping drops the
    # surplus entities instead; the stale count is corrected on the next
    # reconfigure.
    stored_zones = entry.data.get(CONF_NUM_ZONES, 6)
    num_zones = min(stored_zones, manager.engine.num_zones)
    if num_zones != stored_zones:
        _LOGGER.warning(
            "Profile '%s' now has %d zone(s) but the entry recorded %d; "
            "creating %d zone entities",
            entry.title,
            manager.engine.num_zones,
            stored_zones,
            num_zones,
        )
    num_sources = entry.data.get(CONF_NUM_SOURCES, 6)
    # Use entry title for display (set during config flow from profile name)
    profile_name = entry.title.removesuffix(" (Demo)")
    source_names = entry.options.get(CONF_SOURCE_NAMES, {})
    zone_names = entry.options.get(CONF_ZONE_NAMES, {})

    source_names = {int(k): v for k, v in source_names.items()}
    zone_names = {int(k): v for k, v in zone_names.items()}

    entities = []
    for zone_num in range(1, num_zones + 1):
        zone_name = zone_names.get(zone_num, f"Zone {zone_num}")
        entities.append(
            AudioControlZone(
                manager, zone_num, zone_name, source_names, num_sources, profile_name
            )
        )

    async_add_entities(entities)


class AudioControlZone(AudioControlEntity, MediaPlayerEntity):
    """A single zone on an audio device."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(
        self,
        manager: SerialManager,
        zone_num: int,
        zone_name: str,
        source_names: dict[int, str],
        num_sources: int,
        profile_name: str,
    ) -> None:
        """Initialize zone entity."""
        super().__init__(manager, profile_name)
        self._zone_num = zone_num
        self._source_names = source_names
        self._num_sources = num_sources

        self._attr_unique_id = f"ac_{manager.entry_id}_zone_{zone_num}"
        # Just the zone name: HA prefixes the device name itself now.
        self._attr_name = zone_name
        # Keep the historical entity id ("<profile> <zone>" slugified).
        self._legacy_object_id = zone_name

        # Build features from what the profile can actually do. Every flag below
        # is gated on a command existing, because send_command() merely returns
        # False for an unknown command -- so an over-advertised feature renders a
        # control that fails silently, with only a log line.
        engine = manager.engine
        engine_features = engine.features
        features = MediaPlayerEntityFeature(0)

        # Power was advertised unconditionally. Every profile through the first
        # 23 defined both commands, so it never mattered; the AMC XIA100e is
        # powered from its front panel and has no *POWER command at all, which
        # would have given it two dead buttons.
        if engine.has_command("power_on"):
            features |= MediaPlayerEntityFeature.TURN_ON
        if engine.has_command("power_off"):
            features |= MediaPlayerEntityFeature.TURN_OFF

        # Absolute volume needs a real span AND a command to set it. The
        # predicate is span, not max: a dB scale legitimately tops out at 0 (NAD
        # C 368 is -80..0), and `volume_max > 0` hid the slider on a device that
        # supports it.
        if engine.volume_max - engine.volume_min > 0 and engine.has_command(
            "volume_set"
        ):
            features |= MediaPlayerEntityFeature.VOLUME_SET

        # Stepping is independent of the span. Nesting it under `span > 0` hid
        # the +/- buttons on the XIA, which has volume_up/volume_down but no
        # absolute level to report -- relative-only volume is a real device
        # shape, not a degenerate case.
        if engine.has_command("volume_up") and engine.has_command("volume_down"):
            features |= MediaPlayerEntityFeature.VOLUME_STEP

        if engine.has_command("mute_on"):
            features |= MediaPlayerEntityFeature.VOLUME_MUTE

        # Source select needs more than one input AND a way to switch. Gating on
        # the count alone gave the AMC XCDie a fully dead dropdown: it has four
        # media inputs but no `source_set` -- its opcodes are discrete
        # (source_1..source_4), so nothing async_select_source sends exists.
        if num_sources > 1 and (
            engine.has_command("source_set")
            or all(engine.has_command(f"source_{i}") for i in range(1, num_sources + 1))
        ):
            features |= MediaPlayerEntityFeature.SELECT_SOURCE

        # Transport controls for players (CD, DVD, Blu-ray). Both the profile flag
        # and the commands must agree -- see the tone/group flags in services.py
        # for what happens when only the flag is checked.
        if engine_features.get("has_transport"):
            if engine.has_command("play"):
                features |= MediaPlayerEntityFeature.PLAY
            if engine.has_command("pause"):
                features |= MediaPlayerEntityFeature.PAUSE
            if engine.has_command("stop"):
                features |= MediaPlayerEntityFeature.STOP
            if engine.has_command("next_track"):
                features |= MediaPlayerEntityFeature.NEXT_TRACK
            if engine.has_command("prev_track"):
                features |= MediaPlayerEntityFeature.PREVIOUS_TRACK

        self._attr_supported_features = features

    @property
    def _zone(self) -> ZoneState | None:
        """This entity's zone state, or None if the zone no longer exists.

        Every read used to index self._manager.zones[...] directly, so a zone
        absent from the engine raised KeyError inside a state property -- on every
        update, spamming the log with an exception HA cannot act on. Returning
        None instead lets `available` report the entity as unavailable, which is
        the honest answer and is what HA is designed to render.
        """
        return self._manager.zones.get(self._zone_num)

    @property
    def available(self) -> bool:
        """Available only if connected AND this zone still exists."""
        return super().available and self._zone is not None

    @property
    def state(self) -> MediaPlayerState | None:
        zone = self._zone
        if zone is None:
            return None
        return MediaPlayerState.ON if zone.power else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        engine = self._manager.engine
        if engine.volume_max - engine.volume_min == 0:
            # Relative-only devices (AMC XIA: *VOLUP/*VOLDN with no absolute
            # command and no level ever reported) have no level to show. Returning
            # 0.0 rendered a slider pinned at zero beside working +/- buttons,
            # which reads as a broken control. None omits it entirely.
            return None
        zone = self._zone
        if zone is None:
            return None
        return engine.device_volume_to_ha(zone.volume)

    @property
    def is_volume_muted(self) -> bool | None:
        zone = self._zone
        return None if zone is None else zone.mute

    @property
    def source(self) -> str | None:
        zone = self._zone
        if zone is None:
            return None
        return self._source_names.get(zone.source, f"Source {zone.source}")

    @property
    def source_list(self) -> list[str]:
        return [
            self._source_names.get(i, f"Source {i}")
            for i in range(1, self._num_sources + 1)
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        if zone is None:
            return {}
        attrs = {"raw_volume": zone.volume, "group_mode": zone.group}
        if self._manager.engine.features.get("has_tone_controls"):
            attrs["bass"] = zone.bass
            attrs["treble"] = zone.treble
        if self._manager.engine.features.get("has_balance"):
            attrs["balance"] = zone.balance
        return attrs

    async def async_added_to_hass(self) -> None:
        self._manager.register_listener(self._zone_num, self._state_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._manager.unregister_listener(self._zone_num, self._state_updated)

    @callback
    def _state_updated(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        z = zone_state
        prev_power, prev_mute, prev_vol = z.power, z.mute, z.volume
        self._manager.set_zone_power(self._zone_num, True)
        success = await self._manager.async_send_command(
            "power_on", zone=self._zone_num
        )
        if not success:
            self._manager.rollback_zone_power(
                self._zone_num, prev_power, prev_mute, prev_vol
            )

    async def async_turn_off(self) -> None:
        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        z = zone_state
        prev_power, prev_mute, prev_vol = z.power, z.mute, z.volume
        self._manager.set_zone_power(self._zone_num, False)
        success = await self._manager.async_send_command(
            "power_off", zone=self._zone_num
        )
        if not success:
            self._manager.rollback_zone_power(
                self._zone_num, prev_power, prev_mute, prev_vol
            )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, rollback on failure."""
        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        z = zone_state
        prev_vol = z.volume
        device_vol = self._manager.engine.ha_volume_to_device(volume)
        z.volume = device_vol
        self._manager.notify_zone_update(self._zone_num)
        success = await self._manager.async_send_command(
            "volume_set", zone=self._zone_num, volume=device_vol
        )
        if not success:
            z.volume = prev_vol
            self._manager.notify_zone_update(self._zone_num)

    async def async_volume_up(self) -> None:
        """Step volume up, with the same optimistic update as every other path."""
        await self._async_volume_step("volume_up", louder=True)

    async def async_volume_down(self) -> None:
        """Step volume down, with the same optimistic update as every other path."""
        await self._async_volume_step("volume_down", louder=False)

    async def _async_volume_step(self, command: str, *, louder: bool) -> None:
        """Apply a one-step volume change optimistically, rolling back on failure.

        These previously sent the command and mutated nothing, unlike every other
        command path. Because VOLUME_STEP is declared, HA calls this override
        instead of its own volume_level +/- step fallback, so the slider showed
        the stale level until the next 60s poll -- pressing +/- several times
        looked like nothing happened, then the level jumped.
        """
        engine = self._manager.engine
        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        zone = zone_state
        prev_vol = zone.volume

        # On an inverted scale a louder request means a LOWER device value.
        delta = -1 if (louder == engine.volume_inverted) else 1
        new_vol = min(max(prev_vol + delta, engine.volume_min), engine.volume_max)

        zone.volume = new_vol
        self._manager.notify_zone_update(self._zone_num)

        success = await self._manager.async_send_command(command, zone=self._zone_num)
        if not success:
            _LOGGER.warning("Failed %s for zone %d", command, self._zone_num)
            zone.volume = prev_vol
            self._manager.notify_zone_update(self._zone_num)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute, rollback on failure."""
        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        z = zone_state
        prev_mute = z.mute
        z.mute = mute
        self._manager.notify_zone_update(self._zone_num)
        cmd = "mute_on" if mute else "mute_off"
        success = await self._manager.async_send_command(cmd, zone=self._zone_num)
        if not success:
            z.mute = prev_mute
            self._manager.notify_zone_update(self._zone_num)

    def _source_number(self, source: str) -> int | None:
        """Resolve a UI source label back to its 1-based index.

        Must accept everything `source_list` offers. It previously searched only
        `_source_names`, while `source_list` also synthesises "Source N" for any
        unnamed index -- so those entries matched nothing, the loop fell through
        to a log line, and HA left the dropdown showing a value the device never
        received.
        """
        wanted = source.strip().lower()
        for num, name in self._source_names.items():
            if name.lower() == wanted:
                return num
        # Synthesised "Source N" labels, which carry the index in the text.
        for num in range(1, self._num_sources + 1):
            if wanted == f"source {num}":
                return num
        return None

    async def async_select_source(self, source: str) -> None:
        """Select source, rollback on failure."""
        num = self._source_number(source)
        if num is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={
                    "source": source,
                    "available": ", ".join(self.source_list),
                },
            )

        zone_state = self._zone
        if zone_state is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_valid_zone",
                translation_placeholders={"entity_id": self.entity_id},
            )
        z = zone_state
        prev_source = z.source
        z.source = num
        self._manager.notify_zone_update(self._zone_num)

        engine = self._manager.engine
        if engine.has_command("source_set"):
            source_name = engine.source_command_map.get(num, str(num))
            success = await self._manager.async_send_command(
                "source_set",
                zone=self._zone_num,
                source=num,
                source_name=source_name,
            )
        else:
            # Discrete per-input opcodes (AMC XCDie: source_1..source_4) rather
            # than one parameterised command.
            success = await self._manager.async_send_command(
                f"source_{num}", zone=self._zone_num
            )

        if not success:
            z.source = prev_source
            self._manager.notify_zone_update(self._zone_num)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={
                    "command": "select_source",
                    "zone": str(self._zone_num),
                },
            )

    # --- Transport Controls (for CD/DVD/Blu-ray players) --------------------

    async def async_media_play(self) -> None:
        """Send play command."""
        success = await self._manager.async_send_command("play", zone=self._zone_num)
        if not success:
            _LOGGER.warning("Failed play for zone %d", self._zone_num)

    async def async_media_pause(self) -> None:
        """Send pause command."""
        success = await self._manager.async_send_command("pause", zone=self._zone_num)
        if not success:
            _LOGGER.warning("Failed pause for zone %d", self._zone_num)

    async def async_media_stop(self) -> None:
        """Send stop command."""
        success = await self._manager.async_send_command("stop", zone=self._zone_num)
        if not success:
            _LOGGER.warning("Failed stop for zone %d", self._zone_num)

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        success = await self._manager.async_send_command(
            "next_track", zone=self._zone_num
        )
        if not success:
            _LOGGER.warning("Failed next_track for zone %d", self._zone_num)

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        success = await self._manager.async_send_command(
            "prev_track", zone=self._zone_num
        )
        if not success:
            _LOGGER.warning("Failed prev_track for zone %d", self._zone_num)
