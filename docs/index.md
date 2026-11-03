# Audio Control for Home Assistant

Control **RS-232 and network audio hardware** — multi-zone amplifiers, integrated
amplifiers, receivers, CD players — from Home Assistant through one profile-driven
integration. A new device is a YAML file, not new code.

[Get started →](getting-started/prerequisites.md){ .md-button .md-button--primary }
[AMC X86i example](examples/amc-x86i.md){ .md-button }

## Supported devices

| Manufacturer | Profiles | Examples |
|---|---|---|
| AMC | 9 | X86/X86i, XO, XOi, XOir, XGi, X1616e, XAi, XIA100e/150e, XCDie |
| Rotel | 4 | RA-1572/1592, RSP-1576/1582, RCD-1572, Michi M8/S5 |
| Xantech | 3 | MRC-88, MX88/MX88a, ZPR68-10 |
| Monoprice | 2 | 6-Zone (10761/10762), 31028 Commercial 70V |
| Marantz · NAD · Oppo · RTI · Russound · SpeakerCraft · Yamaha | 1 each | PM7000N/SR, C 368/388, UDP-203/205, AD-4x/8x + AD-810, CAV/CAS/MCA (RNET), MZC-66/88, RX-A/RX-V |

Not listed? The custom-device wizard builds a profile from the UI, or drop a
YAML file into `config/audio_control/` — see [Adding a device](reference/adding-a-device.md).

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
