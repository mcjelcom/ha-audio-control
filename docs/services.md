# Services & automations

| Service | Target | Does |
|---|---|---|
| `audio_control.set_bass` | zone entities, devices, areas, floors, labels | Bass level (`0` = flat); the valid levels depend on the device — most take even steps −8…+8, the AMC X86/XO only −8, −6, −4, 0, +4, +6, +8, Monoprice/Xantech every step −7…+7, the AMC XOir −12…+12 — and the AMC X86 needs the zone **on** |
| `audio_control.set_treble` | same | Treble, same scale |
| `audio_control.all_zones_off` | **none — all Audio Control devices** that support it | Turns every zone off |
| `audio_control.group_mode_on` | **none — all devices** with group support | All zones play `source` |
| `audio_control.group_mode_off` | **none — all devices** with group support | Zones return to independent sources |

Tone and group services only do anything on profiles that support them; power,
volume, mute and source are the standard `media_player` actions.

```yaml
# Kitchen a bit warmer at dinner
- action: audio_control.set_bass
  target:
    area_id: kitchen
  data:
    level: 4

# Everything off at midnight
- alias: Audio off at night
  triggers:
    - trigger: time
      at: "00:00:00"
  actions:
    - action: audio_control.all_zones_off

# Party mode: every zone on source 3
- action: audio_control.group_mode_on
  data:
    source: 3
```
