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
        mint_address="MINT",
        stop_price=Decimal("0.88"),
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

    def __init__(self, strategy, rows, peers=()):
        # In call order: the strategy row, this arm's positions, then every
        # OTHER arm's settled trades for the cross-arm comparison.
        self._answers = [_Result(strategy), _Result(rows), _Result(list(peers))]
        self.calls: list[str] = []

    async def execute(self, *_a, **_kw):
        self.calls.append("execute")
        return self._answers.pop(0)

    def __getattr__(self, name):
        raise AssertionError(f"analyst must not call session.{name}()")


_STRATEGY = SimpleNamespace(id="s-1", code="A", lane="hard_stop_guard")


async def _run(rows, strategy=_STRATEGY, peers=()):
    return await analyst.analyse(_Session(strategy, rows, peers), "A")


def _peer(code, position, *, pnl=None, stop=None):
    """A row shaped like the cross-arm SELECT: (code, mint, proceeds, basis, stop)."""
    return (
        code,
        position.mint_address,
        position.cost_basis + pnl if pnl is not None else position.exit_proceeds_usd,
        position.cost_basis,
        stop if stop is not None else position.stop_price,
    )


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


class TestCrossArm:
    """The check that no amount of reading one book on its own could produce.

    Strategy C exists to test a volatility-derived stop against A's flat one.
    On the live lab it set a different stop on all 55 shared trades and got the
    same realised P&L on 54 of them, because the price record is sampled too
    coarsely to resolve the difference. Every finding here is about noticing
    that an arm has stopped buying information.
    """

    @staticmethod
    def _book(n, *, pnl=Decimal("5")):
        return [
            _position(mint_address=f"MINT{i}", exit_proceeds_usd=Decimal("50") + pnl)
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_names_an_arm_that_has_stopped_telling_us_anything(self):
        mine = self._book(30)
        # Same tokens, same result, DIFFERENT stop level — the live case.
        peers = [_peer("C", p, stop=Decimal("0.91")) for p in mine]
        result = await _run(mine, peers=peers)

        finding = next(f for f in result.findings if f.key == "indistinguishable_from_c")
        assert "cannot be told apart" in finding.headline
        assert "30 of the same tokens" in finding.evidence
        assert "different" in finding.evidence
        # The lever must point at the price record, not at either rule.
        assert "sampling" in finding.lever
        assert "measures one rule twice" in finding.lever

    @pytest.mark.asyncio
    async def test_does_not_dress_up_two_arms_configured_alike(self):
        """Same stop, same answer, is a tautology and must be said as one."""
        mine = self._book(30)
        peers = [_peer("C", p) for p in mine]  # stop copied from ours
        result = await _run(mine, peers=peers)

        finding = next(f for f in result.findings if f.key == "indistinguishable_from_c")
        assert "should do" in finding.evidence
        assert "sampling" not in finding.lever
        assert "arithmetic rather than a result" in finding.lever

    @pytest.mark.asyncio
    async def test_does_not_blame_the_price_record_for_a_shared_configuration(self):
        """The live A-vs-D case, which the first version of this check got wrong.

        A and D both run a flat 12% stop. They agreed on 46 of 47 trades and
        differed in stop level on exactly ONE. The check said "despite entering
        1 of those under a different stop level" and pointed the lever at the
        price sampling — an overclaim about a pair whose geometry is identical.
        """
        mine = self._book(30)
        peers = [
            # One trade in thirty entered differently. Everything else alike.
            _peer("C", p, stop=Decimal("0.91") if i == 0 else None)
            for i, p in enumerate(mine)
        ]
        finding = next(
            f
            for f in (await _run(mine, peers=peers)).findings
            if f.key == "indistinguishable_from_c"
        )
        assert "despite" not in finding.evidence
        assert "should do" in finding.evidence
        # Reads as English for the n=1 case, which is the common one here.
        assert "only 1 of those was entered" in finding.evidence
        # And crucially: it must not accuse the price record.
        assert "sampling" not in finding.lever
        assert "arithmetic rather than a result" in finding.lever

    @pytest.mark.asyncio
    async def test_stays_quiet_when_the_arms_genuinely_diverge(self):
        mine = self._book(30)
        # Half of them returned something else entirely.
        peers = [
            _peer("C", p, pnl=Decimal("5") if i % 2 else Decimal("-20"), stop=Decimal("0.91"))
            for i, p in enumerate(mine)
        ]
        keys = [f.key for f in (await _run(mine, peers=peers)).findings]
        assert "indistinguishable_from_c" not in keys

    @pytest.mark.asyncio
    async def test_will_not_call_two_arms_identical_on_a_handful_of_trades(self):
        """A paired comparison needs fewer observations, not none."""
        mine = self._book(analyst.MIN_SHARED_TRADES - 1)
        peers = [_peer("C", p, stop=Decimal("0.91")) for p in mine]
        keys = [f.key for f in (await _run(mine, peers=peers)).findings]
        assert "indistinguishable_from_c" not in keys

    @pytest.mark.asyncio
    async def test_only_pairs_trades_the_two_arms_actually_share(self):
        """An arm that traded different tokens is not being compared at all."""
        mine = self._book(30)
        peers = [_peer("C", p, stop=Decimal("0.91")) for p in self._book(30)]
        for i, row in enumerate(peers):
            peers[i] = ("C", f"OTHER{i}", row[2], row[3], row[4])
        keys = [f.key for f in (await _run(mine, peers=peers)).findings]
        assert "indistinguishable_from_c" not in keys

    @pytest.mark.asyncio
    async def test_the_cross_arm_finding_is_not_a_forecast_either(self):
        mine = self._book(30)
        peers = [_peer("C", p, stop=Decimal("0.91")) for p in mine]
        result = await _run(mine, peers=peers)
        finding = next(f for f in result.findings if f.key == "indistinguishable_from_c")
        for field in (finding.headline, finding.evidence, finding.lever):
            assert not FORTUNE.search(field), f"cross-arm finding predicts: {field!r}"

    @pytest.mark.asyncio
    async def test_still_only_reads(self):
        mine = self._book(30)
        peers = [_peer("C", p, stop=Decimal("0.91")) for p in mine]
        session = _Session(_STRATEGY, mine, peers)
        await analyst.analyse(session, "A")
        assert set(session.calls) == {"execute"}
