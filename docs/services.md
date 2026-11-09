# Automations and extra controls

Audio Control adds a few **actions** for automations, scripts, and buttons.

![An automation: when, if, then do](assets/diagrams/automations.svg)

| Action | What it does |
|---|---|
| **Set bass** | Zone bass (0 = flat) |
| **Set treble** | Zone treble (0 = flat) |
| **All zones off** | Every zone off |
| **Group mode on** | Every zone plays one source |
| **Group mode off** | Each zone plays its own source |

!!! info "Not every amplifier has these"
    **Bass and treble** levels depend on the model. The AMC X86i takes −8, −6, −4, 0,
    +4, +6, and +8, only while the zone is **on**. For a disallowed level, Home
    Assistant lists the allowed ones.

## Ready-made automations (blueprints)

1. Click **Import blueprint**, then in Home Assistant click **Preview** → **Import**.
2. Go to **Settings → Automations & scenes → Blueprints** and click the blueprint.
3. Pick your zones and times, and click **Save**.

A blueprint is a fill-in-the-blanks automation; it does nothing until you create an automation from it.

| Automation | What it does | |
|---|---|---|
| **All zones off at a time** | Turn every zone off at a set time, optionally only on some days | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Fall_zones_off_at_time.yaml) |
| **Scheduled zone on** | Turn a zone on at a set time with a chosen source and volume | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Fscheduled_zone_on.yaml) |
| **Auto off when forgotten** | Turn a zone off after it has been on for a while | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Fzone_auto_off_when_idle.yaml) |
| **Volume limiter** | Pull a zone's volume back down if it goes above a limit — protects speakers | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Fvolume_limiter.yaml) |
| **Group mode switch** | Turn whole-house group mode on and off from any toggle or schedule | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Fgroup_mode_toggle.yaml) |
| **Tone preset per source** | Set bass/treble when a zone switches to a source, and restore it after | [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmcjelcom%2Fha-audio-control%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Faudio_control%2Ftone_preset_on_source.yaml) |

*balena installs already include these under **Blueprints**.*

## Use them in an automation

1. Go to **Settings → Automations & scenes → Create automation → Create new automation**.
2. Add a **trigger**, e.g. *Time: 00:00*.
3. Under **Then do**, click **Add action**, search for **Audio Control**, and choose an
   action, e.g. **All zones off**.
4. Click **Save**.

## Examples

To paste one, choose **⋮ → Edit in YAML** in the automation editor.

**Turn everything off at midnight**

```yaml
triggers:
  - trigger: time
    at: "00:00:00"
actions:
  - action: audio_control.all_zones_off
```

**Warmer kitchen sound at dinner**

```yaml
triggers:
  - trigger: time
    at: "18:30:00"
conditions:
  - condition: state
    entity_id: media_player.kitchen   # your zone
    state: "on"
actions:
  - action: audio_control.set_bass
    target:
      entity_id: media_player.kitchen
    data:
      level: 4
```

**Party mode: every room plays source 3**

```yaml
actions:
  - action: audio_control.group_mode_on
    data:
      source: 3
```

??? note "Details for advanced users"
    | Action | Target | Notes |
    |---|---|---|
    | `audio_control.set_bass` / `set_treble` | zones, devices, areas, floors, labels | `level` −12…+12. Valid levels come from the device profile (default: even −8…+8). Valid zones change; one error lists any that couldn't |
    | `audio_control.all_zones_off` | none — **all** supporting Audio Control amplifiers | |
    | `audio_control.group_mode_on` | none — all amplifiers with group mode | `source` (number) |
    | `audio_control.group_mode_off` | none — all amplifiers with group mode | |
