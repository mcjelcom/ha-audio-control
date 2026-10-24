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
tests/audio_control/                       ← pytest (879)
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
- **Schemas:** import `vol` from `._schema` (probatio on HA 2026.10+, voluptuous before). Never `import voluptuous` directly — HA no longer depends on it.
- **Service targets:** build `TargetSelection(call.data)` for `async_extract_referenced_entity_ids` (HA 2026.x); fall back to passing the call on older HA.

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
  move. Bump it together with the deploy repo's HA base image.
- Never `pip install -e` this package (the editable path hook breaks HA's loader).

## Known gaps

- RTI `set_powerstate` replies carry no zone → dropped on the 10-zone profile (needs a
  global power event).
- RTI `get_outputvol` (status poll) reply has no mapping yet — add once a real reply is captured.
