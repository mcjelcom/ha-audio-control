# Choose how to install

You can put Home Assistant and Audio Control on your Raspberry Pi in two ways.
**If you're not sure, choose Home Assistant OS.** The rest of this guide uses it.

| | 🏠 **Home Assistant OS** (recommended) | ☁️ **balena** (preview) |
|---|---|---|
| **Best for** | One home, one Raspberry Pi | Several Pis, or Pis far away |
| **Setting up** | Memory card → HACS → Audio Control | One click, then the memory card |
| **Updates** | One click in Home Assistant | Deploy a new release in balena |
| **Extra apps** (backups, file editor…) | ✅ Yes | ❌ No |
| **Remote management** | Through Home Assistant | ✅ balena dashboard: logs, restart, terminal |
| **Accounts** | None | Free balenaCloud account |

Both get the same Audio Control, [dashboard](../dashboard.md), and
[ready-made automations](../services.md#ready-made-automations-blueprints). balena sets
them up for you. On Home Assistant OS, you switch the dashboard on once.

!!! note "balena is a preview"
    The balena template is built and tested automatically, but it's new. Choose it if
    remote management matters to you. Then
    [tell us how it went](https://github.com/mcjelcom/haac-balena/issues).

**Next:**

- Home Assistant OS → [2. Install Home Assistant](install-home-assistant.md)
- balena → [Install with balena](install-balena.md)
