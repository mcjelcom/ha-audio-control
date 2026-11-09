# Install with balena (preview)

*Not sure this is for you? See [Choose how to install](choose-install.md). For one
Raspberry Pi at home, [Home Assistant OS](install-home-assistant.md) is simpler.*

You get Home Assistant **with Audio Control and its dashboard already installed**, managed
from the [balenaCloud](https://www.balena.io/cloud) dashboard. You skip the HACS steps.

![Installing with balena](../assets/diagrams/install-balena.svg)

## You'll need

- Everything on the [shopping list](prerequisites.md): a **Raspberry Pi 4 or 5**,
  memory card, power supply, adapter, and cable. A Raspberry Pi 3 works too, but slowly.
- A free **balenaCloud** account. You can create it in step 1.
- **balenaEtcher** on your computer, to write the memory card.
  [Download balenaEtcher](https://etcher.balena.io/).

## 1. Create your fleet

Click this button:

[![Deploy with balena](https://balena.io/deploy.svg)](https://dashboard.balena-cloud.com/deploy?repoUrl=https://github.com/mcjelcom/haac-balena)

Sign in, name the fleet (for example, *audio-control*), choose your **Raspberry Pi model**,
and click **Create and deploy**. The build takes a couple of minutes.

## 2. Prepare the memory card

1. In your new fleet, click **Add device**.
2. Choose **Ethernet only** (recommended). Or choose **Wi-Fi + Ethernet** and type your
   Wi-Fi name and password.
3. Click **Download balenaOS**. Open the file in **balenaEtcher** and write it to the
   memory card. Or click **Flash** to do both in one go.

## 3. Start the Raspberry Pi

1. Put the card in the Raspberry Pi. Connect the network cable, the USB adapter, and
   the power supply.
2. The device appears as **Online** and downloads Home Assistant. Allow **20–40 minutes**.
3. When the **homeassistant** service shows **Running**, note the device's **IP address**.

## 4. Open Home Assistant

In your web browser, open **http://&lt;IP address&gt;:8123**, such as
`http://192.168.1.50:8123`. Create your account and follow the welcome screens.

Then [add your amplifier](install-audio-control.md#add-your-amplifier). Audio Control is
already installed.

## Your Audio Control dashboard

The **Audio Control** dashboard in the sidebar fills in when you add your amplifier: one
card per zone, plus **All Off** and **Group** buttons. It follows zone renames.

![The Audio Control dashboard](../assets/screenshots/balena-dashboard.png)

To change it yourself, see [Make it your own](../dashboard.md#make-it-your-own).

[Ready-made automations](../services.md#ready-made-automations-blueprints) are under
**Settings → Automations & scenes → Blueprints**. They do nothing until you use one.

## Matter (optional)

The template includes **Matter Hub**, switched **off**. It can share your zones with
Google Home, Alexa, or SmartThings. See [Matter (partial)](../matter.md).

To turn it on, add these **device variables** (your device → **Variables** → **Add**,
service `matter-hub`):

| Variable | Value |
|---|---|
| `HAAC_MATTER` | `1` |
| `HAMH_HOME_ASSISTANT_ACCESS_TOKEN` | A long-lived token: Home Assistant → your profile (bottom left) → **Security** → **Create token** |
| `HAMH_HTTP_AUTH_USERNAME` | A username of your choice |
| `HAMH_HTTP_AUTH_PASSWORD` | A password of **at least 12 characters** |

Then open **http://&lt;IP address&gt;:8482**, log in, and
[create a bridge](../matter.md#2-create-a-bridge-for-your-zones). Until all four are set,
Matter Hub stays off.

## Updates

New [template releases](https://github.com/mcjelcom/haac-balena/releases) update Home
Assistant and Audio Control together. To update, deploy the new release to your fleet
with the **Deploy with balena** button or `balena push`.

!!! warning "Don't install Audio Control from HACS on a balena device"
    The built-in copy replaces it at every start. HACS is fine for other integrations.

## Good to know

- Home Assistant is reachable on your **home network only**, behind its own login. Nothing
  else is opened, except Matter Hub's two ports if you turn it on.
- balena has no **Apps** (add-ons). Use the balena dashboard for logs, a terminal, and
  restarts.
- Something not working? See [Help and troubleshooting](../troubleshooting.md) and check
  the **homeassistant** logs on the device page.
