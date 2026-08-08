"""Every description_placeholders key a step passes must be rendered somewhere.

`async_step_user` computed `suggested_ports` (the list of discovered serial ports
plus `demo`) and passed it as a placeholder, but its description string never
interpolated it -- so the hint was dead on the very step where the user picks a
port, and `demo` was undiscoverable unless they read the docs.

An unrendered placeholder is silent: HA does not warn, the form renders fine, and
the only symptom is a missing hint nobody knows to expect. The reverse -- a
description referencing a placeholder that is NOT supplied -- is louder but still
only shows as a literal `{suggested_ports}` in the UI. Both directions are
checked here.

strings.json and translations/en.json must also agree; en.json is what HA
actually serves, so a fix applied to only one of them would not reach users.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

COMPONENT = Path("custom_components/audio_control")
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"

# Placeholders each step supplies, read off the async_show_form calls in
# config_flow.py. Kept explicit rather than parsed so that adding a placeholder
# without a matching string is caught here.
SUPPLIED: dict[str, set[str]] = {
    "user": {"suggested_ports", "error_detail"},
    "reconfigure": {"suggested_ports"},
}

# Supplied only on an error path, so the happy-path description need not use it.
ERROR_ONLY = {"error_detail"}


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def placeholders_in(text: str) -> set[str]:
    """Placeholder names referenced by a description string."""
    return set(re.findall(r"\{([a-z_]+)\}", text))


@pytest.mark.parametrize("path", [STRINGS, EN], ids=["strings.json", "en.json"])
@pytest.mark.parametrize("step", sorted(SUPPLIED))
def test_supplied_placeholders_are_rendered(path: Path, step: str) -> None:
    """A computed placeholder that no string uses is dead code with a cost.

    The work to gather it still happens -- _list_serial_ports() runs in the
    executor on every form render -- while the user sees nothing.
    """
    desc = load(path)["config"]["step"][step].get("description", "")
    used = placeholders_in(desc)
    expected = SUPPLIED[step] - ERROR_ONLY
    missing = expected - used
    assert not missing, f"{path.name} step '{step}' never renders: {sorted(missing)}"


@pytest.mark.parametrize("path", [STRINGS, EN], ids=["strings.json", "en.json"])
@pytest.mark.parametrize("step", sorted(SUPPLIED))
def test_referenced_placeholders_are_supplied(path: Path, step: str) -> None:
    """A description must not reference a placeholder the flow never passes.

    That renders as a literal "{foo}" in the UI.
    """
    desc = load(path)["config"]["step"][step].get("description", "")
    unknown = placeholders_in(desc) - SUPPLIED[step]
    assert not unknown, (
        f"{path.name} step '{step}' references unsupplied: {sorted(unknown)}"
    )


def test_strings_and_en_translation_agree() -> None:
    """en.json is what HA serves; strings.json is the source of truth.

    A divergence means a fix landed in one file only, so users still see the old
    text. Compared structurally rather than byte-wise to tolerate key ordering.
    """
    assert load(STRINGS) == load(EN), (
        "strings.json and translations/en.json have diverged"
    )


def test_demo_is_mentioned_where_the_port_is_chosen() -> None:
    """Demo mode exists but is only reachable by typing 'demo' into a text field.

    There is no checkbox or dropdown entry for it, so the description is the only
    place a user can learn it exists. Losing that mention would effectively
    remove the feature without touching any code.
    """
    for path in (STRINGS, EN):
        step = load(path)["config"]["step"]["user"]
        blob = f"{step.get('description', '')} {step.get('data', {}).get('port', '')}"
        assert "demo" in blob.lower(), f"{path.name} does not mention demo mode"


def test_every_error_key_used_by_the_flow_has_a_string() -> None:
    """A missing error string renders as the raw key in the UI.

    invalid_regex was added with its handler; this guards the next one.
    """
    flow_src = (COMPONENT / "config_flow.py").read_text()
    used = set(re.findall(r'"base"\]\s*=\s*"([a-z_]+)"', flow_src))
    used |= set(re.findall(r'errors\["[a-z_]+"\]\s*=\s*"([a-z_]+)"', flow_src))
    for path in (STRINGS, EN):
        defined = set(load(path)["config"].get("error", {}))
        missing = used - defined
        assert not missing, f"{path.name} missing error strings: {sorted(missing)}"
