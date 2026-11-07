# Phone app

Control your zones from your phone with the free **Home Assistant** app — the same
dashboards as in your browser, plus home-screen widgets.

![Setting up the phone app](assets/diagrams/phone-app.svg)

## Install and connect

1. Install **Home Assistant** from the
   [App Store](https://apps.apple.com/app/home-assistant/id1099568401) (iPhone, iPad)
   or [Google Play](https://play.google.com/store/apps/details?id=io.homeassistant.companion.android)
   (Android). It's free and made by the Home Assistant team.
2. Open it **at home, on your home Wi-Fi**, and tap **Connect to my Home Assistant
   server**. It searches your network and lists your Home Assistant — tap it.
3. *Not listed?* Tap **Enter address manually** and type `http://homeassistant.local:8123`
   (for a balena install: `http://<IP address>:8123`, from the device page in the
   balena dashboard), then **Connect**.
4. **Log in** with your Home Assistant username and password.

<div class="grid" markdown>
![Welcome screen](assets/screenshots/app-1-welcome.png){ width="220" }
![Entering the address](assets/screenshots/app-3-address.png){ width="220" }
![Logging in](assets/screenshots/app-4-login.png){ width="220" }
</div>

Then answer a few questions:

- **Name this device** — anything, e.g. *John's phone* → **Save**.
- **Local by default** — the app works on your home network to start with → **Got it**.
- **Secure your remote connection** — choose **Most secure: Allow this app to know when
  you're home**, then allow location **While using the app** (on Android also
  **Nearby devices**, which is how it reads your Wi-Fi name). The app uses this only to
  tell home from away; the data stays with you.
- **Notifications** — optional; Audio Control doesn't need them.

![The secure-connection question](assets/screenshots/app-7-secure.png){ width="220" }

## Your zones in the app

Open the menu (☰, top left) and tap **Audio Control** — see
[Ready-made dashboard](dashboard.md) — or use any dashboard you've put your zones on
([how](using-zones.md#put-zones-on-a-dashboard)). Tap a zone's name for its full
controls: the **volume** slider, **source** (by your names) and **power**.

<div class="grid" markdown>
![The Audio Control dashboard in the app](assets/screenshots/app-10-dashboard.png){ width="220" }
![A zone's controls](assets/screenshots/app-11-zone.png){ width="220" }
![Choosing the source](assets/screenshots/app-12-source.png){ width="220" }
</div>

**Widgets:** add a Home Assistant widget to your phone's home screen and pick a zone, for
one-tap on/off (long-press the home screen → widgets → Home Assistant).

*Screenshots: the Android app (2026.11), connected to a demo amplifier. The iPhone app
asks similar questions.*

## Away from home

At home the app connects directly. To use it from anywhere you need remote access —
the easiest is **Home Assistant Cloud** (**Settings → Home Assistant Cloud**, a paid
subscription that also gives you Google Home and Alexa — see
[Apple Home, Google Home & Alexa](smart-home.md)). Home Assistant's
[remote access guide](https://www.home-assistant.io/docs/configuration/remote/)
describes the other options.

!!! tip "Use Siri or the Home app instead?"
    With HomeKit Bridge your zones also appear in Apple's **Home** app and work with
    Siri — see [Apple Home](smart-home.md#apple-home-siri).
