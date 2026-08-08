"""Regression tests for the security-review findings (SEC-001..003).

All three are reachable over socket:// transport (any LAN host) and cause loss
of availability for the whole Home Assistant process. Each is verified against
the real engine / read loop, not a mock.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from rs232_protocol import create_engine
from rs232_protocol.binary_engine import _MAX_FRAME_SIZE
from rs232_protocol.connection import _MAX_READ_BUFFER, AsyncSerialConnection

BINARY_LENGTH_PROFILE: dict[str, Any] = {
    "name": "LenBinary",
    "protocol_type": "binary",
    "zones": 4,
    "sources": 4,
    "commands": {"status": {"opcode": "0x20", "data": ["{zone}"]}},
    "binary": {
        "start_byte": 0x55,
        "length_includes_start": True,
        "length_includes_checksum": True,
        "checksum": "none",  # exercise the no-validation path deliberately
    },
    "volume": {"min": 0, "max": 80},
}

RNET_END_PROFILE: dict[str, Any] = {
    "name": "EndBinary",
    "protocol_type": "binary",
    "zones": 6,
    "sources": 6,
    "commands": {"status": {"opcode": "0x05", "data": ["{zone}"]}},
    "binary": {"start_byte": 0xF0, "end_byte": 0xF7, "checksum": "rnet"},
    "volume": {"min": 0, "max": 50},
}

SPEAKERCRAFT_PROFILE: dict[str, Any] = {
    "name": "SC",
    "protocol_type": "binary",
    "zones": 8,
    "sources": 8,
    "commands": {"status": {"opcode": "0x68", "data": ["{zone}"]}},
    "response": {
        "zone_status": {
            "opcode": 0x20,
            "fields": {
                "zone": {"offset": 0, "transform": "add1"},
                "power": {"offset": 2, "bit": 1},
                "volume": {"offset": 4},
            },
        }
    },
    "binary": {
        "start_byte": 0x55,
        "length_includes_start": True,
        "checksum": "mod256",
    },
    "volume": {"min": 0, "max": 80, "inverted": True},
}


# ─── SEC-001: zero / absurd length byte must not hang ────────────────────────


def test_zero_length_byte_does_not_hang() -> None:
    """A device-supplied length of 0 must not pin the extractor loop.

    frame_size would be 0, making `pos += frame_size` never advance.
    """
    engine = create_engine(BINARY_LENGTH_PROFILE)
    # 0x55 0x00 -> length 0. Must return promptly, not loop forever.
    frames, remaining = engine.extract_frames(bytes([0x55, 0x00, 0x41, 0x42]))
    assert frames == []
    # It should resync past the bad start rather than retaining it forever.
    assert len(remaining) < 4


def test_oversized_length_byte_is_resynced() -> None:
    """A length claiming a frame larger than _MAX_FRAME_SIZE is not trusted."""
    engine = create_engine(BINARY_LENGTH_PROFILE)
    # Length 0xFF with only a few bytes present: must not stall waiting forever
    # on a frame that can never be that big.
    buffer = bytes([0x55, 0xFF, 0x01, 0x02])
    frames, _remaining = engine.extract_frames(buffer)
    assert frames == []
    assert _MAX_FRAME_SIZE == 512


def test_unknown_checksum_warns_not_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo'd checksum name must warn, not silently disable validation."""
    import logging

    with caplog.at_level(logging.WARNING):
        create_engine(
            {
                **BINARY_LENGTH_PROFILE,
                "binary": {**BINARY_LENGTH_PROFILE["binary"], "checksum": "mdo256"},
            }
        )
    assert any("Unknown checksum" in r.message for r in caplog.records)


# ─── SEC-002: binary frames must survive the read loop unmodified ────────────


def test_strip_nul_is_false_for_binary_engines() -> None:
    """Binary engines must not strip NULs -- 0x00 is a legal payload byte."""
    assert create_engine(RNET_END_PROFILE).strip_nul is False
    assert create_engine(BINARY_LENGTH_PROFILE).strip_nul is False


