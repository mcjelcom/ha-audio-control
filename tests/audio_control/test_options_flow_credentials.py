"""Options flow must preserve stored credentials across an unrelated edit.

`async_create_entry(data=...)` REPLACES the whole options dict -- it does not
merge. The password field is deliberately rendered with `default=""` (so the UI
never echoes a stored secret), which means a user who opens Options to rename a
zone submits a blank password. The old code only wrote the password key when the
field was non-empty, so the previously-saved credential was dropped from the new
options dict entirely.

The consequence is not cosmetic: `_apply_credential_override` then finds no
credential, the profile falls back to its shipped vendor default (RTI ships
admin/admin), the device rejects the login, and the entry goes unavailable.
Renaming a zone should not log you out of your amplifier.

Only the RTI AD-810-100 profile ships a `json.login` block, so it is the profile
under test here.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from rs232_protocol.profile_loader import load_all_profiles

from custom_components.audio_control import _apply_credential_override
from custom_components.audio_control.const import (
    CONF_LOGIN_PASSWORD,
    CONF_LOGIN_USERNAME,
    DOMAIN,
)

RTI_PROFILE_NAME = "RTI AD-810-100 / AD-46-100"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def make_entry(options: dict[str, Any]) -> MockConfigEntry:
    """An RTI entry with 2 zones/2 sources to keep the options form small."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="RTI (Demo)",
        unique_id="ac_demo_rti",
        data={
            "port": "demo",
            "device_profile": RTI_PROFILE_NAME,
            "num_zones": 2,
            "num_sources": 2,
        },
        options=options,
        version=3,
    )


async def rename_zone_one(
    hass: HomeAssistant, entry: MockConfigEntry, name: str = "Living Room"
) -> Any:
    """Submit the options form the way the UI does: blank credential fields.

    vol.Optional with default="" means an untouched password field arrives as ""
    -- indistinguishable from a user clearing it. That ambiguity is the bug.
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "zone_1": name,
            "zone_2": "Kitchen",
            "source_1": "Source 1",
            "source_2": "Source 2",
            CONF_LOGIN_USERNAME: "",
            CONF_LOGIN_PASSWORD: "",
        },
    )


async def test_rename_preserves_saved_credentials(hass: HomeAssistant) -> None:
    """The core regression: a rename must not drop the stored login."""
    entry = make_entry(
        {
            "source_names": {1: "Source 1", 2: "Source 2"},
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "s3cret",
        }
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await rename_zone_one(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert entry.options["zone_names"][1] == "Living Room"
    assert entry.options.get(CONF_LOGIN_USERNAME) == "installer"
    assert entry.options.get(CONF_LOGIN_PASSWORD) == "s3cret"


async def test_credentials_survive_into_the_engine(hass: HomeAssistant) -> None:
    """End-to-end: after a rename the profile still carries the real password.

    Asserting on entry.options alone would not prove the user-visible symptom
    was fixed; this checks the value that actually reaches the device login.
    """
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            "source_names": {1: "Source 1", 2: "Source 2"},
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "s3cret",
        }
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await rename_zone_one(hass, entry)

    profiles = await hass.async_add_executor_job(
        load_all_profiles, hass.config.config_dir
    )
    merged = _apply_credential_override(profiles[RTI_PROFILE_NAME], entry)
    login = merged["json"]["login"]
    assert login["password"] == "s3cret", "fell back to the vendor default"
    assert login["username"] == "installer"


async def test_new_credentials_still_override(hass: HomeAssistant) -> None:
    """Supplying a new password must replace the old one, not be ignored.

    Pairs with the test above so the fix cannot be "always keep the old value".
    """
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            "source_names": {1: "Source 1", 2: "Source 2"},
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "old-pass",
        }
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "zone_1": "Zone 1",
            "zone_2": "Zone 2",
            "source_1": "Source 1",
            "source_2": "Source 2",
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "new-pass",
        },
    )
    assert entry.options[CONF_LOGIN_PASSWORD] == "new-pass"


async def test_no_credentials_stays_absent(hass: HomeAssistant) -> None:
    """An entry that never had credentials must not gain empty-string ones.

    An empty password written into options would be a real override, and
    _apply_credential_override would send "" instead of the vendor default.
    """
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            "source_names": {1: "Source 1", 2: "Source 2"},
        }
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await rename_zone_one(hass, entry)

    assert CONF_LOGIN_PASSWORD not in entry.options
    assert CONF_LOGIN_USERNAME not in entry.options


async def test_unrelated_options_keys_are_preserved(hass: HomeAssistant) -> None:
    """Any future option key must survive a rename too.

    The bug was not really about passwords -- it was that the flow rebuilt the
    options dict from scratch. Seeding from the existing options fixes the whole
    class, so this pins the general behaviour rather than the one symptom.
    """
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            "source_names": {1: "Source 1", 2: "Source 2"},
            "some_future_setting": 42,
        }
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await rename_zone_one(hass, entry)

    assert entry.options.get("some_future_setting") == 42
