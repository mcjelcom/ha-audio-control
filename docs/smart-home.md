# Apple Home, Google Home, and Alexa

Home Assistant can share your zones with **Apple Home**, **Google Home**, and **Alexa**
("Hey Siri, turn on the Kitchen"). You only switch on Home Assistant's connection to each
service. To see what works where, see [Compatibility](compatibility.md).

![Sharing your zones with Apple, Google and Alexa](assets/diagrams/smart-home.svg)

!!! tip "Rename your zones first"
    You say zone and source names out loud, so use names like *Kitchen* and *Radio*.
    See [Names and settings](configuration.md).

## Apple Home (Siri)

Home Assistant's built-in **HomeKit Bridge** is free and needs no account.

1. Go to **Settings → Devices & services → Add integration**, search for **HomeKit Bridge**,
   and click **OK**.
2. In **Domains to include**, choose only **Media player**, then click **Submit**.

    ![Choosing what to share with Apple Home](assets/screenshots/homekit-setup.png){ width="480" }

3. Home Assistant creates **one HomeKit accessory per zone**, each with a **pairing code
   and QR code** in **Notifications** (bottom left).
4. On your iPhone or iPad, open the **Home app → + → Add Accessory**, scan a zone's
   QR code, and follow the steps. Repeat for each zone.

Each zone appears as a TV-style tile:

| In the Home app | Works |
|---|---|
| On/off | ✅ |
| Source, by name | ✅ |
| Volume up/down, mute | ✅ with the **Remote** in Control Center |
| Volume slider | ❌ Apple has none for TV-style accessories |

!!! note "Why one pairing per zone?"
    Apple allows one TV-style accessory per pairing. HomeKit may also create an empty
    "HASS Bridge"; delete it in **Settings → Devices & services → HomeKit Bridge**.

## Google Home and Alexa

The easiest way is **Home Assistant Cloud** (Nabu Casa), a paid subscription.

1. Go to **Settings → Home Assistant Cloud** and sign in.
2. Turn on **Google Assistant**, **Alexa**, or both, and link them in the Google Home or
   Alexa app.
3. Under **Settings → Voice assistants → Expose**, make sure your zones are switched on.

Without a subscription, you need a developer account and more setup. See Home Assistant's
guides for [Google Assistant](https://www.home-assistant.io/integrations/google_assistant/)
and [Alexa](https://www.home-assistant.io/integrations/alexa/).

### Alexa: name your sources so Alexa can pick them

Alexa only accepts its own input names, such as **TV**, **CD**, **Tuner**, **Aux 1**, or
**HDMI 1**. It ignores names like *Spotify*. To let Alexa switch sources:

1. Rename your sources in [Names and settings](configuration.md).
2. In the Alexa app, run **Devices → Discover devices**.

??? info "All names Alexa accepts"
    AUX 1–7, BLURAY, CABLE, CD, COAX 1–2, COMPOSITE 1, DVD, GAME, HD RADIO, HDMI 1–10,
    HDMI ARC, INPUT 1–10, IPOD, LINE 1–7, MEDIA PLAYER, OPTICAL 1–2, PHONO,
    PLAYSTATION (3, 4), SATELLITE, SMARTCAST, TUNER, TV, USB DAC, VIDEO 1–3, XBOX.

Volume and mute work **by voice** ("Alexa, set Kitchen volume to 6"); the Alexa app has
no volume control for these devices. No Echo? Tap the Alexa button in the app and speak.

## Matter

Google Home, Alexa, SmartThings, and Aqara can also use **Matter**: local and free, with
fewer controls. See [Matter (partial)](matter.md).
