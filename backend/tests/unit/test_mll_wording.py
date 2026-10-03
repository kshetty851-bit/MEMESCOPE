"""The Lab describes; it never advises.

Design rule 9 (docs/MEME_LIFECYCLE_LAB.md): no buy / sell / hold wording in any
user-facing string. Every string literal in the Lab's I/O surface — schemas,
service, API, scheduler — is scanned, as is every rendered label table, so a
new label cannot slip advice in. Docstrings are exempt: they are for the
reader of the code, and several of them state this very rule.

"paper entry" / "paper exit" are the sanctioned names for simulated trades.
The pattern is anchored at a word start, so "threshold" passes while
"holding", "buying" and "considered" do not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.lifecycle_lab import service
from app.lifecycle_lab.domain import EventType, ExitReason

pytestmark = pytest.mark.unit

PACKAGE = Path(service.__file__).parent
SCANNED = ("schemas.py", "service.py", "api.py", "scheduler.py")
ADVICE = re.compile(r"\b(buy|sell|hold|consider|recommend)", re.IGNORECASE)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    skip = _docstring_nodes(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
    ]


@pytest.mark.parametrize("name", SCANNED)
def test_no_advice_wording_in_string_literals(name: str) -> None:
    path = PACKAGE / name
    assert path.exists(), f"{name} moved; the scan must not pass vacuously"
    offending = [s for s in _literals(path) if ADVICE.search(s)]
    assert offending == [], f"{name} has advice wording: {offending}"


def test_every_rendered_label_is_observational() -> None:
    """The label tables cover every code the engines can emit, and none of
    the prose they render reads as advice — including the fallbacks."""
    assert set(service.EVENT_LABELS) == set(EventType)
    assert set(service.EVENT_MARKER_KINDS) == set(EventType)
    assert set(service.EXIT_REASON_TEXT) == set(ExitReason)
    rendered = [
        *service.EVENT_LABELS.values(),
        *service.EVENT_MARKER_KINDS.values(),
        *service.EXIT_REASON_TEXT.values(),
        *service.ENTRY_REASON_TEXT.values(),
        *service.HYPOTHESES.values(),
        *service.SOURCE_LABELS.values(),
        *(service.exit_reason_text(r.value) or "" for r in ExitReason),
        *(service.timeline_text(f"exit:{r.value}", {}) for r in ExitReason),
        *(service.timeline_text(f"event:{e.value}", {}) for e in EventType),
        service.timeline_text("entry", {"reason_code": "conditions_met"}),
    ]
    offending = [s for s in rendered if ADVICE.search(s)]
    assert offending == []


def test_paper_trades_are_labelled_paper() -> None:
    assert service.timeline_text("entry", {"reason_code": "conditions_met"}).startswith(
        "Paper entry"
    )
    assert service.timeline_text("exit:take_profit", {}).startswith("Paper exit")


def test_the_pattern_catches_what_it_must() -> None:
    """A guard against the guard: a regex that matched nothing would pass."""
    for bad in ("Buy now", "consider selling", "holding period", "we recommend"):
        assert ADVICE.search(bad)
    for fine in ("paper entry", "threshold", "paper exit", "take-profit level reached"):
        assert not ADVICE.search(fine)
