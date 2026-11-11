# 1. What you need

## Shopping list

![How the parts connect](../assets/diagrams/hardware-wiring.svg)

| Item | What to get | Why |
|---|---|---|
| **Raspberry Pi** | **Pi 5** or **Pi 4**, **2 GB+ memory** (recommended). A **Pi 3 B/B+** also works: slower, and updates take longer | Runs Home Assistant |
| **Memory card** | microSD, **32 GB+**, marked **A2** | Holds Home Assistant. A USB SSD lasts longer |
| **Power supply** | **Official Raspberry Pi power supply** (Pi 5: 27 W, Pi 4: 15 W) | Phone chargers are often too weak |
| **USB-to-RS232 adapter** | USB to **RS232 (DB9)**, ideally **FTDI** chip | Talks to the amplifier |
| **Serial cable** | **DB9 serial cable**, long enough | Connects adapter and amplifier |
| **Network cable** *(recommended)* | Ethernet to your router | More reliable than Wi-Fi |

Already run Home Assistant? You need only the **adapter** and **cable**.

!!! warning "Buy RS232 — not TTL"
    "USB to TTL" adapters with loose pins look similar but **won't work**. Look for
    **RS232** and a **DB9 plug** (9 pins in two rows).

## Other hardware

Home Assistant OS also runs on other boards. Audio Control works on any of them that
has a USB port for the adapter.

| Hardware | Audio Control |
|---|---|
| **Raspberry Pi 4** | ✅ Tested |
| **Raspberry Pi 3** | ✅ Tested (slower) |
| **Home Assistant Green** or **Yellow** — ready-made boxes from the Home Assistant team | Should work; not yet tested |
| **ODROID** (C2, C4, N2, M1, M1S) or **Khadas VIM3** | Should work; not yet tested |
| **Mini PC** or old laptop (64-bit Intel or AMD) | Should work; not yet tested |
| **Virtual machine** (Proxmox, VirtualBox, VMware, Hyper-V) | Needs USB passthrough for the adapter, or a [serial-to-network adapter](../reference/network-transport.md) |
| **Docker** on any computer | ✅ Tested. See [Docker installs](../advanced/docker.md) |

For the full list, see [Home Assistant's installation page](https://www.home-assistant.io/installation/).

## Which cable?

Serial cables are **straight-through** or **null-modem**; your amplifier's manual
usually says which.

- **AMC X86i:** straight-through (tested).
- **Not sure?** Start with straight-through. No response? Add a **null-modem adapter**
  between cable and amplifier. The wrong one does no harm.

## Your amplifier

It needs an **RS232** port (usually 9 pins, on the back) and must be in
[Supported amplifiers](../index.md#supported-amplifiers).

!!! tip "Amplifier far from the Raspberry Pi?"
    Serial cables reach about 15 m (50 ft). Beyond that, put a small network adapter
    by the amplifier. See [Network connections](../reference/network-transport.md).

## A GitHub account

HACS (step 3) needs a free [GitHub account](https://github.com/signup). Create one now
if needed.

---

**Next:** [2. Install Home Assistant](install-home-assistant.md). To manage the Pi
remotely, first see [Choose how to install](choose-install.md).
