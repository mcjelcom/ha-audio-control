# Audio Control for Home Assistant

Control your **multi-room amplifier** from Home Assistant: your phone, your dashboard,
and your automations. Switch zones on and off, and change the volume and the music source.

[Quickstart →](quickstart.md){ .md-button .md-button--primary }
[Full step-by-step guide](getting-started/prerequisites.md){ .md-button }

![Your zones on a Home Assistant dashboard](assets/screenshots/dashboard.png)

## How it works

![How it works: phone or browser, Raspberry Pi with Home Assistant, USB-RS232 adapter, serial cable, amplifier, zones](assets/diagrams/how-it-works.svg)

Home Assistant talks to your amplifier through its **RS-232 control port**, a small
9-pin connector on the back. Each zone becomes its own player in Home Assistant.

## What you can do

- **Control each zone**: power, volume, mute, and source. See [Use your zones](using-zones.md).
- **Adjust tone and groups**: set bass and treble, turn all zones off, or play one source everywhere. See [Automations and extra controls](services.md).
- **Use your favorite app**: the [Home Assistant phone app](phone-app.md), [Apple Home, Google Home, or Alexa](smart-home.md), or [Matter](matter.md).
- **Name zones and sources**, such as *Kitchen* and *Radio*. See [Names and settings](configuration.md).
- **Stay in sync**: changes made on the amplifier's keypads appear in Home Assistant.
- **Start with a ready-made dashboard and automations**. See [Ready-made dashboard](dashboard.md) and [ready-made automations](services.md#ready-made-automations-blueprints).
- **Connect by RS232 or your network**. See [Network connections](reference/network-transport.md).
- **Try it first** with a pretend amplifier: type `demo` as the connection.
- **Add an amplifier that isn't listed**. See [Adding a device](reference/adding-a-device.md).
- **Keep it local**: Audio Control talks only to your amplifier, never to the internet.
- **Install your way**: Home Assistant OS or balena. See [Choose how to install](getting-started/choose-install.md).

## Works with

| App or assistant | What you can do | How it connects |
|---|---|---|
| 🏠 **Home Assistant** app & dashboard | Everything — on/off, volume, mute, source, bass & treble, all off, group | Built in |
| 🍎 **Apple Home** & Siri | On/off, volume, mute, source | [HomeKit Bridge](smart-home.md#apple-home-siri) — free |
| 🟢 **Google Home** | On/off, volume — source with a [shortcut switch](matter.md#choose-a-source-one-switch-per-favorite) | [Matter](matter.md) — free |
| 🔵 **Alexa** | On/off, source — volume and mute by voice | [Home Assistant Cloud](smart-home.md#google-home-and-alexa) — paid |
| ⚪ **SmartThings / Aqara** | On/off, volume | [Matter](matter.md) — free |

**[See every detail and what we tested →](compatibility.md)**

## Supported amplifiers

**80 models from 11 brands** — including:

| Brand | Models | Examples |
|---|---|---|
| [AMC](supported-models.md#amc) | 13 | X1616e, X86, X86i, DR-X86T… |
| [Marantz](supported-models.md#marantz) | 5 | PM7000N, SR5015, SR6015, SR7015… |
| [Monoprice](supported-models.md#monoprice) | 8 | 31028, 10761, 39261, 44519… |
| [NAD](supported-models.md#nad) | 4 | C368, C388, C658, M10 |
| [Oppo](supported-models.md#oppo) | 4 | UDP-203, UDP-205, BDP-103, BDP-105 |
| [Rotel](supported-models.md#rotel) | 13 | Michi M8, Michi S5, RA-1572, RA-1592… |
| [RTI](supported-models.md#rti) | 5 | AD-4x, AD-8x, AD-46-100, AD-810-100… |
| [Russound](supported-models.md#russound) | 10 | CAV6.6, CAA66, CAS44, CAS66… |
| [SpeakerCraft](supported-models.md#speakercraft) | 3 | MZC-64, MZC-66, MZC-88 |
| [Xantech](supported-models.md#xantech) | 10 | MRC-88, MRC-88m, MRAUDIO8x8, MX88vi… |
| [Yamaha](supported-models.md#yamaha) | 5 | RX-A1080, RX-A2080, RX-A3080, RX-V685… |

**[See every supported model →](supported-models.md)**
