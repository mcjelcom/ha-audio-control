"""Protocol engine factory — selects the right engine based on profile type.

Usage:
    from .rs232_protocol import create_engine
    engine = create_engine(profile_dict)
"""

from __future__ import annotations

from typing import Any

from .base import BaseProtocolEngine
from .binary_engine import BinaryProtocolEngine
from .json_engine import JsonProtocolEngine
from .protocol_engine import ProtocolEngine


def create_engine(profile: dict[str, Any]) -> BaseProtocolEngine:
    """Create the appropriate protocol engine from a profile dict.

    Selects engine based on the `protocol_type` field:
    - "text" (default) — ASCII command/response with regex parsing
    - "binary" — Hex-framed with start byte, length, checksum
    - "json" — Newline-delimited JSON with optional authentication

    Args:
        profile: Device profile dict (loaded from YAML or inline).

    Returns:
        An engine instance ready for use with AsyncSerialConnection.
    """
    protocol_type: str = profile.get("protocol_type", "text")

    if protocol_type == "binary":
        return BinaryProtocolEngine(profile)
    if protocol_type == "json":
        return JsonProtocolEngine(profile)

    # Default: text protocol (backward compatible)
    return ProtocolEngine(profile)
