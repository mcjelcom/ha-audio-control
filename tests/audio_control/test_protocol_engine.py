"""Tests for the ProtocolEngine class — the core of the library.

Tests the ACTUAL library code, not inline patterns.
"""

from __future__ import annotations

from rs232_protocol import ProtocolEngine


class TestCommandFormatting:
    """Test command formatting for various profiles."""

    def test_monoprice_status(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice status is ?1{zone}\\r (unit-prefixed 1-digit zone)."""
        result = monoprice_engine.format_command("status", zone=3)
        assert result == "?13\r"

    def test_monoprice_power_on(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice power on uses <1{zone}PR01."""
        result = monoprice_engine.format_command("power_on", zone=1)
        assert result == "<11PR01\r"

    def test_monoprice_volume_set(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice volume set uses <1{zone}VO{volume:02d}."""
        result = monoprice_engine.format_command("volume_set", zone=2, volume=25)
        assert result == "<12VO25\r"

    def test_monoprice_source_set(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice source select uses <1{zone}CH{source:02d}."""
        result = monoprice_engine.format_command("source_set", zone=4, source=3)
        assert result == "<14CH03\r"

    def test_amc_status(self, amc_engine: ProtocolEngine) -> None:
        """AMC status command uses the ZN prefix (real-hardware confirmed)."""
        result = amc_engine.format_command("status", zone=1)
        assert result == "*ZN01STA00\r"

    def test_amc_power_on(self, amc_engine: ProtocolEngine) -> None:
        """AMC power on."""
        result = amc_engine.format_command("power_on", zone=5)
        assert result == "*ZN05PWR01\r"

    def test_amc_volume_set(self, amc_engine: ProtocolEngine) -> None:
        """AMC volume set."""
        result = amc_engine.format_command("volume_set", zone=3, volume=30)
        assert result == "*ZN03VOL30\r"

    def test_amc_all_off(self, amc_engine: ProtocolEngine) -> None:
        """AMC all-off global command."""
        result = amc_engine.format_command("all_off")
        assert result == "*ZALLPWR00\r"

    def test_undefined_command_returns_none(
        self, monoprice_engine: ProtocolEngine
    ) -> None:
        """Undefined commands return None."""
        assert monoprice_engine.format_command("does_not_exist") is None

    def test_missing_kwargs_returns_none(
        self, monoprice_engine: ProtocolEngine
    ) -> None:
        """Missing template kwargs returns None."""
        assert monoprice_engine.format_command("volume_set", zone=1) is None

    def test_frame_to_bytes(self, amc_engine: ProtocolEngine) -> None:
        """frame_to_bytes produces ASCII bytes."""
        framed = amc_engine.format_command("power_on", zone=1)
        data = amc_engine.frame_to_bytes(framed)
        assert data == b"*ZN01PWR01\r"
        assert all(b < 128 for b in data)


class TestResponseParsing:
    """Test response parsing for various profiles."""

    def test_monoprice_status_response(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice: parse a full status line.

        Wire zone is 11 (unit 1, zone 1); zone_offset -10 maps it to logical
        zone 1. Fields: ZZ PA PR MU DT VL TR BA CH SR, all 2-digit.
        """
        line = "11010100001507070401"
        result = monoprice_engine.parse_response(line)
        assert result is not None
        assert result["zone"] == 1  # wire 11 - 10
        assert result["power"] is True
        assert result["mute"] is False
        assert result["volume"] == 15
        assert result["source"] == 1

    def test_amc_status_response(self, amc_engine: ProtocolEngine) -> None:
        """AMC: parse ZNxx,SRCxx,GRPx,VOL-xx."""
        line = "ZN03,SRC05,GRP0,VOL-25"
        result = amc_engine.parse_response(line)
        assert result is not None
        assert result["zone"] == 3
        assert result["source"] == 5
        assert result["volume"] == 25
        # group=0 means False
        assert result["group"] is False

    def test_amc_status_with_group(self, amc_engine: ProtocolEngine) -> None:
        """AMC: parse with group mode active."""
        line = "ZN01,SRC08,GRP1,VOL-10"
        result = amc_engine.parse_response(line)
        assert result["group"] is True
        assert result["source"] == 8

    def test_amc_tone_response(self, amc_engine: ProtocolEngine) -> None:
        """AMC: parse tone response."""
        line = "ZN02,BASS+6,TREB-4,GRP0"
        result = amc_engine.parse_response(line)
        assert result is not None
        assert result["zone"] == 2
        assert result["bass"] == 6
        assert result["treble"] == -4

    def test_amc_error_response(self, amc_engine: ProtocolEngine) -> None:
        """AMC: error response '?' is parsed."""
        result = amc_engine.parse_response("?")
        assert result == {"error": True}

    def test_amc_global_all_off(self, amc_engine: ProtocolEngine) -> None:
        """AMC: global all-off response."""
        result = amc_engine.parse_response("ZALLOFF")
        assert result is not None
        assert result["global"] == "all_off"

    def test_amc_global_mute_on(self, amc_engine: ProtocolEngine) -> None:
        """AMC: global mute on response."""
        result = amc_engine.parse_response("ZALLMON")
        assert result == {"global": "mute_all_on"}

    def test_amc_global_group_on(self, amc_engine: ProtocolEngine) -> None:
        """AMC: global group on with source."""
        result = amc_engine.parse_response("GRPON,STC05")
        assert result is not None
        assert result["global"] == "group_on"
        assert result["source"] == "05"

    def test_unrecognized_response(self, amc_engine: ProtocolEngine) -> None:
        """Unrecognized lines return None."""
        assert amc_engine.parse_response("GARBAGE") is None
        assert amc_engine.parse_response("") is None

    def test_strip_prefix(self, amc_engine: ProtocolEngine) -> None:
        """AMC: strip # prefix."""
        assert (
            amc_engine.strip_prefix("#ZN01,SRC03,GRP0,VOL-25")
            == "ZN01,SRC03,GRP0,VOL-25"
        )
        assert (
            amc_engine.strip_prefix("ZN01,SRC03,GRP0,VOL-25")
            == "ZN01,SRC03,GRP0,VOL-25"
        )


class TestVolumeConversion:
    """Test volume conversion between normalized and device values."""

    def test_monoprice_standard_volume(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice: 0.0-1.0 maps to 0-38 (not inverted)."""
        assert monoprice_engine.ha_volume_to_device(0.0) == 0
        assert monoprice_engine.ha_volume_to_device(1.0) == 38
        assert monoprice_engine.ha_volume_to_device(0.5) == 19

    def test_monoprice_device_to_ha(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice: device to normalized."""
        assert monoprice_engine.device_volume_to_ha(0) == 0.0
        assert monoprice_engine.device_volume_to_ha(38) == 1.0
        assert abs(monoprice_engine.device_volume_to_ha(19) - 0.5) < 0.01

    def test_amc_inverted_volume(self, amc_engine: ProtocolEngine) -> None:
        """AMC: inverted (0=loud, 62=mute)."""
        # 1.0 HA = 0 attenuation (loudest)
        assert amc_engine.ha_volume_to_device(1.0) == 0
        # 0.0 HA = 62 attenuation (silent)
        assert amc_engine.ha_volume_to_device(0.0) == 62
        # 0.5 HA = ~31 attenuation
        assert amc_engine.ha_volume_to_device(0.5) == 31

    def test_amc_device_to_ha(self, amc_engine: ProtocolEngine) -> None:
        """AMC: device to normalized (inverted)."""
        assert amc_engine.device_volume_to_ha(0) == 1.0
        assert amc_engine.device_volume_to_ha(62) == 0.0
        assert abs(amc_engine.device_volume_to_ha(31) - 0.5) < 0.01

    def test_roundtrip_monoprice(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice: roundtrip through both conversions."""
        for ha_vol in [0.0, 0.25, 0.5, 0.75, 1.0]:
            device_val = monoprice_engine.ha_volume_to_device(ha_vol)
            back = monoprice_engine.device_volume_to_ha(device_val)
            assert abs(back - ha_vol) < 0.03, f"Roundtrip failed for {ha_vol}"

    def test_roundtrip_amc(self, amc_engine: ProtocolEngine) -> None:
        """AMC: roundtrip through both conversions."""
        for ha_vol in [0.0, 0.25, 0.5, 0.75, 1.0]:
            device_val = amc_engine.ha_volume_to_device(ha_vol)
            back = amc_engine.device_volume_to_ha(device_val)
            assert abs(back - ha_vol) < 0.02, f"Roundtrip failed for {ha_vol}"


class TestEngineProperties:
    """Test protocol engine property accessors."""

    def test_monoprice_serial_config(self, monoprice_engine: ProtocolEngine) -> None:
        """Monoprice serial parameters."""
        assert monoprice_engine.baud_rate == 9600
        assert monoprice_engine.data_bits == 8
        assert monoprice_engine.parity == "N"
        assert monoprice_engine.stop_bits == 1
        assert monoprice_engine.command_delay == 0.1

    def test_amc_serial_config(self, amc_engine: ProtocolEngine) -> None:
        """AMC serial parameters."""
        assert amc_engine.baud_rate == 38400
        assert amc_engine.command_delay == 0.5
        assert amc_engine.response_prefix == "#"
        assert amc_engine.response_terminator == "\r"

    def test_zone_and_source_counts(self, monoprice_engine: ProtocolEngine) -> None:
        """Zone/source counts from profile."""
        assert monoprice_engine.num_zones == 6
        assert monoprice_engine.num_sources == 6

    def test_volume_config(self, amc_engine: ProtocolEngine) -> None:
        """Volume configuration from profile."""
        assert amc_engine.volume_max == 62
        assert amc_engine.volume_inverted is True

    def test_feature_flags(self, amc_engine: ProtocolEngine) -> None:
        """Feature flags from profile."""
        assert amc_engine.features["has_tone_controls"] is True
        assert amc_engine.features["has_group_mode"] is True
        assert amc_engine.features["has_all_off"] is True
        assert amc_engine.has_unsolicited_updates is False
