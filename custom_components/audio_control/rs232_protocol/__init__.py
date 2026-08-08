"""rs232_protocol — RS232 serial device protocol library (vendored).

Self-contained with zero Home Assistant imports, but shipped inside the
audio_control integration rather than published to PyPI: HA resolves manifest
requirements against PyPI only, so a local-only distribution cannot satisfy
them on a HACS install.

Supports three protocol types:
- Text (ASCII): command templates with regex response parsing
- Binary: hex-framed with start byte, length, opcode, checksum
- JSON: newline-delimited JSON with optional authentication

Factory function `create_engine()` picks the right engine from a profile's
`protocol_type` field ("text", "binary", or "json").

No Home Assistant dependency — usable standalone.
"""

from __future__ import annotations

from .base import BaseProtocolEngine
from .binary_engine import BinaryProtocolEngine
from .connection import AsyncSerialConnection, AuthenticationError
from .factory import create_engine
from .json_engine import JsonProtocolEngine
from .models import ZoneState
from .profile_loader import (
    get_profile_choices,
    load_all_profiles,
    load_builtin_profiles,
    load_custom_profiles,
)
from .protocol_engine import ProtocolEngine

__all__ = [
    "AsyncSerialConnection",
    "AuthenticationError",
    "BaseProtocolEngine",
    "BinaryProtocolEngine",
    "JsonProtocolEngine",
    "ProtocolEngine",
    "ZoneState",
    "create_engine",
    "get_profile_choices",
    "load_all_profiles",
    "load_builtin_profiles",
    "load_custom_profiles",
]

__version__ = "0.2.0"
