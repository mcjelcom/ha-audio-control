"""Shared test fixtures for Audio Control tests."""

from __future__ import annotations

from typing import Any

import pytest
from rs232_protocol import ProtocolEngine
from rs232_protocol.connection import AsyncSerialConnection

# ─── Sample Profiles ────────────────────────────────────────────────────────


MONOPRICE_PROFILE: dict[str, Any] = {
    "name": "Monoprice 6-Zone",
    "manufacturer": "Monoprice",
    "zones": 6,
    "sources": 6,
    "serial": {
        "baud_rate": 9600,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "command_prefix": "",
        "command_suffix": "\r",
        "response_prefix": "#",
        "response_terminator": "\r",
        "command_delay_ms": 100,
    },
    "commands": {
        # Templates match the shipped monoprice_6zone.yaml: unit-prefixed 1-digit
        # zone (wire zone 11-16), so status is ?1{zone}, not ?{zone:02d}.
        "status": "?1{zone:1d}",
        "power_on": "<1{zone:1d}PR01",
        "power_off": "<1{zone:1d}PR00",
        "volume_set": "<1{zone:1d}VO{volume:02d}",
        "volume_up": "<1{zone:1d}VI",
        "volume_down": "<1{zone:1d}VD",
        "mute_on": "<1{zone:1d}MU01",
        "mute_off": "<1{zone:1d}MU00",
        "source_set": "<1{zone:1d}CH{source:02d}",
    },
    "response": {
        "status_pattern": r"(?P<zone>\d{2})(?P<pa>\d{2})(?P<power>\d{2})(?P<mute>\d{2})(?P<dt>\d{2})(?P<volume>\d{2})(?P<treble>\d{2})(?P<bass>\d{2})(?P<balance>\d{2})(?P<source>\d{2})",
        # Wire zone 11 -> logical zone 1, matching the shipped profile.
        "zone_offset": -10,
        # Shipped profile uses an empty error token (the device has no explicit
        # error reply); must not be "?" or blank lines get flagged as errors.
        "error_response": "",
        "mapping": {
            "power": {"field": "power", "type": "bool", "on_value": "01"},
            "mute": {"field": "mute", "type": "bool", "on_value": "01"},
            "volume": {"field": "volume", "type": "int"},
            "source": {"field": "source", "type": "int"},
            "bass": {"field": "bass", "type": "int", "offset": -7},
            "treble": {"field": "treble", "type": "int", "offset": -7},
            "balance": {"field": "balance", "type": "int", "offset": -10},
        },
    },
    "volume": {
        "min": 0,
        "max": 38,
        "inverted": False,
    },
    "features": {
        "has_tone_controls": True,
        "has_balance": True,
        "has_group_mode": False,
        "has_all_off": False,
        "unsolicited_updates": False,
    },
}


AMC_X86_PROFILE: dict[str, Any] = {
    "name": "AMC X86 / X86i",
    "manufacturer": "AMC",
    "zones": 6,
    "sources": 8,
    "serial": {
        "baud_rate": 38400,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
        "command_prefix": "*",
        "command_suffix": "\r",
        "response_prefix": "#",
        "response_terminator": "\r",
        "command_delay_ms": 500,
    },
    "commands": {
        # Shipped amc_x86.yaml uses the ZN prefix (confirmed on real hardware),
        # not Z. The old fixture predated that hardware finding.
        "status": "ZN{zone:02d}STA00",
        "power_on": "ZN{zone:02d}PWR01",
        "power_off": "ZN{zone:02d}PWR00",
        "volume_set": "ZN{zone:02d}VOL{volume:02d}",
        "volume_up": "ZN{zone:02d}VOLUP",
        "volume_down": "ZN{zone:02d}VOLDN",
        "mute_on": "ZN{zone:02d}MUT01",
        "mute_off": "ZN{zone:02d}MUT00",
        "source_set": "ZN{zone:02d}SRC{source:02d}",
        "all_off": "ZALLPWR00",
    },
    "response": {
        "status_pattern": r"ZN(?P<zone>\d{2}),SRC(?P<source>\d{2}),GRP(?P<group>\d),VOL-(?P<volume>\d{2})",
        "tone_pattern": r"ZN(?P<zone>\d{2}),BASS(?P<bass>[+-]?\d+),TREB(?P<treble>[+-]?\d+),GRP(?P<group>\d)",
        "error_response": "?",
        "global_patterns": {
            "all_off": "ZALLOFF",
            "mute_all_on": "ZALLMON",
            "mute_all_off": "ZALLMOFF",
            "group_off": "GRPOFF",
            "group_on": r"GRPON,STC(?P<source>\d{2})",
        },
        "mapping": {
            "power": {"field": "volume", "type": "threshold", "off_value": 62},
            "mute": {"field": "volume", "type": "equals", "mute_value": 62},
            "volume": {"field": "volume", "type": "int"},
            "source": {"field": "source", "type": "int"},
            "group": {"field": "group", "type": "bool", "on_value": "1"},
            "bass": {"field": "bass", "type": "signed_int"},
            "treble": {"field": "treble", "type": "signed_int"},
        },
    },
    "volume": {
        "min": 0,
        "max": 62,
        "inverted": True,
    },
    "features": {
        "has_tone_controls": True,
        "has_balance": False,
        "has_group_mode": True,
        "has_all_off": True,
        "unsolicited_updates": False,
    },
}


@pytest.fixture
def monoprice_engine() -> ProtocolEngine:
    """Create a Monoprice-style protocol engine."""
    return ProtocolEngine(MONOPRICE_PROFILE)


@pytest.fixture
def amc_engine() -> ProtocolEngine:
    """Create an AMC X86-style protocol engine."""
    return ProtocolEngine(AMC_X86_PROFILE)


@pytest.fixture
def demo_connection(monoprice_engine: ProtocolEngine) -> AsyncSerialConnection:
    """Create a demo-mode connection (no real serial port)."""
    return AsyncSerialConnection(
        port="demo",
        engine=monoprice_engine,
        demo_mode=True,
    )
