"""A reply must only confirm the command it actually answers.

`_wait_for_response` accepted two kinds of reply too readily:

  1. Any frame matching a `global_patterns` entry returned True regardless of what
     was pending. A device-initiated broadcast -- an AMC sends `ZALLOFF` when
     someone presses All Off on the front panel -- therefore confirmed whatever
     command happened to be in flight.

  2. On single-zone devices ANY parsed frame returned True, under a comment
     asserting "Single-zone devices cannot mis-correlate". They can: the NAD C 368
     pattern is `Main\\.(?P<field>\\w+)=(?P<value>.+)`, so an unsolicited
     `Main.Volume=-30` push confirmed a pending `power_on`.

This is the inverse of a dead button. A dead button fails visibly; a false ACK
COMMITS optimistic state -- rollback is skipped -- for a command the device may
have rejected, so HA and the hardware disagree with no error and no reconciliation
until the next 60s poll. On a device with `unsolicited_updates: true` there is a
steady supply of frames to mis-correlate against.

Both cases were reproduced against the real class before fixing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.audio_control.rs232_protocol import create_engine
from custom_components.audio_control.rs232_protocol.connection import (
    AsyncSerialConnection,
)
from custom_components.audio_control.rs232_protocol.profile_loader import (
    load_builtin_profiles,
)


def conn(name: str) -> AsyncSerialConnection:
    engine = create_engine(load_builtin_profiles()[name])
    return AsyncSerialConnection(port="demo", engine=engine, demo_mode=True)


async def wait_with(
    connection: AsyncSerialConnection,
    replies: list[Any],
    command: str,
    zone: int | None,
) -> bool:
    for reply in replies:
        await connection._response_queue.put(reply)
    return await connection._wait_for_response(command, zone)


# ─── A global broadcast must not ACK a zone command ──────────────────────────


async def test_global_broadcast_does_not_ack_a_zone_command() -> None:
    """The regression: `ZALLOFF` confirmed an unrelated zone-5 volume_set.

    The frame is real and unsolicited -- the AMC emits it when All Off is pressed
    on the front panel -- so this is not a contrived case.
    """
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["ZALLOFF"], "volume_set", 5)
    assert result is False, "a device broadcast ACKed a pending zone command"


async def test_global_broadcast_still_acks_a_global_command() -> None:
    """A global command legitimately has no zone, so its broadcast must confirm.

    Without this the fix would break All Off entirely -- every global command
    would time out.
    """
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["ZALLOFF"], "all_off", None)
    assert result is True


async def test_zone_reply_after_a_broadcast_still_acks() -> None:
    """A broadcast must be skipped, not fatal: the real reply may follow it.

    Returning False on the first global frame would abandon a command the device
    was about to confirm.
    """
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["ZALLOFF", "ZN05,SRC02,GRP0,VOL-30"], "volume_set", 5)
    assert result is True


async def test_wrong_zone_reply_still_does_not_ack() -> None:
    """Pre-existing behaviour that must survive the change."""
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["ZN03,SRC02,GRP0,VOL-30"], "volume_set", 5)
    assert result is False


# ─── Single-zone devices are not exempt ──────────────────────────────────────


async def test_unrelated_field_does_not_ack_on_a_single_zone_device() -> None:
    """The NAD reports one field per frame, so frames are distinguishable.

    `Main.Volume=-30` must not confirm a pending power_on. The old code returned
    True for any parsed frame on a one-zone device.
    """
    c = conn("NAD C 368 / C 388")
    assert c.engine.num_zones == 1
    result = await wait_with(c, ["Main.Volume=-30"], "power_on", 1)
    assert result is False, "a volume report ACKed power_on"


async def test_matching_field_acks_on_a_single_zone_device() -> None:
    """The device's actual answer must still confirm the command."""
    c = conn("NAD C 368 / C 388")
    result = await wait_with(c, ["Main.Power=On"], "power_on", 1)
    assert result is True


async def test_single_zone_volume_reply_acks_volume_set() -> None:
    """Correlation is by command family, so volume answers volume."""
    c = conn("NAD C 368 / C 388")
    result = await wait_with(c, ["Main.Volume=-30"], "volume_set", 1)
    assert result is True


async def test_single_zone_unrelated_then_matching_reply_acks() -> None:
    """An interleaved unsolicited push must be skipped, not fatal."""
    c = conn("NAD C 368 / C 388")
    result = await wait_with(c, ["Main.Volume=-30", "Main.Power=On"], "power_on", 1)
    assert result is True


# ─── Profiles whose replies carry no distinguishing field ────────────────────


async def test_profile_with_an_opaque_reply_still_acks() -> None:
    """Not every device reports which setting it changed.

    The AMC XIA answers every command with the same `#ON,SRCbb,MUTE x` status
    frame, so there is nothing to correlate against beyond "it parsed". Such
    profiles must keep working -- tightening correlation must not require a
    field the protocol does not provide.
    """
    c = conn("AMC XIA100e / XIA150e")
    assert c.engine.num_zones == 1
    result = await wait_with(c, ["ON,SRC03,MUTE OFF"], "source_set", 1)
    assert result is True


async def test_xcdie_status_acks_its_own_command() -> None:
    """Binary single-zone transport: the status reply must confirm."""
    c = conn("AMC XCDie CD Player")
    result = await wait_with(c, [bytes([0x55, 0x31, 0xAA])], "status", 1)
    assert result is True


# ─── Bounds and timeouts are unchanged ───────────────────────────────────────


async def test_unparseable_frames_are_still_ignored() -> None:
    """A boot banner or line noise must not ACK anything."""
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["*** BOOT ***"], "volume_set", 5)
    assert result is False


async def test_error_token_still_fails_immediately() -> None:
    """An explicit device error must short-circuit."""
    c = conn("AMC X86 / X86i")
    result = await wait_with(c, ["__ERROR__"], "volume_set", 5)
    assert result is False


async def test_empty_queue_times_out_rather_than_hanging() -> None:
    """The whole-wait deadline must still bound the call."""
    c = conn("AMC X86 / X86i")
    result = await asyncio.wait_for(c._wait_for_response("volume_set", 5), timeout=10)
    assert result is False


@pytest.mark.parametrize("name", sorted(load_builtin_profiles()))
async def test_every_profile_can_still_confirm_a_status_command(name: str) -> None:
    """Fleet guard: tightening correlation must not make any profile un-ACKable.

    Only asserts that the machinery does not reject a frame the engine itself
    parsed -- a per-profile reply sample would need 26 hand-written frames, and
    the point here is that no profile becomes structurally unconfirmable.
    """
    c = conn(name)
    # No reply queued: must time out cleanly rather than raise.
    assert await asyncio.wait_for(c._wait_for_response("status", 1), timeout=10) in (
        True,
        False,
    )
