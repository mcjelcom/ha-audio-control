"""Config flow for Audio Control."""

from __future__ import annotations

import glob
import logging
import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PORT

try:
    # HA 2025.x moved this to helpers.service_info.usb; older releases and the
    # re-export both live under components.usb. Prefer the new location.
    from homeassistant.helpers.service_info.usb import UsbServiceInfo
except ImportError:  # pragma: no cover - depends on HA version
    from homeassistant.components.usb import UsbServiceInfo

from .const import (
    CONF_BAUD_RATE,
    CONF_DEVICE_PROFILE,
    CONF_LOGIN_PASSWORD,
    CONF_LOGIN_USERNAME,
    CONF_NUM_SOURCES,
    CONF_NUM_ZONES,
    CONF_SOURCE_NAMES,
    CONF_ZONE_NAMES,
    DEMO_PORT,
    DOMAIN,
)
from .profile_loader import load_all_profiles

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

CUSTOM_DEVICE_OPTION = ">> Custom Device (define via UI)"


def _resolve_sources(profile: dict[str, Any]) -> tuple[int, dict[int, str]]:
    """Return (count, names) from a profile's `sources`, which may be int or dict.

    Profiles express sources either as a plain count (`sources: 6`) or as a
    mapping (`sources: {count: 2, names: {1: BUS, 2: LINE}}`). The engine already
    handles both, but the config flow did raw arithmetic on the value -- so the
    five profiles using the mapping form (Marantz, Monoprice 31028, NAD, Rotel
    RA-1572, Yamaha) raised TypeError on Submit and could never be added.
    """
    raw = profile.get("sources", 6)
    if isinstance(raw, int):
        return raw, {}
    if isinstance(raw, dict):
        names = {int(k): str(v) for k, v in (raw.get("names") or {}).items()}
        # A names mapping without an explicit count implies one source per name.
        count = raw.get("count") or len(names) or 6
        return int(count), names
    return 6, {}


def _is_network_url(port: str) -> bool:
    """Check if port is a network URL (socket://, rfc2217://)."""
    return port.startswith(("socket://", "rfc2217://"))


def _list_serial_ports() -> list[str]:
    """Discover available serial ports."""
    import serial.tools.list_ports

    ports = []
    for port_info in serial.tools.list_ports.comports():
        ports.append(port_info.device)
    for pattern in [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyAMA*",
        "/dev/serial/by-id/*",
    ]:
        ports.extend(glob.glob(pattern))
    return sorted(set(ports))


def _test_port(port: str) -> str | None:
    """Test a port (serial or network). Returns None on success, error on failure."""
    if port == DEMO_PORT:
        return None

    if _is_network_url(port):
        return _test_network_port(port)
    return _test_serial_port(port)


def _test_serial_port(port: str) -> str | None:
    """Test a local serial port."""
    import serial

    try:
        s = serial.Serial(port, timeout=1)
        s.close()
        return None
    except PermissionError:
        return f"Permission denied for {port}. Add user to 'dialout' group."
    except (serial.SerialException, OSError) as err:
        return str(err)


def _test_network_port(port: str) -> str | None:
    """Test a network URL (socket://host:port) by attempting TCP connect."""
    import socket
    import urllib.parse

    try:
        parsed = urllib.parse.urlparse(port)
        hostname = parsed.hostname
        net_port = parsed.port
        if not hostname or not net_port:
            return f"Invalid URL format: {port}. Use socket://host:port"
        sock = socket.create_connection((hostname, net_port), timeout=3)
        sock.close()
        return None
    except TimeoutError:
        return f"Connection timed out to {port}"
    except OSError as err:
        return f"Cannot connect to {port}: {err}"


class AudioControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Audio Control."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize flow with storage for multi-step custom device wizard."""
        self._custom_data: dict[str, Any] = {}
        self._discovered_port: str | None = None

    async def async_step_usb(self, discovery_info: UsbServiceInfo) -> ConfigFlowResult:
        """Handle a USB-serial adapter discovered via the manifest usb matchers.

        Without this step, plugging in any FTDI/CH340/CP2102/PL2303 adapter --
        the most common USB-serial chips, many unrelated to audio gear -- would
        raise UnknownStep because the manifest registers the integration for USB
        discovery. We pre-fill the port and hand off to the normal user step so
        the person still picks the device profile.
        """
        port = discovery_info.device
        # One config entry per port; do not offer discovery for a port already set.
        await self.async_set_unique_id(f"ac_{port}")
        self._abort_if_unique_id_configured()

        self._discovered_port = port
        # Surface the port in the confirmation form's title.
        self.context["title_placeholders"] = {"port": port}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Select device profile and serial port."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        # Load available profiles
        profiles = await self.hass.async_add_executor_job(
            load_all_profiles, self.hass.config.config_dir
        )
        profile_names = sorted(profiles.keys()) + [CUSTOM_DEVICE_OPTION]

        if user_input is not None:
            profile_name = user_input[CONF_DEVICE_PROFILE]
            port = user_input[CONF_PORT]

            # Custom device -> go to multi-step wizard
            if profile_name == CUSTOM_DEVICE_OPTION:
                self._custom_data["port"] = port
                return await self.async_step_custom_basic()

            profile = profiles.get(profile_name)

            if not profile:
                errors["base"] = "invalid_profile"
            elif port != DEMO_PORT:
                error_msg = await self.hass.async_add_executor_job(_test_port, port)
                if error_msg:
                    errors["base"] = "cannot_connect"
                    description_placeholders["error_detail"] = error_msg

            if not errors and profile:
                await self.async_set_unique_id(f"ac_{port}")
                self._abort_if_unique_id_configured()

                num_zones = profile.get("zones", 6)
                num_sources, profile_source_names = _resolve_sources(profile)
                baud = profile.get("serial", {}).get("baud_rate", 9600)

                # Prefer the profile's own source names (e.g. "HDMI 1",
                # "Optical") over generic "Source N" labels.
                source_names = {
                    i: profile_source_names.get(i, f"Source {i}")
                    for i in range(1, num_sources + 1)
                }
                zone_names = {i: f"Zone {i}" for i in range(1, num_zones + 1)}

                title = profile.get("name", profile_name)
                if port == DEMO_PORT:
                    title += " (Demo)"

                return self.async_create_entry(
                    title=title,
                    data={
                        "port": port,
                        CONF_DEVICE_PROFILE: profile_name,
                        CONF_BAUD_RATE: baud,
                        CONF_NUM_ZONES: num_zones,
                        CONF_NUM_SOURCES: num_sources,
                    },
                    options={
                        CONF_SOURCE_NAMES: source_names,
                        CONF_ZONE_NAMES: zone_names,
                    },
                )

        # Discover serial ports + allow network URLs
        available_ports = await self.hass.async_add_executor_job(_list_serial_ports)
        # Suggest local ports + demo + network example
        suggested_ports = available_ports + [DEMO_PORT]
        # A USB-discovered port takes precedence as the default.
        default_port = self._discovered_port or (
            available_ports[0] if available_ports else DEMO_PORT
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_PROFILE,
                        default=profile_names[0]
                        if len(profile_names) > 1
                        else CUSTOM_DEVICE_OPTION,
                    ): vol.In(profile_names),
                    vol.Required(CONF_PORT, default=default_port): str,
                }
            ),
            errors=errors,
            description_placeholders={
                **description_placeholders,
                "suggested_ports": ", ".join(suggested_ports),
            },
        )

    # --- Custom Device Wizard: Step 1 - Basic Info --------------------------

    async def async_step_custom_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Custom device: basic info (name, zones, sources, baud)."""
        if user_input is not None:
            self._custom_data.update(user_input)
            return await self.async_step_custom_serial()

        return self.async_show_form(
            step_id="custom_basic",
            data_schema=vol.Schema(
                {
                    vol.Required("device_name", default="My Device"): str,
                    vol.Required("zones", default=6): vol.In([2, 4, 6, 8, 12, 16]),
                    vol.Required("sources", default=4): vol.In([2, 4, 6, 8]),
                    vol.Required("baud_rate", default=9600): vol.In(
                        [4800, 9600, 19200, 38400, 57600, 115200]
                    ),
                }
            ),
        )

    # --- Custom Device Wizard: Step 2 - Serial Framing ----------------------

    async def async_step_custom_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Custom device: serial framing (prefix, suffix, terminator)."""
        if user_input is not None:
            self._custom_data.update(user_input)
            return await self.async_step_custom_commands()

        return self.async_show_form(
            step_id="custom_serial",
            data_schema=vol.Schema(
                {
                    vol.Required("command_prefix", default=""): str,
                    vol.Required("command_suffix", default="\\r"): str,
                    vol.Required("response_prefix", default=""): str,
                    vol.Required("response_terminator", default="\\r"): str,
                    vol.Required("command_delay_ms", default=100): vol.All(
                        vol.Coerce(int), vol.Range(min=50, max=2000)
                    ),
                }
            ),
        )

    # --- Custom Device Wizard: Step 3 - Commands ----------------------------

    async def async_step_custom_commands(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Custom device: command templates."""
        if user_input is not None:
            self._custom_data["commands"] = user_input
            return await self.async_step_custom_response()

        return self.async_show_form(
            step_id="custom_commands",
            data_schema=vol.Schema(
                {
                    vol.Required("status", default="Z{zone:02d}STA"): str,
                    vol.Required("power_on", default="Z{zone:02d}PON"): str,
                    vol.Required("power_off", default="Z{zone:02d}POFF"): str,
                    vol.Required(
                        "volume_set", default="Z{zone:02d}VOL{volume:02d}"
                    ): str,
                    vol.Optional("volume_up", default="Z{zone:02d}VU"): str,
                    vol.Optional("volume_down", default="Z{zone:02d}VD"): str,
                    vol.Required("mute_on", default="Z{zone:02d}MUON"): str,
                    vol.Required("mute_off", default="Z{zone:02d}MUOFF"): str,
                    vol.Required(
                        "source_set", default="Z{zone:02d}SRC{source:02d}"
                    ): str,
                }
            ),
        )

    # --- Custom Device Wizard: Step 4 - Response Pattern --------------------

    async def async_step_custom_response(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Custom device: response parsing."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Compile the pattern here, while the user can still see and edit the
            # field. create_engine() compiles it at setup time and sits outside
            # the try/except in async_setup_entry, so a typo'd regex made the
            # entry raise re.error on every load -- and since reconfigure only
            # edits the port, the entry could never be repaired, only deleted.
            try:
                re.compile(user_input["status_pattern"])
            except re.error:
                errors["status_pattern"] = "invalid_regex"
            else:
                self._custom_data["response"] = user_input
                return await self._create_custom_entry()

        # On a validation retry, re-show what the user typed rather than the
        # canned defaults -- otherwise a single bad regex silently discards the
        # four other fields they had already filled in.
        prev = user_input or {}
        return self.async_show_form(
            step_id="custom_response",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "status_pattern",
                        default=prev.get(
                            "status_pattern",
                            r"Z(?P<zone>\d{2}) PWR(?P<power>\d)"
                            r" SRC(?P<source>\d{2})"
                            r" VOL(?P<volume>\d{2})"
                            r" MUT(?P<mute>\d)",
                        ),
                    ): str,
                    vol.Required(
                        "volume_min", default=prev.get("volume_min", 0)
                    ): vol.Coerce(int),
                    vol.Required(
                        "volume_max", default=prev.get("volume_max", 38)
                    ): vol.Coerce(int),
                    vol.Required(
                        "volume_inverted", default=prev.get("volume_inverted", False)
                    ): bool,
                    vol.Required(
                        "error_response", default=prev.get("error_response", "?")
                    ): str,
                }
            ),
        )

    # --- Create entry from custom wizard data -------------------------------

    async def _create_custom_entry(self) -> ConfigFlowResult:
        """Build a profile from the wizard data and create the config entry."""
        d = self._custom_data
        port = d["port"]
        device_name = d["device_name"]

        # Validate serial port (unless demo)
        if port != DEMO_PORT:
            error_msg = await self.hass.async_add_executor_job(_test_port, port)
            if error_msg:
                _LOGGER.warning("Serial port error: %s", error_msg)
                # Continue anyway - user chose the port in step 1

        await self.async_set_unique_id(f"ac_{port}")
        self._abort_if_unique_id_configured()

        num_zones = d["zones"]
        num_sources = d["sources"]
        baud = d["baud_rate"]

        # Build the inline profile (stored in config entry data)
        custom_profile = {
            "name": device_name,
            "manufacturer": "Custom",
            "models": [device_name],
            "zones": num_zones,
            "sources": num_sources,
            "serial": {
                "baud_rate": baud,
                "data_bits": 8,
                "parity": "none",
                "stop_bits": 1,
                "command_delay_ms": d.get("command_delay_ms", 100),
                "command_prefix": d.get("command_prefix", ""),
                "command_suffix": d.get("command_suffix", "\\r"),
                "response_prefix": d.get("response_prefix", ""),
                "response_terminator": d.get("response_terminator", "\\r"),
            },
            "commands": d.get("commands", {}),
            "response": {
                "status_pattern": d["response"]["status_pattern"],
                "error_response": d["response"]["error_response"],
                "mapping": {
                    "power": {
                        "field": "power",
                        "type": "bool",
                        "on_value": "1",
                        "off_value": "0",
                    },
                    "mute": {
                        "field": "mute",
                        "type": "bool",
                        "on_value": "1",
                        "off_value": "0",
                    },
                    "volume": {
                        "field": "volume",
                        "type": "int",
                        "min": d["response"]["volume_min"],
                        "max": d["response"]["volume_max"],
                        "inverted": d["response"]["volume_inverted"],
                    },
                    "source": {"field": "source", "type": "int"},
                },
            },
            "volume": {
                "min": d["response"]["volume_min"],
                "max": d["response"]["volume_max"],
                "inverted": d["response"]["volume_inverted"],
            },
            "features": {
                "has_tone_controls": False,
                "has_group_mode": False,
                "has_all_off": False,
                "has_balance": False,
                "unsolicited_updates": False,
            },
        }

        source_names = {i: f"Source {i}" for i in range(1, num_sources + 1)}
        zone_names = {i: f"Zone {i}" for i in range(1, num_zones + 1)}

        title = device_name + (" (Demo)" if port == DEMO_PORT else "")

        return self.async_create_entry(
            title=title,
            data={
                "port": port,
                CONF_DEVICE_PROFILE: "__custom__",
                CONF_BAUD_RATE: baud,
                CONF_NUM_ZONES: num_zones,
                CONF_NUM_SOURCES: num_sources,
                "custom_profile": custom_profile,
            },
            options={
                CONF_SOURCE_NAMES: source_names,
                CONF_ZONE_NAMES: zone_names,
            },
        )

    # --- Reconfigure Flow ---------------------------------------------------

    # --- Reauthentication ---------------------------------------------------

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002 - HA's required signature
    ) -> ConfigFlowResult:
        """Start reauth after ConfigEntryAuthFailed.

        `entry_data` is the entry's DATA, but our credentials live in options (see
        _apply_credential_override), so it carries nothing useful here and the
        confirm step reads options directly.

        Only the JSON engine authenticates (RTI AD-810 ships admin/admin), so this
        is reached when a device rejects the stored credentials or stays silent to
        the login. Before this existed, AuthenticationError became
        ConfigEntryNotReady and HA retried the same wrong password with backoff
        indefinitely, with nothing prompting the user to correct it.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect replacement credentials and retry setup."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            username = user_input.get(CONF_LOGIN_USERNAME, "").strip()
            password = user_input.get(CONF_LOGIN_PASSWORD, "").strip()
            if not username and not password:
                # Submitting the form unchanged would retry the credentials that
                # just failed, looping the user straight back here.
                errors["base"] = "credentials_required"
            else:
                # Credentials live in options (see _apply_credential_override), so
                # seed from the existing dict rather than replacing it --
                # async_update_entry overwrites options wholesale, and the zone and
                # source names live there too.
                options = dict(reauth_entry.options)
                if username:
                    options[CONF_LOGIN_USERNAME] = username
                if password:
                    options[CONF_LOGIN_PASSWORD] = password
                return self.async_update_reload_and_abort(reauth_entry, options=options)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LOGIN_USERNAME,
                        default=reauth_entry.options.get(CONF_LOGIN_USERNAME, ""),
                    ): str,
                    # Never pre-filled, so the stored secret is not echoed back.
                    vol.Optional(CONF_LOGIN_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"device": reauth_entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration (change serial port without re-adding)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_port = user_input[CONF_PORT]

            if new_port != DEMO_PORT:
                error_msg = await self.hass.async_add_executor_job(_test_port, new_port)
                if error_msg:
                    errors["base"] = "cannot_connect"

            if not errors:
                # The unique_id IS the port (f"ac_{port}") and is the only
                # duplicate guard. Updating data without it left a reconfigured
                # entry still claiming its OLD port, so the same physical port
                # could then be added a second time -- two managers opening one
                # serial link and fighting over it -- while a move onto another
                # entry's port went unchecked in the other direction.
                reconfigure_entry = self._get_reconfigure_entry()
                new_unique_id = f"ac_{new_port}"
                if new_unique_id != reconfigure_entry.unique_id:
                    await self.async_set_unique_id(new_unique_id)
                    self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={"port": new_port},
                    unique_id=new_unique_id,
                )

        # Discover available serial ports. These are offered as a hint rather
        # than as a closed vol.In() set: the port field also accepts
        # socket://host:port and rfc2217://host:port, which discovery cannot
        # enumerate. vol.In() rejected those outright -- including an existing
        # network entry's OWN current value, so the pre-filled form could not be
        # submitted even unchanged. This now matches async_step_user, which has
        # always used free text plus a suggested_ports placeholder.
        available_ports = await self.hass.async_add_executor_job(_list_serial_ports)
        suggested_ports = available_ports + [DEMO_PORT]
        current_port = self._get_reconfigure_entry().data.get("port", DEMO_PORT)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PORT, default=current_port): str,
                }
            ),
            errors=errors,
            description_placeholders={"suggested_ports": ", ".join(suggested_ports)},
        )

    # --- Options Flow -------------------------------------------------------

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> config_entries.OptionsFlow:
        """Create options flow.

        The entry is not passed in: HA sets `config_entry` on the flow itself,
        and assigning it explicitly is deprecated (hard error in 2025.12).
        """
        return AudioControlOptionsFlow()


