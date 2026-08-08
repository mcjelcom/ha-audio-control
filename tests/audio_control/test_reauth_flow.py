"""Authentication failure must prompt for credentials, not retry forever.

Two defects made bad credentials unrecoverable:

1. `_async_login` RETURNED on a login timeout instead of raising. A silent device
   -- the common case for a wrong port, or a non-RTI device on an RTI profile --
   left `engine.logged_in` False while `connect()` carried straight on to the
   status probes, so every subsequent command went to an unauthenticated session
   and failed opaquely.

2. `AuthenticationError` had no consumer. It propagated into async_setup_entry's
   broad `except Exception` and became ConfigEntryNotReady, so HA retried the
   same wrong password with backoff indefinitely -- exactly what the exception
   was introduced to prevent. There was no reauth step at all
   (quality_scale.yaml listed reauthentication-flow as unmet).

Only the JSON engine authenticates; RTI AD-810-100 is the shipped profile that
does, and it ships the vendor default admin/admin.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audio_control.const import (
    CONF_LOGIN_PASSWORD,
    CONF_LOGIN_USERNAME,
    DOMAIN,
)
from custom_components.audio_control.rs232_protocol import AuthenticationError

RTI_PROFILE = "RTI AD-810-100 / AD-46-100"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def make_entry(options: dict[str, Any] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="RTI (Demo)",
        unique_id="ac_demo_rti",
        data={
            "port": "demo",
            "device_profile": RTI_PROFILE,
            "num_zones": 2,
            "num_sources": 2,
        },
        options=options
        or {
            "zone_names": {1: "Zone 1", 2: "Zone 2"},
            "source_names": {1: "Source 1", 2: "Source 2"},
        },
        version=3,
    )


# ─── The library now raises rather than continuing unauthenticated ───────────


async def test_login_timeout_raises() -> None:
    """A device that never answers the login must not be treated as authenticated.

    Reproduces the original defect directly: with no reply, _async_login used to
    return normally and connect() went on to probe zones over an unauthenticated
    session.
    """
    from custom_components.audio_control.rs232_protocol import create_engine
    from custom_components.audio_control.rs232_protocol.connection import (
        AsyncSerialConnection,
    )
    from custom_components.audio_control.rs232_protocol.profile_loader import (
        load_builtin_profiles,
    )

    profile = load_builtin_profiles()[RTI_PROFILE]
    engine = create_engine(profile)
    conn = AsyncSerialConnection(port="x", engine=engine, demo_mode=False)

    class Writer:
        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            return None

    conn._writer = Writer()  # type: ignore[assignment]
    # Nothing is ever enqueued, so the login wait times out.
    with pytest.raises(AuthenticationError):
        await conn._async_login()


async def test_login_timeout_leaves_engine_unauthenticated() -> None:
    """The engine must not claim to be logged in after a timeout."""
    from custom_components.audio_control.rs232_protocol import create_engine
    from custom_components.audio_control.rs232_protocol.connection import (
        AsyncSerialConnection,
    )
    from custom_components.audio_control.rs232_protocol.profile_loader import (
        load_builtin_profiles,
    )

    engine = create_engine(load_builtin_profiles()[RTI_PROFILE])
    conn = AsyncSerialConnection(port="x", engine=engine, demo_mode=False)

    class Writer:
        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            return None

    conn._writer = Writer()  # type: ignore[assignment]
    with pytest.raises(AuthenticationError):
        await conn._async_login()
    assert engine.logged_in is False


# ─── Setup converts it to a reauth prompt, not an endless retry ──────────────


async def test_auth_failure_starts_reauth(hass: HomeAssistant) -> None:
    """The core regression: bad credentials must PROMPT, not retry blindly.

    Note ConfigEntryAuthFailed still yields SETUP_RETRY -- config_entries.py calls
    async_start_reauth() and sets that state -- so the state alone does not
    distinguish this from a transport failure. What distinguishes it is the reauth
    flow, which is the thing that was missing entirely: previously
    AuthenticationError fell into the broad `except Exception`, became
    ConfigEntryNotReady, and HA retried the same wrong password forever with no
    prompt.
    """
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.audio_control.SerialManager.async_connect",
        new=AsyncMock(side_effect=AuthenticationError("Authentication rejected")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # async_start_reauth defers the flow via hass.async_create_task, so it only
    # appears after another loop pass.
    await hass.async_block_till_done()

    # The flow being started is the whole point -- this did not exist before, so
    # a wrong password left the user with nothing to act on. The entry's own state
    # is deliberately NOT asserted here: HA sets SETUP_RETRY for
    # ConfigEntryAuthFailed, but the reauth flow immediately retries setup, which
    # fails again against the still-active mock and lands on SETUP_ERROR. Either
    # is consistent with correct behaviour, so asserting one would be brittle.
    flows = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"].get("source") == SOURCE_REAUTH
    ]
    assert flows, "no reauth flow was started"
    assert flows[0]["step_id"] == "reauth_confirm"
    # The reason must carry OUR message, proving the AuthenticationError branch
    # ran rather than the generic "Could not connect to ..." fallback.
    assert "rejected" in (entry.reason or "").lower(), (
        f"generic transport error instead of the auth message: {entry.reason!r}"
    )


async def test_transport_failure_still_retries(hass: HomeAssistant) -> None:
    """A network blip must remain a retry, not a credential prompt.

    Pairs with the test above so the fix cannot be "treat every failure as auth".
    """
    entry = make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.audio_control.SerialManager.async_connect",
        new=AsyncMock(side_effect=OSError("connection refused")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"].get("source") == SOURCE_REAUTH
    ], "a transport error should not prompt for credentials"


# ─── The reauth form ─────────────────────────────────────────────────────────


async def start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    return result


async def test_reauth_stores_new_credentials(hass: HomeAssistant) -> None:
    """Submitting credentials must persist them and reload the entry."""
    entry = make_entry()
    entry.add_to_hass(hass)

    result = await start_reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "s3cret",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.options[CONF_LOGIN_USERNAME] == "installer"
    assert entry.options[CONF_LOGIN_PASSWORD] == "s3cret"


async def test_reauth_preserves_unrelated_options(hass: HomeAssistant) -> None:
    """Zone and source names live in options too and must survive.

    async_update_entry replaces options wholesale -- the same trap that made the
    options flow drop the saved password earlier in this project.
    """
    entry = make_entry(
        {
            "zone_names": {1: "Living Room", 2: "Kitchen"},
            "source_names": {1: "Turntable", 2: "TV"},
        }
    )
    entry.add_to_hass(hass)

    result = await start_reauth(hass, entry)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LOGIN_USERNAME: "installer", CONF_LOGIN_PASSWORD: "pw"},
    )
    await hass.async_block_till_done()
    assert entry.options["zone_names"][1] == "Living Room"
    assert entry.options["source_names"][1] == "Turntable"


async def test_reauth_rejects_a_wholly_blank_submission(hass: HomeAssistant) -> None:
    """Submitting both fields blank would retry what just failed.

    Without this the user is looped straight back to the same prompt with no
    explanation.
    """
    entry = make_entry()
    entry.add_to_hass(hass)

    result = await start_reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_LOGIN_USERNAME: "", CONF_LOGIN_PASSWORD: ""}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "credentials_required"}


async def test_reauth_allows_changing_only_the_password(
    hass: HomeAssistant,
) -> None:
    """A username that has not changed should not need retyping."""
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1"},
            "source_names": {1: "Source 1"},
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "old",
        }
    )
    entry.add_to_hass(hass)

    result = await start_reauth(hass, entry)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_LOGIN_PASSWORD: "new"}
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_LOGIN_PASSWORD] == "new"
    assert entry.options[CONF_LOGIN_USERNAME] == "installer"


async def test_reauth_form_does_not_echo_the_stored_password(
    hass: HomeAssistant,
) -> None:
    """The password field must not be pre-filled with the secret."""
    entry = make_entry(
        {
            "zone_names": {1: "Zone 1"},
            "source_names": {1: "Source 1"},
            CONF_LOGIN_USERNAME: "installer",
            CONF_LOGIN_PASSWORD: "s3cret",
        }
    )
    entry.add_to_hass(hass)

    result = await start_reauth(hass, entry)
    defaults = result["data_schema"]({})
    assert defaults.get(CONF_LOGIN_PASSWORD) in (None, "")
    # The username IS safe to pre-fill, and saves retyping.
    assert defaults.get(CONF_LOGIN_USERNAME) == "installer"
