# Phone app

Control your zones from your phone with the free **Home Assistant** app — the same
dashboards as in your browser, plus home-screen widgets.

![Setting up the phone app](assets/diagrams/phone-app.svg)

## Install and connect

1. Install **Home Assistant** from the
   [App Store](https://apps.apple.com/app/home-assistant/id1099568401) (iPhone, iPad)
   or [Google Play](https://play.google.com/store/apps/details?id=io.homeassistant.companion.android)
   (Android). It's free and made by the Home Assistant team.
2. Open it **at home, on your home Wi-Fi**. It finds your Home Assistant by itself —
   tap it. *Not listed?* Choose to enter the address yourself:
   `http://homeassistant.local:8123`, or for a balena install `http://<IP address>:8123`
   (the IP address is on the device page in the balena dashboard).
3. **Sign in** with your Home Assistant username and password.
4. The app asks to send notifications and to use your location. Both are optional —
   Audio Control needs neither. (Location is only used if you want automations like
   "turn on the patio when I get home".)

## Your zones in the app

- Open the **Audio Control** dashboard from the menu (☰) — see
  [Ready-made dashboard](dashboard.md) — or any dashboard you've put your zones on
  ([how](using-zones.md#put-zones-on-a-dashboard)).
- Tap a zone for the full controls: on/off, volume, mute and source.
- **Widgets:** add a Home Assistant widget to your phone's home screen and pick a zone,
  for one-tap on/off. (Long-press the home screen → widgets → Home Assistant.)

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
