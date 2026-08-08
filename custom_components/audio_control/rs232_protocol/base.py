"""Base protocol engine interface.

All protocol engines (text, binary, JSON) implement this interface.
AsyncSerialConnection uses it to format/parse without knowing the protocol type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProtocolEngine(ABC):
    """Abstract base for all protocol engines."""

    # Every concrete engine stores the profile it was built from; declared here
    # so shared helpers on this class (has_command) can read it under --strict.
    _profile: dict[str, Any]

    @abstractmethod
    def __init__(self, profile: dict[str, Any]) -> None:
        """Initialize from a profile dict."""

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def baud_rate(self) -> int:
        """Serial baud rate."""

    @property
    @abstractmethod
    def data_bits(self) -> int:
        """Serial data bits."""

    @property
    @abstractmethod
    def parity(self) -> str:
        """Serial parity ('N', 'E', 'O')."""

    @property
    @abstractmethod
    def stop_bits(self) -> int:
        """Serial stop bits."""

    @property
    @abstractmethod
    def command_delay(self) -> float:
        """Minimum delay between commands (seconds)."""

    @property
    @abstractmethod
    def num_zones(self) -> int:
        """Number of zones."""

    @property
    @abstractmethod
    def num_sources(self) -> int:
        """Number of sources."""

    @property
    @abstractmethod
    def volume_max(self) -> int:
        """Maximum volume/attenuation value."""

    @property
    def volume_min(self) -> int:
        """Minimum volume value on the device's own scale.

        Zero for the common 0..max scales. Devices that report volume in dBFS
        use a negative floor (NAD: -80..0, Yamaha: -80..16), and conversion must
        span min..max rather than assuming 0..max -- otherwise every requested
        level collapses toward one end of the range.
        """
        return 0

    @property
    @abstractmethod
    def volume_inverted(self) -> bool:
        """Whether volume scale is inverted."""

    @property
    @abstractmethod
    def features(self) -> dict[str, bool]:
        """Feature flags."""

    @property
    @abstractmethod
    def has_unsolicited_updates(self) -> bool:
        """Whether device pushes state without polling."""

    # ─── Command Formatting ──────────────────────────────────────────────────

    @abstractmethod
    def format_command(self, command_name: str, **kwargs: Any) -> str | bytes | None:
        """Format a command. Returns framed data ready to send, or None."""

    @abstractmethod
    def frame_to_bytes(self, framed_command: str | bytes) -> bytes:
        """Convert formatted command to bytes for transmission."""

    # ─── Response Parsing ────────────────────────────────────────────────────

    @abstractmethod
    def parse_response(self, data: str | bytes) -> dict[str, Any] | None:
        """Parse a response into structured state data. None if unrecognized."""

    @abstractmethod
    def extract_frames(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract complete frames from a byte buffer.

        Returns (list_of_complete_frames, remaining_buffer).
        For text protocols, frames are newline/CR-terminated strings.
        For binary protocols, frames are length-delimited byte sequences.
        """

    @property
    def source_command_map(self) -> dict[int, str]:
        """Source number to command name mapping (for named-source devices)."""
        return {}

    def has_command(self, command_name: str) -> bool:
        """Whether the profile defines this command.

        Lets the entity layer advertise only features the device can actually
        perform. Gating on a value range instead (e.g. volume_max > 0) put dead
        +/- buttons in the UI on profiles with no volume_up/volume_down.
        """
        commands = self._profile.get("commands") or {}
        return command_name in commands

    @property
    def strip_nul(self) -> bool:
        """Whether the read loop should strip NUL bytes before framing.

        Some text devices pad between frames with NULs. Binary protocols must
        NOT strip NULs -- 0x00 is a legal payload byte -- so this defaults to
        False and only the text engine opts in.
        """
        return False

    @property
    def response_timeout(self) -> float:
        """Timeout in seconds waiting for a command response."""
        return 1.5

    @property
    def retry_count(self) -> int:
        """Number of retries on command timeout (0 = no retry)."""
        return 0

    @property
    def init_sequence(self) -> list[bytes]:
        """Bytes to send before first real command (device wakeup)."""
        return []

    @property
    def heartbeat_interval(self) -> float:
        """Interval for heartbeat/keepalive queries (0 = disabled)."""
        return 0.0

    # ─── Volume Conversion ───────────────────────────────────────────────────

    def ha_volume_to_device(self, ha_volume: float) -> int:
        """Convert normalized volume (0.0-1.0) to a device value.

        Maps across the device's full min..max span, so dB scales with a
        negative floor work as well as plain 0..max scales.

        Uses Decimal arithmetic to prevent off-by-one errors at step
        boundaries (notably on inverted scales).
        """
        from decimal import ROUND_HALF_EVEN, Decimal

        vol_min = self.volume_min
        vol_max = self.volume_max
        span = vol_max - vol_min
        if span == 0:
            return vol_max

        fraction = 1.0 - ha_volume if self.volume_inverted else ha_volume
        result = Decimal(str(vol_min)) + Decimal(str(fraction)) * span
        return int(result.to_integral_value(rounding=ROUND_HALF_EVEN))

    def device_volume_to_ha(self, device_volume: int) -> float:
        """Convert a device volume value to normalized volume (0.0-1.0).

        Result is clamped to 0.0-1.0: devices occasionally report values
        outside their documented range (or a mute sentinel), and Home Assistant
        rejects a volume_level outside that interval.
        """
        vol_min = self.volume_min
        vol_max = self.volume_max
        span = vol_max - vol_min
        if span == 0:
            return 0.0

        fraction = (device_volume - vol_min) / span
        if self.volume_inverted:
            fraction = 1.0 - fraction
        return round(min(max(fraction, 0.0), 1.0), 3)
