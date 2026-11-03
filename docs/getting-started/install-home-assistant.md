# 2. Install Home Assistant

Already running Home Assistant? Skip to [Install HACS](install-hacs.md).

Home Assistant's own installation guide is the authoritative source and covers every
platform step by step:

**➜ [home-assistant.io/installation](https://www.home-assistant.io/installation/)**

## Which installation type?

| Type | Use it when | Notes for Audio Control |
|---|---|---|
| **Home Assistant OS** (recommended) | A dedicated Raspberry Pi 4/5, mini PC or VM — see [hardware requirements](prerequisites.md#hardware-requirements) | USB serial adapters are available to Home Assistant automatically. Apps (Terminal, File editor; called *add-ons* before 2026.10) make HACS installation easy |
| **Home Assistant Container** | You already run Docker and want HA as one container | You must pass the USB adapter into the container (below). No apps |

Home Assistant has deprecated the *Core* and *Supervised* installation methods; use one
of the two above.

## Container only: pass the USB adapter in

Find the adapter's stable path on the host:

```bash
ls -l /dev/serial/by-id/
```

Then give the container access to it.

=== "docker compose"

    ```yaml
    services:
      homeassistant:
        image: ghcr.io/home-assistant/home-assistant:stable
        devices:
          - /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0:/dev/ttyUSB0
        # ... volumes, network_mode, etc. as in the HA guide
    ```

=== "docker run"

    ```bash
    docker run -d --name homeassistant \
      --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0:/dev/ttyUSB0 \
      ...  # remaining options as in the HA guide
      ghcr.io/home-assistant/home-assistant:stable
    ```

Inside the container the adapter is then `/dev/ttyUSB0`.

---

Next: [Install HACS](install-hacs.md)
