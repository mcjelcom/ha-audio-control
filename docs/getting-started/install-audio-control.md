# 4. Install Audio Control

## Download it from HACS

1. Click **HACS** in the Home Assistant sidebar.
2. Search for **Audio Control** and open it.
3. Click **Download**, then **Download** again to confirm.
4. **Restart** Home Assistant: **Settings → System → ⏻ (top right) → Restart Home Assistant**.

Or click this button to jump straight to it:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mcjelcom&repository=ha-audio-control&category=integration)

## Add your amplifier

1. Go to **Settings**, then **Devices & services**.

    ![The Settings menu](../assets/screenshots/settings-menu.png){ width="560" }

2. Click **Add integration** (bottom right), type **Audio Control**, and click it.

    ![Searching for Audio Control](../assets/screenshots/add-integration-search.png){ width="420" }

3. Fill in the form:

    ![The setup form](../assets/screenshots/setup-step1-x86i.png){ width="420" }

    - **Device** — choose your amplifier's model from the list.
    - **Connection** — the USB adapter. Home Assistant usually lists it for you under
      *Detected locally*; it looks like `/dev/serial/by-id/usb-FTDI_...`.
      [How to find it](#finding-the-connection).

4. Click **Submit**.

That's it — each zone now appears in Home Assistant. Next, give them proper names:
[Names & settings](../configuration.md).

!!! tip "Try it without the amplifier"
    Type **`demo`** in **Connection** to get a pretend amplifier. Everything works the
    same, so you can set up your dashboard first. Switch to the real connection later
    ([how](../configuration.md#change-the-connection)).

## Finding the connection

Go to **Settings → Connectivity → Serial**. It lists the USB adapters Home Assistant
can see. Copy the one that starts with **`/dev/serial/by-id/`**.

![Settings → Connectivity](../assets/screenshots/connectivity.png){ width="560" }

*(Older Home Assistant versions: **Settings → System → Hardware → ⋮ → All hardware**,
then search for "serial".)*

Nothing listed? See [Help & troubleshooting](../troubleshooting.md#the-adapter-isnt-listed).

## Updates

When a new version comes out, HACS shows an **update** for Audio Control. Click
**Update**, then restart Home Assistant.
