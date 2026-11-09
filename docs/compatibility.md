# Compatibility

What each app can do with your zones, and how we checked.

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

**Bass and treble, all zones off, and group mode** work in Home Assistant's dashboard,
phone app, and [automations](services.md).

## The catches, in plain words

- **Apple Home — volume:** up/down from the Control Center remote; no slider.
- **Google Home — source:** listed but not selectable; use a [shortcut switch](matter.md#choose-a-source-one-switch-per-favorite)
  (e.g. *Kitchen Spotify*).
- **Alexa — volume and mute:** by voice only ("Alexa, set Kitchen volume to 6", "Alexa,
  mute Kitchen").
- **Alexa — source:** only sources with [names Alexa knows](smart-home.md#alexa-name-your-sources-so-alexa-can-pick-them)
  (TV, CD, Tuner, Aux 1, HDMI 1…).
- **Alexa over Matter:** no Matter speakers, so use a ["Music" switch](matter.md#alexa-add-a-music-switch-per-zone).
- **Google over Home Assistant Cloud — source:** depends on how Google classifies the device.
- **SmartThings / Aqara — source:** sources are sent; picking one is untested.

## How we tested

| | Tested how |
|---|---|
| 🏠 Home Assistant | ✅ On a real AMC X86i |
| 🍎 Apple Home | 🔬 What Home Assistant sends; not yet on an iPhone |
| 🟢 Google Home (Matter) | ✅ In the Google Home app |
| 🟢 Google Home (Cloud) | ❔ Not yet |
| 🔵 Alexa (Cloud) | ✅ In the Alexa app; every command checked |
| 🔵 Alexa (Matter) | 🔬 Matter test controller; no Echo yet |
| ⚪ SmartThings / Aqara | 🔬 Matter test controller |

Tried one we haven't? [Tell us about it](https://github.com/mcjelcom/ha-audio-control/issues).
