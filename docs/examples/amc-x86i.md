# Example: AMC X86i

Set up an **AMC X86i** (6 zones, 8 sources) from cable to dashboard. The same steps work
for the AMC X86 and XO with their own profile. Everything here was tested on a real X86i.

## What you need

| Part | For this example |
|---|---|
| Amplifier | **AMC X86i** with an RS-232 (**DB9**) port, rear panel item 8. On some units it's an option. |
| Home Assistant machine | **Raspberry Pi 4 or 5** (2 GB+ RAM), A2 microSD 32 GB+ or USB SSD, official power supply |
| Adapter | **USB-to-RS232** (DB9 male, FTDI chip recommended), not USB-to-TTL |
| Cable | **Straight-through** DB9 serial cable (tested; no null-modem needed) |
| Software | Home Assistant with HACS and Audio Control installed ([steps 2–4](../getting-started/install-home-assistant.md)) |

For details and alternatives, see the [Shopping list](../getting-started/prerequisites.md#shopping-list).

Choosing *AMC X86 / X86i* sets the serial settings for you.

??? note "Serial settings (for reference)"
    38400 baud, 8 data bits, no parity, 1 stop bit, and no flow control, from AMC's RS-232 manual.

## 1. Connect the cable

![AMC X86i wiring](../assets/diagrams/x86i-wiring.svg)

1. Plug the USB adapter into the Home Assistant machine.
2. Connect a **straight-through** DB9 serial cable from the adapter to the X86i's
   **RS232** port.
3. Turn on the X86i.

## 2. Find the connection

Go to **Settings → Connectivity → Serial** and copy the adapter name that starts with
**`/dev/serial/by-id/`**, for example:

`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10XXXXX-if00-port0`

*(On older Home Assistant, go to **Settings → System → Hardware → ⋮ → All hardware** and
search for "serial". If you use Docker, see [Docker / Container installs](../advanced/docker.md).)*

## 3. Add the amplifier

Go to **Settings → Devices & services → Add integration**, search for **Audio Control**,
and enter:

- **Device:** `AMC X86 / X86i`
- **Connection:** the path from step 2

![Setup form with the AMC X86 / X86i profile selected](../assets/screenshots/setup-step1-x86i.png){ width="480" }

Click **Submit**. Audio Control creates **6 zones** (power, volume, mute, and source) and a
**connection indicator** that shows whether the amplifier answers.

![The Audio Control integration with the X86i device](../assets/screenshots/integration-page.png)

!!! note "No amplifier yet?"
    Enter `demo` as the connection for a simulated X86i. Later, use the device's
    **⋮ → Reconfigure** to enter the real port.

## 4. Name your zones and sources

Click the **gear icon** next to the amplifier. Replace *Zone 1…6* and *Source 1…8*
with real names, such as *Kitchen*, *Patio*, *Streamer*, and *TV*.

![Renaming zones and sources](../assets/screenshots/options-names.png){ width="420" }

## 5. Use it

Each zone works like a smart speaker: on dashboards, in the phone app, by voice, and in
automations.

![The amplifier's page with its six zones](../assets/screenshots/device-page.png)

![Zone cards on a dashboard](../assets/screenshots/dashboard.png)

How the X86i behaves:

| Feature | How it behaves |
|---|---|
| **Volume** | Shown as a normal 0–100 % slider |
| **Keypads and remote** | Changes made there also show up in Home Assistant |
| **Bass / treble** | Levels **−8, −6, −4, 0, +4, +6, +8** (no ±2), and only while the zone is **on** |
| **All zones off** | One action turns every zone off |
| **Group mode** | Every room plays the same source |
| **Muted vs off** | Shown correctly |

For bass, treble, all zones off, and group mode, see [Automations and extra controls](../services.md).

Example automation: warmer sound in the kitchen at dinner.

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
| Connection shows **Disconnected** | Adapter path, cable, and power. The X86i needs a **straight-through** cable, not null-modem. |
| Connected, but zones never change | Wrong model selected in *Device*, or another program is using the adapter |
| Older X86 units | Handled automatically |

For more help, see [Troubleshooting](../troubleshooting.md).
