# Audio Control — Home Assistant Integration

[![CI](https://github.com/mcjelcom/ha-audio-control/actions/workflows/ci.yml/badge.svg)](https://github.com/mcjelcom/ha-audio-control/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)

Control RS232 and network-attached audio hardware from Home Assistant —
multi-zone amplifiers, integrated amplifiers, receivers, CD players and power
amplifiers — through one profile-driven integration.

**26 device profiles covering 80 models from 12 manufacturers**, with no
per-device Python: a new device is a YAML file.

## Supported hardware

| Manufacturer | Profiles | Examples |
|---|---|---|
| AMC | 9 | X86/X86i, XO, XOi, XOir, XGi, X1616e, XAi, XIA100e/150e, XCDie |
| Rotel | 4 | RA-1572/1592, RSP-1576/1582, RCD-1572, Michi M8/S5 |
| Xantech | 3 | MRC-88, MX88/MX88a, ZPR68-10 |
| Monoprice | 2 | 6-Zone (10761/10762), 31028 Commercial 70V |
| Marantz · NAD · Oppo · RTI · Russound · SpeakerCraft · Yamaha | 1 each | PM7000N/SR, C 368/388, UDP-203/205, AD-4x/8x + AD-810, CAV/CAS/MCA (RNET), MZC-66/88, RX-A/RX-V |

Not listed? The custom-device wizard builds a profile from the UI, or drop a
YAML file into `config/audio_control/` — see [Adding a device](#adding-a-device).

## Connection types

The **Connection** field accepts any of:

| Value | Use |
|---|---|
| `/dev/ttyUSB0` | Local USB-serial adapter |
| `socket://192.168.1.50:4999` | Network serial bridge, or a native-IP amplifier |
| `rfc2217://192.168.1.50:4999` | RFC2217 telnet-serial server |
| `demo` | Simulated device — try the integration with no hardware |

`demo` is worth knowing about: it exercises the whole entity layer, so you can
evaluate a profile, build a dashboard, and test automations before the amplifier
arrives.

## Features

- **Per-zone `media_player`** — power, volume, mute, source select, and (where
  the device supports it) transport controls
- **Connection `binary_sensor`** for link health, as a diagnostic entity
- **Services** — `set_bass`, `set_treble`, `all_zones_off`, `group_mode_on`,
  `group_mode_off`, targetable by entity, device, area, floor or label
- **Three protocol engines** — ASCII/text, binary (checksummed, frame-extracted),
  and JSON-over-serial with authentication
- **Optimistic state with rollback** — the UI updates immediately and reverts if
  the device rejects the command
- **Capability-gated controls** — a control appears only if the profile actually
  defines the command behind it, so there are no buttons that silently do nothing
- **Reconnection** with fast-then-slow backoff and half-open link detection

## Installation

### HACS (recommended)

Audio Control is in the HACS default store — no custom repository needed.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mcjelcom&repository=ha-audio-control&category=integration)

1. HACS → search for **Audio Control** → **Download**
2. Restart Home Assistant
3. Settings → Devices & Services → **Add Integration** → *Audio Control*

### Manual

Copy `custom_components/audio_control/` from the
[latest release](https://github.com/mcjelcom/ha-audio-control/releases/latest) into
your `config/custom_components/` directory and restart Home Assistant.

## Configuration

Everything is set up in the UI; there is no YAML configuration.

### Add the device

| Field | What to enter |
|---|---|
| **Device** | The profile for your model, or *>> Custom Device (define via UI)* for the wizard |
| **Connection** | A serial port, `socket://host:port`, `rfc2217://host:port`, or `demo` (see [Connection types](#connection-types)). Detected local ports are listed in the form. |

Zone and source counts come from the profile. One `media_player` is created per
zone, plus a connection `binary_sensor`.

**Tip:** on Home Assistant OS, prefer the stable `/dev/serial/by-id/...` path over
`/dev/ttyUSB0`, which can change between reboots. In Docker, pass the adapter in
with `--device`.

### After setup

| Where | Use it to |
|---|---|
| Device → **Configure** | Rename zones and sources; set the device **username/password** for profiles that log in (e.g. RTI). A blank credential field keeps the stored value. |
| Device → ⋮ → **Reconfigure** | Change the connection (e.g. move from `demo` to the real port) without losing entities or automations |
| Re-authentication prompt | Appears if the device rejects the login; enter the current credentials |

## Services

| Service | Target | Does |
|---|---|---|
| `audio_control.set_bass` | zone entities, devices, areas, floors, labels | Bass `-8`…`+8` in steps of 2 (`0` = flat) |
| `audio_control.set_treble` | same | Treble, same scale |
| `audio_control.all_zones_off` | **none — all Audio Control devices** that support it | Turns every zone off |
| `audio_control.group_mode_on` | **none — all devices** with group support | All zones play `source` |
| `audio_control.group_mode_off` | **none — all devices** with group support | Zones return to independent sources |

Tone and group services only do anything on profiles that support them; power,
volume, mute and source are the standard `media_player` actions.

```yaml
# Kitchen a bit warmer at dinner
- action: audio_control.set_bass
  target:
    area_id: kitchen
  data:
    level: 4

# Everything off at midnight
- alias: Audio off at night
  triggers:
    - trigger: time
      at: "00:00:00"
  actions:
    - action: audio_control.all_zones_off

# Party mode: every zone on source 3
- action: audio_control.group_mode_on
  data:
    source: 3
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Connection sensor **off** / entities unavailable | Port path, cable, and that nothing else holds the port. The integration reconnects with backoff on its own. |
| Entities exist but never change state | Wrong profile or baud rate — the device is ignoring commands or the replies don't match. Try `demo` to confirm the entity layer, then compare the profile with your manual. |
| Controls missing (e.g. no bass) | Intentional: controls appear only if the profile defines the command. |
| Changes made on the device's keypad show up late | Devices that don't push state are polled — every zone every 60 s by default (a profile can shorten this with `serial.heartbeat_interval_s`). |
| Re-authentication keeps appearing | Wrong username/password — set them under **Configure**. |

Debug logging (protocol traffic included):

```yaml
logger:
  logs:
    custom_components.audio_control: debug
```

When opening an issue, attach **Download diagnostics** from the device page —
the connection string and credentials are redacted automatically.

## Adding a device

Three routes, in increasing order of effort:

1. **Pick a shipped profile.** Many devices share a protocol with a listed model.
2. **The custom-device wizard.** Choose *>> Custom Device (define via UI)* and
   fill in the command templates and a status regex. The wizard validates the
   regex before creating the entry.
3. **Write a YAML profile.** Copy `custom_components/audio_control/rs232_protocol/profiles/_template.yaml`
   into `config/audio_control/`, edit it, and restart. It appears in the
   dropdown suffixed `(Custom)`. Full guide: [docs/adding-a-device.md](docs/adding-a-device.md).

Profiles are transcribed from manufacturer RS232 documentation. Contributions
are welcome — please cite the manual and, ideally, confirm against real hardware.
A profile that looks plausible but was never verified is worse than none, because
the controls appear to work.

## Documentation

- [Adding a device](docs/adding-a-device.md) — profile format, placeholders, response mapping
- [Protocol types](docs/protocol-types.md) — text, binary and JSON engines
- [Network transport](docs/network-transport.md) — `socket://` / `rfc2217://`, native-IP amplifiers, serial-to-Ethernet gateways

## Development

```bash
make setup   # uv venv --python 3.12 + dev deps
make ci      # ruff (ALL rules) + ruff format + mypy --strict + pytest
```

877 tests. `ruff` runs with `select = ["ALL"]`, and `mypy --strict` covers the
whole integration including the vendored protocol library.

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

## Licence

[MIT](LICENSE) © John Lin
