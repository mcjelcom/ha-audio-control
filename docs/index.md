# Audio Control for Home Assistant

Turn your **multi-room amplifier** into something you can control from your phone,
your dashboard and your automations — switch zones on and off, change the volume and
the music source, all from Home Assistant.

[Quickstart →](quickstart.md){ .md-button .md-button--primary }
[Full step-by-step guide](getting-started/prerequisites.md){ .md-button }

![Your zones on a Home Assistant dashboard](assets/screenshots/dashboard.png)

## How it works

![How it works: phone or browser, Raspberry Pi with Home Assistant, USB-RS232 adapter, serial cable, amplifier, zones](assets/diagrams/how-it-works.svg)

Home Assistant talks to your amplifier through its **RS-232 control port** (a small
9-pin connector on the back). Every zone becomes its own player in Home Assistant.

## Works with

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

## What you can do

- **Switch each zone on and off**, change **volume**, **mute**, and pick the **source**
- **Bass and treble** on amplifiers that have them
- **All zones off** with one tap, and **group mode** (every room plays the same thing)
- Changes made on the amplifier's own keypads show up in Home Assistant too
- Use your zones in **automations** — e.g. turn everything off at midnight
