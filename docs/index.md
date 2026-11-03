# Audio Control for Home Assistant

Turn your **multi-room amplifier** into something you can control from your phone,
your dashboard and your automations — switch zones on and off, change the volume and
the music source, all from Home Assistant.

[Quickstart →](quickstart.md){ .md-button .md-button--primary }
[Full step-by-step guide](getting-started/prerequisites.md){ .md-button }

![Your zones on a Home Assistant dashboard](assets/screenshots/dashboard.png)

## How it works

```
Raspberry Pi with Home Assistant  →  USB-RS232 adapter  →  cable  →  your amplifier
```

Home Assistant talks to your amplifier through its **RS-232 control port** (a small
9-pin connector on the back). Every zone becomes its own player in Home Assistant.

## Works with

| Brand | Models |
|---|---|
| **AMC** | X86 / X86i, XO, XOi, XOir, XGi, X1616e, XAi, XIA100e/150e, XCDie |
| **Monoprice** | 6-Zone (10761 / 10762), 31028 |
| **Xantech** | MRC-88, MX88 / MX88a, ZPR68-10 |
| **Rotel** | RA-1572/1592, RSP-1576/1582, RCD-1572, Michi M8/S5 |
| **Also** | Marantz, NAD, Oppo, RTI, Russound, SpeakerCraft, Yamaha |

Your model not listed? Ask in a
[GitHub issue](https://github.com/mcjelcom/ha-audio-control/issues) — or, if you're
comfortable with a text file, [add it yourself](reference/adding-a-device.md).

## What you can do

- **Switch each zone on and off**, change **volume**, **mute**, and pick the **source**
- **Bass and treble** on amplifiers that have them
- **All zones off** with one tap, and **group mode** (every room plays the same thing)
- Changes made on the amplifier's own keypads show up in Home Assistant too
- Use your zones in **automations** — e.g. turn everything off at midnight
