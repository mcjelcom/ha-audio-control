"""User-supplied profiles dropped into {config}/audio_control/*.yaml.

This is a real, documented feature -- a custom YAML there appears in the config
flow dropdown alongside the 26 built-ins -- and it had no test coverage at all
(rs232_protocol/profile_loader.py sat at 72%, the whole gap being
load_custom_profiles).

It is also the one profile path that bypasses every validation we added. The
custom-device WIZARD now compiles status_pattern at submit time, but a
hand-written file skips the wizard entirely: the loader is deliberately tolerant,
so a profile with an uncompilable regex is listed in the dropdown, selected, and
only fails later inside create_engine -- which sits outside the try in
async_setup_entry, so it escapes as a raw re.error.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import (
    load_all_profiles,
    load_builtin_profiles,
    load_custom_profiles,
)

from custom_components.audio_control.const import DOMAIN

MINIMAL = """\
name: {name}
zones: {zones}
sources: 2
serial:
  command_suffix: "\\r"
commands:
  status: "S{{zone}}"
  power_on: "P{{zone}}1"
  power_off: "P{{zone}}0"
response:
  status_pattern: "Z(?P<zone>\\\\d)V(?P<volume>\\\\d{{2}})"
  mapping:
    volume: {{field: volume, type: int}}
volume:
  min: 0
  max: 38
"""


def write(directory: Path, filename: str, content: str) -> Path:
    path = directory / filename
    path.write_text(content)
    return path


# ─── Loading, and the (Custom) suffix ────────────────────────────────────────


def test_custom_profile_is_loaded(tmp_path: Path) -> None:
    """A well-formed file appears, suffixed so it is distinguishable."""
    write(tmp_path, "mine.yaml", MINIMAL.format(name="My Amp", zones=2))
    profiles = load_custom_profiles(str(tmp_path))
    assert "My Amp (Custom)" in profiles
    assert profiles["My Amp (Custom)"]["zones"] == 2


def test_custom_profile_cannot_shadow_a_builtin(tmp_path: Path) -> None:
    """The (Custom) suffix is what protects the shipped profiles.

    Without it, a user file named "AMC X86 / X86i" would silently replace the
    built-in one in load_all_profiles' dict update -- and an existing config
    entry referencing that name would start using the user's definition after a
    restart, with no indication anything changed.
    """
    write(tmp_path, "clash.yaml", MINIMAL.format(name="AMC X86 / X86i", zones=99))
    profiles = load_all_profiles(str(tmp_path))
    assert profiles["AMC X86 / X86i"]["zones"] == 6, "built-in was overwritten"
    assert profiles["AMC X86 / X86i (Custom)"]["zones"] == 99


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    """Most installs have no custom dir; that must not be a failure."""
    assert load_custom_profiles(str(tmp_path / "does-not-exist")) == {}


def test_custom_profiles_supplement_rather_than_replace(tmp_path: Path) -> None:
    """All 26 built-ins must still be present alongside a custom one."""
    write(tmp_path, "mine.yaml", MINIMAL.format(name="My Amp", zones=2))
    builtin_count = len(load_builtin_profiles())
    combined = load_all_profiles(str(tmp_path))
    assert len(combined) == builtin_count + 1


def test_file_records_its_own_path(tmp_path: Path) -> None:
    """`_file` is what diagnostics reports, so it must point at the real file."""
    path = write(tmp_path, "mine.yaml", MINIMAL.format(name="My Amp", zones=2))
    profiles = load_custom_profiles(str(tmp_path))
    assert profiles["My Amp (Custom)"]["_file"] == str(path)


# ─── Tolerance: one bad file must not hide the good ones ─────────────────────


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("malformed.yaml", "name: [unclosed\n"),
        ("empty.yaml", ""),
        ("no_name.yaml", "zones: 2\nsources: 2\n"),
        ("not_a_mapping.yaml", "- just\n- a\n- list\n"),
        ("null_doc.yaml", "~\n"),
    ],
)
def test_unusable_file_is_skipped_not_fatal(
    tmp_path: Path, filename: str, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A single broken file must not take out the whole directory.

    The user has no feedback channel here other than the log, so it must warn
    rather than fail silently -- but it must also keep going.
    """
    write(tmp_path, filename, content)
    write(tmp_path, "good.yaml", MINIMAL.format(name="Good Amp", zones=2))
    with caplog.at_level(logging.WARNING):
        profiles = load_custom_profiles(str(tmp_path))
    assert "Good Amp (Custom)" in profiles, f"{filename} suppressed the good file"
    assert len(profiles) == 1


