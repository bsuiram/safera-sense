"""Decoding of the hood's status frame.

This module is deliberately free of Home Assistant and bleak imports so the
decoding can be tested with plain pytest against recorded frames. Everything
here is a pure function of the payload bytes; connection handling and entity
plumbing live in ``coordinator.py``.

Offsets were established against a real hood — see ``captures/gatt.md`` and the
notes in ``CLAUDE.md`` for how each one was confirmed and which earlier guesses
turned out to be wrong. Frames are 69 bytes on this firmware (hardware
3.2.255.0, firmware 13, software 75); the guard below is deliberately looser
because the highest offset actually read is 60.
"""

from __future__ import annotations

from typing import Any

from .const import FAN_LEVEL_STEP, LIGHT_PRESET_STEP

# Shortest frame we will decode. Every offset read below is within this, so a
# frame at least this long cannot index out of range.
FRAME_MIN_LENGTH = 61


def signed8(value: int) -> int:
    """Reinterpret a byte as a signed 8-bit value."""
    return value - 256 if value > 127 else value


def signed16(value: int) -> int:
    """Reinterpret a 16-bit little-endian value as signed."""
    return value - 65536 if value > 32767 else value


def parse_frame(data: bytes) -> dict[str, Any]:
    """Decode one status frame into a mapping of field name to value.

    Raises ``ValueError`` if the frame is too short to decode. Callers that
    receive frames off the wire should catch that rather than let it escape
    into the notification handler.
    """
    if len(data) < FRAME_MIN_LENGTH:
        raise ValueError(
            f"frame too short to decode: {len(data)} < {FRAME_MIN_LENGTH} bytes"
        )

    def u(offset: int, length: int = 2) -> int:
        return int.from_bytes(data[offset : offset + length], "little")

    values: dict[str, Any] = {}

    values["temperature"] = (u(0, 2) + 10000) / 100 - 150
    # Misnamed: this is the stove guard's surface/IR temperature aimed at the
    # hob, not a heat index. It tracks hob power while ambient barely moves.
    values["heat_index"] = (u(2, 2) + 10000) / 100 - 150
    values["humidity"] = u(4, 2) / 100
    # Bytes 6-7, value / 32 lux, and **signed**. Confirmed as a real light
    # sensor: the hood's lamp lifts it from ~20 to ~55 lux and a person at
    # the hob shadows it downward. In true darkness it reads slightly below
    # zero — 0xffd8 is −40, about −1.25 lux — so reading it unsigned turns
    # a dark kitchen into 2047 lux, the exact opposite of the truth.
    # Negative illuminance is meaningless, so it is floored at zero.
    values["illuminance"] = max(0.0, signed16(u(6, 2)) / 32)
    values["mounting_height"] = u(8, 1)
    values["aqi"] = u(10, 2)
    # @12-13 / 5, per magicus/safera-ble. The old @13 / 1000 was wrong: byte
    # 13 is zero in all 12604 frames ever captured, so it really computed
    # byte14 * 0.256 and invented three decimals of precision. The app reads
    # 0.0 when this decode reads 0.0, which is what settles it.
    values["pm25"] = u(12, 2) / 5
    # Byte 14 is a coarse, monotonically increasing band index derived from
    # tVOC: across 16202 recorded frames it takes 16 distinct values from 10
    # to 25, and each step maps to a clean, non-overlapping tVOC range (10 is
    # everything up to ~48 µg/m³, 25 is ~530-560). It is exposed raw because
    # the scale is not known. crillebaba/safera-sense-ble reads it as
    # `byte / 20` and calls it a UBA index 1-5, which our data contradicts —
    # that would put every observed frame between 0.5 and 1.25.
    values["voc_index"] = u(14, 1)
    values["co2"] = u(15, 2)
    values["tvoc"] = u(17, 2)
    values["accessories"] = u(25, 1)
    values["battery"] = u(26, 1)
    # Alarm state machine, confirmed by a deliberate trip on 2026-08-31: 1
    # normally, a value counting down once per second through the 15-second
    # pre-alarm buzzer window, then 0 once the cooktop is cut.
    values["alarm_status"] = u(28, 1)
    values["pitch"] = signed8(u(29, 1))
    values["roll"] = signed8(u(31, 1))
    # 2 normally, 7 during pre-alarm, 8 once the cooktop has been cut.
    values["device_state"] = u(33, 1)
    values["sensor_errors"] = u(34, 2)
    # Read as three bytes rather than four: byte 39 is zero in every frame
    # ever captured, so this agrees with a u32 read and cannot be caught out
    # by a stray high byte.
    values["uptime"] = u(36, 3)
    values["pcu_errors"] = u(40, 2)
    # Cooking-session latch. 0 idle, 2 while a session is active — it sets on
    # the frame hob power first goes nonzero and clears about 15 minutes after
    # the hob goes off, which is why the hood can auto-start the light well
    # after cooking has stopped.
    values["activity_type"] = u(43, 1)
    values["alarm_level"] = u(44, 1)
    values["activity"] = u(45, 1)
    values["power"] = u(46, 2)
    # Byte 53 is the light preset as preset * 30, the same encoding byte 56
    # uses for the fan. There is no second encoding: the literal 1s and 2s
    # recorded in older captures were CMD_LIGHT_PRESET being sent the preset
    # index instead of index * 30, so the hood was storing our mistake. Values
    # below 30 are therefore not a preset and decode to 0.
    light_raw = u(53, 1)
    values["light"] = light_raw // LIGHT_PRESET_STEP
    values["light_raw"] = light_raw
    values["light_brightness"] = u(54, 1)
    values["light_color"] = u(55, 1)
    # Whole level numbers, matching the app's 0-4. Byte 56 is level * 30.
    values["fan"] = u(56, 1) // FAN_LEVEL_STEP
    values["fan_speed"] = u(57, 1)
    values["grease_filter"] = u(59, 1)
    values["auto_flags"] = u(60, 1)

    return values
