# Network Transport (`socket://` and `rfc2217://`)

The integration's **Connection** field accepts a network URL as well as a local device
path. No profile changes are needed: `pyserial-asyncio-fast` resolves URL
schemes natively, so the protocol layer is unchanged and every bundled profile
works over the network.

| Port value | Transport |
|---|---|
| `/dev/ttyUSB0` | Local serial device |
| `socket://host:port` | Raw TCP — most serial-to-Ethernet gateways, and amplifiers with native IP control |
| `rfc2217://host:port` | RFC 2217 (Telnet COM port control) — gateways that negotiate baud rate over the link |
| `demo` | No hardware; simulated responses |

Because the wire protocol is identical, an amplifier reached over TCP behaves
exactly as it does over a directly attached cable — including two-way state
verification and optimistic-update rollback.

## Native IP devices

Several supported amplifiers accept the same command set over TCP:

| Device | Port | Example |
|---|---|---|
| Marantz PM7000N / SR Series | 23 | `socket://192.168.1.50:23` |
| Yamaha RX-A / RX-V Series | 50000 | `socket://192.168.1.51:50000` |
| Rotel RA-1572 / RSP-1576 | 9590 | `socket://192.168.1.52:9590` |

## Serial-to-Ethernet gateways

Any transparent TCP bridge works — Global Caché iTach, USR-TCP232, Moxa NPort,
ser2net on a Raspberry Pi. Configure the gateway for the profile's serial
settings (the AMC X-Series uses 38400 8N1) and point the Port field at it.

## Verifying a setup without a gateway

You can prove the `socket://` path end-to-end against a *directly attached*
amplifier by putting a local TCP bridge in front of it. This was used to
validate the transport against a real AMC X86i.

Only one process may hold a serial device, so the integration must release it
first.

```bash
# 1. Disable the existing config entry so it releases /dev/ttyUSB0
#    (Settings > Devices & Services > Audio Control > ... > Disable)

# 2. Bridge TCP:4001 <-> the serial port, using the profile's settings
socat -d TCP-LISTEN:4001,reuseaddr,fork \
  /dev/ttyUSB0,b38400,cs8,parenb=0,cstopb=0,raw,echo=0,nonblock &

# 3. Confirm the bridge reaches the device before involving Home Assistant.
#    Expect a status reply, e.g. #ZN01,SRC00,GRP0,VOL-62
printf '*ZN01STA00\r' | socat - TCP:127.0.0.1:4001,crnl

# 4. Add a second Audio Control entry with Port = socket://127.0.0.1:4001
```

Afterwards, delete the test entry, stop `socat`, and re-enable the original
entry so it reclaims the serial port.

`ser2net` is an alternative to `socat` if you want a persistent service; the
equivalent config is:

```
4001:raw:0:/dev/ttyUSB0:38400 8DATABITS NONE 1STOPBIT
```

## Notes

- Two entries cannot share one serial port. Disable one before enabling the
  other, or the second will fail to connect.
- Latency is higher over TCP. If commands time out, raise `response_timeout`
  and `retry_count` in the profile's `serial:` block.
- A dropped TCP connection is handled by the same reconnect logic as a serial
  disconnect (fast retries, then backoff).
