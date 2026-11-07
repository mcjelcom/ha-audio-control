"""Every Material Design icon we reference must exist in Home Assistant's frontend.

`mdi:speaker-group` is not an MDI icon. HA renders an unknown icon as nothing,
with no warning, so the dashboard's Group button and the group-mode action
showed a blank space since they were added (found while screenshotting the
balena template's dashboard, 2026-11-07).

The dev environment has no copy of HA's frontend, so KNOWN_ICONS lists the
icons we use that were checked against the icon index of the frontend shipped
with HA 2026.10.2 (7449 icons). The balena template's CI repeats the check
against the real frontend inside its image. Adding an icon: check it exists at
https://pictogrammers.com/library/mdi/ and add it here.
"""

from __future__ import annotations

import re
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "audio_control"
KNOWN_ICONS = {
    "music-clef-bass",
    "music-clef-treble",
    "power-off",
    "speaker",
    "speaker-multiple",
}
SOURCES = sorted(
    p
    for pattern in ("*.py", "*.json", "*.yaml")
    for p in COMPONENT.rglob(pattern)
    if "__pycache__" not in p.parts
)


def used_icons() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in SOURCES:
        for name in re.findall(r"mdi:([a-z0-9-]+)", path.read_text(encoding="utf-8")):
            found.setdefault(name, set()).add(path.name)
    return found


def test_every_icon_exists() -> None:
    used = used_icons()
    assert used, "no icons found -- did the paths move?"
    unknown = {n: sorted(f) for n, f in used.items() if n not in KNOWN_ICONS}
    assert not unknown, f"unverified/unknown MDI icons: {unknown}"


def test_speaker_group_is_gone() -> None:
    """The specific icon that rendered blank."""
    assert "speaker-group" not in used_icons()
