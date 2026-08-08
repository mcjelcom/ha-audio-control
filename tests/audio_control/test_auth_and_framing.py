"""Regression tests for SEC-012 (auth), SEC-013 (credentials), SEC-014 (resync).

All three were confirmed against the real library before fixing.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection, AuthenticationError

from custom_components.audio_control import _apply_credential_override
from custom_components.audio_control.const import (
    CONF_LOGIN_PASSWORD,
    CONF_LOGIN_USERNAME,
)
from custom_components.audio_control.diagnostics import TO_REDACT

JSON_AUTH_PROFILE: dict[str, Any] = {
    "name": "JsonAuth",
    "protocol_type": "json",
    "zones": 8,
    "sources": 8,
    "json": {
        "delimiter": "\n",
        "login": {"username": "admin", "password": "admin"},
        "status_field": "status",
        "success_codes": [200, 901],
    },
    "commands": {
        "status": {"type": "get_outputvol", "value": [{"index": "{zone}"}]},
    },
    "response": {},
    "volume": {"min": 0, "max": 100},
}

RNET_PROFILE: dict[str, Any] = {
    "name": "Rnet",
    "protocol_type": "binary",
    "zones": 6,
    "sources": 6,
    "commands": {"status": {"opcode": "0x05", "data": ["{zone}"]}},
    "binary": {"start_byte": 0xF0, "end_byte": 0xF7, "checksum": "rnet"},
}


def rnet_frame(*body: int) -> bytes:
    payload = bytes([0xF0, *body])
    checksum = (sum(payload) + len(payload)) & 0x7F
    return payload + bytes([checksum]) + b"\xf7"


class StubWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


# ─── SEC-012: login_failed was unreachable dead code ─────────────────────────


def test_failed_login_reports_login_failed() -> None:
    """A rejected login must be distinguishable from a generic device error.

    The status-code guard used to return early, so the login_failed flag was
    never set and auth failure looked like a transient error -- the integration
    retried the same wrong password forever.
    """
    engine = create_engine(JSON_AUTH_PROFILE)
    result = engine.parse_response('{"type":"login","status":401}')
    assert result is not None
    assert result.get("login_failed") is True
    assert result.get("error") is True
    assert engine.logged_in is False


def test_successful_login_sets_flag() -> None:
    engine = create_engine(JSON_AUTH_PROFILE)
    result = engine.parse_response('{"type":"login","status":200}')
    assert result is not None
    assert result.get("login_success") is True
    assert engine.logged_in is True


def test_non_login_error_still_flagged() -> None:
    """The generic status guard must still work for other message types."""
    engine = create_engine(JSON_AUTH_PROFILE)
    result = engine.parse_response('{"type":"get_outputvol","status":500}')
    assert result is not None
    assert result.get("error") is True
    assert "login_failed" not in result


# ─── SEC-012: the handshake is actually performed ────────────────────────────


async def test_login_is_sent_for_auth_profiles() -> None:
    """connect() must authenticate before other commands.

    format_login/requires_login/mark_logged_in existed but nothing called them,
    so commands went to an unauthenticated session.
    """
    engine = create_engine(JSON_AUTH_PROFILE)
    conn = AsyncSerialConnection(port="demo", engine=engine, demo_mode=False)
    writer = StubWriter()
    conn._writer = writer  # type: ignore[assignment]
    conn._connected = True

    # Queue the device's success reply so the handshake completes.
    conn._response_queue.put_nowait('{"type":"login","status":200}')
    await conn._async_login()

    assert writer.written, "no login frame sent"
    assert b'"type":"login"' in writer.written[0]
    assert engine.logged_in is True


async def test_rejected_login_raises() -> None:
    """A rejected login raises rather than silently continuing unauthenticated."""
    engine = create_engine(JSON_AUTH_PROFILE)
    conn = AsyncSerialConnection(port="demo", engine=engine, demo_mode=False)
    conn._writer = StubWriter()  # type: ignore[assignment]
    conn._connected = True

    conn._response_queue.put_nowait('{"type":"login","status":401}')
    with pytest.raises(AuthenticationError):
        await conn._async_login()


async def test_login_skipped_for_non_auth_engines() -> None:
    """Text/binary engines have no auth; the handshake must be a no-op."""
    engine = create_engine(RNET_PROFILE)
    conn = AsyncSerialConnection(port="demo", engine=engine, demo_mode=False)
    writer = StubWriter()
    conn._writer = writer  # type: ignore[assignment]
    conn._connected = True

    await asyncio.wait_for(conn._async_login(), timeout=1)
    assert writer.written == []


# ─── SEC-013: credentials are overridable and redacted ───────────────────────


def test_credential_override_replaces_profile_defaults() -> None:
    """A user who changed their device password can supply the real one."""
    entry = MagicMock()
    entry.options = {CONF_LOGIN_USERNAME: "real_user", CONF_LOGIN_PASSWORD: "s3cret"}

    merged = _apply_credential_override(JSON_AUTH_PROFILE, entry)
    assert merged["json"]["login"] == {"username": "real_user", "password": "s3cret"}


def test_credential_override_does_not_mutate_shared_profile() -> None:
    """The profile cache is shared between entries; it must not be mutated."""
    entry = MagicMock()
    entry.options = {CONF_LOGIN_PASSWORD: "s3cret"}

    _apply_credential_override(JSON_AUTH_PROFILE, entry)
    assert JSON_AUTH_PROFILE["json"]["login"]["password"] == "admin"


def test_partial_override_keeps_other_field() -> None:
    entry = MagicMock()
    entry.options = {CONF_LOGIN_PASSWORD: "s3cret"}
    merged = _apply_credential_override(JSON_AUTH_PROFILE, entry)
    assert merged["json"]["login"]["username"] == "admin"
    assert merged["json"]["login"]["password"] == "s3cret"


def test_no_override_returns_profile_unchanged() -> None:
    entry = MagicMock()
    entry.options = {}
    assert _apply_credential_override(JSON_AUTH_PROFILE, entry) is JSON_AUTH_PROFILE


def test_override_ignored_for_profiles_without_login() -> None:
    entry = MagicMock()
    entry.options = {CONF_LOGIN_PASSWORD: "s3cret"}
    assert _apply_credential_override(RNET_PROFILE, entry) is RNET_PROFILE


def test_credentials_are_redacted_in_diagnostics() -> None:
    """Diagnostics downloads get pasted into public issue trackers."""
    for key in ("username", "password", CONF_LOGIN_USERNAME, CONF_LOGIN_PASSWORD):
        assert key in TO_REDACT, f"{key} must be redacted"
    # A custom profile can embed a json.login block.
    assert "custom_profile" in TO_REDACT


# ─── SEC-014: resync must not swallow a nested frame ─────────────────────────


def test_stray_start_byte_does_not_consume_following_frame() -> None:
    """A corrupt frame must not eat the valid frame that follows it.

    On checksum failure pos had already advanced past the end byte, so a stray
    start byte immediately before a good frame consumed it.
    """
    engine = create_engine(RNET_PROFILE)
    good = rnet_frame(0x02, 0x07, 0x00)
    frames, _rem = engine.extract_frames(bytes([0xF0]) + good)
    assert len(frames) == 1
    assert frames[0] == good


def test_corrupt_frame_still_dropped() -> None:
    """The resync change must not weaken checksum validation."""
    engine = create_engine(RNET_PROFILE)
    good = bytearray(rnet_frame(0x02, 0x07, 0x00))
    good[2] ^= 0xFF  # corrupt a body byte, leave the checksum stale
    frames, _rem = engine.extract_frames(bytes(good))
    assert frames == []
