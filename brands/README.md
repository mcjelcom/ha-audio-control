# Brand assets

Staged here for submission to [home-assistant/brands](https://github.com/home-assistant/brands).
HACS's `brands` check fails until `audio_control` exists in that repository; it
does not affect installing this integration as a HACS custom repository.

## Submission

Copy `custom_integrations/audio_control/` into a fork of `home-assistant/brands`
at the same path and open a pull request:

```
custom_integrations/audio_control/icon.png    256x256, RGBA, transparent margin
custom_integrations/audio_control/logo.png    505x144, RGBA, transparent
```

## Provenance and licensing

The glyph is Material Design Icons `speaker-multiple`, from
[Templarian/MaterialDesign-SVG](https://github.com/Templarian/MaterialDesign-SVG),
licensed **Apache-2.0**. Home Assistant itself ships MDI, and the integration
already uses `mdi:speaker-multiple` for its own entity icons, so the two are
visually consistent.

Apache-2.0 permits redistribution and modification. The modifications here are:
recolouring to white, placement on a rounded `#0288D1` tile, and — for the logo —
composition with the wordmark "Audio Control".

`icon.svg` and `logo.svg` are the sources. Regenerate the PNGs with:

```bash
qlmanage -t -s 1024 -o . icon.svg     # macOS; renders onto an opaque canvas
# then crop to content and composite with transparency (see git history)
```

Note that `qlmanage` pads with opaque white and forces a square canvas, so the
PNGs are produced by cropping to the artwork bounding box and recompositing onto
a transparent canvas rather than used directly.
