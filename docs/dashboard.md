# Ready-made dashboard

Audio Control can build a self-updating **Audio Control** dashboard: one card per zone,
plus **All Off** and **Group** buttons.

![The Audio Control dashboard](assets/screenshots/balena-dashboard.png)

![Turning on the ready-made dashboard](assets/diagrams/dashboard.svg)

## Installed with balena?

It's already in the sidebar.

## Home Assistant OS

Switch it on once with the **File editor** app.

### 1. Install the File editor app

1. Go to **Settings → Apps** and open the **app store** (bottom right).
2. Search for **File editor**, open it, and click **Install**.
3. Turn on **Show in sidebar** and click **Start**.

### 2. Create the dashboard file

1. Open **File editor** from the sidebar.
2. Click the folder icon (top left) → **New folder**, named `dashboards`.
3. In `dashboards`, click **New file**, named `audio_control.yaml`.
4. Put exactly this line in it and click **Save** (red disk icon):

    ```yaml
    # audio_control:managed
    ```

### 3. Add the dashboard to your settings

1. In File editor, open **`configuration.yaml`** (top folder).
2. Add this at the end and click **Save**:

    ```yaml
    lovelace:
      dashboards:
        audio-control:
          mode: yaml
          title: Audio Control
          icon: mdi:speaker-multiple
          show_in_sidebar: true
          filename: dashboards/audio_control.yaml
    ```

!!! warning "Already have a `lovelace:` line?"
    Don't add a second one. Add only the part from `dashboards:` down, under your
    existing `lovelace:` (or its `dashboards:`).

### 4. Restart

Go to **Settings → System → ⏻ (top right) → Restart Home Assistant.** **Audio Control**
then appears in the sidebar.

## Make it your own

Audio Control rebuilds the dashboard at each start, replacing your edits. To keep your
own version, delete the first line (`# audio_control:managed`) of
`dashboards/audio_control.yaml`. Audio Control then leaves it alone.
