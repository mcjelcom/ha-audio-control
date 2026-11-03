# Troubleshooting

| Symptom | Check |
|---|---|
| Connection sensor **off** / entities unavailable | Port path, cable, and that nothing else holds the port. The integration reconnects with backoff on its own. |
| Entities exist but never change state | Wrong profile or baud rate — the device is ignoring commands or the replies don't match. Try `demo` to confirm the entity layer, then compare the profile with your manual. |
| Controls missing (e.g. no bass) | Intentional: controls appear only if the profile defines the command. |
| Bass/treble fails with "zone is off" or "level not supported" | The device itself refuses it (e.g. the AMC X86 only changes tone on a powered-on zone). Turn the zone on, or pick one of the listed levels. |
| Changes made on the device's keypad show up late | Devices that don't push state are polled — every zone every 60 s by default (a profile can shorten this with `serial.heartbeat_interval_s`). |
| Re-authentication keeps appearing | Wrong username/password — set them under **Configure**. |

Debug logging (protocol traffic included):

```yaml
logger:
  logs:
    custom_components.audio_control: debug
```

When opening an issue, attach **Download diagnostics** from the device page —
the connection string and credentials are redacted automatically.

## Serial port problems

| Symptom | Fix |
|---|---|
| The port isn't offered during setup | *HA OS:* check **Settings → System → Hardware → All hardware** for the adapter. *Container:* the adapter must be passed in with `--device` / `devices:` ([how](getting-started/install-home-assistant.md#container-only-pass-the-usb-adapter-in)) |
| `Permission denied` on the port (Container) | The container needs the device mapping above; running HA with `privileged: true` also works but grants far more than needed |
| Works until a reboot, then not | Use the `/dev/serial/by-id/...` path, not `/dev/ttyUSBn` — the number can change |
| Garbage or no reply from the device | Wrong baud rate (pick the right profile, or check it in a custom profile), wrong cable type (try a null-modem adapter), or a counterfeit adapter chip |
