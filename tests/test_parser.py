"""Tests for the status-frame decoding.

The frames marked "recorded" are real 69-byte payloads captured from the hood
this integration was written against (hardware 3.2.255.0, firmware 13, software
75). They are the evidence behind the offsets, so a test that only used
synthetic bytes would happily pass against a decode that has drifted from the
device.
"""

from __future__ import annotations

import pytest

from conftest import parser

parse_frame = parser.parse_frame

# Recorded, hood idle: no cooking session, hob off, fan and lamp off.
IDLE = bytes.fromhex(
    "d31c061d8012767346061700000019990221020000000000150164ff01aeff1e0002"
    "0000e93132000000030000000000000001ff2600000000000d140300000000000000"
    "ff"
)
# Recorded, mid cooking session: hob drawing 2360 W, session latch set.
COOKING = bytes.fromhex(
    "ef1b071d3c120a10460611000000133d0229010000000000170164ff01abff1e0002"
    "00008a6733000000030205013809000001ff295aff1b1e170d160300000000000000"
    "ff"
)
# Recorded during a deliberate alarm trip: the 15-second pre-alarm window.
PRE_ALARM = bytes.fromhex(
    "d11b5e22b316e83a4606030000000aab01100000000000005e0164ff76b7ff1e0007"
    "00004a673700000003026401e402000000ff245aff1b3c2b28040300000000000000"
    "ff"
)
# Recorded a moment later: the hood has cut power to the cooktop.
CUT = bytes.fromhex(
    "d71bae22a816df324606030000000aab0110000000000000610164ff01b6ff1e0008"
    "000059673700000003026901bc02000000ff245aff1b3c2b28040300000000000000"
    "ff"
)


def synthetic(**overrides: int) -> bytes:
    """A minimal well-formed frame with individual bytes overridden."""
    frame = bytearray(69)
    for offset, value in overrides.items():
        frame[int(offset.removeprefix("b"))] = value
    return bytes(frame)


