"""AMC XIA100e/XIA150e — a profile with no power, mute, or absolute volume.

Source: AMC "XIA100e/XIA150e RS-232 Protocol" appendix (XIA100e-150e MANUAL.pdf,
PN 21R-XIA150e-1). The appendix lists exactly six commands: *SRCbb, *VOLUP,
*VOLDN, *MODEL, *BRAND, *VERSION. There is no *POWER, no *MUTE, and no absolute
volume command anywhere in the manual -- I grepped the whole extracted text, and
"MUTE OFF" occurs only inside RETURN strings, i.e. as status.

That makes the XIA the first shipped profile without power commands, and it
exposed a latent gap: media_player advertised TURN_ON | TURN_OFF
unconditionally. All 23 previous profiles happened to define both, so the bug
could not fire -- the XIA would have rendered power buttons that call a
non-existent command, where send_command returns False and only logs a warning.
Same silent-failure class as the dead VOLUME_STEP buttons on the Xantech MRC-88.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from rs232_protocol import create_engine
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR, load_builtin_profiles

from custom_components.audio_control.const import DOMAIN

PROFILE_NAME = "AMC XIA100e / XIA150e"
F = MediaPlayerEntityFeature


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load the integration from custom_components/."""


def profile() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (BUILTIN_PROFILES_DIR / "amc_xia100e.yaml").read_text()
    )
    return data


def engine() -> Any:
    return create_engine(profile())


# ─── Wire format matches the manual verbatim ─────────────────────────────────


def test_commands_match_the_manual_byte_for_byte() -> None:
    """Every command the appendix documents, formatted exactly as printed."""
    e = engine()
    assert e.format_command("source_set", source=3) == "*SRC03\r"
    assert e.format_command("volume_up") == "*VOLUP\r"
    assert e.format_command("volume_down") == "*VOLDN\r"
    # No status command exists; *MODEL is the documented harmless probe.
    assert e.format_command("status") == "*MODEL\r"


def test_serial_params_match_the_manual() -> None:
    """ "Baud Rate : 38400, Data : 8 bit, Parity : none, Stop : 1 bit"."""
    e = engine()
    assert e.baud_rate == 38400
    assert e.data_bits == 8
    assert e.parity == "N"
    assert e.stop_bits == 1


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # The three RETURN forms printed in the appendix.
        ("ON,SRC04,MUTE OFF", {"power": True, "mute": False, "source": 4}),
        ("ON,SRC01,MUTE OFF,VOLUP", {"power": True, "mute": False, "source": 1}),
        ("ON,SRC06,MUTE ON", {"power": True, "mute": True, "source": 6}),
    ],
)
def test_manual_return_strings_parse(reply: str, expected: dict[str, Any]) -> None:
    """The trailing ,VOLUP form must parse too -- it is what a step command returns."""
    parsed = engine().parse_response(reply)
    assert parsed is not None
    for key, value in expected.items():
        assert parsed[key] == value, f"{key}: {parsed.get(key)} != {value}"


def test_all_six_documented_inputs_are_named() -> None:
    """bb = 01~06: AUX, VIDEO, TUNER, CD, iPAD, OPTION/PHONO."""
    e = engine()
    assert e.num_sources == 6
    names = profile()["sources"]["names"]
    assert [names[i] for i in range(1, 7)] == [
        "Aux",
        "Video",
        "Tuner",
        "CD",
        "iPad",
        "Option",
    ]


# ─── The absent commands are absent on purpose ───────────────────────────────


@pytest.mark.parametrize(
    "command",
    ["power_on", "power_off", "power_toggle", "mute_on", "mute_off", "volume_set"],
)
def test_undocumented_commands_are_not_declared(command: str) -> None:
    """Declaring these would create controls that fail silently.

    None appear in the appendix. Inventing them is exactly why
    russound_cav66.yaml was deleted earlier.
    """
    assert not engine().has_command(command), f"{command} is not in the manual"


def test_volume_span_is_zero_because_there_is_no_level() -> None:
    """No absolute command and no reported level, so a slider has nothing to show."""
    e = engine()
    assert e.volume_max - e.volume_min == 0


# ─── Entity surface: only controls the device really has ─────────────────────


