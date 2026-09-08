# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single custom Home Assistant integration (`custom_components/safera/`) that reads environmental
sensors from a Safera / Røroshetta Sense kitchen hood over BLE. There is no build system, no test
suite, no linter config, and no `requirements` in the manifest — it is plain Python deployed by
copying `custom_components/safera/` into a Home Assistant config directory and restarting HA.

Status: working. The integration streams all 14 sensors at ~1 Hz against a real hood. The top-level
README still says "does not work" — it predates the fix. Note the component README also describes a
polling design with a 60s interval and 3 retries; that is stale too, see Architecture below.

## Running / debugging

There is no unit test harness and no CI. Four ways to exercise the code, cheapest first:

- **Stub-import the coordinator** — no hardware, no Home Assistant. See "Verifying a change without
  hardware" below. Catches control-flow regressions in seconds; proves nothing about byte offsets.
- **`python test.py`** — standalone bleak script, run from a machine with a BLE adapter near the
  hood. Scans for `Safera Sense`, subscribes to `0000BEEF-…` and prints decoded frames. Reference
  implementation of the decoding (flip `print_bit` / `print_all` in `decode_env1` to probe bytes).
  Note it will fight the integration for the hood's single connection slot — stop one or the other.
- **Deploy to Home Assistant and read the log.** The details below are what make this bearable.
- **Read entity history** via `/api/history/period`. For questions about *values* (did `fan` change
  when I turned the fan on?) this beats sampling the log: it survives BLE disconnects and is already
  deduplicated. Reach for it first when correlating a physical action with a sensor.

### Deploying

Copy `custom_components/safera/` into the HA config directory and **restart Home Assistant**.
Reloading the config entry is *not* enough — Python does not re-import a changed module, so a reload
silently runs the old code. Every code change needs a full restart; only config-entry state changes
can be tested with a reload.

### Reading the log

- `/api/error_log` was **removed** in recent HA versions (returns 404). Use the Supervisor proxy:
  `GET /api/hassio/core/logs?lines=N`, which returns the raw core log including DEBUG lines.
- Turn on debug at runtime with the **`logger.set_level`** service — no YAML edit, no restart:
  `{"custom_components.safera": "debug"}`. It resets on every restart, so re-apply it after one.
- Keep `custom_components.safera.sensor` at `info`. HA reads entity properties constantly and
  debug there is pure noise.
- Raw frames have their own logger, `custom_components.safera.coordinator.frames`, so payloads
  can be captured without enabling debug for everything else. See `captures/`.

### Is it the code or the transport?

Most "it stopped updating" symptoms in this integration have turned out to be BLE transport
problems, not bugs. Before debugging the code, rule that out:

- **A clean `disconnected` with no GATT error means the remote end closed the link deliberately** —
  another client took the hood's single connection slot, or the bluetooth proxy's tunnel collapsed.
  RF failure looks different: GATT errors, timeouts, `error=133`.
- **If an ESPHome bluetooth proxy is in the path, its self-reported WiFi signal is misleading.** It
  reports what it *hears from* the access point, which is flattered by the AP's stronger transmitter.
  Check what the AP hears *from it* — that is the direction that fails. A gap of 25+ dB between the
  two is normal and the lower number is the real one.
- Proxy WiFi drops take every BLE connection tunnelled through them down too, so a hood disconnect
  can have nothing to do with the hood.

## Architecture

Flow: BLE advertisement → config flow → coordinator holds a persistent connection → notifications
push data → sensor entities read from `coordinator.data`.

- **The hood advertises as `Roroshetta Sense`, not `Safera Sense`.** Røroshetta units are rebadged
  Safera hoods — this one reports manufacturer Safera Oy, model IFU10CR-PRO — so the integration is
  named for the manufacturer but **must keep matching the Roroshetta local name**, or discovery
  breaks entirely. `ADVERTISED_NAMES` in `const.py` and the `manifest.json` matchers list both.
- **Discovery is passive, data collection is not.** `manifest.json` declares several bluetooth
  matchers (service UUID `0000f00d-…`, local name, manufacturer id 1837). HA only uses these to
  trigger the config flow; the actual values come from a *connected* GATT notify subscription on
  `BEEF_CHARACTERISTIC` (`0000beef-…`), not from advertisement data.
- **`coordinator.py` is deliberately not a polling coordinator.** It subclasses
  `DataUpdateCoordinator` with `update_interval=None` and never implements `_async_update_data`.
  Instead `async_start_notify()` spawns `_run_notify_loop()`, a long-lived task that: resolves the
  `BLEDevice` from HA's bluetooth cache each iteration, connects via `bleak_retry_connector`'s
  `establish_connection` (falling back to raw `BleakClient` if the helper is missing), subscribes,
  then blocks on `stop_event | disconnect_event` and reconnects with exponential backoff capped at
  30s. Every notification calls `_parse_data()` then `async_set_updated_data()` to push entities.
  The manifest is `local_push` and `appropriate-polling` is marked exempt to match.
