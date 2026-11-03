"""The docs' "Works with" list must name every model the profiles support.

It was hand-written and drifted: it listed an "AMC XOi" no profile supports and
omitted models such as the DR-X86T and 306D. It is now generated from the
profiles; this keeps it in sync.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rs232_protocol.profile_loader import load_builtin_profiles

INDEX = Path(__file__).parents[2] / "docs" / "index.md"


def _works_with() -> str:
    text = INDEX.read_text()
    start = text.index("## Works with")
    return text[start : text.index("\n## ", start + 3)]


@pytest.mark.parametrize("name", sorted(load_builtin_profiles()))
def test_profile_and_all_its_models_are_listed(name: str) -> None:
    section = _works_with()
    profile = load_builtin_profiles()[name]
    assert f"| {name} |" in section, f"profile {name!r} missing from docs/index.md"
    for model in profile.get("models", []):
        assert model in section, f"model {model!r} ({name}) missing from docs/index.md"


def test_model_count_is_current() -> None:
    total = sum(len(p.get("models", [])) for p in load_builtin_profiles().values())
    assert f"**{total} models" in _works_with()