class TestFrameLength:
    """The length guard."""

    def test_rejects_short_frame(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            parse_frame(bytes(40))

    def test_rejects_60_byte_frame(self) -> None:
        """Regression: the old guard was ``len(data) < 60``.

        A frame of exactly 60 bytes passed it, and then ``auto_flags`` read
        ``data[60:61]`` — an empty slice, which ``int.from_bytes`` turns into 0.
        Both auto modes silently reported "disarmed" instead of unknown.
        """
        with pytest.raises(ValueError):
            parse_frame(bytes(60))

    def test_accepts_61_bytes(self) -> None:
        assert parse_frame(bytes(61))["auto_flags"] == 0


class TestIlluminance:
    """Bytes 6-7 are signed, and that is the whole point."""

    def test_darkness_is_not_glare(self) -> None:
        """Regression guard for the sign bug.

        In true darkness the sensor reads slightly below zero. Read unsigned,
        0xffd8 becomes 65496 and divides to 2047 lux — a pitch-dark kitchen
        reported as brighter than it ever gets in daylight.
        """
        assert parse_frame(synthetic(b6=0xD8, b7=0xFF))["illuminance"] == 0.0

    def test_positive_value_scales_by_32(self) -> None:
        # 1760 / 32 = 55 lux, the level measured with room and hood lamp both on.
        assert parse_frame(synthetic(b6=0xE0, b7=0x06))["illuminance"] == 55.0

    def test_floors_at_zero_rather_than_going_negative(self) -> None:
        assert parse_frame(synthetic(b6=0xFF, b7=0xFF))["illuminance"] == 0.0


class TestFanLevel:
    """The command encoding and the feedback encoding must agree.

    ``CMD_MOTOR_SPEED_STEP`` takes ``level * FAN_LEVEL_STEP`` and byte 56
    reports the same thing back. If these ever drift apart the fan entity goes
    back to the old behaviour, where Home Assistant drove the motor and the
    hood's level index sat at 0.
    """

    @pytest.mark.parametrize("level", [0, 1, 2, 3, 4])
    def test_command_parameter_round_trips(self, level: int) -> None:
        from conftest import const

        param = level * const.FAN_LEVEL_STEP
        assert param <= const.FAN_LEVEL_PARAM_MAX
        assert parse_frame(synthetic(b56=param))["fan"] == level

    def test_level_count_stops_at_four(self) -> None:
        """Measured 2026-09-08: params above 120 are silently ignored.

        150, 180 and 210 were each sent with the fan at level 1 and it stayed
        at level 1 every time — no error, no change to byte 56. Boost has a
        preset slot of its own at settings @91 but is not reachable this way,
        and raising this back to 5 on the strength of that slot is exactly the
        wrong inference that shipped in v1.1.0.
        """
        from conftest import const

        assert const.FAN_LEVEL_COUNT == 4
        assert const.FAN_LEVEL_PARAM_MAX == 120

    def test_raw_motor_speed_is_read_separately(self) -> None:
        """Byte 57 is the real speed and is independent of the level index."""
        values = parse_frame(synthetic(b56=60, b57=180))
        assert values["fan"] == 2
        assert values["fan_speed"] == 180


class TestLightPreset:
    """Byte 53 is the preset as ``preset * 30``, and only that.

    It was believed to carry two encodings, because our own ``CMD_LIGHT_PRESET``
    writes had been putting the bare preset index there. Measured 2026-09-08:
    the command takes ``preset * 30``, so the literal values were our mistake
    being echoed back, not something the hood does.
    """

    @pytest.mark.parametrize("preset", [0, 1, 2, 3])
    def test_command_parameter_round_trips(self, preset: int) -> None:
        from conftest import const

        param = preset * const.LIGHT_PRESET_STEP
        assert param <= const.LIGHT_PRESET_PARAM_MAX
        assert parse_frame(synthetic(b53=param))["light"] == preset

    def test_hood_writes_preset_times_30(self) -> None:
        assert parse_frame(synthetic(b53=90))["light"] == 3

    def test_a_bare_index_is_not_a_preset(self) -> None:
        """Regression: sending 2 instead of 60 lit the lamp at a fallback.

        Because ``light.py`` then set brightness and colour by hand, the lamp
        looked right and the bug survived for weeks. A value below one step is
        not a preset and must not decode as one.
        """
        assert parse_frame(synthetic(b53=2))["light"] == 0

    def test_off_is_zero(self) -> None:
        assert parse_frame(synthetic(b53=0))["light"] == 0

    def test_raw_byte_is_preserved(self) -> None:
        assert parse_frame(synthetic(b53=90))["light_raw"] == 90


class TestRecordedIdleFrame:
    """A real frame from an idle hood decodes to plausible values."""

    def test_environment(self) -> None:
        values = parse_frame(IDLE)
        assert values["temperature"] == pytest.approx(23.79, abs=0.01)
        assert 20 <= values["humidity"] <= 60
        assert values["co2"] > 300
        assert values["battery"] == 100

    def test_nothing_is_running(self) -> None:
        values = parse_frame(IDLE)
        assert values["power"] == 0
        assert values["activity_type"] == 0
        assert values["alarm_level"] == 0
        assert values["fan"] == 0

    def test_no_faults_reported(self) -> None:
        values = parse_frame(IDLE)
        assert values["sensor_errors"] == 0
        assert values["pcu_errors"] == 0
        assert values["device_state"] == 2


class TestRecordedCookingFrame:
    """Hob power, the session latch and the surface sensor move together."""

    def test_hob_is_drawing_power(self) -> None:
        values = parse_frame(COOKING)
        assert values["power"] == 2360
        assert values["power"] % 20 == 0, "observed values are multiples of 20 W"

    def test_session_latch_is_set(self) -> None:
        assert parse_frame(COOKING)["activity_type"] == 2

    def test_surface_is_hotter_than_ambient(self) -> None:
        values = parse_frame(COOKING)
        assert values["heat_index"] > values["temperature"]


class TestRecordedAlarm:
    """Byte 33 is the state machine, not byte 28."""

    def test_pre_alarm_state(self) -> None:
        assert parse_frame(PRE_ALARM)["device_state"] == 7

    def test_cooktop_cut_state(self) -> None:
        assert parse_frame(CUT)["device_state"] == 8

    def test_alarm_level_reached_the_trip_threshold(self) -> None:
        from conftest import const

        assert parse_frame(PRE_ALARM)["alarm_level"] >= const.ALARM_TRIP_LEVEL

    def test_alarm_level_is_not_capped_at_the_threshold(self) -> None:
        """It kept climbing past 100 after the cut; the trip is a crossing."""
        assert parse_frame(CUT)["alarm_level"] > parse_frame(PRE_ALARM)["alarm_level"]


class TestVocIndex:
    """Byte 14 is exposed raw because its scale is unknown."""

    def test_read_as_a_plain_byte(self) -> None:
        assert parse_frame(synthetic(b14=25))["voc_index"] == 25

    def test_not_divided_by_20(self) -> None:
        """crillebaba/safera-sense-ble reads this as ``byte / 20``.

        Every value ever recorded here falls between 10 and 25, which that
        scaling would squash into 0.5-1.25 — not the "UBA index 1-5" it is
        labelled as. Until the scale is known, the byte goes out unmodified.
        """
        assert parse_frame(synthetic(b14=10))["voc_index"] == 10


class TestAutoFlags:
    """Byte 60 is a bitmask: bit 0 fan auto, bit 1 light auto.

    These bits are what the fan's Auto preset mode and the light's Auto effect
    read, now that the two auto switches are gone.
    """

    @pytest.mark.parametrize(
        ("raw", "fan_auto", "light_auto"),
        [(0, False, False), (1, True, False), (2, False, True), (3, True, True)],
    )
    def test_bits(self, raw: int, fan_auto: bool, light_auto: bool) -> None:
        from conftest import const

        flags = parse_frame(synthetic(b60=raw))["auto_flags"]
        assert bool(flags & const.AUTO_MASK_FAN) is fan_auto
        assert bool(flags & const.AUTO_MASK_LIGHT) is light_auto


class TestAppParity:
    """The controls mirror the Safera app's own two columns.

    The app shows ventilation as OFF/1/2/3/4/Auto and light as OFF/1/2/3/Auto,
    each one selector. Boost appears in neither picker, which agrees with the
    measurement that params above the top level are ignored.
    """

    def test_fan_has_four_levels(self) -> None:
        from conftest import const

        assert const.FAN_LEVEL_COUNT == 4

    def test_light_has_three_presets(self) -> None:
        from conftest import const

        assert const.LIGHT_PRESET_COUNT == 3

    def test_both_columns_have_the_same_shape(self) -> None:
        """Off, numbered presets, Auto — the two selects share one base class.

        The shared implementation derives its options from the preset count and
        its command parameter from the step, so these constants are what keeps
        the fan picker and the light picker honest.
        """
        from conftest import const

        for count, step in (
            (const.FAN_LEVEL_COUNT, const.FAN_LEVEL_STEP),
            (const.LIGHT_PRESET_COUNT, const.LIGHT_PRESET_STEP),
        ):
            assert count >= 1
            # Off plus the presets plus Auto.
            assert len([0, *range(1, count + 1), "auto"]) == count + 2
            assert count * step <= 0xFF, "top preset must fit in one command byte"

    def test_both_use_the_same_step_encoding(self) -> None:
        """Fan levels and light presets are both ``index * 30``.

        Missing this for the light cost weeks: CMD_LIGHT_PRESET was sent the
        bare index, which lit the lamp at a fallback instead of the stored
        preset.
        """
        from conftest import const

        assert const.FAN_LEVEL_STEP == const.LIGHT_PRESET_STEP == 30


class TestUptime:
    """Read as three bytes; byte 39 is zero in every frame ever captured."""

    def test_three_byte_read(self) -> None:
        assert parse_frame(synthetic(b36=0x01, b37=0x02, b38=0x03))["uptime"] == 0x030201

    def test_agrees_with_a_32_bit_read_when_byte_39_is_zero(self) -> None:
        frame = synthetic(b36=0xE8, b37=0x2F, b38=0x32, b39=0x00)
        values = parse_frame(frame)
        assert values["uptime"] == int.from_bytes(frame[36:40], "little")
