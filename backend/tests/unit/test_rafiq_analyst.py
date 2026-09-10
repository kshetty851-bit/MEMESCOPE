"""The analyst desk must not become a fortune teller.

Everything here guards one boundary: the module may describe what happened and
may name a measurable quantity, and it may not say what will happen next. That
boundary is the whole reason the feature is safe to ship on a platform with
eight recorded no-edge findings, and it is one careless sentence away from
being crossed, so it is asserted rather than trusted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.labs.rafiq import analyst

#: Words that turn a measurement into a prediction. Lifted deliberately from
#: the HQ ideas board's own ban list so the two surfaces cannot drift into
#: disagreeing about what a character is allowed to claim.
FORTUNE = re.compile(
    r"\b(will|should|recommend|expect|predict|profitable soon|guarantee|"
    r"alpha|edge|outperform|winning strategy)\b",
    re.I,
)


def _position(**kw):
    base = dict(
        entry_price=Decimal("1"),
        entry_observed_price=Decimal("1"),
        cost_basis=Decimal("50"),
        exit_proceeds_usd=Decimal("50"),
        target_price=Decimal("1.5"),
        peak_price=Decimal("1"),
        exit_reason="stop",
        detected_at=None,
        opened_at=datetime(2026, 9, 1, tzinfo=UTC),
        closed_at=datetime(2026, 9, 1, 0, 10, tzinfo=UTC),
        entry_liquidity_usd=Decimal("10000"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _Session:
    """Records every call, so 'read-only' is proven rather than asserted."""

    def __init__(self, strategy, rows):
        self._answers = [_Result(strategy), _Result(rows)]
        self.calls: list[str] = []

    async def execute(self, *_a, **_kw):
        self.calls.append("execute")
        return self._answers.pop(0)

    def __getattr__(self, name):
        raise AssertionError(f"analyst must not call session.{name}()")


_STRATEGY = SimpleNamespace(id="s-1", code="A", lane="hard_stop_guard")


async def _run(rows, strategy=_STRATEGY):
    return await analyst.analyse(_Session(strategy, rows), "A")


@pytest.mark.asyncio
async def test_no_trades_is_reported_as_unmeasured_not_as_zero():
    """The invariant the whole HQ is built on, applied to a new surface."""
    result = await _run([])
    assert result.measured is False
    assert result.figures == []
    assert result.findings == []
    # No "$0.00", no "0%", nothing that reads as a measured flat result.
    assert "0" not in result.verdict


@pytest.mark.asyncio
async def test_small_sample_refuses_to_conclude_and_says_so_first():
    rows = [_position(exit_proceeds_usd=Decimal("40")) for _ in range(9)]
    result = await _run(rows)
    assert result.findings[0].key == "sample_too_small"
    assert "No conclusion available" in result.verdict


@pytest.mark.asyncio
async def test_breakeven_win_rate_is_the_arithmetic_it_claims_to_be():
    """A $10 winner against a $10 loser breaks even at 50%; at $5 vs $15, 75%.

    This is the finding that catches a book winning 64% of its trades and still
    losing money, so the identity behind it is pinned to a worked example.
    """
    rows = [_position(exit_proceeds_usd=Decimal("55")) for _ in range(10)]  # +$5
    rows += [_position(exit_proceeds_usd=Decimal("35")) for _ in range(25)]  # -$15
    result = await _run(rows)

    breakeven = next(f for f in result.figures if f.label == "Breakeven win rate")
    assert breakeven.value == "75%"  # 15 / (5 + 15)

    asymmetry = next(f for f in result.findings if f.key == "asymmetry")
    assert "29%" in asymmetry.evidence  # 10 of 35 observed
    assert "75%" in asymmetry.evidence


@pytest.mark.asyncio
async def test_peak_price_separates_a_bad_exit_from_a_bad_entry():
    """The distinction the module exists to make."""
    never = [_position(peak_price=Decimal("1.01")) for _ in range(40)]
    assert "target_never_reached" in [f.key for f in (await _run(never)).findings]

    sometimes = [_position(peak_price=Decimal("1.6")) for _ in range(20)]
    sometimes += [_position(peak_price=Decimal("1.01")) for _ in range(20)]
    keys = [f.key for f in (await _run(sometimes)).findings]
    assert "target_sometimes_reached" in keys
    assert "target_never_reached" not in keys


@pytest.mark.asyncio
async def test_execution_finding_survives_a_book_that_never_moved():
    """Strategy D printed '99074% of the available move' before the guard.

    A near-zero denominator does not produce a dramatic finding; it produces no
    finding, because the peak result already says the true thing.
    """
    rows = [
        _position(peak_price=Decimal("1.0000001"), entry_observed_price=Decimal("0.97"))
        for _ in range(40)
    ]
    keys = [f.key for f in (await _run(rows)).findings]
    assert "execution_eats_the_move" not in keys


@pytest.mark.asyncio
async def test_nothing_the_desk_says_is_a_forecast():
    rows = [_position(exit_proceeds_usd=Decimal("55"), peak_price=Decimal("1.6")) for _ in range(20)]
    rows += [_position(exit_proceeds_usd=Decimal("35")) for _ in range(20)]
    result = await _run(rows)
    assert result.findings, "sanity: this fixture must produce findings to police"

    for finding in result.findings:
        for field in (finding.headline, finding.evidence, finding.lever):
            assert not FORTUNE.search(field), f"{finding.key} predicts: {field!r}"


@pytest.mark.asyncio
async def test_every_figure_names_the_columns_behind_it():
    """A number without its source is an assertion. There are none here."""
    rows = [_position(exit_proceeds_usd=Decimal("55")) for _ in range(40)]
    result = await _run(rows)
    assert result.figures
    for figure in result.figures:
        assert figure.source.strip(), f"{figure.label} has no source"


@pytest.mark.asyncio
async def test_the_desk_only_ever_reads():
    rows = [_position() for _ in range(40)]
    session = _Session(_STRATEGY, rows)
    await analyst.analyse(session, "A")
    # __getattr__ raises on anything but execute(), so reaching here means no
    # add / flush / commit / delete was attempted.
    assert set(session.calls) == {"execute"}
