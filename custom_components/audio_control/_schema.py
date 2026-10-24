"""Schema library shim: probatio on current Home Assistant, voluptuous before it.

Home Assistant 2026.10 replaced voluptuous with probatio throughout core and
dropped voluptuous from its own requirements -- it is still installed only as a
transitive dependency of two unrelated packages. Importing voluptuous directly
would make this integration fail to load the day that stops being true, while
importing probatio alone would break every HA release before 2026.10.

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
