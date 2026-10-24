"""Integration code must not import voluptuous directly.

HA 2026.10 dropped voluptuous from its requirements (core uses probatio); it is
only present transitively. A direct import would stop the integration loading
the day that changes, so everything goes through `_schema.vol`.
"""

from __future__ import annotations

import re
from pathlib import Path

INTEGRATION = Path(__file__).parents[2] / "custom_components" / "audio_control"


def test_no_direct_voluptuous_import() -> None:
    offenders = [
        str(p.relative_to(INTEGRATION))
        for p in INTEGRATION.rglob("*.py")
        if p.name != "_schema.py"
        and re.search(r"^\s*(import|from)\s+voluptuous\b", p.read_text(), re.MULTILINE)
    ]
    assert offenders == [], f"use `from ._schema import vol`: {offenders}"


def test_shim_prefers_probatio() -> None:
    from custom_components.audio_control._schema import vol

    assert vol.__name__ == "probatio"