def test_malformed_yaml_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Silent skipping would leave the user with no way to diagnose it."""
    write(tmp_path, "malformed.yaml", "name: [unclosed\n")
    with caplog.at_level(logging.WARNING):
        load_custom_profiles(str(tmp_path))
    # getMessage() applies args safely; `r.message % r.args` raises once the
    # record has already been formatted.
    assert any("malformed.yaml" in r.getMessage() for r in caplog.records), (
        "no warning naming the offending file"
    )


def test_non_yaml_files_are_ignored(tmp_path: Path) -> None:
    """READMEs and editor backups routinely sit next to the profiles."""
    write(tmp_path, "notes.txt", "name: Not A Profile\n")
    write(tmp_path, "mine.yaml.bak", MINIMAL.format(name="Backup", zones=2))
    write(tmp_path, "mine.yaml", MINIMAL.format(name="My Amp", zones=2))
    profiles = load_custom_profiles(str(tmp_path))
    assert sorted(profiles) == ["My Amp (Custom)"]


def test_builtin_template_file_is_skipped() -> None:
    """_template.yaml documents the schema and is not a device."""
    assert not any("template" in name.lower() for name in load_builtin_profiles())


# ─── The validation gap this feature opens ───────────────────────────────────


def test_custom_profile_with_bad_regex_is_loaded_but_unusable(
    tmp_path: Path,
) -> None:
    """Documents the seam: the loader accepts what create_engine rejects.

    The loader is intentionally tolerant -- it only parses YAML -- so an
    uncompilable status_pattern passes here and raises later. The fix belongs at
    the consumer, not here: making the loader compile regexes would couple it to
    the engine and still not help, since the profile would just vanish from the
    dropdown with no explanation.
    """
    write(
        tmp_path,
        "badregex.yaml",
        "name: Bad Regex\nzones: 1\nsources: 1\n"
        'serial: {command_suffix: "\\r"}\n'
        'commands: {status: "S"}\n'
        'response:\n  status_pattern: "Z(?P<zone>\\\\d{2}"\n  mapping: {}\n'
        "volume: {min: 0, max: 10}\n",
    )
    profiles = load_custom_profiles(str(tmp_path))
    assert "Bad Regex (Custom)" in profiles, "loader should stay tolerant"
    import re

    with pytest.raises(re.error):
        create_engine(profiles["Bad Regex (Custom)"])


def test_every_builtin_profile_builds_an_engine() -> None:
    """The shipped profiles must never have this problem.

    Cheap fleet-wide guard: a typo in any shipped status_pattern would otherwise
    only surface when someone selected that specific device.
    """
    broken = []
    for name, profile in load_builtin_profiles().items():
        try:
            create_engine(profile)
        except Exception as err:
            broken.append((name, type(err).__name__, str(err)[:60]))
    assert not broken, f"profiles that cannot build an engine: {broken}"


async def test_bad_profile_fails_the_entry_readably(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Setup must report a readable error, not leak re.error.

    An uncompilable regex reaches create_engine, which previously sat outside the
    try in async_setup_entry -- so it escaped as a raw traceback with no
    indication which profile was at fault. ConfigEntryError is also the right
    kind: unlike ConfigEntryNotReady it does not retry forever on a fault that
    cannot resolve itself.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bad Custom",
        unique_id="ac_demo_bad",
        data={
            "port": "demo",
            "device_profile": "__custom__",
            "num_zones": 1,
            "num_sources": 1,
            "custom_profile": {
                "name": "Bad Regex",
                "zones": 1,
                "sources": 1,
                "serial": {"command_suffix": "\r"},
                "commands": {"status": "S"},
                # Unterminated group -- re.compile raises.
                "response": {"status_pattern": r"Z(?P<zone>\d{2}", "mapping": {}},
                "volume": {"min": 0, "max": 10},
            },
        },
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR, (
        f"expected SETUP_ERROR, got {entry.state}"
    )
    assert entry.error_reason_translation_key is None
    assert "Bad Regex" in (entry.reason or ""), (
        f"error should name the profile; got {entry.reason!r}"
    )


async def test_good_profile_still_loads(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """The guard must not reject valid profiles.

    Pairs with the test above so "raise on everything" cannot pass.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AMC X86 / X86i (Demo)",
        unique_id="ac_demo_good",
        data={
            "port": "demo",
            "device_profile": "AMC X86 / X86i",
            "num_zones": 6,
            "num_sources": 8,
        },
        version=3,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def test_custom_dir_path_follows_ha_convention() -> None:
    """The HA wrapper looks in {config_dir}/audio_control/, as documented."""
    from custom_components.audio_control.profile_loader import _custom_dir

    assert _custom_dir("/config") == "/config/audio_control"


def test_ha_wrapper_merges_builtin_and_custom(tmp_path: Path) -> None:
    """End-to-end through the HA-facing wrapper, not just the library."""
    from custom_components.audio_control.profile_loader import (
        get_profile_choices,
    )
    from custom_components.audio_control.profile_loader import (
        load_all_profiles as ha_load_all,
    )

    custom = tmp_path / "audio_control"
    custom.mkdir()
    write(custom, "mine.yaml", MINIMAL.format(name="Wrapper Amp", zones=2))

    profiles: dict[str, Any] = ha_load_all(str(tmp_path))
    assert "Wrapper Amp (Custom)" in profiles
    assert "AMC X86 / X86i" in profiles

    choices = get_profile_choices(str(tmp_path))
    assert choices == sorted(choices), "dropdown must be sorted"
    assert "Wrapper Amp (Custom)" in choices
