# CLAUDE.md — AI Working Context for ha-audio-control

Home Assistant custom integration **Audio Control** (`audio_control`) for RS232 / IP
multi-zone audio devices, distributed through the **HACS default list**. Device
behaviour comes from YAML profiles interpreted by the vendored `rs232_protocol` library.

## Layout

```
hacs.json                                  ← HACS manifest (every referenced file must exist in the release)
custom_components/audio_control/
├── manifest.json                          ← "version" must match the release tag
├── brand/{icon,logo}.png                  ← HACS checks in-repo brand assets first
└── rs232_protocol/                        ← zero HA imports; vendored, NOT on PyPI
    ├── protocol_engine.py                 ← text/regex engine
    ├── binary_engine.py                   ← binary frames + checksums
    ├── json_engine.py                     ← JSON-over-serial (login, templates, response.mappings)
    ├── factory.py                         ← create_engine(profile)
    ├── connection.py                      ← AsyncSerialConnection, _process_response → ZoneState
    ├── profile_loader.py                  ← load_builtin_profiles()
    └── profiles/*.yaml                    ← 27 device profiles
tests/audio_control/                       ← pytest (968)
```

## Commands

```bash
make setup   # uv venv --python 3.14 + uv pip install --python .venv -r requirements-dev.txt
make ci      # ruff check + ruff format --check + mypy --strict + pytest
```

## Conventions

- New device = new YAML profile; no code changes unless a protocol feature is missing.
- Parsed reply keys consumed by `_process_response`: `zone`, `power`, `mute`, `volume`,
  `source`, `bass`, `treble`, `balance`, `group`, `global`, `error`. Anything else is ignored.
- JSON `response.mappings` map reply fields to those keys; values are coerced (ints for
  volume/source/tone/balance, bools for power/mute/group; bool is never accepted as int).
- Single-zone devices: a reply with no zone is attributed to zone 1; on multi-zone
  devices it is dropped (never written into an arbitrary zone).
- HA Core style: `entry.runtime_data`, `has_entity_name`, translation keys for errors,
  `PARALLEL_UPDATES = 0`, `async_migrate_entry` (config entry VERSION 3, uid prefix `ac_`).
- `usb` is an `after_dependencies`, not a `dependencies` entry.
- ruff `ALL` (0.15.21), mypy `--strict` (2.2.0). Dev/CI on Python 3.14 (required by the HA 2026.10 harness).
- **Schemas:** import `vol` from `._schema` (probatio on HA 2026.10+, voluptuous before). Don't `import voluptuous` directly — HA no longer depends on it (it currently aliases it to probatio, but don't rely on that).
- **Service targets:** build `TargetSelection(call.data)` for `async_extract_referenced_entity_ids` (HA 2026.x); fall back to passing the call on older HA.

## Documentation site

`docs/` → **Zensical** (pinned, `variant: modern`; reads `mkdocs.yml`) → GitHub Pages: **https://haac.mcjel.com/** (`.github/workflows/docs.yml`, strict
build, runs on pushes to `main` touching docs; no release needed). Preview:
`uv venv .venv-docs && uv pip install --python .venv-docs -r requirements-docs.txt &&
.venv-docs/bin/zensical serve` (binds localhost only — verified). Build: `zensical build --strict --clean`;
validation keys are Zensical's (`invalid_links`, `invalid_link_anchors`). Switched from
MkDocs + Material 2026-11-06: Material is maintenance-only until 2027-05-05 and MkDocs 1.x is
unmaintained. `variant:` is NOT validated (a typo silently falls back to the default). Rules: public content only — no home
IPs, hostnames, account names; screenshots crop to a dialog/panel (never sidebar or
URL bar); after deploy, fetch pages anonymously and require 200. Screenshots come from
a live HA via headless Playwright with an on-device token; open a config flow and
cancel it (Escape) — check no flow is left in progress.

## Releasing

- HACS installs **tagged GitHub Releases**, not `main`. Bump `manifest.json`, commit,
  tag `vX.Y.Z`, push the tag, `gh release create --latest`. Wait for CI (lint/test,
  Hassfest, HACS validation).
- Never move a published tag (orphans the Release) — cut a new patch version instead.

## Lessons

- **Every bug fix ships a regression test that fails on the old code.** Test against
  the shipped profile and end to end through `_process_response`, not only the engine.
- **Stored-but-unused config is a bug smell:** the JSON engine loaded
  `response.mappings` and never applied them (fixed in 2.0.3), so RTI state never
  reflected keypad changes.
- **A tag can lag the fix** — v2.0.0 shipped without the `helpers.target` import fix.
  Verify the tag's content, not just `main`.
- **Pin the test harness to the HA the devices run.** `pytest-homeassistant-custom-component`
  pins HA itself; unpinned on Python 3.12 it resolved to HA 2024.12.5 while devices ran
  2026.x. Moving to the 2026.10.2 harness exposed a live bug (tone services raised
  `'ServiceCall' object has no attribute 'has_any_target'`) and the voluptuous → probatio
  move (HA aliases voluptuous, so that one was a precaution, not a break). Bump it together with the deploy repo's HA base image.
- Never `pip install -e` this package (the editable path hook breaks HA's loader).

- **Trust captured replies over manuals.** The AMC RS232 manual v3.3 shows `,GRP` in the tone
  reply; a real X86i omits it, so an accepted bass change failed (fixed 2.0.5). AMC `VOL-62`
  means both muted and off — power comes from `SRC00`. Manuals: amchome.com/smart/amc-x86i/.
- **YAML keeps the last duplicate key silently** — `test_profile_yaml_no_duplicate_keys.py`
  guards profiles (an edit left `off_value: 62` below `off_value: 0`).

- **Multi-target services: command every valid zone, then raise ONE error** (like
  `_broadcast`). Raising inside the loop left area targets half-applied.
- **JSON mappings: zone and fields must come from the SAME array item** (a 2-item reply
  wrote zone 1's volume into zone 2 until 2.0.7).
- **Review with several models.** A 4-model review (Opus/Sonnet/Haiku/Fable) of
  v2.0.3..2.0.6 found the JSON zone mix-up, missing XO/XOir tone mappings and the
  half-applied tone service; each model caught things others missed.

- **A device-wide reply needs a device-wide confirmation path.** v2.0.8 made RTI
  power replies global, but `_wait_for_response` refused globals for zoned commands,
  so every RTI turn_on/off timed out and rolled the clicked zone back (found by 3 of
  4 reviewers; fixed 2.0.9). Test new reply shapes end to end through `send_command`,
  not only `_process_response`.
- **Anything an optimistic update sets, the rollback must restore** (`power_known`).

## Known gaps

Closed in 2.0.8 (A-E): RTI device-wide power (`scope: device`), RTI `get_outputvol`
mapping, XOir absolute tone (`negative_base: 20`), per-profile odd levels (schema
-12..+12, default even -8..+8), `ZoneState.power_known` gating the off-zone check.
Still **unverified on hardware**: everything RTI, and the AMC XOir tone encoding.
