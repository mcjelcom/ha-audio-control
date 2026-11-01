"""AMC X86 / X86i behaviour captured on a REAL X86i (2026-11-01).

Serial exchange recorded on hardware, zone 1:

    *ZN01PWR01  -> ZN01,SRC01,GRP0,VOL-30    zone on
    *ZN01MUT01  -> ZN01,SRC01,GRP0,VOL-62    on + muted
    *ZN01BAS+0  -> ZN01,BASS+0,TREB+0        tone accepted (zone ON)
    *ZN01BAS+0  -> ?                         tone rejected (zone OFF)
    *ZN01PWR00  -> ZN01,SRC00,GRP0,VOL-62    off

Three integration bugs it exposed:
  1. tone_pattern required ",GRP<n>" (as the RS232 manual v3.3 shows) but the
     amp omits it, so an ACCEPTED bass change still failed with HTTP 500;
  2. power was derived from volume, and VOL-62 means both "muted" and "off",
     so muting a zone made Home Assistant show it as OFF;
  3. the service accepted +/-2, which the AMC never accepts, and an OFF zone
     got "check the device connection" instead of "turn the zone on".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.connection import AsyncSerialConnection
from rs232_protocol.profile_loader import load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

PROFILE = "AMC X86 / X86i"

ON = "ZN01,SRC01,GRP0,VOL-30"
ON_MUTED = "ZN01,SRC01,GRP0,VOL-62"
OFF = "ZN01,SRC00,GRP0,VOL-62"
TONE = "ZN01,BASS+0,TREB+0"


def engine() -> Any:
    return create_engine(load_builtin_profiles()[PROFILE])


# ─── Bug 2: mute must not read as power off ──────────────────────────────────


@pytest.mark.parametrize(
    ("reply", "power", "mute"),
    [(ON, True, False), (ON_MUTED, True, True), (OFF, False, True)],
)
def test_power_and_mute_from_real_status_replies(
    reply: str, power: bool, mute: bool
) -> None:
    parsed = engine().parse_response(reply)
    assert parsed is not None
    assert parsed["zone"] == 1
    assert parsed["power"] is power, f"{reply}: power"
    assert parsed["mute"] is mute, f"{reply}: mute"


@pytest.mark.parametrize("name", ["AMC X86 / X86i", "AMC XO", "AMC XOir"])
def test_same_family_profiles_take_power_from_source(name: str) -> None:
    e = create_engine(load_builtin_profiles()[name])  # KeyError, not a skip
    on_muted, off = e.parse_response(ON_MUTED), e.parse_response(OFF)
    assert on_muted is not None
    assert off is not None
    assert on_muted["power"] is True
    assert off["power"] is False


# ─── Bug 1: the real tone reply has no ,GRP ──────────────────────────────────


def test_grp_less_tone_reply_parses() -> None:
    parsed = engine().parse_response(TONE)
    assert parsed is not None
    assert parsed["zone"] == 1
    assert parsed["bass"] == 0
    assert parsed["treble"] == 0
    # The optional GRP group did not match: it must be ABSENT, not group=False
    # (which would switch group mode off on every bass/treble change).
    assert "group" not in parsed


def test_tone_reply_with_grp_still_parses() -> None:
    """The manual's documented form must keep working."""
    parsed = engine().parse_response("ZN01,BASS-4,TREB+6,GRP1")
    assert parsed is not None
    assert (parsed["bass"], parsed["treble"], parsed["group"]) == (-4, 6, True)


class _FakeAmc:
    """Writer stand-in: answers each write with the reply the real amp sent."""

    def __init__(self, conn: AsyncSerialConnection, reply: str) -> None:
        self._conn = conn
        self._reply = reply
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)
        asyncio.get_running_loop().call_soon(self._conn._process_response, self._reply)

    async def drain(self) -> None:
        return None


async def test_accepted_bass_set_succeeds_end_to_end() -> None:
    """The exact exchange that returned HTTP 500 on hardware must now succeed."""
    conn = AsyncSerialConnection(port="x", engine=engine(), demo_mode=False)
    fake = _FakeAmc(conn, TONE)
    conn._writer = fake  # type: ignore[assignment]
    conn._connected = True
    conn.zones[1].group = True

    assert await conn.send_command("bass_set", zone=1, level=0) is True
    assert fake.written[0] == b"*ZN01BAS+0\r"
    assert conn.zones[1].bass == 0
    assert conn.zones[1].group is True, "tone reply must not clear group mode"


async def test_rejected_bass_set_still_fails() -> None:
    conn = AsyncSerialConnection(port="x", engine=engine(), demo_mode=False)
    conn._writer = _FakeAmc(conn, "?")  # type: ignore[assignment]
    conn._connected = True
    assert await conn.send_command("bass_set", zone=1, level=0) is False


# ─── Bug 3: levels and off zones are rejected with a useful message ──────────


def test_profile_declares_verified_tone_rules() -> None:
    e = engine()
    assert e.tone_levels == (-8, -6, -4, 0, 4, 6, 8)
    assert e.tone_requires_power is True


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


async def _setup(hass: HomeAssistant) -> str:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        title=PROFILE,
        data={
            "port": "demo",
            "device_profile": PROFILE,
            "num_zones": 6,
            "num_sources": 8,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ids = [
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "media_player"
    ]
    return sorted(ids)[0]


async def _bass(hass: HomeAssistant, eid: str, level: int) -> None:
    await hass.services.async_call(
        DOMAIN, "set_bass", {"entity_id": eid, "level": level}, blocking=True
    )


async def test_unsupported_level_lists_the_valid_ones(hass: HomeAssistant) -> None:
    eid = await _setup(hass)
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": eid}, blocking=True
    )
    with pytest.raises(HomeAssistantError) as excinfo:
        await _bass(hass, eid, 2)
    assert excinfo.value.translation_key == "unsupported_tone_level"
    assert "+4" in excinfo.value.translation_placeholders["allowed"]


async def test_off_zone_says_turn_it_on(hass: HomeAssistant) -> None:
    eid = await _setup(hass)
    with pytest.raises(HomeAssistantError) as excinfo:
        await _bass(hass, eid, 4)
    assert excinfo.value.translation_key == "zone_off_tone"


async def test_on_zone_valid_level_succeeds(hass: HomeAssistant) -> None:
    eid = await _setup(hass)
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": eid}, blocking=True
    )
    await _bass(hass, eid, -4)
