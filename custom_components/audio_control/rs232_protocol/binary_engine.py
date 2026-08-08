"""Binary protocol engine for hex-framed RS232 devices.

Supports devices like SpeakerCraft MZC that use:
- Fixed start byte (e.g., 0x55)
- Length field
- Opcode + data bytes
- Checksum (configurable algorithm)

Profile YAML specifies commands as hex templates with placeholders.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseProtocolEngine

_LOGGER = logging.getLogger(__name__)


def _checksum_mod256(frame_bytes: bytes) -> int:
    """Calculate (0x100 - sum) & 0xFF checksum."""
    return (0x100 - (sum(frame_bytes) % 256)) & 0xFF


def _checksum_xor(frame_bytes: bytes) -> int:
    """Calculate XOR checksum."""
    result = 0
    for b in frame_bytes:
        result ^= b
    return result


def _checksum_rnet(frame_bytes: bytes) -> int:
    """Calculate Russound RNET checksum: (sum + count) & 0x7F."""
    return (sum(frame_bytes) + len(frame_bytes)) & 0x7F


_CHECKSUM_FUNCS = {
    "mod256": _checksum_mod256,
    "xor": _checksum_xor,
    "rnet": _checksum_rnet,
}

# Upper bound on a single binary frame. A length byte is one octet, so no
# legitimate frame exceeds this; anything larger is line noise or a hostile
# length field and is resynced past rather than trusted.
_MAX_FRAME_SIZE = 512

# Command parameters that are genuinely signed on the wire and are therefore
# encoded as two's-complement bytes (e.g. RNET bass/treble span -8..+8).
_SIGNED_BYTE_KEYS = frozenset({"level", "bass", "treble", "balance"})


class BinaryProtocolEngine(BaseProtocolEngine):
    """Protocol engine for binary-framed RS232 devices.

    Profile schema for binary protocols:

    ```yaml
    protocol_type: binary
    serial:
      baud_rate: 57600
      ...
    binary:
      start_byte: 0x55
      length_includes_start: true
      length_includes_checksum: false
      checksum: mod256        # mod256, xor, or none
      flow_control: xon_xoff  # xon_xoff or none
    commands:
      power_on:
        opcode: 0xA0
        data: ["{zone}"]      # zone is 0-indexed on wire
      volume_set:
        opcode: 0x57
        data: ["0x00", "0x00", "0x05", "{volume}", "{zone}"]
    response:
      zone_status:
        opcode: 0x20
        fields:
          zone: {offset: 0, transform: add1}
          power: {offset: 2, bit: 1}
          mute: {offset: 2, bit: 0}
          source: {offset: 3, transform: add1}
          volume: {offset: 4}
    ```
    """

    def __init__(self, profile: dict[str, Any]) -> None:
        """Initialize from a binary protocol profile."""
        self._profile = profile
        self._serial_cfg: dict[str, Any] = profile.get("serial", {})
        self._binary_cfg: dict[str, Any] = profile.get("binary", {})
        self._commands: dict[str, Any] = profile.get("commands", {})
        self._responses: dict[str, Any] = profile.get("response", {})
        self._volume_cfg: dict[str, Any] = profile.get("volume", {})

        # Start sequence: single byte or multi-byte header (e.g., [0x02, 0x00] for HTD)
        start_raw = self._binary_cfg.get("start_bytes")
        if start_raw and isinstance(start_raw, list):
            self._start_bytes: bytes = bytes(start_raw)
            self._start_byte: int = start_raw[0]
        else:
            self._start_byte = self._binary_cfg.get("start_byte", 0x55)
            self._start_bytes = bytes([self._start_byte])
        self._end_byte: int | None = self._binary_cfg.get("end_byte")
        esc_default = 0xF1 if self._end_byte else None
        self._escape_byte: int | None = self._binary_cfg.get("escape_byte", esc_default)
        # Some protocols carry no length field at all: the AMC XCDie frame is a
        # fixed `55 <opcode> AA`, and injecting a length byte made every frame
        # unparseable to the device. Defaults True so existing profiles (Russound
        # RNET, SpeakerCraft MZC) are unaffected.
        self._has_length_byte: bool = self._binary_cfg.get("has_length_byte", True)
        self._length_includes_start: bool = self._binary_cfg.get(
            "length_includes_start", True
        )
        self._length_includes_checksum: bool = self._binary_cfg.get(
            "length_includes_checksum", False
        )
        checksum_name: str = self._binary_cfg.get("checksum", "mod256")
        self._checksum_func = _CHECKSUM_FUNCS.get(checksum_name)
        # A typo ("mdo256") otherwise disables all frame validation silently and
        # is indistinguishable from the documented `checksum: none`. Warn so the
        # misconfiguration is visible; use "none" to intentionally disable.
        if self._checksum_func is None and checksum_name not in ("none", None):
            _LOGGER.warning(
                "Unknown checksum '%s' in profile; frame validation disabled. "
                "Use one of %s, or 'none' to disable intentionally.",
                checksum_name,
                sorted(_CHECKSUM_FUNCS),
            )
        self._flow_control: str = self._binary_cfg.get("flow_control", "none")

        # Parse response opcodes for dispatch
        self._response_map: dict[int, dict[str, Any]] = {}
        for resp_name, resp_cfg in self._responses.items():
            if isinstance(resp_cfg, dict) and "opcode" in resp_cfg:
                opcode = int(str(resp_cfg["opcode"]), 0)
                self._response_map[opcode] = resp_cfg
                self._response_map[opcode]["_name"] = resp_name

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def baud_rate(self) -> int:
        """Serial baud rate."""
        rate: int = self._serial_cfg.get("baud_rate", 57600)
        return rate

    @property
    def data_bits(self) -> int:
        """Serial data bits."""
        bits: int = self._serial_cfg.get("data_bits", 8)
        return bits

    @property
    def parity(self) -> str:
        """Serial parity."""
        p: str = self._serial_cfg.get("parity", "none")
        return {"none": "N", "even": "E", "odd": "O"}.get(p.lower(), "N")

    @property
    def stop_bits(self) -> int:
        """Serial stop bits."""
        bits: int = self._serial_cfg.get("stop_bits", 1)
        return bits

    @property
    def command_delay(self) -> float:
        """Minimum delay between commands."""
        ms: int = self._serial_cfg.get("command_delay_ms", 100)
        return ms / 1000.0

    @property
    def num_zones(self) -> int:
        """Number of zones."""
        zones: int = self._profile.get("zones", 1)
        return zones

    @property
    def num_sources(self) -> int:
        """Number of sources."""
        sources: int | dict[str, Any] = self._profile.get("sources", 1)
        return sources if isinstance(sources, int) else sources.get("count", 1)

    @property
    def volume_max(self) -> int:
        """Maximum volume/attenuation value."""
        vol_max: int = self._volume_cfg.get("max", 80)
        return vol_max

    @property
    def volume_min(self) -> int:
        """Minimum volume value on the device's own scale (0 for most)."""
        vol_min: int = self._volume_cfg.get("min", 0)
        return vol_min

    @property
    def volume_inverted(self) -> bool:
        """Whether volume scale is inverted."""
        inverted: bool = self._volume_cfg.get("inverted", True)
        return inverted

    @property
    def features(self) -> dict[str, bool]:
        """Feature flags."""
        feats: dict[str, bool] = self._profile.get("features", {})
        return feats

    @property
    def has_unsolicited_updates(self) -> bool:
        """Whether device pushes state without polling."""
        return self.features.get("unsolicited_updates", False)

    @property
    def flow_control(self) -> str:
        """Application-level flow control type."""
        return self._flow_control

    @property
    def xon_byte(self) -> int:
        """XON byte (device ready to receive)."""
        val: int = self._binary_cfg.get("xon_byte", 0x11)
        return val

    @property
    def xoff_byte(self) -> int:
        """XOFF byte (device busy)."""
        val: int = self._binary_cfg.get("xoff_byte", 0x13)
        return val

    # ─── Command Formatting ──────────────────────────────────────────────────

    def format_command(self, command_name: str, **kwargs: Any) -> bytes | None:
        """Format a binary command frame.

        Returns complete frame bytes (start + length + data + checksum),
        or None if command is not defined.
        """
        cmd_cfg = self._commands.get(command_name)
        if not cmd_cfg:
            _LOGGER.debug("Command '%s' not defined in profile", command_name)
            return None

        if isinstance(cmd_cfg, dict):
            opcode = int(str(cmd_cfg.get("opcode", "0x00")), 0)
            data_template: list[str] = cmd_cfg.get("data", [])
        else:
            _LOGGER.warning("Invalid command config for '%s'", command_name)
            return None

        # Resolve data bytes from template
        data_bytes: list[int] = []
        for item in data_template:
            resolved = self._resolve_data_byte(item, kwargs)
            if resolved is None:
                # Out-of-range or non-numeric parameter: refuse to build a
                # malformed frame rather than sending a wrapped value.
                _LOGGER.warning(
                    "Cannot build '%s': invalid data byte from template '%s'",
                    command_name,
                    item,
                )
                return None
            data_bytes.append(resolved)

        # Build frame: start + length + opcode + data
        payload = bytes([opcode, *data_bytes])
        frame = self._build_frame_header(payload)

        # Append checksum
        if self._checksum_func:
            frame += bytes([self._checksum_func(frame)])

        # End-delimited protocols (Russound RNET) need the terminator, and any
        # body byte that collides with a framing byte must be escaped first --
        # otherwise the device sees the frame end early. Escaping is applied
        # after the checksum so the checksum covers the unescaped bytes, which is
        # what the receiver reconstructs before validating.
        if self._end_byte is not None:
            frame = self._escape_body(frame) + bytes([self._end_byte])

        return frame

    def _escape_body(self, frame: bytes) -> bytes:
        """Escape framing bytes inside a frame body, leaving the start intact.

        Mirror of the decoder in `_extract_frames_end_delimited`: a byte equal to
        the end byte or the escape byte is replaced with
        `escape_byte, ~byte & 0xFF`.
        """
        if self._escape_byte is None:
            return frame

        special = {self._end_byte, self._escape_byte}
        prefix_len = len(self._start_bytes)
        out = bytearray(frame[:prefix_len])
        for byte in frame[prefix_len:]:
            if byte in special:
                out.append(self._escape_byte)
                out.append(~byte & 0xFF)
            else:
                out.append(byte)
        return bytes(out)

    def frame_to_bytes(self, framed_command: str | bytes) -> bytes:
        """Convert to bytes (already bytes for binary protocols)."""
        if isinstance(framed_command, bytes):
            return framed_command
        return framed_command.encode("ascii")

    def _resolve_data_byte(self, template: str, kwargs: dict[str, Any]) -> int | None:
        """Resolve a single data byte from template string.

        Templates can be:
        - "0xFF" — literal hex value
        - "{zone}" — kwarg value (0-indexed: subtracts 1 from 1-based zone)
        - "{volume}" — kwarg value (direct)
        - "{source}" — kwarg value (0-indexed)
        """
        template = template.strip()

        # Literal hex
        if template.startswith("0x") or template.startswith("0X"):
            return int(template, 16)

        # Literal decimal
        if template.isdigit():
            return int(template)

        # Placeholder
        if template.startswith("{") and template.endswith("}"):
            key = template[1:-1]
            # A missing kwarg must refuse the frame, not default to 0. Defaulting
            # made a dropped parameter indistinguishable from an explicit zero,
            # and 0 is the LOUDEST value on an inverted scale -- so omitting
            # `volume` built a valid, checksummed frame commanding maximum
            # volume. The text engine already fails closed here (format_command
            # returns None on the KeyError), which is the contract to match.
            if key not in kwargs:
                _LOGGER.warning(
                    "Missing parameter '%s' for binary command; refusing frame", key
                )
                return None
            value = kwargs[key]
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                _LOGGER.warning("Non-numeric value for '%s': %r", key, value)
                return None
            # Zone and source are 0-indexed on the wire. A zone of 0 would map
            # to -1, which bytes() rejects with a ValueError that escaped
            # format_command entirely.
            if key in ("zone", "source"):
                numeric -= 1

            # Tone/balance controls carry signed values. The wire encoding is
            # per-device: RNET is offset-encoded (+10 bias, 0x00..0x14), while
            # other devices use two's complement. Read the bias the profile
            # declared for DECODING and apply its inverse here, so transmit and
            # receive cannot drift apart.
            if key in _SIGNED_BYTE_KEYS:
                bias = self._tone_bias(key)
                if bias is not None:
                    wire = numeric + bias
                    if not 0 <= wire <= 0xFF:
                        _LOGGER.warning(
                            "Biased value for '%s' out of byte range: %d", key, wire
                        )
                        return None
                    return wire
                if not -128 <= numeric <= 127:
                    _LOGGER.warning(
                        "Signed value for '%s' out of range: %d", key, numeric
                    )
                    return None
                return numeric & 0xFF

            if not 0 <= numeric <= 0xFF:
                # Silently masking with & 0xFF turned volume=-1 into 0xFF (full
                # attenuation on an inverted scale) and volume=300 into 44.
                _LOGGER.warning(
                    "Value for '%s' out of byte range after encoding: %d",
                    key,
                    numeric,
                )
                return None
            return numeric

        _LOGGER.warning("Unknown data template: '%s'", template)
        return None

    def _tone_bias(self, key: str) -> int | None:
        """Bias declared for this tone field's DECODE path, if any.

        `level` in a command maps to whichever tone field the response config
        biases (bass/treble/balance all share the same bias in practice), so a
        single lookup keeps encode and decode symmetric.
        """
        candidates = (key,) if key != "level" else ("bass", "treble", "balance")
        for resp_cfg in self._responses.values():
            if not isinstance(resp_cfg, dict):
                continue
            fields = resp_cfg.get("fields")
            if not isinstance(fields, dict):
                continue
            for name in candidates:
                cfg = fields.get(name)
                if isinstance(cfg, dict) and cfg.get("transform") == "bias":
                    return int(cfg.get("bias", 0))
        return None

    def _build_frame_header(self, payload: bytes) -> bytes:
        """Build start byte(s) + optional length_byte + payload.

        Uses the full `_start_bytes` sequence rather than the scalar
        `_start_byte`, so profiles declaring a multi-byte preamble (e.g. HTD's
        `start_bytes: [0x02, 0x00]`) emit all of it.
        """
        start = self._start_bytes
        if not self._has_length_byte:
            # Fixed-width protocols such as the AMC XCDie (`55 <opcode> AA`)
            # define no length field, so emitting one desynchronises the frame.
            return bytes([*start, *payload])

        length = (
            len(start) + 1 + len(payload)  # start + length + payload
            if self._length_includes_start
            else len(payload)
        )
        if self._length_includes_checksum:
            length += 1

        return bytes([*start, length, *payload])

    # ─── Response Parsing ────────────────────────────────────────────────────

    def parse_response(self, data: str | bytes) -> dict[str, Any] | None:
        """Parse a binary response frame into structured data."""
        if isinstance(data, str):
            data = data.encode("latin-1")

        if len(data) < 3:
            return None

        # Verify start byte
        if data[0] != self._start_byte:
            return None

        # Opcode sits after the length byte, or immediately after the start
        # byte(s) on protocols that carry no length field (AMC XCDie).
        opcode_index = len(self._start_bytes) + (1 if self._has_length_byte else 0)
        if opcode_index >= len(data):
            return None
        opcode = data[opcode_index]

        resp_cfg = self._response_map.get(opcode)
        if not resp_cfg:
            _LOGGER.debug("Unknown response opcode: 0x%02X", opcode)
            return None

        fields_cfg: dict[str, Any] = resp_cfg.get("fields", {})
        result: dict[str, Any] = {"type": resp_cfg.get("_name", "unknown")}

        # Constants carried by the opcode itself, for protocols where the reply
        # code IS the state and there is no payload to read offsets from. The AMC
        # XCDie status frame is exactly `55 <code> AA`, with the input in the high
        # nibble and the transport state in the low nibble. Applied before
        # `fields` so a payload-derived value can still override a constant.
        static_cfg = resp_cfg.get("static")
        if isinstance(static_cfg, dict):
            result.update(static_cfg)

        # Payload follows the opcode.
        payload = data[opcode_index + 1 :]

        for field_name, field_cfg in fields_cfg.items():
            if not isinstance(field_cfg, dict):
                continue
            offset = field_cfg.get("offset", 0)
            if offset >= len(payload):
                continue

            raw_value = payload[offset]

            # Bit extraction
            if "bit" in field_cfg:
                bit = field_cfg["bit"]
                result[field_name] = bool(raw_value & (1 << bit))
            # Transform
            elif "transform" in field_cfg:
                transform = field_cfg["transform"]
                if transform == "add1":
                    result[field_name] = raw_value + 1
                elif transform == "signed":
                    result[field_name] = (
                        raw_value if raw_value < 128 else raw_value - 256
                    )
                elif transform == "bias":
                    # Value is offset-encoded, not two's complement: subtract a
                    # fixed bias. RNET tone controls are 0x00..0x14 meaning
                    # -10..+10, so `bias: 10` maps 0x0A (flat) to 0. Reading
                    # these as `signed` made flat decode as +10 (full boost).
                    # NOTE: `offset` above is a BYTE POSITION in the payload, so
                    # a separate key is required for a value bias.
                    result[field_name] = raw_value - int(field_cfg.get("bias", 0))
                else:
                    result[field_name] = raw_value
            else:
                result[field_name] = raw_value

        return result

    def extract_frames(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract complete binary frames from buffer.

        Two modes:
        - End-byte delimited (RNET): start_byte ... end_byte, with escape handling
        - Length-based (SpeakerCraft): start_byte + length field

        Returns (frames, remaining_buffer).
        """
        if self._end_byte is not None:
            return self._extract_frames_end_delimited(buffer)
        return self._extract_frames_length_based(buffer)

    def _frame_checksum_valid(self, frame: bytes) -> bool:
        """Whether an end-delimited frame's trailing checksum is correct.

        Frame layout is `start ... body checksum end`, so the checksum covers
        everything up to (but excluding) the checksum and the end byte. Frames
        are accepted when the profile declares no checksum algorithm.
        """
        if self._checksum_func is None:
            return True
        # start(>=1) + at least one body byte + checksum + end
        if len(frame) < len(self._start_bytes) + 3:
            return False
        body = frame[:-2]
        return frame[-2] == self._checksum_func(body)

    def _extract_frames_end_delimited(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract frames delimited by start_byte and end_byte.

        Handles escape sequences: escape_byte followed by inverted byte.
        Example (RNET): 0xF0 ... 0xF7, escape 0xF1 + ~byte.
        """
        frames: list[bytes] = []
        pos = 0
        end_byte = self._end_byte  # already checked not None by caller

        while pos < len(buffer):
            # Find the start sequence (may be multiple bytes)
            if not buffer.startswith(self._start_bytes, pos):
                pos += 1
                continue

            # Scan for end byte, handling escape sequences
            frame_start = pos
            pos += len(self._start_bytes)
            payload: list[int] = list(self._start_bytes)

            while pos < len(buffer):
                byte = buffer[pos]

                if byte == end_byte:
                    # End of frame found
                    payload.append(byte)
                    pos += 1
                    frame = bytes(payload)
                    # Validate the checksum. The length-based extractor already
                    # did this; skipping it here meant RS232 line noise wrote
                    # corrupt volume/source values straight into zone state,
                    # even though the profile declares a checksum algorithm.
                    if self._frame_checksum_valid(frame):
                        frames.append(frame)
                    else:
                        _LOGGER.debug(
                            "Dropping frame with bad checksum: %s", frame.hex(" ")
                        )
                        # Resync one byte past the start rather than past the end
                        # byte. A stray start byte immediately before a good
                        # frame (line noise injecting 0xF0) would otherwise
                        # swallow the real frame that follows it.
                        pos = frame_start + 1
                    break

                if self._escape_byte is not None and byte == self._escape_byte:
                    # Escape sequence: next byte is bitwise inverted
                    pos += 1
                    if pos >= len(buffer):
                        # Incomplete escape — put back and wait for more data
                        return frames, buffer[frame_start:]
                    payload.append(~buffer[pos] & 0xFF)
                    pos += 1
                else:
                    payload.append(byte)
                    pos += 1
            else:
                # Reached end of buffer without finding end_byte
                return frames, buffer[frame_start:]

        return frames, buffer[pos:]

    def _extract_frames_length_based(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract frames using start_byte + length field.

        Requires `has_length_byte`. extract_frames() routes on `end_byte`, so a
        profile that sets `has_length_byte: false` WITHOUT an end byte would land
        here and read its opcode as a length -- extracting nothing, forever. The
        AMC XCDie avoids this only because it declares end_byte 0xAA and takes the
        delimited path. Warn rather than raise: losing frame extraction is bad,
        but taking down the integration for a profile authoring error is worse.
        """
        if not self._has_length_byte:
            _LOGGER.warning(
                "Profile sets has_length_byte: false with no end_byte; "
                "length-based framing cannot work. Declare an end_byte."
            )
            return [], b""
        frames: list[bytes] = []
        pos = 0

        while pos < len(buffer):
            # Find the start sequence (may be multiple bytes)
            if not buffer.startswith(self._start_bytes, pos):
                # Skip XON/XOFF flow control bytes
                if buffer[pos] in (self.xon_byte, self.xoff_byte):
                    pos += 1
                    continue
                pos += 1
                continue

            # Need at least start + length
            start_len = len(self._start_bytes)
            if pos + start_len >= len(buffer):
                break

            length = buffer[pos + start_len]

            # Calculate total frame size
            frame_size = length if self._length_includes_start else length + 2

            if not self._length_includes_checksum:
                frame_size += 1  # add checksum byte

            # A device-supplied length byte drives frame_size, so it must be
            # sanity-checked before use as a buffer advance. A zero (or absurdly
            # large) length would otherwise pin the loop -- frame_size == 0 makes
            # `pos += frame_size` never advance, hanging the event loop on input
            # like 0x55 0x00.
            min_size = start_len + 2  # start(s) + length + at least one byte
            if frame_size < min_size or frame_size > _MAX_FRAME_SIZE:
                pos += 1  # implausible length; resync one byte forward
                continue

            # Check if complete frame available
            if pos + frame_size > len(buffer):
                break

            frame = buffer[pos : pos + frame_size]

            # Verify checksum if configured
            if self._checksum_func:
                frame_data = frame[:-1]
                expected_checksum = self._checksum_func(frame_data)
                actual_checksum = frame[-1]
                if expected_checksum != actual_checksum:
                    _LOGGER.debug(
                        "Checksum mismatch: expected 0x%02X got 0x%02X",
                        expected_checksum,
                        actual_checksum,
                    )
                    pos += 1  # Skip this start byte, try next
                    continue

            frames.append(frame)
            pos += frame_size

        return frames, buffer[pos:]
