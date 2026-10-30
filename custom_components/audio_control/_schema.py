"""Schema library shim: probatio on current Home Assistant, voluptuous before it.

Home Assistant 2026.10 replaced voluptuous with probatio throughout core and
dropped it from its own requirements. HA itself aliases `voluptuous` to probatio
in sys.modules at startup (`probatio.compat.install_as_voluptuous()` in
homeassistant/__init__.py), so a direct voluptuous import still works today --
this shim is a precaution, not a fix: it uses the real library by name and does
not depend on that alias being kept. Importing probatio alone would break every
HA release before 2026.10.

probatio is API-compatible for everything used here (Schema, Required,
Optional, All, Coerce, In, Range, Marker), and HA's config_validation helpers
return probatio validators, so schemas built from `vol` interoperate with `cv`.
"""

from __future__ import annotations

try:
    import probatio as vol
except ImportError:  # pragma: no cover - Home Assistant before 2026.10
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
