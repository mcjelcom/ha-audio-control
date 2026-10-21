"""JSON protocol engine for JSON-over-serial RS232 devices.

Supports devices like RTI AD-46-100 that use:
- Newline-delimited JSON commands/responses
- Authentication (login required before commands)
- Status codes in responses
- Array-indexed zone addressing

Profile YAML specifies commands as JSON templates with placeholders.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import BaseProtocolEngine

_LOGGER = logging.getLogger(__name__)


class _Unresolved:
    """Marker for a placeholder with no matching kwarg.

    Distinct from None, which is a legitimate JSON value a profile may intend.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<unresolved>"


_UNRESOLVED = _Unresolved()

# ZoneState field types, for coercing values pulled through response.mappings.
_BOOL_KEYS = frozenset({"power", "mute", "group"})
_INT_KEYS = frozenset({"volume", "source", "bass", "treble", "balance"})


def _contains_unresolved(value: Any) -> bool:
    """Whether a resolved template still holds an unresolved placeholder.

    Recursive because value_template is arbitrary nested JSON -- a missing kwarg
    can sit several levels down inside a list of dicts.
    """
    if isinstance(value, _Unresolved):
        return True
    if isinstance(value, list):
        return any(_contains_unresolved(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_unresolved(v) for v in value.values())
    return False


class JsonProtocolEngine(BaseProtocolEngine):
    """Protocol engine for JSON-framed RS232 devices.

    Profile schema for JSON protocols:

    ```yaml
    protocol_type: json
    serial:
      baud_rate: 9600
      ...
    json:
      delimiter: "\\n"         # Frame delimiter (newline-delimited JSON)
      login:
        username: "admin"
        password: "admin"
      status_field: "status"   # Field containing status code
      success_codes: [200, 901]
    commands:
      power_on:
        type: set_powerstate
        value: true
      volume_set:
        type: set_outputvol
        value_template: [{"index": "{zone}", "value": "{volume}"}]
      source_set:
        type: set_outputsource1
        value_template: [{"index": "{zone}", "value": "{source}"}]
    response:
      mappings:
        set_outputvol:
          zone_field: index
          fields:
            volume: value
        set_powerstate:
          fields:
            power: value
    ```
    """

    def __init__(self, profile: dict[str, Any]) -> None:
        """Initialize from a JSON protocol profile."""
        self._profile = profile
        self._serial_cfg: dict[str, Any] = profile.get("serial", {})
        self._json_cfg: dict[str, Any] = profile.get("json", {})
        self._commands: dict[str, Any] = profile.get("commands", {})
        self._responses: dict[str, Any] = profile.get("response", {})
        self._volume_cfg: dict[str, Any] = profile.get("volume", {})

        self._delimiter: str = self._json_cfg.get("delimiter", "\n")
        self._login_cfg: dict[str, str] = self._json_cfg.get("login", {})
        self._status_field: str = self._json_cfg.get("status_field", "status")
        self._success_codes: list[int] = self._json_cfg.get("success_codes", [200, 901])
        self._logged_in: bool = False

    # ─── Properties ──────────────────────────────────────────────────────────

    @property
    def baud_rate(self) -> int:
        """Serial baud rate."""
        rate: int = self._serial_cfg.get("baud_rate", 9600)
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
        ms: int = self._serial_cfg.get("command_delay_ms", 50)
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
        """Maximum volume value."""
        vol_max: int = self._volume_cfg.get("max", 100)
        return vol_max

    @property
    def volume_min(self) -> int:
        """Minimum volume value on the device's own scale (0 for most)."""
        vol_min: int = self._volume_cfg.get("min", 0)
        return vol_min

    @property
    def volume_inverted(self) -> bool:
        """Whether volume scale is inverted."""
        inverted: bool = self._volume_cfg.get("inverted", False)
        return inverted

    @property
    def features(self) -> dict[str, bool]:
        """Feature flags."""
        feats: dict[str, bool] = self._profile.get("features", {})
        return feats

    @property
    def has_unsolicited_updates(self) -> bool:
        """Whether device pushes state without polling."""
        return self.features.get("unsolicited_updates", True)

    @property
    def requires_login(self) -> bool:
        """Whether the device requires authentication before commands."""
        return bool(self._login_cfg)

    @property
    def delimiter(self) -> str:
        """Frame delimiter for JSON messages."""
        return self._delimiter

    # ─── Authentication ──────────────────────────────────────────────────────

    def format_login(self) -> bytes:
        """Format the login command."""
        login_obj = {
            "type": "login",
            "username": self._login_cfg.get("username", ""),
            "password": self._login_cfg.get("password", ""),
        }
        return (json.dumps(login_obj, separators=(",", ":")) + self._delimiter).encode(
            "utf-8"
        )

    def mark_logged_in(self) -> None:
        """Mark the session authenticated without seeing a login reply.

        NOT used by AsyncSerialConnection: parse_response sets `_logged_in`
        itself when it decodes a successful `type: login` frame, which is the only
        evidence that actually proves the credentials were accepted. Kept as
        public API for a standalone consumer that authenticates out of band (e.g.
        a device already logged in on a shared link), and because calling it
        speculatively is exactly the mistake that made an unauthenticated session
        look healthy.
        """
        self._logged_in = True

    @property
    def logged_in(self) -> bool:
        """Whether we've successfully authenticated."""
        return self._logged_in

    # ─── Command Formatting ──────────────────────────────────────────────────

    def format_command(self, command_name: str, **kwargs: Any) -> bytes | None:
        """Format a JSON command.

        Returns UTF-8 encoded JSON + delimiter, or None if undefined.
        """
        cmd_cfg = self._commands.get(command_name)
        if not cmd_cfg:
            _LOGGER.debug("Command '%s' not defined in profile", command_name)
            return None

        if not isinstance(cmd_cfg, dict):
            return None

        # Build JSON object
        cmd_obj: dict[str, Any] = {"type": cmd_cfg["type"]}

        # Handle value — either literal or template
        if "value" in cmd_cfg:
            cmd_obj["value"] = cmd_cfg["value"]
        elif "value_template" in cmd_cfg:
            resolved = self._resolve_template(cmd_cfg["value_template"], kwargs)
            if _contains_unresolved(resolved):
                _LOGGER.warning(
                    "Refusing '%s': template has unresolved placeholders", command_name
                )
                return None
            cmd_obj["value"] = resolved

        return (json.dumps(cmd_obj, separators=(",", ":")) + self._delimiter).encode(
            "utf-8"
        )

    def frame_to_bytes(self, framed_command: str | bytes) -> bytes:
        """Convert to bytes."""
        if isinstance(framed_command, bytes):
            return framed_command
        return framed_command.encode("utf-8")

    def _resolve_template(self, template: Any, kwargs: dict[str, Any]) -> Any:
        """Recursively resolve placeholders in a JSON template.

        Placeholders are strings like "{zone}", "{volume}", "{source}".

        Returns _UNRESOLVED if a placeholder has no matching kwarg. A sentinel is
        needed rather than None because None is a legitimate JSON value, and the
        old behaviour -- substituting the template text itself -- shipped the
        literal string "{zone}" to the device inside otherwise well-formed JSON.
        """
        if isinstance(template, str):
            # Check if it's a pure placeholder
            if template.startswith("{") and template.endswith("}"):
                key = template[1:-1]
                if key not in kwargs:
                    _LOGGER.warning(
                        "Missing parameter '%s' for JSON command; refusing frame", key
                    )
                    return _UNRESOLVED
                return kwargs[key]
            # Check for embedded placeholders
            for key, value in kwargs.items():
                template = template.replace(f"{{{key}}}", str(value))
            return template
        if isinstance(template, list):
            return [self._resolve_template(item, kwargs) for item in template]
        if isinstance(template, dict):
            return {k: self._resolve_template(v, kwargs) for k, v in template.items()}
        return template

    # ─── Response Parsing ────────────────────────────────────────────────────

    def parse_response(self, data: str | bytes) -> dict[str, Any] | None:
        """Parse a JSON response into structured data."""
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")

        data = data.strip()
        if not data:
            return None

        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            _LOGGER.debug("Invalid JSON response: '%s'", data[:100])
            return None

        if not isinstance(obj, dict):
            return None

        result: dict[str, Any] = {"type": obj.get("type", "unknown")}

        status = obj.get(self._status_field)
        if status is not None:
            result["status"] = status

        # Login responses are checked BEFORE the generic status-code guard.
        # With the guard first, a failing status returned early and the
        # login_failed flag below was unreachable -- so an auth failure was
        # indistinguishable from a transient device error and the integration
        # retried forever with no actionable diagnostic.
        if obj.get("type") == "login":
            if status in self._success_codes:
                self._logged_in = True
                result["login_success"] = True
            else:
                result["login_failed"] = True
                result["error"] = True
            return result

        # Generic status-code check for all other message types.
        if status is not None and status not in self._success_codes:
            result["error"] = True
            return result

        # Extract value field
        value = obj.get("value")
        if value is not None:
            result["value"] = value

            # Try to extract zone-specific data from array values
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "index" in item:
                        # JSON permits any type here. Comparing a str/None to an
                        # int raised TypeError straight out of send_command into
                        # HA service calls, and six such frames killed the read
                        # loop via its consecutive-error bound.
                        try:
                            zone = int(item["index"])
                        except (TypeError, ValueError):
                            _LOGGER.debug(
                                "Ignoring non-numeric zone index: %r", item["index"]
                            )
                            continue
                        if zone > 0:  # index 0 = all zones
                            result["zone"] = zone
                        if "value" in item:
                            result["raw_value"] = item["value"]
            elif isinstance(value, bool):
                result["power"] = value

        mapping = self._responses.get("mappings", {}).get(obj.get("type"))
        if isinstance(mapping, dict) and value is not None:
            self._apply_mapping(mapping, value, result)

        return result

    def _apply_mapping(
        self, mapping: dict[str, Any], value: Any, result: dict[str, Any]
    ) -> None:
        """Translate a reply's value into zone-state keys via response.mappings.

        Without this, a mapped reply only carried `zone` / `raw_value`, which
        _process_response does not consume -- so changes made on a keypad or the
        unit itself never reached Home Assistant.

        Array values are scanned for the item carrying `zone_field`; a scalar
        value (e.g. set_powerstate's bare bool) is treated as the item itself.
        """
        fields: dict[str, str] = mapping.get("fields", {})
        zone_field: str | None = mapping.get("zone_field")

        item: dict[str, Any] | None = None
        if isinstance(value, list):
            item = next(
                (
                    v
                    for v in value
                    if isinstance(v, dict) and (zone_field is None or zone_field in v)
                ),
                None,
            )
        elif isinstance(value, dict):
            item = value

        # The generic scan above only knows "index"; honour a custom zone_field.
        if item is not None and zone_field and "zone" not in result:
            try:
                zone = int(item[zone_field])
            except (KeyError, TypeError, ValueError):
                zone = 0
            if zone > 0:
                result["zone"] = zone

        for state_key, src_field in fields.items():
            if item is not None:
                if src_field not in item:
                    continue
                raw = item[src_field]
            elif src_field == "value":
                raw = value  # scalar reply: the bare value IS the field
            else:
                continue
            coerced = self._coerce(state_key, raw)
            if coerced is not None:
                result[state_key] = coerced

    @staticmethod
    def _coerce(state_key: str, raw: Any) -> Any:
        """Coerce a mapped value to the type ZoneState expects.

        bool is checked before int because bool is an int subclass: a stray
        `true` for volume must not become volume 1.
        """
        if state_key in _BOOL_KEYS:
            return raw if isinstance(raw, bool) else None
        if state_key in _INT_KEYS:
            if isinstance(raw, bool):
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                _LOGGER.debug("Ignoring non-numeric %s: %r", state_key, raw)
                return None
        return raw

    def extract_frames(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        """Extract complete JSON frames (delimiter-separated)."""
        frames: list[bytes] = []
        delimiter_bytes = self._delimiter.encode("utf-8")

        while delimiter_bytes in buffer:
            frame, buffer = buffer.split(delimiter_bytes, 1)
            frame = frame.strip()
            if frame:
                frames.append(frame)

        return frames, buffer
