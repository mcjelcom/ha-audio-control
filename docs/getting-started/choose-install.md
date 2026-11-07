# Choose how to install

There are two ways to put Home Assistant and Audio Control on your Raspberry Pi.
**If you are not sure, choose Home Assistant OS** — it is what the rest of this
guide uses.

| | **Home Assistant OS** — recommended | **balena** — preview |
|---|---|---|
| **Best for** | One home, one Raspberry Pi | Looking after a Pi remotely (a second home, a family member's system) or several of them |
| **Setting up** | Write the memory card → install HACS → install Audio Control | Click **Deploy with balena** → write the memory card → done. Audio Control is already installed |
| **Accounts** | None (HACS asks you to sign in with GitHub) | A free **balenaCloud** account (free for up to 10 devices) |
| **Updates** | One click inside Home Assistant, for both Home Assistant and Audio Control | When a new release of the template comes out, you update the fleet in the balena dashboard. There is no update button in Home Assistant |
| **Dashboard** | The same ready-made dashboard, switched on once by hand ([how](../dashboard.md#home-assistant-os)); the automations are one-click imports ([list](../services.md#ready-made-automations-blueprints)) | ✅ A ready-made **Audio Control** dashboard and automation blueprints, filled in automatically |
| **Apps (add-ons)** | ✅ The full Apps store: backups, file editor, remote access… | ❌ None — balena runs Home Assistant without its Supervisor |
| **Managing from far away** | Through Home Assistant itself (Home Assistant Cloud or a remote-access app) | ✅ The balena dashboard shows status and logs, opens a terminal and restarts the device from anywhere — even when Home Assistant is down |
| **Several devices** | Each one is set up and updated on its own | ✅ All devices in a fleet update together |
| **When something goes wrong** | Large community; almost every guide assumes Home Assistant OS | You need to know a little about balena as well; fewer guides |
| **Internet needed** | Only to install and update | Only to install, update and manage — Home Assistant keeps running offline |

!!! note "balena is a preview"
    The balena template is built and tested automatically, but it is new. Choose it if
    remote management matters to you, and [tell us](https://github.com/mcjelcom/haac-balena/issues)
    how it went.

**Next:**

- Home Assistant OS → [2. Install Home Assistant](install-home-assistant.md)
- balena → [Install with balena](install-balena.md)
