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

## A way for Home Assistant to reach the device

Pick one:

| Option | You need | Connection value |
|---|---|---|
| **USB-to-RS232 adapter** on the Home Assistant machine (most common) | A USB-to-serial adapter and a cable to the device's RS-232 port | `/dev/serial/by-id/...` (or `/dev/ttyUSB0`) |
| **Serial-to-Ethernet / Wi-Fi gateway** next to the device | A gateway such as an Elfin-EW10, USR-TCP232, Moxa NPort, or Global Cache iTach | `socket://<gateway-ip>:<port>` |
| **The device's own network control** (some receivers / amplifiers) | Nothing extra | `socket://<device-ip>:<port>` |

!!! tip "Choosing a USB adapter"
    Adapters with an **FTDI** chip (FT232R) are the most reliable on Linux and are
    recognised automatically. Prolific (PL2303), Silicon Labs (CP2102) and CH340 adapters
    also work. Avoid unbranded adapters with counterfeit chips — they are the most common
    cause of "no response from device".

!!! info "Straight-through or null-modem?"
    RS-232 cables come in two wirings. If your device's manual does not say which it
    needs, start with a **straight-through** cable; if the device never answers, add a
    **null-modem adapter** (it swaps the transmit and receive pins). A wrong cable damages
    nothing — it just gives no reply.

## A machine to run Home Assistant

A Raspberry Pi 4/5, a small x86 PC (e.g. an Intel NUC), or a virtual machine. With the
USB-adapter option, the adapter plugs into this machine, so it has to be within cable
reach of the device (RS-232 is fine up to about 15 m / 50 ft) — otherwise use a
network gateway.

## A GitHub account

HACS (the community store used to install Audio Control) signs in with GitHub. A free
account is enough.

---

Next: [Install Home Assistant](install-home-assistant.md)
