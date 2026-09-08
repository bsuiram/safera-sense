"""Constants for the Safera Sense integration."""

DOMAIN = "safera"

# Services
SERVICE_SEND_COMMAND = "send_command"
SERVICE_WRITE_SETTING = "write_setting"

# Bluetooth characteristic UUIDs
BEEF_CHARACTERISTIC = "0000beef-1212-efde-1523-785fef13d123"

# Command channel. Writes are 8 bytes: a 4-byte LE code then a 4-byte LE
# parameter. Confirmed working on this hood — see captures/gatt.md.
BABE_CHARACTERISTIC = "0000babe-1212-efde-1523-785fef13d123"

# Fallback for BABE_CHARACTERISTIC. Resolving it by UUID string has been seen to
# fail against a partial cached GATT table while notifications on the same
# service were streaming fine, so the handle is used if the lookup comes up
# empty. Verified against firmware 13; re-check if the hood is ever updated.
BABE_HANDLE = 42

# Settings channel. Reads give the whole 200-byte configuration block; writes
# are two bytes, an offset into that block then the value to store there.
# Confirmed by watching the Safera app edit a ventilation preset: abba held
# [87, 22] afterwards, and dcba byte 87 had become 22.
DCBA_CHARACTERISTIC = "0000dcba-1212-efde-1523-785fef13d123"
ABBA_CHARACTERISTIC = "0000abba-1212-efde-1523-785fef13d123"
DCBA_HANDLE = 38

# Device event log. Read and notify, laid out as a u16 count followed by
# 5-byte records of (event code, u32 LE device uptime in seconds). No alarm has
# ever been observed, so which code an alarm uses is unknown — the point of
# subscribing is to catch it the moment one fires.
ABCF_CHARACTERISTIC = "0000abcf-1212-efde-1523-785fef13d123"
ABCF_HANDLE = 50
EVENT_RECORD_SIZE = 5

# Event codes seen so far. 100 was identified by pressing the button and
# watching it appear; 103 and 104 landed on the exact seconds byte 33 went to
# pre-alarm and to cooktop-cut during a deliberate trip. 1, 3 and 6 appeared
# around a cooking session and are unidentified.
EVENT_OK_PRESSED = 100
EVENT_ALARM_RAISED = 103
EVENT_COOKTOP_CUT = 104
ABBA_HANDLE = 36
SETTINGS_LENGTH = 200

# Ventilation preset tables inside the settings block, one byte per step for
# levels 0, 1, 2, 3, 4 and boost. Values are 0-254, not 0-255: the Safera app
# shows percentages of 254.
# Offsets inside the settings block, all confirmed against the Safera app.
SETTINGS_MOTOR1_PRESETS = 86  # levels 0-4 then boost
SETTINGS_MOTOR2_PRESETS = 93  # same order
SETTINGS_VENT_LIMITS = 82  # 3 bytes, (max << 4) | min, active/after/no cooking
SETTINGS_LIGHT_BRIGHTNESS = 103  # presets 1-3
SETTINGS_LIGHT_COLOR = 107  # presets 1-3
SETTINGS_LIGHT_AUTOMATION = 111  # which preset each automatic situation uses
SETTINGS_VENT_SENSITIVITY = 133  # percent, stored directly with no scaling
SETTINGS_SENSOR_HEIGHT = 41  # cm, mirrored live at payload @8
SETTINGS_COOKER_WIDTH = 42  # cm

# The app offers cooker width as a fixed list, not free entry: 50 to 100 cm in
# 10 cm steps.
COOKER_WIDTHS = (50, 60, 70, 80, 90, 100)

# Ventilation presets are stored as a fraction of 254; light brightness of 255.
FAN_PRESET_MAX = 254
LIGHT_PRESET_BRIGHTNESS_MAX = 255

