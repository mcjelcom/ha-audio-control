# Matter (partial)

Matter lets **Google Home**, **Alexa**, **SmartThings**, and **Aqara** control your zones
locally, with no subscription. Matter has no amplifier type yet, so each zone appears as a
**speaker** with power, volume, and sources.

![How Matter fits in](assets/diagrams/matter.svg)

## What works where

| App | Works | Not over Matter |
|---|---|---|
| 🟢 **Google Home** | On/off, volume · source with a [shortcut switch](#choose-a-source-one-switch-per-favorite) | Choosing a source directly, mute |
| 🔵 **Alexa** | On/off with a ["Music" switch](#alexa-add-a-music-switch-per-zone) · source with a shortcut switch | Volume, mute |
| ⚪ **SmartThings / Aqara** | On/off, volume | Mute |
| 🍎 **Apple Home** | — use [HomeKit Bridge](smart-home.md#apple-home-siri) instead | |

Tested in the Google Home app; see [how we tested](compatibility.md#how-we-tested).

!!! tip "Turn the zone on first"
    In Google Home, moving the volume doesn't switch a zone on. Tap power first.

## What you need

- **A Matter hub from your app's maker** on your home network. The app alone isn't enough.
  - Google: a Nest speaker or display, Nest Wifi, or Google TV Streamer.
  - Alexa: an Echo that supports Matter.
- **Nothing extra on the Raspberry Pi.** Matter uses your home network (Ethernet is
  best). You don't need a Thread USB stick.
- **Home Assistant OS** (with the Matter Hub app, below) or **balena**, whose template
  includes Matter Hub, switched off. See
  [Turn on Matter on balena](getting-started/install-balena.md#matter-optional).

## 1. Install the Matter Hub app

[Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) is a free
community app that shares Home Assistant devices over Matter.

1. Go to **Settings → Apps → app store** (bottom right) → **⋮** (top right) → **Repositories**.
2. Add `https://github.com/riddix/home-assistant-addons` and click **Add**.
3. Refresh, find **Home-Assistant-Matter-Hub**, click **Install** and **Start**, and turn
   on **Show in sidebar**.

## 2. Create a bridge for your zones

Open **Matter Hub** from the sidebar and create a bridge:

- **Name:** for example, *Audio Control*. **Port:** keep **5540**. Alexa only finds bridges on 5540.
- **Include:** *platform* `audio_control` (all your zones) and *entity label* `matter`
  (the extra switches below, which you give the **Matter** label).
- **Exclude:** *domain* `binary_sensor` (connection status, nothing to control).
- Turn on **Prefer entity registry name** for short names (*Living Room*, not
  *AMC X86 / X86i Living Room*). Do this **before pairing**; paired apps keep the old names.

![The bridge filters](assets/screenshots/matter-hub-filters.png)

The bridge lists every zone as a **Speaker** and each labeled switch as a **Plug**:

![Zones and switches on the bridge](assets/screenshots/matter-hub-endpoints.png)

## Alexa: add a "Music" switch per zone

1. Go to **Settings → Devices & services → Helpers → Create helper → Template → Switch.**
2. **Name:** for example, `Kitchen Music`.
3. **Value template:** `{{ is_state('media_player.YOUR_ZONE', 'on') }}`. The zone's
   entity ID is on its settings page (⚙).
4. **Actions on turn on:** *Media player: Turn on* → your zone. **Actions on turn off:**
   *Media player: Turn off* → your zone. Click **Submit.**
5. Open the new switch's settings (⚙) and add the label **Matter** (create it the first
   time).

Repeat for each zone you want Alexa to switch.

## Choose a source: one switch per favorite

Google Home can't pick a source, and Alexa can't over Matter. Instead, make a switch per
combination, like **Kitchen Spotify**. Turning it on switches the zone on and picks the
source ("Hey Google, turn on Kitchen Spotify").

1. **Create helper → Template → Switch**, named for example `Kitchen Spotify`.
2. **Value template** (on while that zone plays that source):
   `{{ is_state('media_player.YOUR_ZONE', 'on') and is_state_attr('media_player.YOUR_ZONE', 'source', 'Spotify') }}`
3. **Actions on turn on:** *Media player: Turn on* → your zone, then
   *Media player: Select source* → your zone, source `Spotify`.
   **Actions on turn off:** *Media player: Turn off* → your zone. Click **Submit.**
4. Add the label **Matter** to the switch.

!!! warning "Name your sources first"
    A source switch uses the source's **name**. If you rename a source (for example, to
    an [Alexa input name](smart-home.md#alexa-name-your-sources-so-alexa-can-pick-them)),
    update the switch: **Settings → Devices & services → Helpers** → the switch →
    **⚙ → Template options**. Paired apps may keep the old name; rename it there.

!!! tip "Make only the ones you'll use"
    Each switch becomes a device in your app. All 48 combinations of a 6-zone,
    8-source amplifier work (tested, 60 devices), but the list is long, and Alexa
    rejects bridges above about 80–100 devices. Pick your favorites.

!!! note "New switches appear after a bridge restart"
    After you add or label switches, restart the bridge: **⋮ → Restart** on its page.

## 3. Pair with your app

On the bridge page, Matter Hub shows a **QR code** and a **manual code**.

- **Google Home:** tap **+ → Device → Matter-enabled device** and scan the code. Google
  warns that it's an *uncertified device*; continue. (Optional: to drop the warning,
  register it in the
  [Google Home Developer Console](https://console.home.google.com/projects/) with
  vendor ID `0xFFF1` and product ID `0x8000`.)
- **Alexa:** tap **+ → Device → Other → Matter** and scan the code.
- **SmartThings / Aqara:** add a Matter device and scan the code.

To pair a second app with the same bridge, use **Add Another Controller** on the bridge page.

!!! tip "Devices show as offline?"
    Matter needs IPv6 and mDNS on your home network. If zones go "unavailable", see
    Matter Hub's [troubleshooting guide](https://riddix.github.io/home-assistant-matter-hub/).
