# Adding a Device Profile

This guide shows how to add support for a new RS232 audio device. Most devices can be added with a single YAML file — no Python code required.

## Quick Start

**Using a device that isn't bundled (no code, survives updates):**

1. Copy [`_template.yaml`](../custom_components/audio_control/rs232_protocol/profiles/_template.yaml)
   into your Home Assistant config as `config/audio_control/<manufacturer>_<model>.yaml`
   (create the `audio_control` folder if needed).
2. Fill it in from the device's RS232 manual (format below).
3. Restart Home Assistant. The profile appears in the **Device** dropdown with a
   `(Custom)` suffix.
4. Try it first with the connection set to `demo`, then switch to the real port
   via **Reconfigure**.

Do **not** edit the bundled `profiles/` folder on an installed copy: HACS
replaces it on every update.

**Contributing a profile to the bundle:** add the file to
`custom_components/audio_control/rs232_protocol/profiles/`, validate it (see
[Validation](#validation)), and open a PR.

## Profile Template

```yaml
# manufacturer_model.yaml
name: "Manufacturer Model Name"
manufacturer: "Manufacturer"
models: ["Model1", "Model2"]

zones: 6
sources: 8

serial:
  baud_rate: 9600
  data_bits: 8
  parity: "none"        # none, even, odd
  stop_bits: 1
  command_delay_ms: 100 # minimum ms between commands
  command_prefix: ""    # prepended to every command (e.g., "*", "!")
  command_suffix: "\r"  # appended to every command
  response_prefix: ""   # stripped from responses (e.g., "#", ">")
  response_terminator: "\r"  # end-of-response delimiter

commands:
  status:      "Z{zone:02d}STA"
  power_on:    "Z{zone:02d}PON"
  power_off:   "Z{zone:02d}POFF"
  volume_set:  "Z{zone:02d}VOL{volume:02d}"
  volume_up:   "Z{zone:02d}VU"
  volume_down: "Z{zone:02d}VD"
  mute_on:     "Z{zone:02d}MUON"
  mute_off:    "Z{zone:02d}MUOFF"
  source_set:  "Z{zone:02d}SRC{source:02d}"
  # Optional:
  bass_set:    "Z{zone:02d}BAS{sign}{level}"
  treble_set:  "Z{zone:02d}TRB{sign}{level}"
  all_off:     "ALLOFF"
  group_on:    "GRP{source:02d}"
  group_off:   "GRPOFF"

response:
  status_pattern: "Z(?P<zone>\\d{2}),PWR(?P<power>\\d),SRC(?P<source>\\d{2}),VOL(?P<volume>\\d{2}),MUT(?P<mute>\\d)"
  error_response: "?"
  # Optional:
  tone_pattern: "Z(?P<zone>\\d{2}),BASS(?P<bass>[+-]?\\d+),TREB(?P<treble>[+-]?\\d+)"
  global_patterns:
    all_off: "ALLOFF"
    group_on: "GRP(?P<source>\\d{2})"

  mapping:
    power:
      field: "power"
      type: "bool"
      on_value: "1"
    mute:
      field: "mute"
      type: "bool"
      on_value: "1"
    volume:
      field: "volume"
      type: "int"
    source:
      field: "source"
      type: "int"
    # Optional tone mappings:
    bass:
      field: "bass"
      type: "signed_int"
    treble:
      field: "treble"
      type: "signed_int"

volume:
  min: 0
  max: 38
  inverted: false  # true if 0=loud, max=mute (like AMC's attenuation)

features:
  has_tone_controls: false
  has_group_mode: false
  has_all_off: false
  has_balance: false
  unsolicited_updates: false  # true if device pushes state without polling
```

## Command Placeholders

| Placeholder | Description | Example |
|---|---|---|
| `{zone}` | Zone number (1-based) | 1, 2, ... 16 |
| `{zone:02d}` | Zone zero-padded to 2 digits | 01, 02, ... 16 |
| `{zone:1d}` | Zone as single digit | 1, 2, ... 8 |
| `{source}` | Source number (1-based) | 1, 2, ... 8 |
| `{source:02d}` | Source zero-padded | 01, 02, ... 16 |
| `{volume}` | Volume value (device units) | 0-38, 0-62, 0-100 |
| `{volume:02d}` | Volume zero-padded | 00-62 |
| `{level}` | Tone level (bass/treble) | 0-14, or absolute |
| `{sign}` | Sign character for tone | `+` or `-` |
| `{source_name}` | Named source (for Rotel/Marantz) | `cd`, `aux1` |

## Response Mapping Types

| Type | Description | Example |
|---|---|---|
| `int` | Parse as integer | `"25"` → 25 |
| `signed_int` | Signed integer (for +/- values) | `"-4"` → -4 |
| `bool` | Compare to `on_value` string | `"1"` == `"1"` → True |
| `string_bool` | String comparison | `"ON"` == `"ON"` → True |
| `threshold` | True if value != `off_value` | `25` != 62 → True (power on) |
| `equals` | True if value == `mute_value` | `62` == 62 → True (muted) |
| `string` | Keep as string | `"cd"` → `"cd"` |

Add `offset: -7` to shift raw values (e.g., Xantech bass 0-14 → -7 to +7).

## Validation

From a checkout of this repository (`make setup` once):

```bash
# Every bundled profile must load and format its commands
.venv/bin/python -m pytest tests/audio_control/test_profile_loader.py -q

# Or poke at one profile directly:
PYTHONPATH=custom_components/audio_control .venv/bin/python -c "
from rs232_protocol import create_engine, load_builtin_profiles
engine = create_engine(load_builtin_profiles()['Your Device Name'])
print(engine.format_command('power_on', zone=1))
print(engine.format_command('volume_set', zone=1, volume=25))
"
```

## Where to Find Protocol Info

| Source | What you'll find |
|--------|-----------------|
| Device manual (PDF) | RS232 appendix with command table |
| Manufacturer website | Support/downloads section |
| GitHub search | `<manufacturer> rs232` — often has protocol docs |
| Control4/Crestron driver DBs | Protocol specs embedded in drivers |
| Home automation forums | Community reverse-engineering |
| `pypi.org` search | Python libraries with protocol details |

## Protocol Types

Most audio devices use the default text protocol. For binary or JSON protocols, see [protocol-types.md](protocol-types.md).

## Submitting

1. Name your file: `manufacturer_model.yaml` (lowercase, underscores)
2. Include a comment header with the full device name
3. List all compatible models in the `models:` array
4. Cite the manual (and ideally confirm on real hardware) in the PR
5. Run `make ci` to verify all checks pass, then open a PR
