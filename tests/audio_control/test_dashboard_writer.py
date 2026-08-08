"""Tests for the in-integration dashboard writer.

This exists because the boot-time generator reads `.storage`, which HA flushes
on a timer (10s running / 180s at startup) -- so it races. These tests cover the
two things that matter: it reads the live registry, and it refuses to touch a
file the user has taken ownership of.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from homeassistant.helpers import entity_registry as er

from custom_components.audio_control import dashboard_writer as dw
from custom_components.audio_control.const import CONF_ZONE_NAMES

ENTRY_ID = "01ABCDEF"


def make_entry(
    zone_names: dict[str, str] | None = None,
    *,
    features: dict[str, bool] | None = None,
) -> MagicMock:
    """A config-entry double.

    `features` must be a real dict, not left to MagicMock: an auto-created
    attribute is truthy, so `features.get("has_group_mode")` would return a Mock
    and every feature would appear supported. Defaults to both global features
    on, matching the AMC profiles most of these tests describe.
    """
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.options = {CONF_ZONE_NAMES: zone_names or {}}
    entry.runtime_data.engine.features = (
        {"has_all_off": True, "has_group_mode": True} if features is None else features
    )
    return entry


def make_registry_entry(
    zone: int,
    *,
    slug: str = "amc_x86_x86i",
    domain: str = "media_player",
    disabled: bool = False,
) -> MagicMock:
    ent = MagicMock()
    ent.entity_id = f"{domain}.{slug}_zone_{zone}"
    ent.domain = domain
    ent.unique_id = f"ac_{ENTRY_ID}_zone_{zone}"
    ent.disabled_by = "user" if disabled else None
    return ent


@pytest.fixture
def dashboard(tmp_path: Path) -> Path:
    """A managed dashboard file in a fake config dir."""
    path = tmp_path / "dashboards" / "audio_control.yaml"
    path.parent.mkdir()
    path.write_text(f"{dw.MANAGED_MARKER}\ntitle: Starter\n", encoding="utf-8")
    return path


@pytest.fixture
def hass_stub(tmp_path: Path) -> MagicMock:
    """Minimal hass double: real path() plus an executor that runs inline."""
    hass = MagicMock()
    hass.config.path.side_effect = lambda rel: str(tmp_path / rel)

    async def run(func: Any, *args: Any) -> Any:
        return func(*args)

    hass.async_add_executor_job.side_effect = run
    return hass


def read(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return result


def media_cards(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in cfg["views"][0]["cards"] if c.get("type") == "media-control"]


# ─── _zone_number ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"ac_{ENTRY_ID}_zone_1", 1),
        (f"ac_{ENTRY_ID}_zone_16", 16),
        ("ac_x_connection", None),
        ("ac_x_zone_abc", None),
        ("", None),
    ],
)
def test_zone_number(unique_id: str, expected: int | None) -> None:
    assert dw._zone_number(unique_id) == expected


# ─── build_config ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [1, 4, 6, 8, 10, 16])
def test_card_count_matches_zones(count: int) -> None:
    """One card per zone -- the static file hardcoded 6 and was wrong for 17
    of 25 bundled profiles."""
    zones = [(n, f"media_player.z{n}") for n in range(1, count + 1)]
    cfg = dw.build_config(make_entry(), zones)
    assert len(media_cards(cfg)) == count


def test_single_zone_omits_global_buttons() -> None:
    cfg = dw.build_config(make_entry(), [(1, "media_player.z1")])
    assert not any(
        c.get("type") == "horizontal-stack" for c in cfg["views"][0]["cards"]
    )


def test_multi_zone_includes_global_buttons() -> None:
    zones = [(n, f"media_player.z{n}") for n in (1, 2)]
    cards = dw.build_config(make_entry(), zones)["views"][0]["cards"]
    stacks = [c for c in cards if c.get("type") == "horizontal-stack"]
    assert len(stacks) == 1
    assert [b["tap_action"]["perform_action"] for b in stacks[0]["cards"]] == [
        "audio_control.all_zones_off",
        "audio_control.group_mode_on",
    ]


# ─── Global buttons must follow the profile's features ───────────────────────
#
# The buttons were gated on zone count alone, so a multi-zone device without the
# feature got a button that called a service raising "This device does not
# support ...". Six of the 13 bundled multi-zone profiles lack has_group_mode
# (Xantech MRC-88/MX88/ZPR68-10, SpeakerCraft MZC, Monoprice 31028) and the
# Monoprice 6-Zone lacks both.


def stack_actions(cfg: dict[str, Any]) -> list[str]:
    """Service names of the global buttons, or [] if the stack is absent."""
    for card in cfg["views"][0]["cards"]:
        if card.get("type") == "horizontal-stack":
            return [b["tap_action"]["perform_action"] for b in card["cards"]]
    return []


TWO_ZONES = [(1, "media_player.z1"), (2, "media_player.z2")]


def test_no_group_button_without_group_mode() -> None:
    """Xantech MX88 and friends: all-off yes, group no."""
    entry = make_entry(features={"has_all_off": True, "has_group_mode": False})
    assert stack_actions(dw.build_config(entry, TWO_ZONES)) == [
        "audio_control.all_zones_off"
    ]


def test_no_all_off_button_without_all_off() -> None:
    """The mirror case, so the gate cannot be hardcoded to one feature."""
    entry = make_entry(features={"has_all_off": False, "has_group_mode": True})
    assert stack_actions(dw.build_config(entry, TWO_ZONES)) == [
        "audio_control.group_mode_on"
    ]


def test_no_stack_at_all_without_either_feature() -> None:
    """Monoprice 6-Zone has neither, so an empty button row must be omitted.

    An empty horizontal-stack renders as a blank card, which looks like a
    rendering fault rather than an intentionally absent control.
    """
    entry = make_entry(features={"has_all_off": False, "has_group_mode": False})
    cfg = dw.build_config(entry, TWO_ZONES)
    assert stack_actions(cfg) == []
    assert not any(
        c.get("type") == "horizontal-stack" for c in cfg["views"][0]["cards"]
    )
    # The zone cards themselves must still be there.
    assert len(media_cards(cfg)) == 2


def test_missing_runtime_data_falls_back_to_showing_buttons() -> None:
    """A missing engine must not crash the writer or lose the zone cards.

    async_write_dashboard is explicitly best-effort ("never raises"), so an
    entry whose runtime_data is not a manager should degrade to the old
    behaviour rather than produce a broken file.
    """
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.options = {CONF_ZONE_NAMES: {}}
    entry.runtime_data = None
    cfg = dw.build_config(entry, TWO_ZONES)
    assert len(media_cards(cfg)) == 2


def test_zone_names_from_options() -> None:
    zones = [(1, "media_player.z1"), (2, "media_player.z2")]
    cfg = dw.build_config(make_entry({"1": "Kitchen"}), zones)
    assert [c["name"] for c in media_cards(cfg)] == ["Kitchen", "Zone 2"]


def test_view_type_is_always_masonry() -> None:
    """`sections` needs a `sections:` key; HA does not validate YAML dashboards
    server-side, so a mismatch fails silently in the browser."""
    zones = [(n, f"media_player.z{n}") for n in range(1, 17)]
    view = dw.build_config(make_entry(), zones)["views"][0]
    assert view["type"] == "masonry"
    assert "cards" in view


# ─── _collect_zones reads the live registry ──────────────────────────────────


def test_collect_zones_sorted_and_filtered(hass_stub: MagicMock) -> None:
    entries = [
        make_registry_entry(10),
        make_registry_entry(2),
        make_registry_entry(1),
        make_registry_entry(3, domain="binary_sensor"),  # wrong platform
        make_registry_entry(4, disabled=True),  # disabled
    ]
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=entries),
    ):
        zones = dw._collect_zones(hass_stub, ENTRY_ID)

    assert [z for z, _ in zones] == [1, 2, 10]


# ─── Ownership guard ─────────────────────────────────────────────────────────


def test_should_write_requires_marker(tmp_path: Path) -> None:
    managed = tmp_path / "a.yaml"
    managed.write_text(f"{dw.MANAGED_MARKER}\ntitle: x\n")
    owned = tmp_path / "b.yaml"
    owned.write_text("title: mine\n")

    assert dw._should_write(managed) is True
    assert dw._should_write(owned) is False
    assert dw._should_write(tmp_path / "missing.yaml") is False


async def test_writes_when_managed(hass_stub: MagicMock, dashboard: Path) -> None:
    entries = [make_registry_entry(n) for n in (1, 2)]
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=entries),
    ):
        await dw.async_write_dashboard(hass_stub, make_entry())

    cfg = read(dashboard)
    assert len(media_cards(cfg)) == 2
    assert dashboard.read_text().startswith(dw.MANAGED_MARKER)


async def test_does_not_write_when_user_owned(
    hass_stub: MagicMock, dashboard: Path
) -> None:
    """Removing the marker is how a user opts out; it must be honoured."""
    dashboard.write_text("title: My Own Dashboard\n", encoding="utf-8")
    entries = [make_registry_entry(1)]
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=entries),
    ):
        await dw.async_write_dashboard(hass_stub, make_entry())

    assert dashboard.read_text() == "title: My Own Dashboard\n"


async def test_does_not_create_missing_file(
    hass_stub: MagicMock, tmp_path: Path
) -> None:
    """A plain HACS install never provisioned a dashboard -- do not invent one."""
    (tmp_path / "dashboards").mkdir()
    target = tmp_path / "dashboards" / "audio_control.yaml"
    entries = [make_registry_entry(1)]
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=entries),
    ):
        await dw.async_write_dashboard(hass_stub, make_entry())

    assert not target.exists()


async def test_no_zones_leaves_file_untouched(
    hass_stub: MagicMock, dashboard: Path
) -> None:
    before = dashboard.read_text()
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=[]),
    ):
        await dw.async_write_dashboard(hass_stub, make_entry())

    assert dashboard.read_text() == before


async def test_write_failure_is_swallowed(
    hass_stub: MagicMock, dashboard: Path
) -> None:
    """Setup must not fail because a convenience file could not be written."""
    entries = [make_registry_entry(1), make_registry_entry(2)]
    with (
        patch.object(er, "async_get"),
        patch.object(er, "async_entries_for_config_entry", return_value=entries),
        patch.object(dw, "_write", side_effect=OSError("read-only fs")),
    ):
        await dw.async_write_dashboard(hass_stub, make_entry())  # must not raise
