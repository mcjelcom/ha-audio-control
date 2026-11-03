"""The docs' "Works with" list must name every model the profiles support.

It was hand-written and drifted: it listed an "AMC XOi" no profile supports and
omitted models such as the DR-X86T and 306D. It is now generated from the
profiles; this keeps it in sync.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rs232_protocol.profile_loader import load_builtin_profiles

INDEX = Path(__file__).parents[2] / "docs" / "supported-models.md"


def _works_with() -> str:
    return INDEX.read_text()


@pytest.mark.parametrize("name", sorted(load_builtin_profiles()))
def test_profile_and_all_its_models_are_listed(name: str) -> None:
    section = _works_with()
    profile = load_builtin_profiles()[name]
    assert f"| {name} |" in section, (
        f"profile {name!r} missing from docs/supported-models.md"
    )
    for model in profile.get("models", []):
        assert model in section, (
            f"model {model!r} ({name}) missing from docs/supported-models.md"
        )


def test_model_count_is_current() -> None:
    total = sum(len(p.get("models", [])) for p in load_builtin_profiles().values())
    assert f"**{total} models" in _works_with()


def test_home_summary_counts_add_up() -> None:
    """The home page's per-brand counts must sum to the real model count."""
    import re

    home = (INDEX.parent / "index.md").read_text()
    counts = [
        int(n)
        for n in re.findall(
            r"^\| \[[^]]+\]\(supported-models\.md#[^)]+\) \| (\d+) \|",
            home,
            re.MULTILINE,
        )
    ]
    total = sum(len(p.get("models", [])) for p in load_builtin_profiles().values())
    assert counts, "brand summary table not found on the home page"
    assert sum(counts) == total
    assert f"**{total} models" in home
