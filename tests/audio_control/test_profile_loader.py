"""Tests for the profile loader — loads YAML device profiles."""

from __future__ import annotations

from rs232_protocol import load_all_profiles, load_builtin_profiles
from rs232_protocol.profile_loader import BUILTIN_PROFILES_DIR


class TestBuiltinProfiles:
    """Test loading of built-in device profiles."""

    def test_profiles_dir_exists(self) -> None:
        """The builtin profiles directory exists."""
        assert BUILTIN_PROFILES_DIR.exists()
        assert BUILTIN_PROFILES_DIR.is_dir()

    def test_loads_profiles(self) -> None:
        """At least 5 profiles are loaded."""
        profiles = load_builtin_profiles()
        assert len(profiles) >= 5

    def test_all_profiles_have_required_keys(self) -> None:
        """Every profile has name, serial, commands, response."""
        profiles = load_builtin_profiles()
        for name, profile in profiles.items():
            assert "name" in profile, f"{name} missing 'name'"
            assert "serial" in profile, f"{name} missing 'serial'"
            assert "commands" in profile, f"{name} missing 'commands'"
            assert "response" in profile, f"{name} missing 'response'"

    def test_all_profiles_have_valid_serial_config(self) -> None:
        """Every profile has a valid baud rate."""
        profiles = load_builtin_profiles()
        valid_bauds = {4800, 9600, 19200, 38400, 57600, 115200}
        for name, profile in profiles.items():
            baud = profile.get("serial", {}).get("baud_rate", 9600)
            assert baud in valid_bauds, f"{name} has invalid baud_rate={baud}"

    def test_power_commands_are_declared_in_pairs(self) -> None:
        """A profile defines both power commands or neither, never one.

        This previously required power_on/power_off on EVERY profile. That held
        for the first 23 but is not a property of RS232 audio gear: the AMC
        XIA100e/XIA150e appendix documents six commands and no *POWER at all --
        the amplifier is powered from its front panel. Requiring the commands
        would force inventing them, which is how russound_cav66.yaml got deleted.

        The real invariant is pairing: one without the other guarantees a dead
        button, since the entity gates each flag on its own command.
        """
        for name, profile in load_builtin_profiles().items():
            commands = profile.get("commands", {})
            has_on = "power_on" in commands
            has_off = "power_off" in commands
            assert has_on == has_off, (
                f"{name} declares only one of power_on/power_off "
                f"(on={has_on}, off={has_off})"
            )

    def test_every_profile_has_a_status_command(self) -> None:
        """Status is the one command that genuinely must exist.

        The connection layer probes with it on connect to decide whether the
        device actually replied (as opposed to the port merely opening), so a
        profile without one can never be confirmed reachable.
        """
        for name, profile in load_builtin_profiles().items():
            assert "status" in profile.get("commands", {}), f"{name} has no status"

    def test_amc_x86_profile_exists(self) -> None:
        """The AMC X86 profile is present."""
        profiles = load_builtin_profiles()
        amc_names = [n for n in profiles if "AMC" in n.upper() or "X86" in n.upper()]
        assert len(amc_names) >= 1

    def test_monoprice_profile_exists(self) -> None:
        """The Monoprice profile is present."""
        profiles = load_builtin_profiles()
        mono_names = [n for n in profiles if "Monoprice" in n]
        assert len(mono_names) >= 1

    def test_template_file_excluded(self) -> None:
        """Files starting with _ are excluded."""
        profiles = load_builtin_profiles()
        for name in profiles:
            assert not name.startswith("_")

    def test_load_all_without_custom_dir(self) -> None:
        """load_all_profiles with None custom_dir only returns builtins."""
        profiles = load_all_profiles(custom_dir=None)
        assert len(profiles) == len(load_builtin_profiles())

    def test_load_all_with_nonexistent_custom_dir(self) -> None:
        """Nonexistent custom dir is gracefully ignored."""
        profiles = load_all_profiles(custom_dir="/nonexistent/path")
        assert len(profiles) == len(load_builtin_profiles())


class TestProfileEngineIntegration:
    """Test that loaded profiles work with create_engine factory."""

    def test_all_profiles_create_engine(self) -> None:
        """Every profile can create an engine without errors."""
        from rs232_protocol import create_engine

        profiles = load_builtin_profiles()
        for name, profile in profiles.items():
            engine = create_engine(profile)
            assert engine.num_zones >= 1, f"{name} has invalid zone count"
            assert engine.baud_rate > 0, f"{name} has invalid baud_rate"

    def test_declared_power_commands_all_format(self) -> None:
        """Where power commands exist they must format to a non-empty frame.

        Scoped to profiles that declare them: the AMC XIA100e has no *POWER
        command in its manual, so format_command correctly returns None there and
        the entity omits the buttons. A template that silently fails to format
        would otherwise look identical to an absent command.
        """
        from rs232_protocol import create_engine

        for name, profile in load_builtin_profiles().items():
            engine = create_engine(profile)
            if not engine.has_command("power_on"):
                continue
            on = engine.format_command("power_on", zone=1)
            off = engine.format_command("power_off", zone=1)
            assert on, f"{name} declares power_on but it formatted to {on!r}"
            assert off, f"{name} declares power_off but it formatted to {off!r}"

    def test_every_profile_formats_its_status_command(self) -> None:
        """The connect-time probe must produce a real frame for every profile."""
        from rs232_protocol import create_engine

        for name, profile in load_builtin_profiles().items():
            engine = create_engine(profile)
            frame = engine.format_command("status", zone=1)
            assert frame, f"{name} status formatted to {frame!r}"
