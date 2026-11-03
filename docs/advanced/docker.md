# Docker / Container installs

If Home Assistant runs in Docker (*Home Assistant Container*), the USB adapter must be
passed into the container. Home Assistant OS does this automatically.

Find the adapter's stable path on the host:

```bash
ls -l /dev/serial/by-id/
```

Then map it into the container:

=== "docker compose"

    ```yaml
    services:
      homeassistant:
        image: ghcr.io/home-assistant/home-assistant:stable
        devices:
          - /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0:/dev/ttyUSB0
        # ... volumes, network_mode, etc. as in the Home Assistant guide
    ```

=== "docker run"

    ```bash
    docker run -d --name homeassistant \
      --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0:/dev/ttyUSB0 \
      ...  # remaining options as in the Home Assistant guide
      ghcr.io/home-assistant/home-assistant:stable
    ```

Inside the container the adapter is then **`/dev/ttyUSB0`** — use that as the
**Connection** when adding Audio Control.

Notes:

- `privileged: true` also works but grants far more access than needed; prefer the
  single `devices:` mapping.
- Home Assistant has deprecated the *Core* and *Supervised* installation methods; use
  Home Assistant OS or Container.
- HACS on Container: run the HACS download command inside the container
  (`docker exec -it homeassistant bash`), as the [HACS guide](https://hacs.xyz/docs/use/)
  describes.
