"""Async serial connection for RS232 devices.

No Home Assistant dependency. Uses pyserial-asyncio-fast directly.
Can be used standalone in scripts, CLI tools, or other frameworks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any, ClassVar

try:
    import serial_asyncio_fast as serial_asyncio
except ImportError:
    try:
        import serial_asyncio  # type: ignore[import-not-found, no-redef]
    except ImportError:
        serial_asyncio = None  # type: ignore[assignment]

from .base import BaseProtocolEngine
from .models import ZoneState

_LOGGER = logging.getLogger(__name__)

# Reconnection constants
RECONNECT_DELAY_FAST = 5.0
RECONNECT_DELAY_SLOW = 60.0
MAX_FAST_RECONNECT_ATTEMPTS = 10
STATE_REFRESH_INTERVAL = 60.0

# Bounded queue prevents memory growth from unsolicited device updates
_RESPONSE_QUEUE_MAX = 64

# Cap the read buffer so a device that streams a start byte without an end byte
# cannot grow it without limit (a DoS vector over socket:// transport).
_MAX_READ_BUFFER = 4096

# Commands whose effect is RELATIVE to the current state, so re-sending them is
# not a no-op. These are never retried: a slow ACK would double-step the value.
_NON_IDEMPOTENT_COMMANDS = frozenset(
    {
        "volume_up",
        "volume_down",
        "power_toggle",
        "mute_toggle",
        "source_next",
        "source_prev",
    }
)

# Type for zone state change callbacks
ZoneCallback = Callable[[int, ZoneState], None]


class AuthenticationError(Exception):
    """The device rejected the supplied credentials.

    Distinct from a transport error so the caller can prompt for new credentials
    rather than retrying the same wrong password indefinitely.
    """


class AsyncSerialConnection:
    """Async serial connection manager driven by a ProtocolEngine.

    Handles: connection, reconnection, command queuing, response parsing,
    zone state management, and listener notification.

    This is framework-agnostic — it uses raw asyncio and can be driven
    by Home Assistant, a CLI, or any other async runtime.
    """

    def __init__(
        self,
        port: str,
        engine: BaseProtocolEngine,
        *,
        demo_mode: bool = False,
    ) -> None:
        """Initialize the connection manager.

        Args:
            port: Serial port path (e.g., /dev/ttyUSB0)
            engine: Protocol engine configured with a device profile
            demo_mode: If True, don't actually open the serial port
        """
        self._port = port
        self._engine = engine
        self._demo_mode = demo_mode

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._command_lock = asyncio.Lock()
        self._response_queue: asyncio.Queue[str | bytes] = asyncio.Queue(
            maxsize=_RESPONSE_QUEUE_MAX
        )
        self._listeners: list[ZoneCallback] = []
        self._read_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._connected: bool = False
        self._shutting_down: bool = False
        # True while connect() is running. connect() issues its own status probes
        # through send_command, and a failing probe must not spawn a competing
        # reconnect task while the connect attempt is still in progress.
        self._connecting: bool = False
        # Set by connect() when a status probe actually got a parsed reply.
        # Distinct from _connected, which only means the port opened.
        self._device_responded: bool = False

        # Zone states. Volume starts at the profile's own QUIET end rather than a
        # bare 0: 0 is a raw device value whose meaning depends on the scale, so
        # it reads as maximum volume on an inverted scale (AMC: 0..62 inverted)
        # and as 0 dB on a negative-floor scale (NAD: -80..0). Real hardware
        # overwrites this at the first status poll, which is why it went
        # unnoticed -- but demo mode never polls, so a demo of an AMC or NAD
        # opened showing full volume.
        self._zones: dict[int, ZoneState] = {
            i: ZoneState(volume=engine.ha_volume_to_device(0.0))
            for i in range(1, engine.num_zones + 1)
        }

    @property
    def demo_mode(self) -> bool:
        """Return whether running in demo mode."""
        return self._demo_mode

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connected

    @property
    def zones(self) -> dict[int, ZoneState]:
        """Return zone state dict."""
        return self._zones

    @property
    def engine(self) -> BaseProtocolEngine:
        """Return the protocol engine."""
        return self._engine

    # ─── Listener Management ─────────────────────────────────────────────────

    def add_listener(self, callback: ZoneCallback) -> Callable[[], None]:
        """Register a zone state change listener.

        Args:
            callback: Called with (zone_number, zone_state) on state change.

        Returns:
            A removal function — call it to unregister.
        """
        self._listeners.append(callback)

        def remove() -> None:
            # Idempotent: calling the remover twice previously raised ValueError.
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove

    def notify_zone(self, zone: int) -> None:
        """Notify listeners of a zone state change.

        Call after directly modifying zone state for optimistic updates.
        """
        state = self._zones.get(zone)
        if state is None:
            return
        # Iterate a snapshot: a callback that unregisters itself during
        # notification (entity teardown racing a state push) would otherwise
        # mutate the list mid-loop and silently skip the next listener -- masked
        # by the per-callback except below.
        for cb in list(self._listeners):
            try:
                cb(zone, state)
            except Exception:
                _LOGGER.exception("Error in listener callback for zone %d", zone)

    # Keep private alias for internal use
    _notify_zone = notify_zone

    def _notify_all(self) -> None:
        """Notify all listeners for all zones."""
        for zone in self._zones:
            self._notify_zone(zone)

    # ─── Zone State Mutation ─────────────────────────────────────────────────

    def set_zone_power(self, zone: int, power: bool) -> None:
        """Optimistic power state update."""
        if zone in self._zones:
            state = self._zones[zone]
            state.power = power
            if not power:
                state.mute = True
                state.volume = (
                    self._engine.volume_max if self._engine.volume_inverted else 0
                )
            self._notify_zone(zone)

    def rollback_zone_power(
        self, zone: int, prev_power: bool, prev_mute: bool, prev_vol: int
    ) -> None:
        """Rollback a failed power state change."""
        if zone in self._zones:
            state = self._zones[zone]
            state.power = prev_power
            state.mute = prev_mute
            state.volume = prev_vol
            self._notify_zone(zone)

    # ─── Connection ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open serial connection (or enter demo mode)."""
        if self._demo_mode:
            self._connected = True
            # Demo mode has no device to answer, but it is by definition healthy.
            self._device_responded = True
            _LOGGER.info("RS232 connection running in DEMO mode")
            self._notify_all()
            return

        # A reconnect-driven cleanup may have set this; clear it so a retry is
        # not permanently suppressed.
        self._shutting_down = False
        self._connecting = True

        try:
            if serial_asyncio is None:
                raise ImportError(
                    "pyserial-asyncio-fast (or pyserial-asyncio) is required "
                    "for real serial connections. Install with: "
                    "pip install pyserial-asyncio-fast"
                )
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self._port,
                baudrate=self._engine.baud_rate,
                bytesize=self._engine.data_bits,
                parity=self._engine.parity,
                stopbits=self._engine.stop_bits,
            )
            self._connected = True
            self._read_task = asyncio.create_task(self._read_loop())
            self._refresh_task = asyncio.create_task(self._periodic_refresh())
            _LOGGER.info(
                "Connected to RS232 device on %s at %d baud",
                self._port,
                self._engine.baud_rate,
            )
            self._notify_all()

            # Send init/wakeup sequence if configured
            for init_bytes in self._engine.init_sequence:
                self._writer.write(init_bytes)
                await self._writer.drain()
                await asyncio.sleep(0.01)  # 10ms settle between init bytes

            # Authenticate before any other command. The login machinery existed
            # but was never called, so devices requiring auth (the RTI JSON
            # profile) had every command sent to an unauthenticated session.
            await self._async_login()

            # Poll initial state (with zone prefix auto-detection)
            from .protocol_engine import ProtocolEngine

            first_success = await self.send_command("status", zone=1)
            if (
                not first_success
                and isinstance(self._engine, ProtocolEngine)
                and self._engine.has_zone_prefix_fallback
            ):
                self._engine.switch_to_fallback_prefix()
                first_success = await self.send_command("status", zone=1)
            if first_success and isinstance(self._engine, ProtocolEngine):
                self._engine.lock_zone_prefix()
            # Record whether the device actually answered. _connected only
            # reflects "the port opened", and a status probe that times out is
            # swallowed by _wait_for_response, so _connected stays True on a
            # half-open link. The reconnect loop needs this stronger signal.
            self._device_responded = bool(first_success)
            # Poll remaining zones
            for zone in range(2, self._engine.num_zones + 1):
                await self.send_command("status", zone=zone)
        except Exception as err:
            _LOGGER.error("Failed to connect: %s", err)
            self._connected = False
            # Release the reader/writer and the read/refresh tasks created above.
            # Without this they outlive the failed connect: async_setup_entry
            # awaits connect() before assigning runtime_data, so on a raise HA
            # has no manager object and never calls disconnect() -- leaking two
            # tasks and an open fd per setup retry.
            # Cleanup that preserves the ability to reconnect: disconnect()
            # would set _shutting_down and permanently disable retries.
            await self._release_transport(cancel_reconnect=False)
            raise
        finally:
            self._connecting = False

    async def _async_login(self) -> None:
        """Authenticate if the engine's profile declares credentials.

        No-op for the text and binary engines, which have no auth concept.
        Raises AuthenticationError so the caller can surface a re-auth prompt
        instead of retrying a wrong password forever.
        """
        from .json_engine import JsonProtocolEngine

        engine = self._engine
        # Only the JSON engine implements authentication; isinstance (rather than
        # getattr probing) lets mypy verify the login API actually exists.
        if not isinstance(engine, JsonProtocolEngine):
            return
        if not engine.requires_login or engine.logged_in:
            return
        if not self._writer:
            return

        _LOGGER.debug("Authenticating to %s", self._port)
        self._writer.write(engine.format_login())
        await self._writer.drain()

        # Wait for the login reply specifically; a generic response does not
        # prove the credentials were accepted.
        deadline = asyncio.get_running_loop().time() + engine.response_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                # A silent device must NOT be treated as authenticated. Returning
                # here left engine.logged_in False while connect() carried on to
                # the status probes, so every subsequent command went to an
                # unauthenticated session and failed opaquely. Silence is the
                # common case for a wrong port, or a non-RTI device on an RTI
                # profile -- exactly when a clear error matters most.
                msg = f"No login response from {self._port}"
                raise AuthenticationError(msg)
            try:
                raw = await asyncio.wait_for(
                    self._response_queue.get(), timeout=remaining
                )
            except TimeoutError as err:
                msg = f"No login response from {self._port}"
                raise AuthenticationError(msg) from err
            parsed = engine.parse_response(raw)
            if not parsed:
                continue
            if parsed.get("login_success"):
                _LOGGER.info("Authenticated to %s", self._port)
                return
            if parsed.get("login_failed"):
                msg = f"Authentication rejected by {self._port}"
                raise AuthenticationError(msg)

    async def disconnect(self) -> None:
        """Close the connection permanently and cancel background tasks.

        Sets _shutting_down, so no further reconnect will be scheduled. Use
        _release_transport() for cleanup that should still allow reconnecting.
        """
        self._shutting_down = True
        await self._release_transport(cancel_reconnect=True)

    async def _release_transport(self, *, cancel_reconnect: bool) -> None:
        """Cancel tasks and close the reader/writer without ending the session.

        Kept separate from disconnect() so a failed connect() can clean up its
        partially-created tasks and still be retried -- setting _shutting_down
        there would have permanently disabled reconnection.
        """
        tasks = [self._refresh_task, self._read_task]
        if cancel_reconnect:
            tasks.insert(0, self._reconnect_task)
        for task in tasks:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if cancel_reconnect:
            self._reconnect_task = None
        self._refresh_task = None
        self._read_task = None
        if self._writer:
            # close() must be inside the guard too. On a physically unplugged
            # USB-serial adapter pyserial raises OSError from close(), which
            # escaped disconnect() -> escaped async_unload_entry -> left the
            # entry half-unloaded with _writer set and _connected True, so a
            # reload stacked a second connection on the first.
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug("Error closing serial: %s", err)
            self._writer = None
        self._reader = None
        self._connected = False

    # ─── Command Sending ─────────────────────────────────────────────────────

    async def send_command(self, command_name: str, **kwargs: Any) -> bool:
        """Format and send a command. Returns True on success.

        Supports configurable retry (from engine.retry_count) and
        per-device response timeout (from engine.response_timeout).
        """
        if self._demo_mode:
            _LOGGER.debug("DEMO TX: %s(%s)", command_name, kwargs)
            return True

        framed = self._engine.format_command(command_name, **kwargs)
        if framed is None:
            _LOGGER.warning("Command '%s' not available for this device", command_name)
            return False

        # Never retry a RELATIVE command. Retries are driven by "no correlated
        # reply in time", but a device that acted on the command and merely
        # replied slowly would get it twice -- so volume_up would double-step.
        # Worse, send_command still returns False after such a double-send, so
        # the caller rolls the UI back to the old value while the device sits two
        # steps higher, and they disagree until the next poll. Absolute commands
        # (volume_set, power_on, mute_on) are idempotent and safe to repeat.
        max_attempts = 1
        if command_name not in _NON_IDEMPOTENT_COMMANDS:
            max_attempts += self._engine.retry_count
        for attempt in range(max_attempts):
            result = await self._send_once(command_name, framed, kwargs)
            if result:
                return True
            if attempt < max_attempts - 1:
                _LOGGER.debug(
                    "Retry %d/%d for '%s'",
                    attempt + 1,
                    self._engine.retry_count,
                    command_name,
                )
        return False

    async def _send_once(
        self, command_name: str, framed: str | bytes, kwargs: dict[str, Any]
    ) -> bool:
        """Send a single command attempt. Returns True on success."""
        async with self._command_lock:
            if not self._writer or not self._connected:
                _LOGGER.warning("Cannot send '%s', not connected", command_name)
                # Ensure a disconnected state always has recovery pending. This
                # branch previously short-circuited without scheduling, so a
                # connection that went down outside the read loop stayed down.
                self._schedule_reconnect()
                return False
            try:
                # Drain stale responses
                while not self._response_queue.empty():
                    try:
                        self._response_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                data = self._engine.frame_to_bytes(framed)
                _LOGGER.debug("TX: %s", data)
                self._writer.write(data)
                await self._writer.drain()

                # Wait for correlated response with configurable timeout
                expected_zone = kwargs.get("zone")
                result = await self._wait_for_response(command_name, expected_zone)

                await asyncio.sleep(self._engine.command_delay)
                return result
            except (TimeoutError, OSError) as err:
                _LOGGER.error("Send error for '%s': %s", command_name, err)
                self._connected = False
                # Tell the entities. `available` is derived from _connected, but
                # HA only re-reads it when a state write is requested, so without
                # this every entity kept reporting available=True and its stale
                # volume until the next successful poll.
                self._notify_all()
                self._schedule_reconnect()
                return False
            except Exception:
                # A malformed device response must not surface as a raw traceback
                # in an HA service call. Report the command as failed (which
                # triggers optimistic-state rollback) and keep the link up --
                # this is a data problem, not a transport one.
                _LOGGER.exception("Unexpected error sending '%s'", command_name)
                return False

    # Reply `field` values, lowercased, grouped by the command family they answer.
    # Only used to REJECT a reply that positively identifies a different setting;
    # a reply with no field is never rejected, because most protocols answer every
    # command with the same status frame and have nothing to correlate on.
    _COMMAND_FAMILIES: ClassVar[dict[str, frozenset[str]]] = {
        "power": frozenset({"power", "standby", "pwr"}),
        "volume": frozenset({"volume", "vol", "mastervolume"}),
        "mute": frozenset({"mute", "mut"}),
        "source": frozenset({"source", "src", "input"}),
        "bass": frozenset({"bass", "bas"}),
        "treble": frozenset({"treble", "treb", "trb"}),
        "balance": frozenset({"balance", "bal"}),
    }

    @classmethod
    def _command_family(cls, command_name: str) -> str | None:
        """Which setting family a command belongs to, or None if unclassified."""
        for family in cls._COMMAND_FAMILIES:
            if command_name.startswith(family):
                return family
        return None

    @classmethod
    def _response_contradicts(cls, command_name: str, parsed: dict[str, Any]) -> bool:
        """Whether a parsed reply positively describes a DIFFERENT setting.

        Deliberately conservative. Rejection needs ALL of:
          - the command maps to a known family, AND
          - the reply carries an explicit `field` naming its setting, AND
          - that field maps to a family too, AND
          - the two families differ.

        Anything short of that is accepted. Most protocols answer every command
        with the same status frame (the AMC XIA always replies `#ON,SRCbb,MUTE x`)
        and genuinely cannot be correlated further, so requiring a positive
        contradiction is what keeps those working.

        A heuristic over which mapped keys are present was tried and rejected: the
        NAD maps power, volume AND source from the same `value` group, so all three
        appear on every frame and the typed result cannot distinguish
        `Main.Power=On` from `Main.Volume=-30`. Only the raw `field` group can --
        which is why _apply_mapping now preserves it.
        """
        command_family = cls._command_family(command_name)
        if command_family is None:
            return False

        field = parsed.get("field")
        if not isinstance(field, str):
            return False

        normalised = field.strip().lower().replace("_", "")
        reply_family = next(
            (f for f, names in cls._COMMAND_FAMILIES.items() if normalised in names),
            None,
        )
        if reply_family is None:
            return False
        return reply_family != command_family

    async def _wait_for_response(
        self, command_name: str, expected_zone: int | None
    ) -> bool:
        """Wait for a correlated response.

        For multi-zone devices, keeps consuming responses until one matches
        the expected zone or a global response arrives. Bounded by timeout.
        Uses engine.response_timeout for per-device timing.
        """
        max_mismatches = 10  # Safety bound against a chatty device
        mismatches = 0
        # Deadline for the WHOLE wait. Previously the timeout was per-message and
        # reset on every arrival, so a chatty device could hold _command_lock for
        # max_mismatches * response_timeout (15s by default) and, with retries,
        # block the command path for minutes.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._engine.response_timeout
        try:
            while mismatches < max_mismatches:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                response = await asyncio.wait_for(
                    self._response_queue.get(), timeout=remaining
                )

                if response == "__ERROR__":
                    _LOGGER.warning("Device error for '%s'", command_name)
                    return False

                parsed = self._engine.parse_response(response)

                # Only a PARSED response confirms a command. Accepting an
                # unrecognized line (a boot banner, an echo, line noise) as an
                # ACK let the zone-prefix auto-detection lock in the wrong prefix
                # permanently, and made unrelated traffic satisfy pending
                # commands.
                if not parsed:
                    _LOGGER.debug(
                        "Ignoring unparseable response while awaiting '%s': %r",
                        command_name,
                        response,
                    )
                    mismatches += 1
                    continue

                # A global frame confirms only a GLOBAL command. Accepting it for
                # anything pending meant a device-initiated broadcast -- an AMC
                # emits ZALLOFF when All Off is pressed on the front panel --
                # confirmed whatever command was in flight, committing optimistic
                # state (rollback skipped) for a command the device may have
                # rejected.
                if "global" in parsed:
                    if expected_zone is None:
                        return True
                    mismatches += 1
                    continue

                # No zone expected (global commands) — any parsed response is ok.
                if expected_zone is None:
                    return True

                # Single-zone devices were exempted entirely, under a comment
                # claiming they "cannot mis-correlate". They can: the NAD C 368
                # reports one field per frame, so an unsolicited Main.Volume=-30
                # push confirmed a pending power_on. Correlate by command family
                # where the reply says which setting it describes, and fall back to
                # "it parsed" for protocols whose replies are opaque (the AMC XIA
                # answers everything with the same status frame).
                if self._engine.num_zones == 1:
                    if self._response_contradicts(command_name, parsed):
                        mismatches += 1
                        continue
                    return True

                if parsed.get("zone") == expected_zone:
                    return True

                # Parsed, but for a different zone — keep waiting.
                mismatches += 1

            _LOGGER.warning(
                "Too many unmatched responses for '%s' zone %s",
                command_name,
                expected_zone,
            )
            return False
        except TimeoutError:
            _LOGGER.warning("No response for '%s' (timeout)", command_name)
            return False

    # ─── Reconnection ────────────────────────────────────────────────────────

    def _schedule_reconnect(self) -> None:
        """Schedule reconnection, unless shutting down or already connecting."""
        if self._shutting_down or self._connecting:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnect with fast then slow retries."""
        attempt = 0
        while not self._shutting_down:
            attempt += 1
            delay = (
                RECONNECT_DELAY_FAST
                if attempt <= MAX_FAST_RECONNECT_ATTEMPTS
                else RECONNECT_DELAY_SLOW
            )
            _LOGGER.warning("Reconnect attempt %d to %s", attempt, self._port)
            await asyncio.sleep(delay)
            try:
                # Clean up old tasks before reconnecting
                if self._read_task:
                    self._read_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._read_task
                    self._read_task = None
                if self._refresh_task:
                    self._refresh_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._refresh_task
                    self._refresh_task = None
                if self._writer:
                    self._writer.close()
                    self._writer = None
                self._reader = None
                # Re-run zone-prefix detection: a prefix locked in from a bad
                # first probe would otherwise persist for the process lifetime.
                from .protocol_engine import ProtocolEngine

                if isinstance(self._engine, ProtocolEngine):
                    self._engine.reset_zone_prefix_detection()
                self._device_responded = False
                await self.connect()
                # connect() can return without raising on a link that is open but
                # dead. _connected alone is NOT sufficient evidence: a status
                # probe that times out is caught inside _wait_for_response, so it
                # never reaches the handler that would clear _connected. Require
                # proof the device actually replied -- otherwise a half-open
                # socket (Wi-Fi drop, NAT timeout) was mistaken for success and
                # the loop exited, stranding the integration offline with no
                # pending retry.
                if self._connected and self._device_responded:
                    return
                _LOGGER.warning(
                    "Reconnect %d opened %s but the device did not respond",
                    attempt,
                    self._port,
                )
            except Exception as err:
                _LOGGER.warning("Reconnect %d failed: %s", attempt, err)

    # ─── Periodic Refresh ────────────────────────────────────────────────────

    async def _periodic_refresh(self) -> None:
        """Poll all zones periodically.

        Uses engine.heartbeat_interval if configured (for faster dead-connection
        detection), otherwise falls back to STATE_REFRESH_INTERVAL (60s).
        """
        interval = self._engine.heartbeat_interval or STATE_REFRESH_INTERVAL
        while not self._shutting_down:
            await asyncio.sleep(interval)
            if self._connected and not self._shutting_down:
                for zone in range(1, self._engine.num_zones + 1):
                    if not self._connected:
                        break
                    await self.send_command("status", zone=zone)

    # ─── Read Loop ───────────────────────────────────────────────────────────

    async def _read_loop(self) -> None:
        """Read from serial port and process responses."""
        buffer = b""
        consecutive_errors = 0

        while True:
            try:
                if not self._reader:
                    break
                data = await self._reader.read(256)
                if not data:
                    _LOGGER.warning("Serial EOF")
                    self._connected = False
                    self._notify_all()
                    self._schedule_reconnect()
                    break
                # NUL stripping is text-only. Binary protocols use 0x00 as a
                # legal payload byte, so stripping it there corrupts frames.
                if self._engine.strip_nul:
                    data = data.replace(b"\x00", b"")
                buffer += data

                # Bound the buffer so a device (over socket://, any LAN host)
                # streaming bytes with a start-but-no-end sequence cannot grow it
                # without limit and starve/OOM the event loop.
                if len(buffer) > _MAX_READ_BUFFER:
                    _LOGGER.warning(
                        "Discarding %d unparseable bytes (no complete frame)",
                        len(buffer) - _MAX_READ_BUFFER // 2,
                    )
                    buffer = buffer[-(_MAX_READ_BUFFER // 2) :]

                # Pass each frame to the engine UNMODIFIED. The text engine
                # decodes to str in parse_response; binary engines need the raw
                # bytes. Decoding here with errors="ignore" silently dropped
                # every byte >= 0x80, breaking binary volume/framing values.
                frames, buffer = self._engine.extract_frames(buffer)
                for frame in frames:
                    self._process_response(frame)

                # Reset only after a full successful iteration. Resetting right
                # after read() made the consecutive-error break below
                # unreachable: a device that reads fine but whose frames crash
                # the engine hit read-success -> reset -> raise -> increment, so
                # the counter never passed 1 and the loop spun at 1 traceback
                # per second forever with no reconnect ever scheduled.
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except OSError as err:
                _LOGGER.error("Read error: %s", err)
                self._connected = False
                self._notify_all()
                self._schedule_reconnect()
                break
            except Exception:
                consecutive_errors += 1
                _LOGGER.exception("Read loop error (count: %d)", consecutive_errors)
                if consecutive_errors > 5:
                    self._connected = False
                    # Matches the OSError branch above: give up on the link AND
                    # tell the entities, or they stay "available" indefinitely.
                    self._notify_all()
                    self._schedule_reconnect()
                    break
                await asyncio.sleep(1)

    def _process_response(self, line: str | bytes) -> None:
        """Parse and apply a response frame to zone state.

        Accepts bytes for binary protocols; only the text engine works with str.
        Frames are passed to the engine unmodified so binary payloads are not
        corrupted by a text-oriented decode.
        """
        _LOGGER.debug("RX: %r", line)

        parsed = self._engine.parse_response(line)
        if parsed is None:
            _LOGGER.debug("Unrecognized response: '%s'", line)
            self._enqueue_response(line)
            return

        # Error
        if parsed.get("error"):
            self._enqueue_response("__ERROR__")
            return

        # Global response (all_off, group_on, etc.)
        if "global" in parsed:
            global_type = parsed["global"]
            if global_type == "all_off":
                for zn, zs in self._zones.items():
                    zs.power = False
                    zs.mute = True
                    self._notify_zone(zn)
            elif global_type in ("mute_all_on",):
                for zn, zs in self._zones.items():
                    zs.mute = True
                    self._notify_zone(zn)
            elif global_type in ("mute_all_off",):
                for zn, zs in self._zones.items():
                    zs.mute = False
                    self._notify_zone(zn)
            elif global_type in ("group_off",):
                for zn, zs in self._zones.items():
                    zs.group = False
                    self._notify_zone(zn)
            elif global_type in ("group_on",):
                for zn, zs in self._zones.items():
                    zs.group = True
                    self._notify_zone(zn)
            self._enqueue_response(line)
            return

        # Zone-specific response
        zone_num: int | None = parsed.get("zone")
        if zone_num is None and self._engine.num_zones == 1:
            # A one-zone device has no zone to report, so 13 single-zone profiles
            # emit replies with no zone group and had every parsed value silently
            # discarded here -- their entities showed the ZoneState defaults
            # forever, and the 60s poll discarded its re-read too, so there was no
            # path back to consistency. The `static:` block added for the XCDie
            # fed this same path, which made it a no-op.
            #
            # Deliberately NOT unconditional: on a multi-zone device an
            # unattributable reply must be dropped rather than written into zone
            # 1, which would corrupt a zone the message was never about. Mirrors
            # the num_zones == 1 shortcut in _wait_for_response.
            zone_num = 1
        if zone_num is not None and zone_num in self._zones:
            state = self._zones[zone_num]
            if "power" in parsed:
                state.power = parsed["power"]
            if "mute" in parsed:
                state.mute = parsed["mute"]
            if "volume" in parsed:
                state.volume = parsed["volume"]
            if "source" in parsed:
                state.source = parsed["source"]
            if "bass" in parsed:
                state.bass = parsed["bass"]
            if "treble" in parsed:
                state.treble = parsed["treble"]
            if "balance" in parsed:
                state.balance = parsed["balance"]
            if "group" in parsed:
                state.group = parsed["group"]
            self._notify_zone(zone_num)

        self._enqueue_response(line)

    def _enqueue_response(self, line: str | bytes) -> None:
        """Put a response on the queue, dropping oldest if full."""
        if self._response_queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._response_queue.get_nowait()  # Drop oldest
        self._response_queue.put_nowait(line)
