# Quickstart

Control your amplifier from Home Assistant in five steps. Each step links to a more
detailed guide if you get stuck.

!!! abstract "You'll need"
    - Your amplifier (for example an **AMC X86i**)
    - A **Raspberry Pi 4 or 5** with its official power supply
    - A **USB-to-RS232 adapter** and a **serial cable** (DB9)
    - About **1 hour**

![The five steps](assets/diagrams/quickstart-steps.svg)

## Step 1 — Connect the hardware

Plug the USB adapter into the Raspberry Pi, and the serial cable from the adapter
into the **RS232** port on the back of the amplifier.

[What to buy →](getting-started/prerequisites.md)

## Step 2 — Install Home Assistant

Install **Home Assistant OS** on the Raspberry Pi by following the official guide.
When it's done you open Home Assistant in your web browser.

[Install Home Assistant →](getting-started/install-home-assistant.md)

## Step 3 — Install HACS

HACS is a free "app store" for Home Assistant add-ons made by the community. Audio
Control is installed from there.

[Install HACS →](getting-started/install-hacs.md)

## Step 4 — Install Audio Control

In Home Assistant open **HACS**, search for **Audio Control**, click **Download**, and
**restart** Home Assistant.

[Install Audio Control →](getting-started/install-audio-control.md)

## Step 5 — Add your amplifier

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Audio Control** and click it.

    ![Searching for Audio Control](assets/screenshots/add-integration-search.png){ width="420" }

3. Choose your amplifier in the **Device** list, and pick its port in **Connection**.

    ![Choosing the amplifier](assets/screenshots/setup-step1-x86i.png){ width="420" }

4. Click **Submit**.

Done — each zone of your amplifier now appears in Home Assistant, ready to switch on,
turn up and change source.

![Your zones on a dashboard](assets/screenshots/dashboard.png)

!!! tip "No amplifier connected yet?"
    Type `demo` in **Connection** to try everything with a pretend amplifier. You can
    switch to the real one later.

**Next:** [rename your zones and sources](configuration.md), or see the full
[AMC X86i example](examples/amc-x86i.md).