# Local names the hardware advertises, as fnmatch patterns so the manifest's
# bluetooth matchers and the config flow agree on what counts as a hood.
#
# The Roroshetta units are rebadged Safera hoods, so both are matched: renaming
# this integration must not stop it recognising a hood that still calls itself
# Roroshetta Sense. Note it advertises "Roroshetta", with a plain o — the
# "Røroshetta*" pattern crillebaba/ha-safera-sense uses would not match it.
# "iSense*" and "Sense_*" cover Safera's other product names; they come from
# crillebaba/ha-safera-sense and are unverified against hardware here, but a
# surplus matcher only ever offers a config flow the user can dismiss, while a
# missing one makes a device undiscoverable.
ADVERTISED_NAME_PATTERNS = (
    "Roroshetta Sense",
    "Safera Sense",
    "iSense*",
    "Sense_*",
)
# Kept as the exact-match subset for anything that wants literal names.
ADVERTISED_NAMES = ("Roroshetta Sense", "Safera Sense")

# Advertised identifiers, kept in sync with the matchers in manifest.json
SERVICE_UUID = "0000f00d-1212-efde-1523-785fef13d123"
MANUFACTURER_ID = 1837

# Update interval in seconds
UPDATE_INTERVAL = 60

# Device Information Service (0x180A) characteristics. Read once per hood and
# cached in the config entry so Home Assistant's device page shows the real
# manufacturer, model and revisions instead of hardcoded guesses.
DIS_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"
DIS_MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
DIS_SERIAL = "00002a25-0000-1000-8000-00805f9b34fb"
DIS_HARDWARE_REV = "00002a27-0000-1000-8000-00805f9b34fb"
DIS_FIRMWARE_REV = "00002a26-0000-1000-8000-00805f9b34fb"
DIS_SOFTWARE_REV = "00002a28-0000-1000-8000-00805f9b34fb"

# Config entry data keys
DATA_PAIRED_ONCE = "paired_once"
DATA_DEVICE_INFO = "device_info"

# Pairing window delay on first setup
PAIRING_WINDOW_SECONDS = 5

# Connection loop timings
DEVICE_WAIT_SECONDS = 5
MAX_BACKOFF_SECONDS = 30
STOP_TIMEOUT_SECONDS = 5

# Command codes, from magicus/safera-ble and verified against this hood on
# 2026-08-28 except where noted. Payload is a 4-byte LE code then a 4-byte LE
# parameter, written to BABE_CHARACTERISTIC.
CMD_MOTOR_SPEED_STEP = 0x2001  # parameter is level * 30, matching byte 56
CMD_MOTOR_RAW_SPEED = 0x2002  # parameter 0-255, 0 stops the motor
CMD_MOTOR_AUTO_MODE = 0x2004  # 1 enables fan auto, 0 disables
CMD_LIGHT_PRESET = 0x2005  # 0 off, 1 on
CMD_LIGHT_BRIGHTNESS = 0x2006  # parameter 0-255; 0 is a dim floor, not off
CMD_LIGHT_COLOR = 0x2007  # parameter 0-255, warm to cool. Not in the external
# table at all — found by reading back what the Safera app had last written.
CMD_LIGHT_AUTO_MODE = 0x2008  # 1 enables light auto, 0 disables
CMD_FILTER_CHANGED = 0x2009  # parameter 0 resets the grease filter counter

# Byte 60 is an auto-mode bitmask. Any manual light or fan command clears the
# corresponding bit — the hood drops out of auto as soon as it is driven by
# hand, whether from Home Assistant, the app or its own panel.
# Byte 33 is the stove-guard state machine, captured during a deliberate trip on
# 2026-08-31: 2 normal, 7 pre-alarm (buzzer, 15 s), 8 alarm with the cooktop cut.
DEVICE_STATE_NORMAL = 2
DEVICE_STATE_PRE_ALARM = 7
DEVICE_STATE_ALARM = 8
DEVICE_STATES = {
    DEVICE_STATE_NORMAL: "normal",
    DEVICE_STATE_PRE_ALARM: "pre_alarm",
    DEVICE_STATE_ALARM: "alarm",
}

# Byte 43, the cooking-session latch: 0 idle, 2 while a session is active. It
# sets on the frame hob power first goes nonzero and clears about fifteen
# minutes after the hob goes off.
ACTIVITY_TYPE_IDLE = 0
ACTIVITY_TYPE_COOKING = 2

