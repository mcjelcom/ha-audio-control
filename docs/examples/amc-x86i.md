# Example: AMC X86i

A complete setup for the **AMC X86i** 6-zone / 8-source amplifier, from cable to
dashboard. The same steps apply to the AMC X86, XO and XOi (pick their profile instead).

Everything on this page was verified against a real X86i over RS-232.

## What you need

| Part | For this example |
|---|---|
| Amplifier | **AMC X86i** with its RS-232 port (rear panel, item 8 in the AMC manual — a standard **DB9** connector; AMC lists RS-232 as an option on some units) |
| Home Assistant machine | **Raspberry Pi 4 or 5** (2 GB+ RAM), A2 microSD 32 GB+ or USB SSD, official power supply, Home Assistant OS |
| Adapter | **USB-to-RS232** (DB9 male, FTDI chip recommended) — not a USB-to-TTL adapter |
| Cable | **Straight-through** DB9 serial cable from the adapter to the X86i (tested; no null-modem adapter needed) |
| Software | Home Assistant with HACS and Audio Control installed ([steps 2–4](../getting-started/install-home-assistant.md)) |

Full details and alternatives: [Hardware requirements](../getting-started/prerequisites.md#hardware-requirements).

The X86i's serial settings are **38400 baud, 8 data bits, no parity, 1 stop bit, no
flow control**. You don't enter these anywhere — the *AMC X86 / X86i* profile sets them.

## 1. Connect the cable

1. Plug the USB adapter into the Home Assistant machine.
2. Connect a **straight-through** DB9 serial cable from the adapter to the X86i's
   **RS232** port.
3. Power the X86i on.

## 2. Find the serial port

=== "Home Assistant OS"

    **Settings → Connectivity → Serial** lists the serial ports and which integrations
    use them (on Home Assistant older than 2026.10: **Settings → System → Hardware → ⋮ →
    All hardware**, search `serial`). Use the path under **`/dev/serial/by-id/`**, e.g.

    `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10XXXXX-if00-port0`

=== "Container"

    On the host: `ls -l /dev/serial/by-id/`, pass it into the container
    ([how](../getting-started/install-home-assistant.md#container-only-pass-the-usb-adapter-in)),
    and use the path *inside* the container (e.g. `/dev/ttyUSB0`).

!!! tip
    Prefer `/dev/serial/by-id/...` over `/dev/ttyUSB0`: the `ttyUSB` number can change
    after a reboot or when another USB device is plugged in; the `by-id` path never does.

## 3. Add the integration

**Settings → Devices & services → Add integration → Audio Control**, then:

- **Device:** `AMC X86 / X86i`
- **Connection:** the path from step 2

![Setup form with the AMC X86 / X86i profile selected](../assets/screenshots/setup-step1-x86i.png){ width="480" }

Click **Submit**. Audio Control connects, reads every zone's status, and creates:

- **6 media players** — one per zone (power, volume, mute, source)
- **1 connection sensor** — shows whether the amplifier is answering

![The Audio Control integration with the X86i device](../assets/screenshots/integration-page.png)

!!! note "No amplifier yet?"
    Enter `demo` as the connection to get the same entities with a simulated X86i.
    Later, open the device's **⋮ → Reconfigure** and enter the real port — nothing else
    changes.

## 4. Name your zones and sources

Open the device → **Configure** and replace *Zone 1…6* and *Source 1…8* with real names
(*Kitchen*, *Patio*, *Streamer*, *TV*…). The names appear in the media players' source
lists and on the dashboard.

## 5. Use it

Each zone is a normal Home Assistant media player — use it on any dashboard, in voice
assistants, and in automations.

![Zone cards on a dashboard](../assets/screenshots/dashboard.png)

Things specific to the X86i:

| Feature | How it behaves |
|---|---|
| **Volume** | The amplifier's 0–62 attenuation scale (0 = loudest) is converted to Home Assistant's 0–100 % automatically |
| **Changes made on the keypads or IR** | The X86i reports them, and every zone is also re-read every 60 s, so HA stays in sync |
| **Bass / treble** | `audio_control.set_bass` / `set_treble` with **−8, −6, −4, 0, +4, +6, +8** only (the amplifier has no ±2). The **zone must be on** — the X86i refuses tone changes on an off zone, and you get a clear error saying so |
| **All zones off** | `audio_control.all_zones_off` |
| **Group mode** | `audio_control.group_mode_on` with a `source` puts every zone on that source; `group_mode_off` returns them to independent sources |
| **Muted vs off** | Shown correctly (the X86i reports both with the same volume value; Audio Control tells them apart) |

Example automation — warmer sound in the kitchen at dinner:

```yaml
- alias: Kitchen dinner EQ
  triggers:
    - trigger: time
      at: "18:30:00"
  conditions:
    - condition: state
      entity_id: media_player.kitchen   # your zone 1 entity
      state: "on"                       # tone needs the zone on
  actions:
    - action: audio_control.set_bass
      target:
        entity_id: media_player.kitchen
      data:
        level: 4
```

## If it doesn't work

| Symptom | Check |
|---|---|
| Connection sensor **off** | Adapter path, cable seated, amplifier powered. The X86i needs a **straight-through** cable — a null-modem cable or adapter will not work |
| Sensor on, but zones never change | Wrong profile selected, or another program has the port open |
| Older X86 firmware | Handled automatically — Audio Control falls back to the older `Z01…` command form if `ZN01…` is not accepted |

More in [Troubleshooting](../troubleshooting.md).
