"""Text protocol engine — formats commands and parses responses from device profiles.

No Home Assistant dependency. Pure protocol logic.
This is the default engine for ASCII text-based RS232 devices.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .base import BaseProtocolEngine

_LOGGER = logging.getLogger(__name__)


class ProtocolEngine(BaseProtocolEngine):
    """Formats commands and parses responses based on a device profile."""

    def __init__(self, profile: dict[str, Any]) -> None:
        """Initialize with a device profile dict."""
        self._profile = profile
        self._serial_cfg = profile.get("serial", {})
        self._commands = profile.get("commands", {})
        self._response_cfg = profile.get("response", {})
        self._volume_cfg = profile.get("volume", {})
        self._mapping = self._response_cfg.get("mapping", {})
        sources_raw = profile.get("sources", {})
        # "sources" can be an int (count) or dict (config with command_map)
        self._sources_cfg = sources_raw if isinstance(sources_raw, dict) else {}
        self._source_command_map = self._sources_cfg.get("command_map", {})

        # Zone prefix auto-detection (AMC X-Series: "ZN" vs "Z")
        self._zone_prefix: str = profile.get("zone_prefix", "")
        self._zone_prefix_fallback: str | None = profile.get("zone_prefix_fallback")
        self._zone_prefix_locked: bool = False

        # Compile response patterns
        self._status_re: re.Pattern[str] | None = None
        self._tone_re: re.Pattern[str] | None = None
        self._global_patterns: dict[str, re.Pattern[str] | str] = {}

        if "status_pattern" in self._response_cfg:
            self._status_re = re.compile(self._response_cfg["status_pattern"])
        if "tone_pattern" in self._response_cfg:
            self._tone_re = re.compile(self._response_cfg["tone_pattern"])

        for name, pattern in self._response_cfg.get("global_patterns", {}).items():
            try:
                self._global_patterns[name] = re.compile(pattern)
            except re.error:
                # Plain string match (not a regex)
                self._global_patterns[name] = pattern

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def command_delay(self) -> float:
        """Return inter-command delay in seconds."""
        ms: int = self._serial_cfg.get("command_delay_ms", 100)
        return ms / 1000.0

    @property
    def baud_rate(self) -> int:
        """Return baud rate."""
        rate: int = self._serial_cfg.get("baud_rate", 9600)
        return rate

    @property
    def data_bits(self) -> int:
        """Return data bits (5, 6, 7, or 8)."""
        bits: int = self._serial_cfg.get("data_bits", 8)
        return bits

    @property
    def parity(self) -> str:
        """Return parity ('N', 'E', 'O')."""
        p: str = self._serial_cfg.get("parity", "none")
        return {"none": "N", "even": "E", "odd": "O"}.get(p.lower(), "N")

    @property
    def stop_bits(self) -> int:
        """Return stop bits (1 or 2)."""
        bits: int = self._serial_cfg.get("stop_bits", 1)
        return bits

    @property
    def num_zones(self) -> int:
        """Return zone count."""
        zones: int = self._profile.get("zones", 6)
        return zones

    @property
    def num_sources(self) -> int:
        """Return source count."""
        sources: int | dict[str, Any] = self._profile.get("sources", 6)
        if isinstance(sources, int):
            return sources
        # Dict-style config: {"count": 6, "command_map": {...}}
        count: int = sources.get("count", 6)
        return count

    @property
    def response_terminator(self) -> str:
        """Return response terminator character(s)."""
        term: str = self._serial_cfg.get("response_terminator", "\r")
        return term.encode().decode("unicode_escape")

    @property
    def strip_nul(self) -> bool:
        """Text devices may pad frames with NULs; safe to strip before framing.

        Overridable per profile via serial.strip_nul for devices that don't.
        """
        stripped: bool = self._serial_cfg.get("strip_nul", True)
        return stripped

    @property
    def response_prefix(self) -> str:
        """Return response prefix to strip."""
        prefix: str = self._serial_cfg.get("response_prefix", "")
        return prefix

    @property
    def error_response(self) -> str:
        """Return the error response string."""
        resp: str = self._response_cfg.get("error_response", "?")
        return resp

    @property
    def has_unsolicited_updates(self) -> bool:
        """Return whether device pushes unsolicited state updates."""
        features: dict[str, Any] = self._profile.get("features", {})
        result: bool = features.get("unsolicited_updates", False)
        return result

    @property
    def volume_inverted(self) -> bool:
        """Return whether volume scale is inverted (0=loud, max=mute)."""
        inverted: bool = self._volume_cfg.get("inverted", False)
        return inverted

    @property
    def volume_max(self) -> int:
        """Return maximum volume/attenuation value."""
        vol_max: int = self._volume_cfg.get("max", 38)
        return vol_max

    @property
    def volume_min(self) -> int:
        """Minimum volume value on the device's own scale (0 for most)."""
        vol_min: int = self._volume_cfg.get("min", 0)
        return vol_min

    @property
    def features(self) -> dict[str, bool]:
        """Return feature flags."""
        feats: dict[str, bool] = self._profile.get("features", {})
        return feats

    @property
    def response_timeout(self) -> float:
        """Configurable response timeout (seconds)."""
        timeout: float = self._serial_cfg.get("response_timeout_s", 1.5)
        return timeout

    @property
    def retry_count(self) -> int:
        """Number of retries on timeout."""
        count: int = self._serial_cfg.get("retry_count", 0)
        return count

    @property
    def init_sequence(self) -> list[bytes]:
        """Wakeup bytes to send before first command."""
        raw: list[str] = self._serial_cfg.get("init_sequence", [])
        return [s.encode("ascii") for s in raw]

    @property
    def heartbeat_interval(self) -> float:
        """Heartbeat interval (0 = use default refresh)."""
        interval: float = self._serial_cfg.get("heartbeat_interval_s", 0.0)
        return interval

    @property
    def source_command_map(self) -> dict[int, str]:
        """Return source number to command name mapping.

        For devices that use source names in commands.
        """
        return (
            {int(k): v for k, v in self._source_command_map.items()}
            if self._source_command_map
            else {}
        )

    # ─── Zone Prefix Auto-Detection ─────────────────────────────────────────

    def switch_to_fallback_prefix(self) -> bool:
        """Swap the active and candidate zone prefixes.

        Returns True if a candidate was available. Both values are retained
        (swapped rather than discarded) so detection stays retryable: a
        transient timeout on the first probe previously discarded the correct
        prefix permanently, leaving the device unusable until HA was reloaded.
        """
        if self._zone_prefix_fallback and not self._zone_prefix_locked:
            _LOGGER.info(
                "Zone prefix '%s' rejected, trying '%s'",
                self._zone_prefix,
                self._zone_prefix_fallback,
            )
            self._zone_prefix, self._zone_prefix_fallback = (
                self._zone_prefix_fallback,
                self._zone_prefix,
            )
            return True
        return False

    def lock_zone_prefix(self) -> None:
        """Lock the current zone prefix after successful communication."""
        if not self._zone_prefix_locked and self._zone_prefix:
            self._zone_prefix_locked = True
            _LOGGER.debug("Zone prefix locked to '%s'", self._zone_prefix)

    def reset_zone_prefix_detection(self) -> None:
        """Allow re-detection on the next connect.

        Called before a reconnect so a prefix locked in from a bad probe (or a
        device swap on the same port) is not carried forward forever.
        """
        self._zone_prefix_locked = False

    @property
    def has_zone_prefix_fallback(self) -> bool:
        """Whether a candidate prefix is available for auto-detection."""
        return bool(self._zone_prefix_fallback) and not self._zone_prefix_locked

    # ─── Command Formatting ──────────────────────────────────────────────────

    def format_command(self, command_name: str, **kwargs: Any) -> str | None:
        """Format a command string using the profile template.

        Returns the full framed command ready to send, or None if command not defined.
        Automatically injects {zp} (zone prefix) if configured in profile.
        """
        template = self._commands.get(command_name)
        if not template:
            _LOGGER.debug("Command '%s' not defined in profile", command_name)
            return None

        # Inject zone prefix for templates that use {zp}
        if self._zone_prefix and "{zp}" in template:
            kwargs.setdefault("zp", self._zone_prefix)

        # Tone controls: convert a signed level to the encoding this template
        # expects. Callers pass the true signed value (e.g. -8); templates using
        # {sign} want the magnitude alongside it, while offset-encoded devices
        # (Monoprice/Xantech: 0=-7, 7=flat, 14=+7) want a shifted unsigned value.
        # Previously the caller pre-applied abs(), so -8 and +8 produced
        # byte-identical commands on every profile without a {sign} placeholder
        # and tone cut was impossible on 8 of 12 profiles.
        if command_name in ("bass_set", "treble_set", "balance_set"):
            kwargs = self._encode_tone_level(command_name, template, kwargs)

        try:
            body = template.format(**kwargs)
        except (KeyError, ValueError, IndexError) as err:
            _LOGGER.warning(
                "Failed to format command '%s' with %s: %s", command_name, kwargs, err
            )
            return None

        prefix = self._serial_cfg.get("command_prefix", "")
        suffix = self._serial_cfg.get("command_suffix", "\r")
        # Decode escape sequences in suffix (e.g., "\r" -> actual CR)
        suffix = suffix.encode().decode("unicode_escape")

        return f"{prefix}{body}{suffix}"

    def _encode_tone_level(
        self, command_name: str, template: str, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Return kwargs with `level`/`sign` encoded for this template's style.

        Three styles are in use across the bundled profiles:

        - ``{sign}{level}``  AMC -- explicit sign plus magnitude
        - ``{level:+d}``     RTI/Rotel -- Python's own signed formatting
        - ``{level:02d}``    Monoprice/Xantech/Russound -- unsigned, offset-encoded
        """
        if "level" not in kwargs:
            return kwargs

        result = dict(kwargs)
        try:
            level = int(result["level"])
        except (TypeError, ValueError):
            return result

        # Sign is only meaningful for the {sign} style; magnitude goes with it.
        if "{sign}" in template:
            result["sign"] = "+" if level >= 0 else "-"
            result["level"] = abs(level)
            return result

        # Python's :+d renders the sign itself, so pass the signed value through.
        if "{level:+d}" in template:
            result["level"] = level
            return result

        # Otherwise the device expects an unsigned, offset-encoded value. The
        # profile's response mapping already documents the offset it uses for
        # decoding, so reuse it rather than inventing a second convention.
        state_key = command_name.removesuffix("_set")
        mapping = self._mapping.get(state_key) or {}
        offset = mapping.get("offset")
        if offset is None:
            # No offset declared: the template cannot represent a sign at all,
            # so only the magnitude can be sent. Boost and cut are
            # indistinguishable on these profiles until an offset is added.
            result["level"] = abs(level)
            return result

        # Decoding is `wire + offset`, so encoding is `level - offset`.
        wire = level - int(offset)
        # Clamp to the wire range the device accepts. The service schema allows
        # +/-8, but offset-encoded devices are typically +/-7 (0..14), and a
        # negative value would render as "-1" in a {level:02d} field -- a
        # malformed command rather than a quiet no-op.
        wire_min = 0
        wire_max = mapping.get("max")
        if wire_max is None:
            wire_max = abs(int(offset)) * 2
        wire = min(max(wire, wire_min), int(wire_max))
        result["level"] = wire
        return result

    def frame_to_bytes(self, framed_command: str | bytes) -> bytes:
        """Convert a framed command string to bytes for serial transmission."""
        if isinstance(framed_command, bytes):
            return framed_command
        return framed_command.encode("ascii")

    # ─── Response Parsing ────────────────────────────────────────────────────

    def strip_prefix(self, raw: str) -> str:
        """Strip response prefix from raw line."""
        prefix = self.response_prefix
        if prefix and raw.startswith(prefix):
            return raw[len(prefix) :]
        return raw

    def parse_response(self, line: str | bytes) -> dict[str, Any] | None:
        """Parse a response line into structured state data.

        Returns dict with keys like 'zone', 'power', 'volume', 'source', etc.
        Returns None if the line doesn't match any known pattern.
        """
        if isinstance(line, bytes):
            line = line.decode("ascii", errors="ignore")

        # Check error response. Guard against a falsy sentinel: the Monoprice
        # profile sets `error_response: ""`, and matching that would classify
        # every blank line as a device error -- which rolls back optimistic
        # state for commands the device actually accepted.
        error_token = self.error_response
        if error_token and line == error_token:
            return {"error": True}

        # Check global patterns
        for name, pattern in self._global_patterns.items():
            if isinstance(pattern, re.Pattern):
                match = pattern.search(line)
                if match:
                    result: dict[str, Any] = {"global": name}
                    result.update(match.groupdict())
                    return result
            elif isinstance(pattern, str) and line == pattern:
                return {"global": name}

        # Check status pattern
        if self._status_re:
            match = self._status_re.search(line)
            if match:
                return self._apply_mapping(match.groupdict(), "status")

        # Check tone pattern
        if self._tone_re:
            match = self._tone_re.search(line)
            if match:
                return self._apply_mapping(match.groupdict(), "tone")

        return None

    def _apply_mapping(
        self, raw_groups: dict[str, str], response_type: str
    ) -> dict[str, Any]:
        """Apply the response mapping to convert raw regex groups to typed state."""
        result: dict[str, Any] = {"type": response_type}

        # Zone number (with optional offset for devices like Monoprice
        # where wire zone 11 = logical zone 1)
        if "zone" in raw_groups:
            zone_offset: int = self._response_cfg.get("zone_offset", 0)
            result["zone"] = int(raw_groups["zone"]) + zone_offset

        # Preserve a `field` group verbatim. Profiles that report one setting per
        # frame name it here (NAD: `Main\.(?P<field>\w+)=(?P<value>.+)`), and it is
        # the only thing distinguishing `Main.Power=On` from `Main.Volume=-30` --
        # every mapped key reads from the same `value` group, so the typed result
        # looks identical for both. Without it, response correlation could not tell
        # an unsolicited volume push from the answer to a power command.
        if "field" in raw_groups and raw_groups["field"] is not None:
            result["field"] = raw_groups["field"]

        for state_key, mapping in self._mapping.items():
            field = mapping.get("field")
            if field not in raw_groups:
                continue

            raw_value = raw_groups[field]
            map_type = mapping.get("type", "int")

            try:
                if map_type == "int":
                    value = int(raw_value)
                    offset = mapping.get("offset", 0)
                    result[state_key] = value + offset
                elif map_type == "signed_int":
                    result[state_key] = int(raw_value)
                elif map_type == "string":
                    result[state_key] = raw_value
                elif map_type == "bool":
                    on_value = str(mapping.get("on_value", "1"))
                    result[state_key] = raw_value == on_value
                elif map_type == "string_bool":
                    on_value = mapping.get("on_value", "ON")
                    result[state_key] = raw_value == on_value
                elif map_type == "threshold":
                    off_value = mapping.get("off_value", 0)
                    result[state_key] = int(raw_value) != off_value
                elif map_type == "equals":
                    mute_value = mapping.get("mute_value", 0)
                    result[state_key] = int(raw_value) == mute_value
            except (ValueError, TypeError) as err:
                _LOGGER.debug(
                    "Skipping field '%s' (type=%s): cannot convert '%s': %s",
                    state_key,
                    map_type,
                    raw_value,
                    err,
                )

        return result

    # ─── Volume Conversion ───────────────────────────────────────────────────
    #
    # Intentionally NOT overridden. BaseProtocolEngine implements the conversion
    # once, spanning volume_min..volume_max with Decimal rounding. This class
    # previously carried a near-duplicate that assumed a 0..max scale and used
    # plain round(), which silently broke dB-scale profiles (NAD -80..0 mapped
    # every level to 0 dB = full volume) and reintroduced the off-by-one errors
    # the Decimal arithmetic exists to prevent.

    # ─── Frame Extraction ────────────────────────────────────────────────────

    def extract_frames(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract complete text frames from buffer (CR/LF terminated).

        Returns (list_of_frames, remaining_buffer).
        """
        frames: list[bytes] = []
        terminator = self.response_terminator.encode("ascii")

        while terminator in buffer:
            frame, buffer = buffer.split(terminator, 1)
            frame = frame.strip()
            if frame:
                # Strip response prefix
                prefix = self.response_prefix.encode("ascii")
                if prefix and frame.startswith(prefix):
                    frame = frame[len(prefix) :]
                if frame:
                    frames.append(frame)

        return frames, buffer
