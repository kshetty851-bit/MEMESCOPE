"""Every stable code the lab emits has a sentence, and none gives advice.

Prose is rendered from codes when a result is read (never stored), so a code
without a sentence would show the page a raw snake_case token. And the page is
research and paper only: its text must read the same to someone who is not
allowed to trade, so nothing here may say buy, sell, hold, consider or should.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.labs.forex import compare, csv_import, data, engine, meta, prose, research, targets
from app.labs.forex.types import ExitReason, SkipReason

pytestmark = pytest.mark.unit

PACKAGE = Path(__file__).resolve().parents[4] / "app" / "labs" / "forex"

#: Recommendation language. Word-bounded so "threshold" or "household" cannot
#: trip it, and "sell"/"buy" are caught anywhere they stand alone.
ADVICE = re.compile(
    r"\b(buy|buys|buying|sell|sells|selling|hold|holds|holding|consider|considers|"
    r"should|recommend\w*|advis\w*|suggest\w*|worth|opportunity|good time|bad time)\b",
    re.IGNORECASE,
)


def _module_constants(module: object, prefix: str) -> set[str]:
    return {
        value
        for name, value in vars(module).items()
        if name.startswith(prefix) and isinstance(value, str)
    }


def _signal_reasons() -> set[str]:
    """The `reason` literal on every `Signal(...)` a strategy emits."""
    tree = ast.parse((PACKAGE / "strategies.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Signal"
            and node.args
            and isinstance(node.args[-1], ast.Constant)
            and isinstance(node.args[-1].value, str)
        ):
            found.add(node.args[-1].value)
    return found


def _emitted_codes() -> set[str]:
    """Codes written by this package's own serialiser and jobs."""
    found: set[str] = set()
    for name in ("serialize.py", "jobs.py", "service.py"):
        text = (PACKAGE / name).read_text()
        found |= set(re.findall(r'\{"code": "([a-z0-9_]+)"\}', text))
        found |= set(re.findall(r'\bcode\("([a-z0-9_]+)"\)', text))
        if name == "jobs.py":  # module constants naming a research note
            found |= set(re.findall(r'^[A-Z_]+ = "([a-z0-9_]+)"$', text, re.MULTILINE))
    return found - {"code"}


def _all_codes() -> dict[str, set[str]]:
    return {
        "engine assumptions": set(engine.ASSUMPTIONS),
        "ruin assumptions": set(targets.RUIN_ASSUMPTIONS),
        "target disclaimers": set(targets.DISCLAIMER_CODES),
        "monte carlo assumptions": set(research.MC_ASSUMPTIONS),
        "skip reasons": {r.value for r in SkipReason},
        "exit reasons": {r.value for r in ExitReason},
        "signal reasons": _signal_reasons(),
        "scorecard flags": {
            compare.NEGATIVE_EXPECTANCY,
            compare.INSUFFICIENT_TRADES,
            compare.EXCESSIVE_DRAWDOWN,
            compare.COST_SENSITIVE,
            compare.POOR_OUT_OF_SAMPLE,
            compare.POSSIBLE_OVERFITTING,
            compare.NOT_SIGNIFICANT,
            compare.NO_OUT_OF_SAMPLE,
        },
        "verdicts": {"candidate_edge", "no_edge_detected", "inconclusive"},
        "data quality notes": _module_constants(data, "NOTE_"),
        "csv notes": _module_constants(csv_import, "NOTE_"),
        "metric notes": {
            "no_losses",
            "no_trades",
            "insufficient_days",
            "zero_variance",
            "zero_downside",
            "insufficient_trades",
            "insufficient_observations",
        },
        "run errors": {
            "window_too_short_for_split",
            "invalid_split_fractions",
            "end_not_after_start",
            "no_data_for_range",
            "no_candles_in_window",
            "no_fold_fits_range",
            "market_lacks_trend_timeframe",
            "interrupted",
        },
        "meta disclaimer": {meta.DISCLAIMER_CODE},
        "codes this package emits": _emitted_codes(),
    }


@pytest.mark.parametrize("group", sorted(_all_codes()))
def test_every_code_has_a_sentence(group: str) -> None:
    codes = _all_codes()[group]
    assert codes, f"no codes found for {group}: the collector is broken"
    missing = sorted(c for c in codes if c not in prose.TEXT)
    assert not missing, f"{group} without prose: {missing}"


def test_the_code_collectors_see_what_they_should() -> None:
    """Pin a few members so a collector that silently matches nothing fails."""
    assert "asian_high_breakout" in _signal_reasons()
    assert "bb_reentry_short" in _signal_reasons()
    assert "selection_on_development_only" in _emitted_codes()
    assert "baseline_stand_aside" in _emitted_codes()


def test_a_sentence_is_a_sentence() -> None:
    for code, text in prose.TEXT.items():
        assert text.strip() == text, code
        assert text[0].isupper() or text[0].isdigit(), code
        assert text.endswith("."), code
        assert text != code


def test_no_sentence_gives_advice() -> None:
    offenders = {c: m.group(0) for c, t in prose.TEXT.items() if (m := ADVICE.search(t))}
    assert not offenders, offenders


def test_no_form_text_gives_advice() -> None:
    """The strategy descriptions and field help are rendered to the page too."""
    texts: list[str] = [s["description"] for s in meta.strategies_meta()]
    for fields in [meta.shared_fields(), *(s["param_fields"] for s in meta.strategies_meta())]:
        texts.extend(f["help"] + " " + f["label"] for f in fields)
    offenders = [t for t in texts if ADVICE.search(t)]
    assert not offenders, offenders


def test_the_advice_filter_can_fail() -> None:
    assert ADVICE.search("You should buy the dip")
    assert ADVICE.search("Consider holding")
    assert not ADVICE.search("The threshold was reached and the household moved")


def test_unknown_code_renders_as_itself() -> None:
    assert prose.text("a_code_from_the_future") == "a_code_from_the_future"
    assert prose.render({"code": "a_code_from_the_future"}) == {
        "code": "a_code_from_the_future",
        "text": "a_code_from_the_future",
    }


def test_render_adds_text_and_keeps_other_keys() -> None:
    out = prose.render(
        {
            "skipped_text": [{"code": "outside_session", "count": 4}],
            "nested": {"notes": [{"code": "no_trades"}], "value": 3},
            "plain": "no_trades",
        }
    )
    row = out["skipped_text"][0]
    assert row["count"] == 4
    assert row["text"] == prose.TEXT["outside_session"]
    assert out["nested"]["notes"][0]["text"] == prose.TEXT["no_trades"]
    assert out["nested"]["value"] == 3
    # A bare string is data, not a code object: untouched.
    assert out["plain"] == "no_trades"


def test_render_does_not_mutate_its_input() -> None:
    src = {"flags": [{"code": "no_trades"}]}
    prose.render(src)
    assert src == {"flags": [{"code": "no_trades"}]}


def test_render_leaves_an_existing_text_alone() -> None:
    assert prose.render({"code": "x", "text": "kept"}) == {"code": "x", "text": "kept"}


def test_error_text_renders_known_codes_and_passes_the_rest_through() -> None:
    assert prose.error_text("interrupted") == prose.TEXT["interrupted"]
    assert prose.error_text("ZeroDivisionError: division by zero") == (
        "ZeroDivisionError: division by zero"
    )
    assert prose.error_text(None) is None
