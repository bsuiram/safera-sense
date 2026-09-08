# Safera Sense

A Home Assistant integration for **Safera Sense** kitchen hoods and stove guards, including the
**Røroshetta Sense** rebadges sold in Norway. It talks to the hood over Bluetooth LE — no cloud, no
account, no bridge.

Røroshetta units are rebadged Safera hardware (this one reports manufacturer Safera Oy, model
IFU10CR-PRO), so the integration is named for the manufacturer but discovers **both** advertised
names. If your hood shows up as `Roroshetta Sense`, that is expected.

## What you get

The hood pushes a status frame about once a second, so everything below updates live rather than on
a poll interval.

**Sensors** — temperature, humidity, CO₂, tVOC, PM2.5, air quality index, illuminance, hob surface
temperature, mains power drawn by the cooktop, grease filter saturation, stove-guard alarm level and
presence/activity, light and fan state, pitch and roll, device uptime, and the time the OK button
was last pressed. Plus diagnostics: battery, VOC index, alarm status, sensor and PCU error
registers, and connected accessories.

**Binary sensors** — stove alarm, whether the hood has cut power to the cooktop, and whether a
cooking session is currently latched.

**Controls**

| entity | notes |
|---|---|
| Light | on/off, brightness, and colour temperature (2700–4995 K, in 9 K steps) |
| Fan | on/off and four speed levels, using the hood's own level command so its panel and automatic mode stay in step. Boost is not reachable over BLE |
| Fan auto / Light auto switches | the hood's own automation; see the warning below |
| Reset grease filter | button |
| 13 number entities | ventilation sensitivity, sensor height, the five Motor 1 ventilation presets, and brightness + colour for the three light presets |
| Cooker width | select |

The numbers and the cooker width write into the hood's own settings block, so they appear under
**Configuration** on the device page rather than mixed in with the controls.

Two services, `safera.send_command` and `safera.write_setting`, expose the raw BLE command and
settings-block channels for anyone who wants to poke at parts of the protocol that do not have an
entity yet.

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Three-dot menu → **Custom repositories**.
3. Repository `https://github.com/bsuiram/safera-sense`, type **Integration**. Add.
4. Find **Safera Sense** in HACS and download it.
5. **Restart Home Assistant.** A config-entry reload is not enough — Python will keep running the
   old module.

### Manually

Copy `custom_components/safera/` into your Home Assistant `config/custom_components/` directory and
restart. If you have previously installed it this way, remove that copy before switching to HACS —
otherwise the two fight over the same directory.

## Setup and pairing

Home Assistant should discover the hood on its own once the integration is installed; if not, add
**Safera Sense** from Settings → Devices & services.

Pairing is a **one-time** dance and needs someone standing at the hood:

1. Start the config flow and pick your hood from the list.
2. When the flow asks, press the **pairing button on the hood** to put it into pairing mode.
3. Confirm. The integration waits a few seconds, pairs, and subscribes.

After that it reconnects by itself on every restart — the flow records that pairing succeeded and
skips both the wait and the pair call from then on.

## Things worth knowing before you install

- **The hood accepts one Bluetooth connection at a time, and this integration holds it open
  permanently.** While Home Assistant is running, the Safera phone app cannot connect. That is a
  deliberate trade: everything the app showed is available as entities instead. If you need the app,
  disable the config entry first.
- **The hood also stops advertising while a central is connected**, so nothing else can even scan
  for it in the meantime.
- **Turning the light or fan on manually disarms the hood's corresponding auto mode** — from Home
  Assistant, from the app, or from the hood's own buttons alike. The two auto switches exist so that
  is visible and reversible rather than a silent surprise.
- **Arming light auto can switch the lamp on a second later.** The hood evaluates its automation
  rules the moment it is armed, and will apply a preset if it thinks cooking is in progress. This is
  normal, not a fault.
- A Bluetooth proxy works fine and is how this is usually deployed. If entities go unavailable, the
  proxy's link is a more likely culprit than the hood.

## Requirements

- Home Assistant 2024.12 or newer
- A Bluetooth adapter or an ESPHome Bluetooth proxy within range of the hood

## How this works

The BLE protocol is not documented by the manufacturer; all of it was reverse-engineered against a
real hood. `captures/gatt.md` holds the full GATT table, the command codes, the 200-byte settings
block layout and the per-byte meaning of the status frame, including which parts are still unknown.
`CLAUDE.md` records how each field was established and which earlier guesses turned out to be wrong.

Credit to [magicus/safera-ble](https://github.com/magicus/safera-ble/discussions/1) for an
independent decoding of an earlier firmware, which several offsets here were checked against, and to
[CrilleBaba/ha-safera-sense](https://github.com/CrilleBaba/ha-safera-sense) — an independent
integration for the same hardware, which decodes several bytes this one had left alone and got the
fan's command choice right before this did.

## Development

`pytest` from the repo root runs the test suite. It needs neither Home Assistant nor a Bluetooth
adapter — the frame decoding lives in `custom_components/safera/parser.py`, which deliberately
imports nothing from either, so it can be tested directly against recorded frames.

## Status

Working, and in daily use on one hood — firmware 13, software 75, hardware 3.2.255.0. Some bytes of
the status frame are still unexplained and a different firmware generation may well disagree with
this decoding. Issues and captures welcome.

## Licence

MIT. See [LICENSE](LICENSE).