- **Pairing is a one-time dance.** The device must be put into pairing mode by a physical button.
  The config flow has a dedicated `pair` step that waits ~5s after the user confirms; the coordinator
  additionally sleeps `PAIRING_WINDOW_SECONDS` before the first connect and calls `client.pair()` once;
  only after `start_notify` succeeds does it persist `DATA_PAIRED_ONCE` into the config entry data, so
  later restarts skip both the delay and the pair call. Preserve this flag when writing entry data.
- **`entry.runtime_data` is the coordinator** (typed via `type SaferaConfigEntry =
  ConfigEntry[SaferaDataUpdateCoordinator]` in `coordinator.py`) — no `hass.data[DOMAIN]`.
- **The BLE link is held open permanently, by design.** The hood almost certainly accepts one
  central at a time, so while HA is running the Safera phone app cannot connect. This was considered
  and accepted (2026-08-27): the app was only ever a debugging tool, and log/data access through HA
  replaces it. Do not add connection-sharing or idle-release logic on the assumption that app access
  matters — it does not.
- **Availability is connection state, not `last_update_success`.** On a push coordinator with no
  `_async_update_data`, `last_update_success` is `True` forever, so entities would show stale values
  as live. `coordinator.device_available` instead requires an active connection plus a notification
  newer than `STALE_AFTER_SECONDS`, and `_set_connected()` calls `async_update_listeners()` on
  transition so entities re-render the instant a link drops. Caveat: staleness alone does not
  self-trigger a re-render — only connect/disconnect pushes do.
- **Eight platforms: `binary_sensor`, `button`, `fan`, `light`, `number`, `select`, `sensor`,
  `switch`.** All but `sensor.py` share `entity.py`'s `SaferaEntity` for device wiring and
  availability. `sensor.py` deliberately does **not** use it — its entities predate the base and
  switching them over risks changing unique ids or names, which would orphan history. New platforms
  should use it.
- **The controls mirror the Safera app's own two columns**, decided 2026-09-08 from a screenshot of
  it. The app shows ventilation as `OFF 1 2 3 4 Auto` and light as `OFF 1 2 3 Auto`, each a single
  selector, plus a separate colour swatch. So:
  - the **fan** is four levels via `percentage` plus `Auto` as a `preset_mode`;
  - the **light** keeps brightness and colour, and carries the presets and `Auto` as *effects*;
  - a **`Light mode` select** carries the same column again — `Off`, `Preset 1-3`, `Auto`.
  - the two auto-mode **switches were removed**. Auto is a position on each selector, as in the app.

  The select is not redundant with the light's effects. **Home Assistant hides a light's `effect`
  attribute while the light is off**, and the hood's lamp is off most of the time, so light auto
  would have been both invisible and unselectable in exactly the state you most want to check it.
  `preset_mode` has no such rule, which is why the fan needs no equivalent. Verified on the hood:
  with the lamp off and `@60` bit 1 set, `light.effect` read `None` while the select read `Auto`.

  Removing the switches orphaned `switch.safera_sense_fan_auto_mode` and
  `switch.safera_sense_light_auto_mode` and their history. That was a deliberate call.
- **`EntityCategory` is the only thing that groups entities on the device page**, and the four
  groups — Controls, Sensors, Configuration, Diagnostic — are hardcoded in the frontend. There is no
  way to add a fifth or name your own; sub-devices via `via_device` or a dashboard card are the only
  routes to arbitrary grouping. So:
  - `number.py` and `select.py` are **`CONFIG`**. Everything on them writes a byte into the hood's
    200-byte settings block, which is configuration, not something you operate. `number.py` defaults
    the whole table on `SaferaNumberDescription` rather than repeating it fourteen times.
  - `light`, `fan`, `switch` and `button` stay **uncategorised** so Controls holds the five things
    you actually use.
  - Diagnostics are set per description in `sensor.py`.

  Until 2026-09-08 nothing declared `CONFIG`, so the device page showed three groups and all
  fourteen settings entities sat in Controls next to the light and fan. `number.py` even set
  `entity_category=None` explicitly on the fan presets. An explicit `None` silently overrides the
  table default and is invisible — the entity still works — so `tests/test_entity_category.py`
  guards against it.
- **`parser.py` holds the frame decoding and imports neither Home Assistant nor bleak.**
  `coordinator._parse_data` is now just "call `parse_frame`, copy the fields onto `self.data`". That
  split is what makes the decoding testable — see "Tests" below — so keep new offsets in `parser.py`
  and resist pulling anything HA-shaped into it. It raises `ValueError` on a frame shorter than
  `FRAME_MIN_LENGTH` (61) rather than returning junk; the old guard was `< 60`, which let a 60-byte
  frame through and then read `auto_flags` off an empty slice as 0.
- **`sensor.py` is table-driven.** Each sensor is a `SaferaSensorEntityDescription` with a
  `value_fn(coordinator)`; adding a sensor means adding a field to the `SaferaData` dataclass,
  a decode line in `_parse_data`, and one entry in the `SENSORS` tuple.

## The BLE payload

