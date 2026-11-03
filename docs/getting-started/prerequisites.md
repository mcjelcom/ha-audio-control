# 1. Prerequisites

What you need before installing anything.

## The audio device

Any device on the [supported list](../index.md#supported-devices), or one you can
describe with a [profile](../reference/adding-a-device.md). The device must have an
**RS-232 control port** (usually a DB9 connector, sometimes a 3.5 mm jack or RJ45) or
**network control** (TCP/IP).

Have the device's **RS-232 / IP control manual** at hand — it lists the port settings
(baud rate etc.) and, for the cable, whether it needs a straight-through or null-modem
connection.

## How Home Assistant reaches the device

Pick one:

| Option | You need | Connection value |
|---|---|---|
| **USB-to-RS232 adapter** on the Home Assistant machine (most common) | A USB-to-serial adapter and a cable to the device's RS-232 port | `/dev/serial/by-id/...` (or `/dev/ttyUSB0`) |
| **Serial-to-Ethernet / Wi-Fi gateway** next to the device | A gateway such as an Elfin-EW10, USR-TCP232, Moxa NPort, or Global Cache iTach | `socket://<gateway-ip>:<port>` |
| **The device's own network control** (some receivers / amplifiers) | Nothing extra | `socket://<device-ip>:<port>` |

!!! tip "Choosing a USB adapter"
    Adapters with an **FTDI** chip (FT232R) are the most reliable on Linux. Avoid
    unbranded adapters with counterfeit chips — they are a common cause of "no response
    from device".

!!! info "Straight-through or null-modem?"
    RS-232 cables come in two wirings. If your device's manual does not say which it
    needs, start with a **straight-through** cable; if the device never answers, add a
    **null-modem adapter** (it swaps the transmit and receive pins). A wrong cable damages
    nothing — it just gives no reply.

## Hardware requirements

The standard setup is a **USB-to-RS232 adapter plugged into a Raspberry Pi running
Home Assistant OS**, with a serial cable to the audio device:

```
[Raspberry Pi + Home Assistant OS] --USB--> [USB-RS232 adapter] --DB9 cable--> [amplifier RS-232 port]
```

| Item | Requirement | Notes |
|---|---|---|
| **Raspberry Pi** | **Raspberry Pi 5 or 4** with **at least 2 GB RAM** | Home Assistant's [Raspberry Pi guide](https://www.home-assistant.io/installation/raspberrypi) lists only the Pi 4 and Pi 5. Home Assistant OS still publishes a 64-bit Pi 3 image, but the guide no longer recommends it (1 GB RAM is below the 2 GB minimum); Audio Control itself has been tested on a Pi 3, but Home Assistant is slow there. 32-bit installs are no longer supported |
| **Storage** | microSD card, **32 GB or more**, **A2** rated — or a USB SSD | A USB SSD (Pi 4/5 can boot from USB) is far more durable than an SD card for a system that runs 24/7. Not every USB-to-SATA adapter works |
| **Power supply** | The **official Raspberry Pi power supply** for your model: Pi 5 — 27 W USB-C (5.1 V / 5 A); Pi 4 — 15 W USB-C (5.1 V / 3 A) | Don't use a phone charger or a computer's USB port. An undersized supply causes "undervoltage" — and with it unreliable USB and Wi-Fi, which shows up as a device that randomly stops answering. See [Raspberry Pi's power guidance](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply) |
| **Network** | Ethernet (recommended) or Wi-Fi | Ethernet avoids Wi-Fi dropouts on a device that should always be reachable |
| **USB-to-RS232 adapter** | One per audio device: **USB-A to DB9 male, true RS-232 levels** | Chip: **FTDI FT232R** (recommended), Prolific PL2303, Silicon Labs CP2102 or CH340 — all use standard Linux drivers; FTDI is the most widely used and least trouble |
| **Serial cable** | DB9 cable matching the device's port (straight-through or null-modem — see below), up to ~15 m / 50 ft | Further away? Use a network gateway instead (below) |

!!! warning "RS-232, not TTL"
    Buy a **USB-to-RS232** (DB9) adapter. **USB-to-TTL / UART** adapters (bare pins,
    3.3 V or 5 V, sold for microcontrollers) use different voltage levels and will not
    talk to an amplifier.

Other machines work too — a mini PC, a NUC, or a virtual machine — as long as they run
Home Assistant OS (or Home Assistant in Docker with the adapter passed in) and are within
cable reach of the device.

## A GitHub account

HACS (the community store used to install Audio Control) signs in with GitHub. A free
account is enough.

---

Next: [Install Home Assistant](install-home-assistant.md)
