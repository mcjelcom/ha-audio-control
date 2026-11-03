# 3. Install HACS

[HACS](https://hacs.xyz) (Home Assistant Community Store) installs and updates
community integrations such as Audio Control. Already have HACS? Skip to
[Install Audio Control](install-audio-control.md).

HACS's own guide is authoritative and kept current:

**➜ [hacs.xyz/docs/use](https://hacs.xyz/docs/use/)**

## Summary

1. **Download HACS** into Home Assistant, following the guide for your installation
   type:
    - *Home Assistant OS:* the guide offers an add-on, or a one-line command run from the
      **Terminal & SSH** add-on.
    - *Container:* run the guide's download command inside the Home Assistant container
      (`docker exec -it homeassistant bash`).
2. **Restart Home Assistant** (Settings → System → ⋮ → Restart).
3. **Add the HACS integration:** Settings → Devices & services → **Add integration** →
   search **HACS**. Tick the acknowledgements.
4. **Link GitHub:** HACS shows a short code. Open
   [github.com/login/device](https://github.com/login/device), enter the code and
   authorise HACS.
5. **HACS** now appears in the sidebar.

!!! note
    HACS only needs read access to public repositories. Audio Control itself makes no
    internet connections — it talks only to your audio device.

---

Next: [Install Audio Control](install-audio-control.md)