async def setup_xia(hass: HomeAssistant) -> Any:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_profile": PROFILE_NAME, CONF_PORT: "demo"},
    )
    await hass.async_block_till_done()
    assert result["type"].value == "create_entry", result
    assert result["result"].state is ConfigEntryState.LOADED
    return result["result"]


def features_of(hass: HomeAssistant, entry_id: str) -> MediaPlayerEntityFeature:
    registry = er.async_get(hass)
    ent = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry_id)
        if e.domain == "media_player"
    )
    state = hass.states.get(ent.entity_id)
    assert state is not None
    return MediaPlayerEntityFeature(state.attributes["supported_features"])


async def test_no_power_buttons_without_power_commands(hass: HomeAssistant) -> None:
    """The regression: TURN_ON/TURN_OFF were advertised unconditionally.

    All 23 earlier profiles define both power commands, so this never fired
    before. The XIA is powered from the front panel, so the buttons would call a
    command that does not exist -- send_command returns False, logs a warning,
    and the UI shows nothing wrong.
    """
    entry = await setup_xia(hass)
    features = features_of(hass, entry.entry_id)
    assert not features & F.TURN_ON, "power button offered but no power_on command"
    assert not features & F.TURN_OFF, "power button offered but no power_off command"


async def test_step_and_source_are_offered(hass: HomeAssistant) -> None:
    """The controls the XIA does have must still appear.

    Guards against over-correcting into "advertise nothing".
    """
    entry = await setup_xia(hass)
    features = features_of(hass, entry.entry_id)
    assert features & F.VOLUME_STEP, "volume_up/volume_down exist"
    assert features & F.SELECT_SOURCE, "6 inputs exist"


async def test_slider_and_mute_are_not_offered(hass: HomeAssistant) -> None:
    """No absolute volume and no mute command, so neither control belongs."""
    entry = await setup_xia(hass)
    features = features_of(hass, entry.entry_id)
    assert not features & F.VOLUME_SET
    assert not features & F.VOLUME_MUTE


async def test_source_names_reach_the_dropdown(hass: HomeAssistant) -> None:
    """The mapping-form `sources` must seed real names, not "Source N".

    This is the profile shape that used to crash the config flow entirely.
    """
    entry = await setup_xia(hass)
    registry = er.async_get(hass)
    ent = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player"
    )
    state = hass.states.get(ent.entity_id)
    assert state is not None
    assert state.attributes["source_list"] == [
        "Aux",
        "Video",
        "Tuner",
        "CD",
        "iPad",
        "Option",
    ]


# ─── The 4-input sibling (XIA / 306D) ────────────────────────────────────────
#
# The appendix documents one protocol serving two input counts and prints both
# maps verbatim:
#   6 Input ; bb = 01~06 ; 01=AUX,02=VIDEO,03=TUNER,04=CD,05=iPAD,06=OPTION/...
#   4 Input ; bb = 01~04 ; 01=AUX,02=TUNER,03=CD,04=OPTION/...
# Identify which you have with *MODEL: "#306D" vs "#XIA100e/XIA150e".

FOUR_INPUT_NAME = "AMC XIA / 306D (4-input)"


def four_input_profile() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (BUILTIN_PROFILES_DIR / "amc_xia_4input.yaml").read_text()
    )
    return data


def test_four_input_map_matches_the_manual() -> None:
    """01=AUX, 02=TUNER, 03=CD, 04=OPTION -- VIDEO and iPAD absent."""
    p = four_input_profile()
    e = create_engine(p)
    assert e.num_sources == 4
    names = p["sources"]["names"]
    assert [names[i] for i in range(1, 5)] == ["Aux", "Tuner", "CD", "Option"]
    assert "Video" not in names.values()
    assert "iPad" not in names.values()


def test_input_numbers_differ_between_the_two_variants() -> None:
    """The reason these are separate profiles rather than one superset.

    The count is not the only difference -- the input NUMBERS shift, because
    VIDEO and iPAD are removed from the middle of the map. CD is 04 on the
    6-input and 03 on the 4-input. A merged profile would silently select the
    wrong physical input on one of the two families: the command succeeds, the
    device ACKs, and the user hears the wrong source with nothing logged.
    """
    six = create_engine(profile())
    four = create_engine(four_input_profile())

    def cd_input(prof: dict[str, Any]) -> int:
        return next(k for k, v in prof["sources"]["names"].items() if v == "CD")

    assert cd_input(profile()) == 4
    assert cd_input(four_input_profile()) == 3
    assert six.format_command("source_set", source=4) == "*SRC04\r"
    assert four.format_command("source_set", source=3) == "*SRC03\r"