class AudioControlOptionsFlow(config_entries.OptionsFlow):
    """Options flow for renaming zones and sources."""

    # No __init__: assigning self.config_entry is deprecated (HA reports it and
    # it becomes a hard error in 2025.12). The base class already provides it.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            num_sources = self.config_entry.data.get(CONF_NUM_SOURCES, 6)
            num_zones = self.config_entry.data.get(CONF_NUM_ZONES, 6)

            source_names = {
                i: user_input.get(f"source_{i}", f"Source {i}")
                for i in range(1, num_sources + 1)
            }
            zone_names = {
                i: user_input.get(f"zone_{i}", f"Zone {i}")
                for i in range(1, num_zones + 1)
            }

            # Seed from the existing options: async_create_entry REPLACES the
            # options dict rather than merging into it. Building a fresh dict
            # here silently dropped every key the form does not render -- most
            # damagingly the saved password, since its field is intentionally
            # blank-by-default so the UI never echoes a stored secret. Renaming
            # a zone therefore reverted the credential to the profile's vendor
            # default and the device rejected the next login.
            options: dict[str, Any] = dict(self.config_entry.options)
            options[CONF_SOURCE_NAMES] = source_names
            options[CONF_ZONE_NAMES] = zone_names
            # A blank credential field means "leave the stored value alone", not
            # "set an empty password", so only overwrite on a non-empty entry.
            for key in (CONF_LOGIN_USERNAME, CONF_LOGIN_PASSWORD):
                value = user_input.get(key, "").strip()
                if value:
                    options[key] = value
            return self.async_create_entry(title="", data=options)

        num_sources = self.config_entry.data.get(CONF_NUM_SOURCES, 6)
        num_zones = self.config_entry.data.get(CONF_NUM_ZONES, 6)
        current_sources = self.config_entry.options.get(CONF_SOURCE_NAMES, {})
        current_zones = self.config_entry.options.get(CONF_ZONE_NAMES, {})
        current_sources = {int(k): v for k, v in current_sources.items()}
        current_zones = {int(k): v for k, v in current_zones.items()}

        schema_dict = {}
        for i in range(1, num_zones + 1):
            schema_dict[
                vol.Optional(f"zone_{i}", default=current_zones.get(i, f"Zone {i}"))
            ] = str
        for i in range(1, num_sources + 1):
            schema_dict[
                vol.Optional(
                    f"source_{i}", default=current_sources.get(i, f"Source {i}")
                )
            ] = str

        # Credential override, shown only for profiles with a json.login block
        # (they ship vendor defaults such as RTI's admin/admin).
        if await self._async_profile_requires_login():
            schema_dict[
                vol.Optional(
                    CONF_LOGIN_USERNAME,
                    default=self.config_entry.options.get(CONF_LOGIN_USERNAME, ""),
                )
            ] = str
            schema_dict[vol.Optional(CONF_LOGIN_PASSWORD, default="")] = str

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))

    async def _async_profile_requires_login(self) -> bool:
        """Whether this entry's profile declares a json.login block.

        Profile loading reads YAML from disk, so it goes through the executor.
        """
        profile_name = self.config_entry.data.get(CONF_DEVICE_PROFILE, "")
        if profile_name == "__custom__":
            profile = self.config_entry.data.get("custom_profile") or {}
        else:
            profiles = await self.hass.async_add_executor_job(
                load_all_profiles, self.hass.config.config_dir
            )
            profile = profiles.get(profile_name) or {}
        json_cfg = profile.get("json")
        return isinstance(json_cfg, dict) and bool(json_cfg.get("login"))
