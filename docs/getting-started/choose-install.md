# Choose how to install

There are two ways to put Home Assistant and Audio Control on your Raspberry Pi.
**If you are not sure, choose Home Assistant OS** — it is what the rest of this
guide uses.

| | 🏠 **Home Assistant OS** (recommended) | ☁️ **balena** (preview) |
|---|---|---|
| **Best for** | One home, one Raspberry Pi | Looking after Pis far away, or several |
| **Setting up** | Memory card → HACS → Audio Control | One click, then the memory card |
| **Updates** | One click in Home Assistant | Deploy a new release in balena |
| **Extra apps** (backups, file editor…) | ✅ Yes | ❌ No |
| **Remote management** | Through Home Assistant | ✅ balena dashboard: logs, restart, terminal |
| **Accounts** | None | Free balenaCloud account |

Both get the same Audio Control, [dashboard](../dashboard.md) and
[ready-made automations](../services.md#ready-made-automations-blueprints) — balena
sets them up for you; on Home Assistant OS you switch the dashboard on once.

!!! note "balena is a preview"
    The balena template is built and tested automatically, but it is new. Choose it if
    remote management matters to you, and [tell us](https://github.com/mcjelcom/haac-balena/issues)
    how it went.

**Next:**

- Home Assistant OS → [2. Install Home Assistant](install-home-assistant.md)
- balena → [Install with balena](install-balena.md)