**Real frames are 69 bytes, arriving about once per second.** `test.py`'s docstring claims "≈ 54
bytes" and `_parse_data` guards on `len(data) < 60` — both were written before anyone measured, and
both are wrong. Highest mapped offset is 59; bytes 60-68 are still largely unexplained.

`_parse_data` decodes the frame little-endian by hardcoded offsets, mirroring `decode_env1` in
`test.py`. **Keep `test.py` and `coordinator._parse_data` in sync** — if you change a scaling factor
or offset in one, change it in the other, and validate against a live device before trusting a new
mapping.

To capture frames, switch on the dedicated frame logger
(`custom_components.safera.coordinator.frames` → `debug` via the `logger.set_level` service)
and grep the core log for `coordinator.frames`. See `captures/` for tooling, stored captures, and a
per-byte analyser that labels each offset with the field currently read from it.

`captures/gatt.md` holds the hood's full GATT table, dumped 2026-08-28, together with the command
protocol from [magicus/safera-ble](https://github.com/magicus/safera-ble/discussions/1) — an
independent reverse-engineering of the same device. Two things there matter
beyond reference value: **the hood stops advertising entirely while a central is connected**, so
nothing else can scan it while the integration runs (disable the config entry first); and
**writable characteristics do exist**, and BLE control is no longer theoretical — a command has
audibly run the fan.
Commands go to `babe` as a 4-byte LE code plus a 4-byte LE parameter, and **this has been tested on
the real hood** — see "Controlling the hood" below. Do not touch the Nordic DFU service at
`0000fe59-…`; it is the firmware bootloader.

### What the hood actually is

Safera Sense is a **stove guard first** and an air-quality sensor second. Its safety function cuts
power to the cooktop when something on the plate stays too hot for too long. That subsystem is what
most of the unexplained bytes belong to, and knowing it is what made them decodable — read the
frame as "hazard interlock plus environment", not "hood telemetry".

The mechanism, confirmed against a live cooking session: **`alarm_level` accumulates while the hob
draws power, `activity` (presence at the hob) knocks it back down, and an alarm fires if
`alarm_level` passes a threshold with no `activity`.**

### Confirmed by the 2026-08-28 cooking session

A full session (frying an egg, 2871 frames, 53 min, hob 11:31:41–11:39:57) settled the three
offsets that were previously marked unsure, and corrected one that was wrongly assumed dead:

- **`power` @46-47 is genuinely mains power in watts, u16 LE.** 0 → 2660 W, every observed value a
  multiple of 20 W, nonzero for exactly the span the hob was on and zero on both sides. It had read
  a constant 0 in every earlier capture **only because nobody had ever turned the hob on while
  capturing** — do not conclude a field is dead from idle data alone.
- **`alarm_level` @44 is the interlock integrator, gated on hob power.** Mean 1.58 while the hob
  drew power vs 0.00 while it did not; of 854 hob-off frames only 3 were nonzero, all value 1 and
  all the tail of a decay. It climbed 1 → 17 over ~65 s of unattended cooking, then a presence
  spike drove it to 0 within 19 s. 83% of its increments occur while `activity` ≤ 1. It ramps and
  decays in steps of 1 at roughly 3 s intervals. **Peak ever observed is 35, so the trip threshold
  is unknown.** `magicus/safera-ble` documents it as a percentage, which our data neither confirms
  nor contradicts — never seeing it above 35 says nothing about the top of the scale.
- **`activity` @45 is a presence detector with strict linear decay.** Impulse up on presence, then
  **every single decrement is exactly −2** (70 of 70 in this session, 594 of 594 on 2026-08-27).
  Peak observed 100.
- **`grease_filter` @59 is a slow monotonic counter.** Constant within any one capture, but the HA
  recorder shows 20 → 21 (08-27 14:43 UTC) → 22 (08-28 05:44 UTC): about 1 per 15 h, extrapolating
  to ~62 days for 0 → 100. Consistent with filter saturation in percent.
- **Byte 43 is a cooking-session latch**, `Activity Type` in `magicus/safera-ble`'s table. It
  flipped 0 → 2 on the exact frame `power` first went nonzero, held at 2 through the whole session,
  and cleared back to 0 at 11:54:42 — ~15 min after the hob went off and ~10 min after the fan
  stopped. Not decoded by either parser.
- **`heat_index` @2-3 is misnamed** — it is Surface Temperature, which `magicus/safera-ble`
  confirms independently. Ambient `temperature` @0-1 moved only 21.5 → 21.8 °C across the
  session while @2-3 went 23.4 → 28.0 and correlates with hob power at +0.39. A true heat index at
  21.7 °C / 52% RH is ~21.7, not 28. @2-3 is a second heat measurement, most plausibly the stove
  guard's IR sensor aimed at the hob — which also explains why it jumps when a person stands in
  front of it. The name is inherited from `test.py` and should not be trusted.
- Light and fan came on **one second after** the hob drew power and switched off together 4.5 min
  after it stopped, which looks like auto-start and run-on rather than button presses. Data cannot
  distinguish the two; do not assume a control change was user-initiated.

### Fields taken from crillebaba/safera-sense-ble

An independent integration for the same hardware, found 2026-09-05:
[crillebaba/ha-safera-sense](https://github.com/CrilleBaba/ha-safera-sense) plus its
`safera-sense-ble` PyPI library. It decodes several bytes this component did not, all now added as
diagnostics: `voc_index @14`, `accessories @25`, `battery @26`, `alarm_status @28`,
`sensor_errors @34-35`, `pcu_errors @40` and `activity_type @43`.

`@25`, `@26`, `@34-35` and `@40` are **constant in every frame ever captured here** — 1, 100, 0 and
0. That is the argument for surfacing them rather than against it: this file is a monument to
constant bytes that turned out to be alive the moment the right thing happened, `power @46-47` most
embarrassingly.

Two of its decodes do **not** survive our data and were not adopted: `@14` as `/20` "UBA index 1-5"
(see above) and `heat_index = @24 × 2`, which puts the value at 22-152 °C. Its ambient light at
`@6-7` is also unsigned, which is the bug fixed here on 2026-08-31.

Worth knowing about it beyond the fields: it keeps the BLE protocol in a **separate PyPI package**,
which is the architecture Home Assistant actually wants, and it reads a **WiFi status
characteristic** we have never touched.

### Where the external table disagrees

[magicus/safera-ble](https://github.com/magicus/safera-ble/discussions/1) documents a "54+ byte"
payload and stops at offset 47. Our frames are consistently 69 bytes and carry `light@53`,
`fan@56` and `grease_filter@59`, which its table does not mention at all — most likely a different
firmware generation (this hood reports hardware 3.2.255.0, firmware 13, software 75). Two of its
offsets do not survive contact with our frames, so **prefer the measured values here**:

- ~~its particle index at `@12-13 / 5`~~ **it was right and we were wrong.** A 2026-08-31 app
  screenshot shows PM2.5 = **0** while our `@13 / 1000` read 2.56. Byte 13 is zero in all 12604
  frames ever captured, so that decode really computed `byte14 × 0.256` and invented three decimals.
  `pm25` is now `@12-13 / 5`, and a cooking session on 2026-08-31 validated the scaling too: it
  peaked at **40.4 µg/m³** while frying and settled back to 1-3, which are sensible magnitudes.
  Incidentally `aqi` at `@10-11` tracks the same quantity one update behind — the raw particle
  sequence 100, 80, 78, 162, 128, 202 reappears as AQI one sample later — so the index is derived
  from the particle reading with a lag;
- its heat index at `@24 × 2` gives 48 °C, which is not credible.

Everything else it lists agrees, including several of our constant bytes: `@26` battery (100),
`@28` alarm status (1), `@33` device state (2), `@34-35` sensor error bitmask (0).

### Still open

- **`@14` is a coarse tVOC band index.** Across all 16202 recorded frames it takes 16 distinct
  values from 10 to 25, and each one maps to a clean, non-overlapping tVOC range — 10 covers
  everything up to ~48 µg/m³, then roughly 30-40 µg/m³ per step, up to 25 at ~530-560. Strictly
  monotonic, so it is derived from tVOC. The *scale* is unknown, so it is exposed raw as
  `voc_index`. `crillebaba/safera-sense-ble` reads it as `byte / 20` and labels it a UBA index 1-5,
  which our data contradicts flatly: that would put every frame ever captured between 0.5 and 1.25.
- Bytes 61-68 are static at `00 00 00 00 00 00 00 ff` and unexplained.
- ~~Bytes 6-7~~ **resolved and exposed**: ambient light, `value / 32` lux — and **signed**. Proved
  by switching the kitchen lights off: 55 lux with room and hood lamp, 20 with the hood lamp alone,
  and in true darkness `0xffd8` = **−40**, about −1.25 lux. Read unsigned that becomes 2047 lux, the
  exact opposite of the truth, so darkness looked like glare. 446 frames in the existing captures
  were already above 32767, which means earlier "ambient light" figures quoted here — including a
  mean of 108 lux — were computed partly from nonsense. Negative illuminance is meaningless so the
  sensor floors at zero.

  The lesson: three independent lines of evidence agreed on the unsigned read — the external table,
  the hood lamp lifting the value, and the shadowing when someone stands at the hob — because every
  observation had been made in a lit room. Only the untried condition exposed the sign.
- **`@29` is pitch and `@31` is roll**, both signed int8 degrees, and **`@8` is the configured
  mounting height in cm** — the same value the settings block holds at `@41`. Pitch and roll are
  live accelerometer readings: `@29` jitters across 181-183 frame to frame, and it shifted from
  ~172 (−84°) on 2026-08-27/28 to ~182 (−74°) by 08-31, so the mounting is not fixed and a knock
  would show up here.
- **`@58` is the Motor 2 speed**, the counterpart to `@57`'s Motor 1. During a 2026-08-31 session
  the fan walked all five levels and `@57` reproduced the Motor 1 preset table (`dcba @86-91`) while
  `@58` reproduced the Motor 2 table (`@93-98`) exactly, including values edited in the app. That
  also re-proves the preset tables drive the hardware.
- **`@24` is a scaled restatement of hob heat**, about 6 counts per °C, correlating +0.99 with
  surface temperature. Whether it is absolute surface temperature or surface-above-ambient cannot be
  separated yet — ambient moved only 1 °C across the session, so both fits are equally good. It is
  **not** the external table's "heat index × 2", which would put it at 22-152 °C.
- Bytes 24-35 are near-constant in normal running, but **`@28` and `@33` are the alarm state
  machine** and both move on a trip — do not assume a constant byte is dead, which this whole file
  is a monument to. Byte 9 and byte 52 vary slightly and are unexplained.
- **Byte 53 is the light preset as `preset × 30`, and that is the only encoding.** It was believed
  to carry two, because `CMD_LIGHT_PRESET` was being sent the bare preset index and the hood was
  faithfully storing our mistake. Measured 2026-09-08: params 30, 60 and 90 produced 56%/2790 K,
  20%/2970 K and 100%/2943 K — this hood's three stored presets exactly — while 1, 2 and 3 all lit
  the lamp at the same fallback around 56%/2790 K. The parser now divides by 30 flat; a value below
  one step is not a preset.

  **This hid for weeks because `light.py` overwrote brightness and colour by hand immediately after
  selecting the preset.** The lamp always looked right, so nothing pointed at the preset command.
  It also explains the old note that "the light's intermediate steps have never been observed from
  the hood's own controls": `@53` only ever read 0 or 90 from the hood because the hood uses presets
  properly, and the 1s and 2s in our captures were ours.
- The fan's steps were seen during the 2026-08-31 taco session, where auto mode walked `@56` through
  30, 60, 90 and 120 with `@57` reading raw speeds 23, 26, 36 and 82 — markedly non-linear, and all
  well below the 0-255 range a raw speed command can reach.


**tVOC's unit is µg/m³, not ppb.** The app displays "16 tVOC µg/m³" for the value our frames carry,
so our declaration is right and the external table is wrong on this firmware. Confirmed 2026-08-31,
after being marked unconfirmed since the beginning.

**Air quality can look frozen when the air is simply clean.** On 2026-08-31 AQI, tVOC, CO₂ and byte
14 each held one value for 2.5 hours (3, 16, 427, 10), which looked like a stalled sensor. A cooking
session that afternoon moved all of them hard — AQI 3 → 202, tVOC 16 → 2417, PM2.5 0 → 40.4 — so
nothing was wrong. Judge a sensor stuck only after something that should move it does not.

**tVOC distinguishes frying from boiling; particles do not.** A frying session peaked at tVOC 2417
and PM2.5 40.4; making jam the same evening peaked at tVOC 83 and PM2.5 **48.4**. So particles come
from both, and a prediction that boiling would be low-particle was wrong — tVOC is the field that
responds to fats.

Values confirmed plausible on a real device: temp 23.4 °C, humidity 49 %, CO₂ 657 ppm, PM2.5
6.1 µg/m³, AQI 22, uptime 3287464 s (~38 days). Note `uptime` is read as a 3-byte LE value via
`get_u16_le(36, 3)` despite the helper's name.

## Controlling the hood

**Light, fan and the grease filter reset all work over BLE**, confirmed against the real hood on
2026-08-28 with someone standing at it. Commands go to `babe` as a 4-byte LE code plus a 4-byte LE
parameter; the codes live in `const.py`.

| what | command | parameter | feedback |
|---|---|---|---|
| light preset | `0x2005` CMD_LIGHT_PRESET | **preset × 30**, 0 off | `@53`, same encoding |
| light brightness | `0x2006` CMD_LIGHT_BRIGHTNESS | 0-255 | `@54`, exact |
| light colour | `0x2007` CMD_LIGHT_COLOR | 0-255, warm to cool | `@55`, exact |
| fan level | `0x2001` CMD_MOTOR_SPEED_STEP | **level × 30**, 0 stops, max 120 | `@56` level, `@57` speed |
| fan speed | `0x2002` CMD_MOTOR_RAW_SPEED | 0-255, 0 stops | `@57`, but `@56` goes stale |
| filter reset | `0x2009` CMD_FILTER_CHANGED | 0 | `@59` drops to 0 |
| fan auto | `0x2004` CMD_MOTOR_AUTO_MODE | 1 arm, 0 disarm | `@60` bit 0 |
| light auto | `0x2008` CMD_LIGHT_AUTO_MODE | 1 arm, 0 disarm | `@60` bit 1 |

**`0x2007` is not in `magicus/safera-ble`'s table.** It was found by letting the Safera app change
the colour while the integration was disabled, then reading `babe` back — it holds the last command
written, so the app's own writes can be read straight out of it. That trick is worth remembering
for anything else the app can do and we cannot.

Things that shaped the implementation, all learned the hard way:

- **The light has full feedback on all three channels**, each confirmed 1:1 against commanded
  values. `@54` and `@55` both read **0 while the lamp is off**, so brightness and colour have to be
  remembered across an off/on cycle — the hood also comes back at a dim default. `light.py` keeps
  the last non-zero values and re-applies them on turn-on.
- **Brightness 0 is a dim floor, not off.** Turning the lamp off has to go through the preset
  command. Confirmed by eye.
- **`@56` and `@57` are different things, and which command you send decides whether `@56` stays
  honest.** `@56` is a level index the hood's own controller maintains — it reads 30 with the fan on
  low from the panel. `@57` is the actual motor speed in the same 0-255 units `CMD_MOTOR_RAW_SPEED`
  takes, and it tracked a commanded sweep (0 → 50 → 100 → 180 → 255 → 0) exactly, ramping between
  steps.

  **`fan.py` drives `CMD_MOTOR_SPEED_STEP` (`0x2001`), not the raw command**, because the step
  command's parameter is `level × 30` — the identical encoding `@56` reports back. Driving the raw
  command instead moves the motor while `@56` sits at **0**, because the hood's own controller never
  learns the speed changed, so the panel, the `fan_level` sensor and the hood's automatic mode all
  disagree with reality for as long as HA is in control. That was the old behaviour here and it was
  written off as "not a bug"; it was a consequence of picking the wrong command, and
  `crillebaba/safera-sense-ble` had this right first.

  **Confirmed on the hood 2026-09-08.** Sweeping the command gave an exact result:

  | param | `@56` | `@57` speed | matches preset |
  |---|---|---|---|
  | 30 | 1 | 9 | Motor 1 preset 1 = 9 |
  | 60 | 2 | 18 | preset 2 = 18 |
  | 90 | 3 | 39 | preset 3 = 39 |
  | 120 | 4 | 55 | preset 4 = 55 |
  | 150, 180, 210 | **unchanged** | **unchanged** | ignored |

  So byte 56 now tracks Home Assistant's commands, the `fan_level` sensor is honest while HA is
  driving, and the motor speeds are the stored preset values — the preset table drives the hardware,
  re-proved a third way.

  **There are four levels, not five, and boost is not reachable through `0x2001`.** Params above 120
  are dropped silently: sent with the fan at level 1, it stayed at level 1 each time with no error
  and no change to `@56`. `FAN_LEVEL_COUNT = 5` shipped in v1.1.0 on the strength of the sixth Motor
  1 preset slot at `@91` (boost, 100% on this hood), and that extrapolation was simply wrong — the
  slot exists, the command will not select it. The visible symptom was that asking the fan for 100%
  did nothing at all. Whatever triggers boost is something else; do not raise the count back to 5
  without finding it. `fan.py` now raises rather than sending a parameter the hood would drop.
- **Above roughly 180 the motor is not audibly different**, though `@57` still reports the value.
- **The Kelvin mapping is measured, not assumed.** The app showed 2790 K, 2970 K and 2943 K for
  stored preset bytes 10, 30 and 27 — an exact fit for **`K = 2700 + byte × 9`**. So the lamp runs
  2700 K to 4995 K in 9 K steps, and a requested colour snaps to the nearest step.

### Auto mode, and byte 60

**Byte 60 is an auto-mode bitmask**: bit 0 is fan auto, bit 1 is light auto, so 3 means both armed
and 0 means neither. That finally explains a byte that had defeated two earlier readings.

**Any manual light or fan command disarms the corresponding auto mode** — from Home Assistant, the
Safera app or the hood's own controls alike. Switching the hood light on from HA therefore stops it
auto-starting the next time someone cooks, until the auto switch is turned back on. The two switch
entities exist to make that visible and reversible rather than a silent surprise.

**Arming light auto applies a preset immediately, and that is normal.** Enabling it has been seen
to switch the lamp on about a second later at preset 3 — the Active cooking preset — with no command
from Home Assistant: the logbook records those transitions with no context at all, so the hood is
acting on its own. It does not always fire; on one occasion arming auto left the lamp off. The hood
is evaluating its automation rules the moment it is armed, and the outcome depends on presence and
on whether a cooking session is still latched at `@43`, which holds for ~15 minutes after the hob
goes off. This was mistaken for a fault on 2026-08-31. If it needs investigating again, the two
facts worth recording at the time are whether anyone was near the hood and whether the hob had been
on in the previous fifteen minutes — they separate normal behaviour from a real fault immediately.

This also settles the 2026-08-27 readings that looked contradictory: 3 while idle, 1 with the light
on, 0 with the fan on. Those are not an operating state at all — they are auto bits being cleared by
the manual actions that turned the light and fan on. And it confirms the cooking session
independently: `@60` sat at 3 throughout, so the light and fan really did **auto-start** rather than
being switched by hand.

Finding it needed a known starting state. The earlier attempt diffed the settings blocks around
enabling auto in the app and saw nothing, because our own probes had already left both autos armed —
the app changed nothing. Repeating it from a known-disarmed state made the byte obvious.

### The settings block

`dcba` returns a 200-byte configuration block and `abba` writes into it: **two bytes, an offset then
a value**. That was found the same way as the colour command — `abba` retains the last write, so
after editing a ventilation preset in the Safera app it held `[87, 22]`, and `dcba` byte 87 had
become 22.

Offsets confirmed against the app's own screens:

| offsets | what |
|---|---|
| `86-91` | Motor 1 ventilation presets: level 0, 1, 2, 3, 4, boost. Fraction of **254** |
| `93-98` | Motor 2 presets, same order (Motor 2 is the external blower, unused on this hood) |
| `82-84` | ventilation automation limits, packed as `(max << 4) \| min` — active cooking, after-cooking, no cooking |
| `103-105` | light preset brightness, presets 1-3. Fraction of **255** |
| `107-109` | light preset colour, presets 1-3, as `2700 + byte × 9` Kelvin |
| `111-114` | which light preset each automatic situation uses |
| `133` | ventilation sensitivity, a plain percentage with no scaling |
| `41` | sensor / hood mounting height in cm, mirrored live at payload `@8` |
| `42` | cooker width in cm |

Ventilation sensitivity was pinned down the same way: setting it to 48 in the app changed exactly
one byte in the whole block, `@133`. Three other offsets also happened to read 50 and were ruled out
by the same diff — a reminder that matching a value is a hypothesis, and only a change is evidence.

The preset values as configured on this hood are recorded in `captures/gatt.md` so there is
something to restore from. They are **observed values, not verified factory defaults** — the hood
was in use before any of this began.

`coordinator.async_read_settings()` caches the block, refreshed **once per connection and after
every write** — nothing else changes it, so an edit made in the app appears on the next reconnect.
`async_write_setting()` writes one byte and reads it back, returning what actually landed so a
silently ignored write is distinguishable from one that took. The `number` platform builds eleven
entities on that: ventilation sensitivity, sensor height and cooker width, five Motor 1 presets, and
brightness plus colour for the three light presets. Height and width are **settings**, so they are
editable numbers rather than sensors, even though the payload mirrors the height at `@8`.

**The read is ordered after `_set_connected(True)` deliberately** — `async_read_settings` refuses to
run while the coordinator still counts as disconnected, so reading earlier in the connect path fails
every time.

### The alarm, captured 2026-08-31

A deliberate trip settled every open question about the interlock. **`alarm_level` trips at exactly
100**, so it really is a percentage — but it is **not capped there**, and kept climbing to 107 after
the cooktop had already been cut. The trip is a crossing, not a ceiling.

**Byte 33 is the state machine**, not byte 28 as the external table implies:

| | normal | pre-alarm | cooktop cut | acknowledged |
|---|---|---|---|---|
| `@33` | 2 | **7** | **8** | 2 |
| `@28` | 1 | **118, counting down 1/s** | 0 | 1 |
| `@50` | 1 | **0** | **0** | 1 |
| `power @46-47` | live | live | **0** | restored |

The pre-alarm lasted **exactly 15 seconds** before power was cut — the buzzer window. `@28` counted
down from 118 through it; what it was counting toward is unknown, because the state changed at 104.
Acknowledging at the hood returned `@33` to 2 and `@50` to 1, and the presence spike from walking up
to it (`activity` hit 58) collapsed `alarm_level` from 107 to 0 in about 90 seconds.

The event log recorded it as well, which is what it was added for:

| code | meaning |
|---|---|
| 1, 3 | cooking session start |
| **100** | **OK button pressed** — identified by pressing it and watching the event appear |
| **103** | alarm raised — same second `@33` went to 7 |
| **104** | cooktop cut — same second `@33` went to 8 |
| 6 | after acknowledgement |

**There is no "time since OK pressed" counter on the hood.** It timestamps the press in its own
uptime as code 100, and wall-clock is derived by subtracting from the current uptime — which is
what the `Last OK pressed` timestamp sensor does. It resolves the moment the event arrives and
caches it; recomputing every frame would make the timestamp jitter by a second forever.

Two traps in doing that. The event log is read **on connect, before the first notification has
delivered an uptime to subtract from**, so a press seen there has to be held and resolved when a
frame arrives or it is silently dropped. And the log is a rolling buffer that empties itself, so an
empty read must not wipe what is already known.

`abdf` is **not** where the OK press registers — its six u16 LE counters did not move at all for a
press. They all decrease over days and are still unexplained; the external table's "day statistics"
label does not fit something that counts down.

`alarm_level`'s `PERCENTAGE` unit in `sensor.py` is therefore **correct**, vindicating the external
table over the doubt recorded here earlier.

### The event log

`abcf` is the device event log: **a u16 count followed by 5-byte records of (event code, u32 LE
device uptime in seconds)**. It reads and notifies, so the coordinator subscribes on connect and
logs anything new on `custom_components.safera.coordinator.events`.

It is a rolling or volatile buffer, not a permanent history: it held two code-100 events on
2026-08-28 and read empty (`0000`) three days later, so a baseline reading of zero is normal.

Nothing here is confirmed against a real alarm, because none has ever fired. Other places worth
watching when one does:

- `@28` "Alarm Status" in the external table — a constant **1** in every capture, idle and cooking
- `@33` "Device State" — a constant **2**
- `@43` Activity Type — seen as 0 idle and 2 cooking; an alarm may add a value
- **`power @46-47` dropping to zero while the hob is still switched on** — the actual safety action
- `abcd` (178 bytes) and `abce` (183 bytes), both read+notify and currently all zero, may be a
  longer history that only fills on events

Note "Stove Alarm Stop" is **disabled** on this hood, so an alarm will *not* force ventilation to
preset 0. That side effect is unavailable as a signal unless the setting is turned on.

### Writing commands

`coordinator.async_send_command(code, param)` is the only write path. It resolves the characteristic
object once per connection (`_resolve_command_char`), serialises writes behind a lock, spaces them
by `COMMAND_MIN_INTERVAL_SECONDS`, and raises `HomeAssistantError` rather than failing quietly. The
`safera.send_command` service exposes it raw for experimentation — that is deliberate while the
command set is still being mapped, and it is how everything above was discovered without a redeploy
per attempt.

**Do not write from a boot-time experiment.** Writing seconds after `start_notify` returned
`[Errno 104] Connection reset by peer`, dropped the link and left every entity unavailable until a
restart; repeated restarts compound it, because the hood accepts one central at a time and each
restart re-takes the slot. Let the link settle, then drive writes on demand.

## Traps that already bit this code

Four bugs here cost real debugging time and are easy to reintroduce:

- **`asyncio.wait()` requires tasks.** Passing bare coroutines raises `TypeError: Passing coroutines
  is forbidden` on Python 3.11+. It fired every connection right after `start_notify`, got swallowed
  by the loop's broad `except Exception`, and disconnected — so exactly one frame arrived and the
  integration looked like it "fetched once then stopped".
- **`BleakClient.set_disconnected_callback` no longer exists** (removed in bleak 0.19). The old code
  guarded it with `hasattr`, so it silently did nothing and dropped links were never noticed. The
  callback must be passed to `establish_connection(...)` / `BleakClient(...)` at construction.
- **`info` from this component is invisible at Home Assistant's default log level.** Twice now a
  failure has hidden there: the settings read that left eleven entities unavailable with no visible
  cause, and event-log lines that never appeared. Anything that must be noticed without someone
  having turned debug on first has to be `warning`.
- **`write_gatt_char` by UUID string can fail while notifications on the same service work.**
  Writing to `"0000babe-…"` raised `BleakCharacteristicNotFoundError` on connections where
  `start_notify` on `beef` — same service — was streaming fine, which is the signature of a partial
  cached GATT table. Resolve the characteristic object by walking `client.services`, or write to its
  handle (`babe` is 42).

The broad `except Exception` in `_run_notify_loop` is what turned the first two into silent
misbehaviour rather than a traceback. Be suspicious of it when a symptom looks like "works once,
then nothing".

## Tests

`pytest` from the repo root. **No Home Assistant, no bleak, no hardware** — `tests/conftest.py`
loads `parser.py` and `const.py` by file path, which works precisely because neither imports
anything HA-shaped. `.github/workflows/tests.yaml` runs the same command on every push.

53 tests covering the decoding, the discovery matchers and entity categorisation. Several are regression guards for bugs
that actually happened here, and those are the ones worth not deleting:

- signed illuminance — an unsigned read turns a dark kitchen into 2047 lux
- the 60-byte frame that used to pass the length guard and silently read `auto_flags` as 0
- `level × FAN_LEVEL_STEP` round-tripping through byte 56, which is the whole reason the fan uses
  the step command
- byte 53's two encodings both decoding
- `Roroshetta` matching and `Røroshetta*` **not** matching, asserted in both directions
- the manifest's `local_name` matchers agreeing with `ADVERTISED_NAME_PATTERNS`
- no settings entity carrying `entity_category=None`, which drops it back into Controls

The recorded frames in `tests/test_parser.py` are four real payloads — idle, cooking, pre-alarm and
cooktop-cut. They are deliberately a handful and not a capture: the repo is public and captures stay
in `~/priv/roroshetta-captures/`. They earn their place because a purely synthetic suite would pass
happily against a decode that had drifted from the device.

**These tests say nothing about entity behaviour.** Anything that imports Home Assistant — the
platforms, the config flow, the coordinator's connection loop — is still untested, and would need
`pytest-homeassistant-custom-component`.

## Verifying a change without hardware

`homeassistant` and `bleak` are not installed locally, so `coordinator.py` cannot simply be imported.
The workable pattern is to stub both module trees in `sys.modules` (each stub needs `__path__ = []`
to act as a package, and the `DataUpdateCoordinator` stub needs `__class_getitem__` to be
subscriptable), then load `coordinator.py` by file path under a synthetic package whose `__path__`
points at the component directory — that satisfies `from .const import ...` without executing
`__init__.py`. A fake client that streams N notifications then fires its `disconnected_callback` is
enough to exercise connect, stream, disconnect, reconnect and shutdown timing.

This proves control flow only. It says nothing about byte offsets, which need a real device.
