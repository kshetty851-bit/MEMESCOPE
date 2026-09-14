"""The entry-filter A/B's pre-registered terms, held in tests.

These exist so the terms cannot drift between now and 10 October. A decision
rule written down and then quietly relaxed is not a decision rule, and this
platform has thirteen findings that looked real until somebody wrote the rule
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import ab, config


@dataclass
class Row:
    """Enough of a GradPaperPosition for the judge, which only reads three
    fields. A real row would bring ninety columns and a database."""

    mint: str
    pnl_usd: Decimal
    opened_at: datetime = datetime(2026, 9, 20, tzinfo=UTC)


AFTER = config.AB_JUDGE_DATE + timedelta(days=1)
BEFORE = config.AB_JUDGE_DATE - timedelta(days=1)


def book(pnls: list[float], prefix: str = "m") -> list[Row]:
    return [Row(f"{prefix}{i}", Decimal(str(v))) for i, v in enumerate(pnls)]


def split(losers: list[float], winners: list[float]) -> tuple[list[Row], list[Row]]:
    """A control of losers+winners, and a filter that admits only the winners."""
    control = book(losers, "bad") + book(winners, "good")
    filtered = book(winners, "good")
    return control, filtered


# --- the term that stops an early call ---------------------------------------


def test_it_refuses_to_conclude_before_the_judge_date():
    """The whole point of a four-week experiment. The forex lab's interim
    window read PF 1.337 and its final window read 1.045 — an early peek is
    how a window gets chosen."""
    control, filtered = split([-1.0] * 500, [2.0] * 500)
    v = ab.judge(control, filtered, today=BEFORE)

    assert v.ready is False
    assert v.adopt is False
    date_check = next(c for c in v.checks if c.name == "judge date reached")
    assert date_check.passed is False
    assert config.AB_JUDGE_DATE.isoformat() in date_check.detail


def test_the_same_data_one_day_later_is_judgeable():
    control, filtered = split([-1.0] * 500, [2.0] * 500)
    assert ab.judge(control, filtered, today=AFTER).ready is True


# --- the endpoint: the refused set, not the two book totals -------------------


def test_the_endpoint_is_the_refused_set():
    """The filtered book is a subset of the control, so the two differ by
    exactly the graduations the filter refused. That is what gets measured."""
    control, filtered = split([-3.0] * 500, [1.0] * 500)
    v = ab.judge(control, filtered, today=AFTER)

    assert v.stats["refused"] == 500
    assert v.stats["admitted"] == 500
    assert v.stats["refused_mean_pnl"] == -3.0
    assert v.stats["admitted_mean_pnl"] == 1.0
    assert v.stats["retention_pct"] == 50.0


def test_a_filter_that_refused_winners_fails():
    """Throwing away profitable trades is a cost, and the judge must say so
    however good the surviving book looks."""
    control, filtered = split([5.0] * 500, [1.0] * 500)
    v = ab.judge(control, filtered, today=AFTER)

    assert v.adopt is False
    assert next(c for c in v.checks if c.name == "refused set lost money").passed is False


# --- the control that has killed the most findings ---------------------------


def test_a_filter_no_better_than_chance_fails():
    """The term most easily left out. Discarding half a book improves it about
    half the time by luck; refusing a RANDOM half of a mixed book must not pass.

    Here the refused and admitted sets are drawn from the same distribution, so
    the filter carries no information — and the judge has to notice even though
    the refused set does lose money on average.
    """
    losers = [-1.0, 3.0] * 250  # mean +1.0
    winners = [-1.0, 3.0] * 250  # identical distribution
    control, filtered = split(losers, winners)
    v = ab.judge(control, filtered, today=AFTER)

    random_check = next(c for c in v.checks if c.name.startswith("beats a random filter"))
    assert random_check.passed is False
    assert v.adopt is False


def test_a_filter_that_really_separates_beats_the_random_bar():
    """The positive case, so the test suite can tell a real separation from a
    refusal to ever say yes."""
    control, filtered = split([-4.0] * 500, [2.0] * 500)
    v = ab.judge(control, filtered, today=AFTER)

    assert (
        next(c for c in v.checks if c.name.startswith("beats a random filter")).passed is True
    )
    assert v.adopt is True


def test_the_null_distribution_is_seeded():
    """Two runs on the same data must reach the same verdict; a changed verdict
    should mean changed data, never a changed draw."""
    control, filtered = split([-2.0] * 500, [1.0] * 500)
    a = ab.judge(control, filtered, today=AFTER)
    b = ab.judge(control, filtered, today=AFTER)
    assert a.stats["random_bar_mean_pnl"] == b.stats["random_bar_mean_pnl"]


# --- the precondition Track Record V2 established -----------------------------


def test_shrinking_a_loss_is_not_an_edge():
    """V2 cut its catastrophe rate from 26.7-90% down to 1.4% and still scored
    PF 0.54. A filter whose survivors still lose has produced a smaller loss,
    and the judge must not call that an edge."""
    control, filtered = split([-10.0] * 500, [-0.5] * 500)
    v = ab.judge(control, filtered, today=AFTER)

    assert next(c for c in v.checks if c.name == "refused set lost money").passed is True
    assert (
        next(c for c in v.checks if c.name.startswith("admitted set is positive")).passed
        is False
    )
    assert v.adopt is False


# --- concentration ------------------------------------------------------------


def test_one_token_may_not_carry_the_refused_loss():
    """Every fake edge this platform has found died on this test."""
    losers = [-0.01] * 499 + [-900.0]
    control, filtered = split(losers, [2.0] * 500)
    v = ab.judge(control, filtered, today=AFTER)

    share = next(c for c in v.checks if c.name == "no single token carries it")
    assert share.passed is False
    assert v.adopt is False


# --- sample size --------------------------------------------------------------


def test_a_thin_experiment_is_not_ready_however_good_it_looks():
    control, filtered = split([-50.0] * 5, [50.0] * 5)
    v = ab.judge(control, filtered, today=AFTER)
    assert v.ready is False
    assert v.adopt is False


# --- the terms themselves -----------------------------------------------------


def test_the_pre_registered_terms_are_what_was_written_down():
    """If this fails, someone moved a bar. That is allowed — but it has to be
    a deliberate, visible act, not a drift."""
    assert date(2026, 10, 10) == config.AB_JUDGE_DATE
    assert config.AB_MIN_EXCLUDED == 400
    assert config.AB_MIN_ADMITTED == 400
    assert Decimal("0.20") == config.AB_MAX_TOKEN_SHARE
    assert config.AB_RANDOM_PERCENTILE == 5
    assert config.AB_RANDOM_DRAWS >= 2000
    assert config.PAPER_BOOKS == ("F01_all_2m", "F14_symnight_2m")


def test_every_term_must_pass_to_adopt():
    """`adopt` is an AND over all seven, not a majority."""
    control, filtered = split([-4.0] * 500, [2.0] * 500)
    v = ab.judge(control, filtered, today=AFTER)
    assert v.adopt is True
    assert len(v.checks) == 7
    assert all(c.passed for c in v.checks)
