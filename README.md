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
| Fan mode | a select with **Off / Preset 1-4 / Auto** — the app's ventilation column |
| Light mode | a select with **Off / Preset 1-3 / Auto** — the app's light column |
| Light | on/off, brightness, color temperature (2700–4995 K, in 9 K steps), and the presets as effects |
| Fan | on/off, a speed slider showing the **real motor duty**, and **Auto / Preset 1-4 / Manual** preset modes. The slider reaches any speed, including the range between level 4 and boost that the hood's own controls cannot select. Boost itself is not reachable over BLE — it is a nine-minute mode started by long-pressing the hood's plus button |
| Reset grease filter | button |
| 13 number entities | ventilation sensitivity, sensor height, the five Motor 1 ventilation presets, and brightness + color for the three light presets (grouped as Light brightness preset 1-3 and Light color preset 1-3) |
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
  Assistant, from the app, or from the hood's own buttons alike. Auto is a position on the **Fan mode** and
  **Light mode** selects, so this is visible and reversible rather than a
  silent surprise.
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

## Upgrading

**1.4.0 renamed nine entity ids** so they match their display names — the light preset numbers,
`light_colour_temperature`, and the two preset-level sensors. Home Assistant does not regenerate an
entity id when an integration renames an entity, so on an existing install these keep their old ids
until you rename them yourself (Settings → Devices & services → the entity → its id). A fresh
install gets the new ids automatically.

**1.2.0 removed the two auto-mode switches.** Auto is now a position on the **Fan mode** and
**Light mode** selects. Automations referencing `switch.safera_sense_fan_auto_mode` or
`switch.safera_sense_light_auto_mode` need updating.

## Status

Working, and in daily use on one hood — firmware 13, software 75, hardware 3.2.255.0. Some bytes of
the status frame are still unexplained and a different firmware generation may well disagree with
this decoding. Issues and captures welcome.

## Licence

MIT. See [LICENSE](LICENSE).
