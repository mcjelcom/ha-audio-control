"""Regressions for the second 4-model review (v2.0.7..v2.0.8).

R1 (Opus/Haiku/Fable): RTI power commands carry a zone, the device-wide reply
    did not confirm them -> timeout, retry, rollback of the commanded zone
    while every other zone had flipped.
R2 (all four): rollback after a failed power command left power_known=True.
R3 (Sonnet/Opus/Fable): Monoprice 6-zone and Xantech MRC88 (offset -7) lacked
    tone levels, so odd steps were refused and +/-8 silently clamped.
"""

from __future__ import annotations

import asyncio

import pytest
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles

RTI = "RTI AD-810-100 / AD-46-100"


class _FakeDevice:
    """Answers each write with a canned reply, like the real unit."""

    def __init__(self, conn: AsyncSerialConnection, reply: str) -> None:
        self._conn = conn
        self._reply = reply

    def write(self, _data: bytes) -> None:
        asyncio.get_running_loop().call_soon(self._conn._process_response, self._reply)

    async def drain(self) -> None:
        return None


def _rti_conn(reply: str) -> AsyncSerialConnection:
    conn = AsyncSerialConnection(
        port="x", engine=create_engine(load_builtin_profiles()[RTI]), demo_mode=False
    )
    conn._writer = _FakeDevice(conn, reply)  # type: ignore[assignment]
    conn._connected = True
    return conn


@pytest.mark.parametrize(
    ("command", "value"), [("power_on", "true"), ("power_off", "false")]
)
async def test_rti_power_command_is_confirmed_by_device_wide_reply(
    command: str, value: str
) -> None:
    conn = _rti_conn(f'{{"type":"set_powerstate","status":200,"value":{value}}}')
    assert await conn.send_command(command, zone=3) is True
    assert all(z.power is (value == "true") for z in conn.zones.values())


async def test_unrelated_global_still_does_not_confirm_a_zoned_command() -> None:
    """The narrow exception must not let any broadcast confirm any command."""
    conn = _rti_conn('{"type":"set_powerstate","status":200,"value":true}')
    assert await conn.send_command("volume_set", zone=3, volume=20) is False


def test_rollback_restores_power_known() -> None:
    conn = AsyncSerialConnection(
        port="x", engine=create_engine(load_builtin_profiles()[RTI]), demo_mode=False
    )
    z = conn.zones[1]
    assert z.power_known is False
    conn.set_zone_power(1, True)
    assert z.power_known is True
    conn.rollback_zone_power(1, False, False, 0, False)
    assert (z.power, z.power_known) == (False, False)


def test_rollback_without_known_argument_is_backward_compatible() -> None:
    conn = AsyncSerialConnection(
        port="x", engine=create_engine(load_builtin_profiles()[RTI]), demo_mode=False
    )
    conn.set_zone_power(1, True)
    conn.rollback_zone_power(1, False, False, 0)
    assert conn.zones[1].power_known is True


@pytest.mark.parametrize("needle", ["Monoprice 6-Zone", "MRC-88"])
def test_offset_profiles_all_declare_every_step(needle: str) -> None:
    matches = [
        (k, p)
        for k, p in load_builtin_profiles().items()
        if needle.lower() in (k + str(p.get("models"))).lower()
    ]
    assert matches, needle
    for name, profile in matches:
        assert create_engine(profile).tone_levels == tuple(range(-7, 8)), name


def test_every_offset_minus_7_tone_profile_declares_levels() -> None:
    """Guard: no offset -7 tone profile may fall back to the even default."""
    offenders = []
    for name, profile in load_builtin_profiles().items():
        bass = (profile.get("response") or {}).get("mapping", {}).get("bass") or {}
        has_tone = "bass_set" in (profile.get("commands") or {})
        declared = (profile.get("tone") or {}).get("levels")
        if bass.get("offset") == -7 and has_tone and not declared:
            offenders.append(name)
    assert offenders == []