def test_four_input_shares_the_command_set_and_the_gaps() -> None:
    """Same protocol: same commands present, same commands absent."""
    six = create_engine(profile())
    four = create_engine(four_input_profile())
    for command in ("status", "source_set", "volume_up", "volume_down"):
        assert four.has_command(command), f"{command} missing"
        assert six.has_command(command) == four.has_command(command)
    for command in ("power_on", "power_off", "mute_on", "volume_set"):
        assert not four.has_command(command), f"{command} is not in the manual"


def test_four_input_serial_params_match() -> None:
    """One protocol, so the wire settings must not diverge."""
    six = create_engine(profile())
    four = create_engine(four_input_profile())
    assert four.baud_rate == six.baud_rate == 38400
    assert (four.data_bits, four.parity, four.stop_bits) == (
        six.data_bits,
        six.parity,
        six.stop_bits,
    )


async def test_four_input_sets_up_with_four_named_sources(hass: HomeAssistant) -> None:
    """End to end: the dropdown shows the 4-input names, not "Source N"."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_profile": FOUR_INPUT_NAME, CONF_PORT: "demo"},
    )
    await hass.async_block_till_done()
    assert result["type"].value == "create_entry", result
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    ent = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "media_player"
    )
    state = hass.states.get(ent.entity_id)
    assert state is not None
    assert state.attributes["source_list"] == ["Aux", "Tuner", "CD", "Option"]
    # Same gaps as its 6-input sibling.
    features = MediaPlayerEntityFeature(state.attributes["supported_features"])
    assert not features & F.TURN_ON
    assert not features & F.VOLUME_SET
    assert features & F.VOLUME_STEP
    assert features & F.SELECT_SOURCE


# ─── Fleet-wide invariant ────────────────────────────────────────────────────


def test_power_features_track_power_commands_across_all_profiles() -> None:
    """Advertising power must imply having the commands, for every profile.

    The entity gate now depends on this; asserting it here means a future
    profile that declares one without the other fails at the library level
    rather than as dead buttons in someone's UI.
    """
    offenders = [
        name
        for name, prof in load_builtin_profiles().items()
        if (e := create_engine(prof))
        and e.has_command("power_on") != e.has_command("power_off")
    ]
    assert not offenders, f"only one of power_on/power_off declared: {offenders}"


# ─── The status probe must actually correlate ────────────────────────────────


@pytest.mark.parametrize(
    "reply", ["XIA100e/XIA150e", "XIA100/XIA150", "306D", " 306D "]
)
def test_model_reply_parses_so_the_probe_correlates(reply: str) -> None:
    """The regression: *MODEL is the status probe, and its reply never parsed.

    _wait_for_response only accepts a PARSED response, so the probe timed out,
    connect() left _device_responded False, and _reconnect_loop -- which exits
    only on a real reply -- retried forever. A real XIA would have looked like a
    permanently dead device.

    The manual prints the model two ways: "#XIA100/XIA150" in the RETURN column
    and "#XIA100e/XIA150e" in the REMARK column, hence the optional 'e'.
    """
    for prof in (profile(), four_input_profile()):
        parsed = create_engine(prof).parse_response(reply)
        assert parsed is not None, f"{reply!r} did not parse for {prof['name']}"
        assert parsed.get("global") == "model"


def test_status_replies_are_not_swallowed_by_the_model_pattern() -> None:
    """The global pattern must not shadow the real status form.

    An over-broad pattern would make every reply a content-free ACK, losing
    power/source/mute entirely.
    """
    parsed = create_engine(profile()).parse_response("ON,SRC03,MUTE OFF")
    assert parsed is not None
    assert parsed.get("type") == "status"
    assert parsed["source"] == 3


def test_relative_only_volume_reports_no_level(hass: HomeAssistant) -> None:
    """A zero-width scale must expose no volume_level.

    Returning 0.0 rendered a slider pinned at zero next to working +/- buttons,
    which reads as a broken control rather than an absent one.
    """
    engine_obj = create_engine(profile())
    assert engine_obj.volume_max - engine_obj.volume_min == 0