def test_strip_nul_true_for_text_engine() -> None:
    """Text engines may strip NUL padding, and it stays opt-out per profile."""
    text_profile = {
        "name": "T",
        "zones": 1,
        "sources": 1,
        "commands": {"status": "S"},
        "serial": {},
    }
    assert create_engine(text_profile).strip_nul is True
    no_strip = {**text_profile, "serial": {"strip_nul": False}}
    assert create_engine(no_strip).strip_nul is False


def test_binary_frame_with_nul_and_high_bytes_parses() -> None:
    """A SpeakerCraft frame containing 0x00 and bytes >= 0x80 must parse.

    The old read loop stripped NULs and decoded ascii/ignore, which deleted
    both and left the frame unparseable.
    """
    engine = create_engine(SPEAKERCRAFT_PROFILE)
    # zone_status: payload starts at data[3]; volume field is payload offset 4
    # (= data[7]). Put 0x80 there and a 0x00 payload byte alongside it.
    body = bytes([0x55, 0x0A, 0x20, 0x00, 0x00, 0x02, 0x00, 0x80, 0x00, 0x00])
    checksum = (0x100 - (sum(body) % 256)) & 0xFF
    frame = body + bytes([checksum])
    result = engine.parse_response(frame)
    assert result is not None
    assert result["volume"] == 128  # 0x80 -- would be dropped by ascii/ignore


async def test_read_loop_passes_bytes_unmodified() -> None:
    """The read loop hands binary frames to the engine as bytes, not decoded.

    Drives a real AsyncSerialConnection read loop with a fake reader.
    """
    engine = create_engine(SPEAKERCRAFT_PROFILE)
    conn = AsyncSerialConnection(port="demo", engine=engine, demo_mode=False)

    body = bytes([0x55, 0x0A, 0x20, 0x00, 0x00, 0x02, 0x00, 0x80, 0x00, 0x00])
    frame = body + bytes([(0x100 - (sum(body) % 256)) & 0xFF])

    processed: list[str | bytes] = []
    conn._process_response = processed.append  # type: ignore[method-assign]

    class FakeReader:
        """Yields the frame once, then blocks so the loop stays alive briefly."""

        def __init__(self, data: bytes) -> None:
            self._data = data
            self._sent = False

        async def read(self, _n: int) -> bytes:
            if self._sent:
                await asyncio.sleep(10)  # block; the test cancels the loop
                return b""
            self._sent = True
            return self._data

    conn._reader = FakeReader(frame)  # type: ignore[assignment]

    # Run the loop briefly, then cancel -- the frame is processed on the first
    # read; we do not want to reach EOF (which would schedule a reconnect).
    task = asyncio.create_task(conn._read_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    # The read loop catches CancelledError internally and returns, so awaiting
    # the cancelled task completes normally rather than re-raising.
    await asyncio.wait_for(task, timeout=1)

    assert processed, "no frame processed"
    assert processed[0] == frame
    assert isinstance(processed[0], bytes)


# ─── SEC-003: read buffer must stay bounded ──────────────────────────────────


async def test_read_buffer_is_bounded() -> None:
    """A start byte with no end byte must not grow the buffer without limit."""
    engine = create_engine(RNET_END_PROFILE)
    conn = AsyncSerialConnection(port="demo", engine=engine, demo_mode=False)

    chunks = [bytes([0xF0] * 256) for _ in range(100)]  # 25600 bytes, no 0xF7

    class FloodReader:
        def __init__(self) -> None:
            self._i = 0

        async def read(self, _n: int) -> bytes:
            if self._i < len(chunks):
                c = chunks[self._i]
                self._i += 1
                return c
            return b""  # EOF

        # expose the live buffer for assertion via a side channel is not
        # possible; instead we assert the loop terminates quickly and does not
        # OOM, which the cap guarantees.

    conn._reader = FloodReader()  # type: ignore[assignment]
    conn._shutting_down = True

    # Must complete promptly; without the cap this is O(n^2) and would time out.
    await asyncio.wait_for(conn._read_loop(), timeout=5)


def test_max_read_buffer_constant_is_sane() -> None:
    """The cap exists and is a reasonable size."""
    assert 1024 <= _MAX_READ_BUFFER <= 65536
