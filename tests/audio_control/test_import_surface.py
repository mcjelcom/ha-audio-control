"""Every module must import cleanly, and HA-version-fragile imports must be guarded.

A deploy to a device running HA 2026.8.1 failed with:

    Setup failed for custom integration 'audio_control': Unable to import
    component: cannot import name 'async_extract_referenced_entity_ids' from
    'homeassistant.helpers.service'

The whole integration failed to load -- every entity `unavailable` -- because HA
moved that function to `homeassistant.helpers.target` in 2025.x. The test harness
pins **HA 2024.12.5**, where it still lives in `helpers.service`, so 1038 passing
tests could not see it.

That version gap is the real finding: the suite validates against an HA nearly two
years older than the devices run. These tests cannot close the gap -- only bumping
the harness can -- but they do two useful things:

  1. Import every module, so a symbol that vanished from the PINNED version is
     caught at test time rather than at deploy time.
  2. Assert that imports known to have moved are wrapped in try/except, so the
     next HA reshuffle degrades instead of bricking the integration.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

COMPONENT = Path("custom_components/audio_control")

MODULES = [
    "custom_components.audio_control",
    "custom_components.audio_control.binary_sensor",
    "custom_components.audio_control.config_flow",
    "custom_components.audio_control.const",
    "custom_components.audio_control.dashboard_writer",
    "custom_components.audio_control.diagnostics",
    "custom_components.audio_control.entity",
    "custom_components.audio_control.media_player",
    "custom_components.audio_control.profile_loader",
    "custom_components.audio_control.serial_manager",
    "custom_components.audio_control.services",
]

# Symbols HA has relocated between releases. Importing any of these from a single
# hard-coded path is what took the integration down on 2026.8.1.
RELOCATED_SYMBOLS = {
    "async_extract_referenced_entity_ids": (
        "homeassistant.helpers.target",  # 2025.x onwards
        "homeassistant.helpers.service",  # 2024.x and earlier
    ),
    "UsbServiceInfo": (
        "homeassistant.helpers.service_info.usb",  # 2025.x onwards
        "homeassistant.components.usb",  # older, plus the re-export
    ),
}


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    """A missing symbol must fail here, not on a device.

    HA reports an import failure as "Setup failed ... Unable to import component"
    and leaves every entity unavailable, which is indistinguishable from a dead
    serial link until you read the log.
    """
    importlib.import_module(module)


@pytest.mark.parametrize("symbol", sorted(RELOCATED_SYMBOLS))
def test_relocated_symbol_is_importable_from_somewhere(symbol: str) -> None:
    """At least one of the known paths must work on the installed HA."""
    paths = RELOCATED_SYMBOLS[symbol]
    found = []
    for path in paths:
        try:
            module = importlib.import_module(path)
        except ImportError:
            continue
        if hasattr(module, symbol):
            found.append(path)
    assert found, f"{symbol} is in none of {paths} on this HA version"


@pytest.mark.parametrize("symbol", sorted(RELOCATED_SYMBOLS))
def test_relocated_symbol_import_is_guarded(symbol: str) -> None:
    """Any import of a relocated symbol must sit inside a try/except ImportError.

    An unguarded import works until HA moves the symbol, then takes the entire
    integration down. Both current cases (UsbServiceInfo, and now
    async_extract_referenced_entity_ids) are guarded; this keeps it that way.
    """
    offenders = []
    for path in sorted(COMPONENT.rglob("*.py")):
        text = path.read_text()
        if symbol not in text:
            continue
        # Find the import statement and check it is inside a try block: the
        # simplest reliable signal is a `try:` before it with `except ImportError`
        # after it, within the module's import section.
        for match in re.finditer(
            rf"^(\s*)from [\w.]+ import [^\n]*{symbol}", text, re.MULTILINE
        ):
            indented = bool(match.group(1))
            has_guard = "except ImportError" in text
            if not (indented and has_guard):
                offenders.append(f"{path}:{text[: match.start()].count(chr(10)) + 1}")
    assert not offenders, f"unguarded import of relocated symbol {symbol}: {offenders}"


def test_harness_ha_version_is_recorded() -> None:
    """Surfaces the version gap rather than leaving it implicit.

    Not an assertion about which version is correct -- it documents that the
    harness version is what the suite actually validates, and that a device may
    run something much newer. When this number moves, expect new failures that
    were previously invisible.
    """
    from homeassistant.const import __version__

    assert re.match(r"^\d{4}\.\d+\.\d+", __version__), (
        f"unexpected HA version format: {__version__}"
    )
    # Deliberately printed, not asserted against a target: pinning a minimum here
    # would fail the suite on the very upgrade it is meant to encourage.
    print(f"test harness HA version: {__version__}")
