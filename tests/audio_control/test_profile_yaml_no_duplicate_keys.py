"""Profile YAML must not contain duplicate keys.

PyYAML silently keeps the LAST of two equal keys. An edit that added
`off_value: 0` above an existing `off_value: 62` left the old value in force,
so the AMC X86 power fix did nothing -- caught only by a test fed the real
hardware reply. This guard makes that class of mistake fail loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

PROFILES = (
    Path(__file__).parents[2]
    / "custom_components"
    / "audio_control"
    / "rs232_protocol"
    / "profiles"
)


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            msg = f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
            raise yaml.constructor.ConstructorError(
                None, None, msg, key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


@pytest.mark.parametrize("path", sorted(PROFILES.glob("*.yaml")), ids=lambda p: p.name)
def test_no_duplicate_keys(path: Path) -> None:
    yaml.load(path.read_text(), Loader=_StrictLoader)
