"""The user docs follow the Google developer documentation style guide.

https://developers.google.com/style/highlights -- these are the rules that a
script can check. Added 2026-11-08 after a concision pass (10,448 -> 9,007 words)
so later edits don't drift back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
PAGES = sorted(DOCS.rglob("*.md"))
VAGUE_LINK = re.compile(
    r"\[(how|here|this|list|partial|more|details|click here|what works)\]\(",
    re.IGNORECASE,
)
FILLER = re.compile(
    r"\b(simply|just|easily|basically|please note|note that|in order to)\b",
    re.IGNORECASE,
)
MAX_WORDS = 28


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """Lines of running text: skip code blocks, tables, admonition headers, HTML, images."""
    out, in_code = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or line.strip().startswith(("|", "!!!", "???", "<", "![")):
            continue
        out.append((n, line))
    return out


@pytest.mark.parametrize("path", PAGES, ids=lambda p: str(p.relative_to(DOCS)))
def test_style(path: Path) -> None:
    problems = []
    for n, line in prose_lines(path):
        if m := VAGUE_LINK.search(line):
            problems.append(
                f"{n}: vague link text [{m.group(1)}] -- name where it goes"
            )
        if re.match(r"#{1,6} .*&", line):
            problems.append(f"{n}: use 'and', not '&', in headings")
        if m := FILLER.search(line):
            problems.append(f"{n}: filler word '{m.group(1)}'")
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if (w := len(sentence.split())) > MAX_WORDS:
                problems.append(f"{n}: {w}-word sentence (max {MAX_WORDS})")
    assert not problems, "\n".join(problems)