# alarm_level trips at exactly 100, so it really is a percentage — it is not
# capped there though, and was seen to keep climbing to 107 after the cut.
ALARM_TRIP_LEVEL = 100

AUTO_MASK_FAN = 0x01
AUTO_MASK_LIGHT = 0x02

# CMD_LIGHT_PRESET takes preset * 30, exactly like CMD_MOTOR_SPEED_STEP, and
# byte 53 reports the same encoding back. Measured 2026-09-08: params 30, 60 and
# 90 produced 56%/2790 K, 20%/2970 K and 100%/2943 K, an exact match for this
# hood's three stored light presets.
#
# This was previously LIGHT_PRESET_ON = 1. Sending 1 does switch the lamp on,
# but at a fallback rather than a stored preset, and light.py then overwrote
# brightness and colour by hand — which masked the bug completely for weeks.
# It is also why byte 53 appeared to have "two encodings": the literal 1s and 2s
# were our own bad writes coming back, not something the hood does.
LIGHT_PRESET_STEP = 30
LIGHT_PRESET_COUNT = 3
LIGHT_PRESET_OFF = 0
LIGHT_PRESET_PARAM_MAX = LIGHT_PRESET_COUNT * LIGHT_PRESET_STEP
# Preset applied by a bare turn-on when nothing else is remembered. The gentlest
# of the three on this hood; preset 3 is the Active cooking one.
LIGHT_PRESET_DEFAULT = 1

# The colour channel is a warm-to-cool slider, 0-255, and the mapping to Kelvin
# is measured rather than assumed: the app showed 2790 K, 2970 K and 2943 K for
# stored preset bytes 10, 30 and 27, an exact fit for 2700 + byte * 9.
LIGHT_KELVIN_BASE = 2700
LIGHT_KELVIN_PER_STEP = 9
LIGHT_MIN_KELVIN = LIGHT_KELVIN_BASE
LIGHT_MAX_KELVIN = LIGHT_KELVIN_BASE + 255 * LIGHT_KELVIN_PER_STEP

# CMD_MOTOR_RAW_SPEED takes 0-255 and byte 57 reports the same units back.
# Anything above roughly 180 was not audibly different. The fan entity no longer
# uses the raw command — see FAN_LEVEL_STEP below — but it is still reachable
# through the safera.send_command action.
FAN_RAW_SPEED_MAX = 255

# The hood's own speed levels. ``CMD_MOTOR_SPEED_STEP`` takes the level scaled
# by 30 — the identical encoding byte 56 reports back — so driving the fan this
# way keeps the hood's level index meaningful. ``CMD_MOTOR_RAW_SPEED`` does not:
# it moves the motor while byte 56 sits at 0, because the hood's own controller
# never learns about the change.
#
# Four levels. Measured on the hood 2026-09-08 by sweeping the command: params
# 30, 60, 90 and 120 set byte 56 to 1, 2, 3 and 4 and produced motor speeds 9,
# 18, 39 and 55 — an exact match for this hood's stored Motor 1 presets, which
# re-proves the preset table drives the hardware.
#
# **Params above 120 are silently ignored.** 150, 180 and 210 were each sent
# with the fan sitting at level 1; it stayed at level 1 every time, with no
# error and no change to byte 56. So boost is NOT reachable through this
# command, even though the settings block has a sixth Motor 1 slot at @91 (100%
# on this hood). Whatever triggers boost is something else — the hood's own
# button, or a command not yet found. Do not raise this count back to 5 on the
# strength of that preset slot: it was a plausible extrapolation and it was
# wrong.
FAN_LEVEL_STEP = 30
FAN_LEVEL_COUNT = 4
FAN_LEVEL_PARAM_MAX = FAN_LEVEL_COUNT * FAN_LEVEL_STEP

# Commands are rate limited. The hood is a stove guard on a single BLE
# connection and a burst of writes has dropped the link before.
COMMAND_MIN_INTERVAL_SECONDS = 1.0
COMMAND_TIMEOUT_SECONDS = 10

# Mark entities unavailable if no notification arrives within this window.
# The device pushes roughly once per second, so this is ~30 missed frames.
STALE_AFTER_SECONDS = 30
