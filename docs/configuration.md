# Configuration

Everything is set up in the UI; there is no YAML configuration.

## Add the device

| Field | What to enter |
|---|---|
| **Device** | The profile for your model, or *>> Custom Device (define via UI)* for the wizard |
| **Connection** | A serial port, `socket://host:port`, `rfc2217://host:port`, or `demo` (see [Connection types](index.md#connection-types)). Detected local ports are listed in the form. |

Zone and source counts come from the profile. One `media_player` is created per
zone, plus a connection `binary_sensor`.

**Tip:** on Home Assistant OS, prefer the stable `/dev/serial/by-id/...` path over
`/dev/ttyUSB0`, which can change between reboots. In Docker, pass the adapter in
with `--device`.

## After setup

| Where | Use it to |
|---|---|
| Device → **Configure** | Rename zones and sources; set the device **username/password** for profiles that log in (e.g. RTI). A blank credential field keeps the stored value. |
| Device → ⋮ → **Reconfigure** | Change the connection (e.g. move from `demo` to the real port) without losing entities or automations |
| Re-authentication prompt | Appears if the device rejects the login; enter the current credentials |
