# Compatibility

What you can do with your zones from each app — and how we checked it.

## At a glance

| | On / off | Volume | Mute | Source |
|---|:---:|:---:|:---:|:---:|
| 🏠 **Home Assistant** app & dashboard | ✅ | ✅ | ✅ | ✅ |
| 🍎 **Apple Home** (HomeKit Bridge) | ✅ | 🟡 up / down | ✅ | ✅ |
| 🟢 **Google Home** (Matter) | ✅ | ✅ | ❌ | 🟡 shortcut switch |
| 🟢 **Google Home** (Home Assistant Cloud) | ✅ | ✅ | ✅ | 🟡 |
| 🔵 **Alexa** (Home Assistant Cloud) | ✅ | 🟡 by voice | 🟡 by voice | 🟡 some names |
| 🔵 **Alexa** (Matter) | 🟡 Music switch | ❌ | ❌ | 🟡 shortcut switch |
| ⚪ **SmartThings / Aqara** (Matter) | ✅ | ✅ | ❌ | 🟡 |

✅ works · 🟡 works with a catch (see below) · ❌ not available

**Bass & treble, all zones off, group mode:** in Home Assistant itself — the dashboard,
the phone app and [automations](services.md).

## The catches, in plain words

- **Apple Home — volume:** up and down from the Control Center remote; there's no slider.
- **Google Home — source:** the app lists your sources but can't select one. Make a
  [shortcut switch](matter.md#choose-a-source-one-switch-per-favourite) such as
  *Kitchen Spotify* instead.
- **Alexa — volume and mute:** say it ("Alexa, set Kitchen volume to 6", "Alexa, mute
  Kitchen"); the Alexa app has no volume control for these devices.
- **Alexa — source:** only sources with [names Alexa knows](smart-home.md#alexa-name-your-sources-so-alexa-can-pick-them)
  (TV, CD, Tuner, Aux 1, HDMI 1…).
- **Alexa over Matter:** Alexa doesn't accept Matter speakers, so you switch zones with
  a ["Music" switch](matter.md#alexa-add-a-music-switch-per-zone) instead.
- **Google over Home Assistant Cloud — source:** depends on how Google sees the device.
- **SmartThings / Aqara — source:** the sources are sent; whether the app lets you pick one isn't tested yet.

## How we tested

| | Tested how |
|---|---|
| 🏠 Home Assistant | ✅ On a real AMC X86i |
| 🍎 Apple Home | 🔬 What Home Assistant sends to Apple — not yet on an iPhone |
| 🟢 Google Home (Matter) | ✅ In the Google Home app |
| 🟢 Google Home (Cloud) | ❔ Not yet |
| 🔵 Alexa (Cloud) | ✅ In the Alexa app, plus every Alexa command checked |
| 🔵 Alexa (Matter) | 🔬 With a Matter test controller — no Echo yet |
| ⚪ SmartThings / Aqara | 🔬 With a Matter test controller |

Tried one we haven't? [Tell us](https://github.com/mcjelcom/ha-audio-control/issues).
