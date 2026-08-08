"""Write the Audio Control dashboard from the live entity registry.

Why this lives in the integration rather than a boot script:

`generate_dashboard.py` in the deployment layer reads `.storage/`, which HA
flushes on a timer (`SAVE_DELAY` 10s while running, `SAVE_DELAY_LONG` 180s
during startup). A boot script therefore reads a stale snapshot from the
*previous* session and cannot see zones added since. Reading the in-memory
registry here removes that race entirely -- the entities exist by the time this
runs, so the file is correct on first write.

Scope guard: this only ever writes `dashboards/audio_control.yaml`, only when
that file already exists (i.e. the deployment provisioned it) and still carries
our generated/starter header. It never creates a dashboard on an install that
did not ask for one, which keeps HACS installs untouched by default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er

from .const import CONF_ZONE_NAMES, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DASHBOARD_RELPATH = "dashboards/audio_control.yaml"

# Written into every file we generate. Its presence is how we know a file is
# ours to overwrite -- a user who takes ownership just deletes this line.
MANAGED_MARKER = "# audio_control:managed"

_HEADER = f"""{MANAGED_MARKER}
# Generated from the live entity registry. Rewritten whenever the integration
# reloads, so edits here are lost -- remove the line above to take ownership,
# or copy this into a dashboard of your own.
"""

# Zone number is the trailing integer of the unique_id: ac_{entry_id}_zone_{n}
_ZONE_SUFFIX = "_zone_"


def _zone_number(unique_id: str) -> int | None:
    """Extract the trailing zone number from a unique_id."""
    _, sep, tail = unique_id.rpartition(_ZONE_SUFFIX)
    if not sep or not tail.isdigit():
        return None
    return int(tail)


def _collect_zones(hass: HomeAssistant, entry_id: str) -> list[tuple[int, str]]:
    """Return sorted [(zone_number, entity_id)] from the live registry."""
    registry = er.async_get(hass)
    zones: list[tuple[int, str]] = []

    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.domain != Platform.MEDIA_PLAYER:
            continue
        if entity.disabled_by is not None:
            continue
        zone = _zone_number(entity.unique_id)
        if zone is not None:
            zones.append((zone, entity.entity_id))

    return sorted(zones)


def _zone_label(entry: ConfigEntry, zone: int) -> str:
    """Human label for a zone, honouring names set in integration options."""
    names = entry.options.get(CONF_ZONE_NAMES) or {}
    label = names.get(str(zone)) or names.get(zone)
    return str(label) if label else f"Zone {zone}"


def _entry_features(entry: ConfigEntry) -> dict[str, bool]:
    """Profile feature flags for this entry, or {} if the engine is unavailable.

    Written defensively because the dashboard is best-effort: async_write_dashboard
    promises never to raise, so an entry without a live manager must degrade
    rather than break setup.
    """
    engine = getattr(getattr(entry, "runtime_data", None), "engine", None)
    features = getattr(engine, "features", None)
    return features if isinstance(features, dict) else {}


def _global_buttons(entry: ConfigEntry) -> list[dict[str, Any]]:
    """All Off / Group buttons, for the features this device actually has.

    Previously gated on zone count alone, so a multi-zone device whose profile
    lacks the feature still got a button -- and pressing it raised "This device
    does not support ...". Six of the 13 bundled multi-zone profiles have no
    group mode, and the Monoprice 6-Zone has neither. An unavailable engine
    falls back to showing both, preserving the old behaviour.
    """
    features = _entry_features(entry)
    unknown = not features
    buttons: list[dict[str, Any]] = []

    if unknown or features.get("has_all_off"):
        buttons.append(
            {
                "type": "button",
                "name": "All Off",
                "icon": "mdi:power-off",
                "icon_height": "40px",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": f"{DOMAIN}.all_zones_off",
                },
            }
        )

    if unknown or features.get("has_group_mode"):
        buttons.append(
            {
                "type": "button",
                "name": "Group",
                "icon": "mdi:speaker-group",
                "icon_height": "40px",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": f"{DOMAIN}.group_mode_on",
                    "data": {"source": 1},
                },
                "hold_action": {
                    "action": "perform-action",
                    "perform_action": f"{DOMAIN}.group_mode_off",
                },
            }
        )

    return buttons


def build_config(entry: ConfigEntry, zones: list[tuple[int, str]]) -> dict[str, Any]:
    """Build the Lovelace config for the given zones."""
    cards: list[dict[str, Any]] = []
    if len(zones) > 1:
        # Omit the row entirely when no global feature applies: an empty
        # horizontal-stack renders as a blank card, which reads as a rendering
        # fault rather than an absent control.
        buttons = _global_buttons(entry)
        if buttons:
            cards.append({"type": "horizontal-stack", "cards": buttons})

    cards.extend(
        {
            "type": "media-control",
            "entity": entity_id,
            "name": _zone_label(entry, zone),
        }
        for zone, entity_id in zones
    )

    return {
        "title": "Audio Control",
        "views": [
            {
                "title": "Zones",
                "path": "zones",
                "icon": "mdi:speaker-multiple",
                # Always masonry: the `sections` view type takes a `sections:`
                # key rather than `cards:`, and HA does not validate YAML
                # dashboards server-side, so a mismatch fails silently in the
                # browser with nothing in the log.
                "type": "masonry",
                "cards": cards,
            }
        ],
    }


def _write(path: Path, body: str) -> None:
    """Write the dashboard file (blocking; call from the executor)."""
    path.write_text(_HEADER + body, encoding="utf-8")


def _should_write(path: Path) -> bool:
    """Whether we may overwrite this file.

    Only if it exists and is still marked as managed. A missing file means the
    deployment never provisioned a dashboard (e.g. a plain HACS install), and a
    missing marker means the user has taken ownership.
    """
    if not path.exists():
        return False
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return False
    return MANAGED_MARKER in head


async def async_write_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Regenerate the dashboard file if we own it.

    Never raises: a dashboard is a convenience, and failing to write one must
    not prevent the integration from setting up.
    """
    path = Path(hass.config.path(DASHBOARD_RELPATH))

    if not await hass.async_add_executor_job(_should_write, path):
        _LOGGER.debug(
            "Not writing %s: absent or no longer marked managed", DASHBOARD_RELPATH
        )
        return

    zones = _collect_zones(hass, entry.entry_id)
    if not zones:
        _LOGGER.debug("No zone entities registered yet; leaving dashboard as-is")
        return

    body = yaml.safe_dump(
        build_config(entry, zones), sort_keys=False, allow_unicode=True
    )

    try:
        await hass.async_add_executor_job(_write, path, body)
    except OSError as err:
        _LOGGER.warning("Could not write %s: %s", DASHBOARD_RELPATH, err)
        return

    _LOGGER.info("Wrote %s with %d zone card(s)", DASHBOARD_RELPATH, len(zones))
