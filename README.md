# Audio Control — Home Assistant Integration

[![CI](https://github.com/mcjelcom/ha-audio-control/actions/workflows/ci.yml/badge.svg)](https://github.com/mcjelcom/ha-audio-control/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)

Control RS232 and network-attached audio hardware from Home Assistant —
multi-zone amplifiers, integrated amplifiers, receivers, CD players and power
amplifiers — through one profile-driven integration.

**26 device profiles covering 80 models from 11 brands**, with no
per-device Python: a new device is a YAML file.

## 📖 Documentation

**[https://haac.mcjel.com/](https://haac.mcjel.com/)**

| | |
|---|---|
| **New here?** | **[Quickstart — five steps with pictures](https://haac.mcjel.com/quickstart/)** |
| **Step by step** | [What you need](https://haac.mcjel.com/getting-started/prerequisites/) → [Install Home Assistant](https://haac.mcjel.com/getting-started/install-home-assistant/) → [Install HACS](https://haac.mcjel.com/getting-started/install-hacs/) → [Install Audio Control](https://haac.mcjel.com/getting-started/install-audio-control/) |
| **Remote / several Pis** | [Choose how to install](https://haac.mcjel.com/getting-started/choose-install/) · [Install with balena (preview)](https://haac.mcjel.com/getting-started/install-balena/) — template: [mcjelcom/haac-balena](https://github.com/mcjelcom/haac-balena) |
| **Example** | [AMC X86i, from cable to dashboard](https://haac.mcjel.com/examples/amc-x86i/) |
| **Everyday use** | [Using your zones](https://haac.mcjel.com/using-zones/) · [Phone app](https://haac.mcjel.com/phone-app/) · [Ready-made dashboard](https://haac.mcjel.com/dashboard/) · [Names and settings](https://haac.mcjel.com/configuration/) · [Automations and extra controls](https://haac.mcjel.com/services/) · [Apple Home, Google Home, and Alexa](https://haac.mcjel.com/smart-home/) · [Matter](https://haac.mcjel.com/matter/) · [Help and troubleshooting](https://haac.mcjel.com/troubleshooting/) |
| **Advanced** | [Docker](https://haac.mcjel.com/advanced/docker/) · [Network connections](https://haac.mcjel.com/reference/network-transport/) · [Adding a device](https://haac.mcjel.com/reference/adding-a-device/) · [Protocol types](https://haac.mcjel.com/reference/protocol-types/) |

## Quick install

Audio Control is in the **HACS default store**:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mcjelcom&repository=ha-audio-control&category=integration)

HACS → search **Audio Control** → **Download** → restart → Settings → Devices &
services → **Add integration** → *Audio Control*. New to HACS? Follow
[Getting started](https://haac.mcjel.com/getting-started/prerequisites/).

## Supported hardware

| Manufacturer | Profiles | Examples |
|---|---|---|
| AMC | 9 | X86/X86i, XO, XOir, XGi, X1616e, XAi, XIA, XIA100e/150e, XCDie |
| Rotel | 4 | RA-1572/1592, RSP-1576/1582, RCD-1572, Michi M8/S5 |
| Xantech | 3 | MRC-88, MX88/MX88a, ZPR68-10 |
| Monoprice | 2 | 6-Zone (10761/10762), 31028 Commercial 70V |
| Marantz · NAD · Oppo · RTI · Russound · SpeakerCraft · Yamaha | 1 each | PM7000N/SR, C 368/388, UDP-203/205, AD-4x/8x + AD-810, CAV/CAS/MCA (RNET), MZC-66/88, RX-A/RX-V |

Not listed? The custom-device wizard builds a profile from the UI, or drop a
YAML file into `config/audio_control/` — see [Adding a device](https://haac.mcjel.com/reference/adding-a-device/).

## Development

```bash
make setup   # uv venv --python 3.12 + dev deps
make ci      # ruff (ALL rules) + ruff format + mypy --strict + pytest
```

968 tests, run against Home Assistant 2026.10.2. `ruff` runs with `select = ["ALL"]`, and `mypy --strict` covers the
whole integration including the vendored protocol library.

The docs site is built from `docs/` with [Zensical](https://zensical.org) (`pip install -r
requirements-docs.txt && zensical serve` previews it on `localhost:8000`) and published to
GitHub Pages at [haac.mcjel.com](https://haac.mcjel.com/) by `.github/workflows/docs.yml` on
every push to `main`. Diagrams: edit `docs/diagrams/*.puml`, run `scripts/render-diagrams.sh`.

## Architecture

```
custom_components/audio_control/
├── config_flow.py        UI: setup, custom-device wizard, options, reauth
├── media_player.py       One entity per zone
├── binary_sensor.py      Connection status
├── services.py           Tone and whole-device services
├── dashboard_writer.py   Optional generated dashboard
└── rs232_protocol/       Vendored protocol library, zero HA imports
    ├── connection.py     Transport, framing, retry, reconnect
    ├── protocol_engine.py  Text/ASCII
    ├── binary_engine.py    Binary framing + checksums
    ├── json_engine.py      JSON + authentication
    └── profiles/           26 device profiles
```

`rs232_protocol` has no Home Assistant imports and is usable standalone. It is
vendored rather than published to PyPI because Home Assistant resolves manifest
requirements against PyPI only, so a local distribution could never satisfy them
on a HACS install.

## Release history

| Version | Highlights |
|---|---|
| 2.0.14 | The six automation **blueprints** ship with each release (one copy for HACS docs, the balena template and the deploy) — no code changes |
| 2.0.13 | The dashboard's **Group** button and the group-mode action show their icon (it referenced an icon that doesn't exist, so it was blank) |
| 2.0.12 | AMC: a missed first reply at start-up no longer leaves the amplifier ignoring every command ("Check the device connection") until a reload — found on a real X86i |
| 2.0.11 | The rename form (**Configure**) shows friendly labels — "Zone 1 name", "Source 1 name" — instead of `zone_1` / `source_1` |
| 2.0.10 | Home Assistant's **Documentation** link now opens the user guide at [haac.mcjel.com](https://haac.mcjel.com/) |
| 2.0.9 | RTI power on/off now confirms (it timed out and rolled the zone back); every tone step on Monoprice 6-zone / Xantech MRC-88; a failed power command no longer leaves the zone marked as "known off" |
| 2.0.8 | RTI unit-wide power and status polling now update every zone; AMC XOir absolute tone levels (per manual); every tone step on Monoprice/Xantech (±7); off-zone tone check waits until the zone's state is known |
| 2.0.7 | Fixes from a four-model code review: RTI multi-zone replies no longer mix zones; bass/treble across several zones applies to all valid zones; AMC XO/XOir tone state updates; no "Source 0" for off AMC zones |
| 2.0.5 / 2.0.6 | Verified on a real AMC X86i: accepted tone changes no longer report failure; muting no longer shows a zone as off; clear errors for off-zone tone and unsupported levels; manifest drops `pyserial` (hassfest) |
| 2.0.4 | Bass/treble fixed on Home Assistant 2026.x; ready for HA's move from voluptuous to probatio; tested against HA 2026.10.2 |
| 2.0.3 | RTI (JSON) state follows keypad/unit changes; accepted into the HACS default store |

## Licence

[MIT](LICENSE) © McJEL, LLC
