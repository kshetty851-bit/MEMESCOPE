"""Strategy E: the entry gate, and the two ways it must refuse.

E is the only one of the five that gates entry at all, so its tests are about
refusals rather than about admissions. Both required refusals are here:

  * a manipulation reading vetoes OUTRIGHT, even with full consensus — it does
    not merely count as one non-confirming stream among several;
  * a missing safety stream blocks, because `require_safety` means safety must
    be among the CONFIRMING streams, and absent is not confirming.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.evidence import StreamVerdict
from app.labs.rafiq.strategies.strategy_d_daily_breaker import DailyState
from app.labs.rafiq.strategies.strategy_e_ensemble import (
    ENSEMBLE_GUARDED,
    evaluate_entry,
    exits_for,
    portfolio_halted,
    size_for,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: Clean market data: 40 buyers to 20 sellers, ordinary trade counts, 5-minute
#: volume 1% of market cap, a deep pool. Nothing here trips a check.
CLEAN = {"buyers": 40, "sellers": 20, "buys": 120, "sells": 90,
         "volume_m5": Decimal(1_000), "market_cap": Decimal(100_000),
         "liquidity": Decimal(100_000)}


def streams(*names: str) -> tuple[StreamVerdict, ...]:
    return tuple(StreamVerdict(n, True, NOW, f"{n} ok") for n in names)


def test_full_consensus_admits() -> None:
    """The control. Without this the refusal tests could pass vacuously."""
    assert evaluate_entry(streams("onchain", "dex", "safety"), now=NOW,
                          **CLEAN).admitted


def test_manipulation_vetoes_even_with_full_consensus() -> None:
    """Three confirming streams including safety, and it is still refused."""
    manipulated = {**CLEAN, "buyers": 5, "sellers": 60}
    decision = evaluate_entry(streams("onchain", "dex", "safety"), now=NOW,
                              **manipulated)
    assert decision.consensus.agreed, "consensus must be intact for this test"
    assert decision.manipulation.manipulated
    assert not decision.admitted
    # The veto's cause leads the reasons, ahead of the consensus commentary.
    assert "sellers outnumber buyers" in decision.reasons[0]


def test_wash_shaped_trade_counts_veto() -> None:
    """A different check, same outright veto: 300 trades over 30 wallets."""
    wash = {**CLEAN, "buyers": 20, "sellers": 10, "buys": 200, "sells": 100}
    assert not evaluate_entry(streams("onchain", "dex", "safety"), now=NOW,
                              **wash).admitted


def test_missing_safety_stream_blocks_entry() -> None:
    """Two confirming streams, neither of them safety. `require_safety=True`
    means that is not enough, however good the other two look."""
    decision = evaluate_entry(streams("onchain", "dex"), now=NOW, **CLEAN)
    assert not decision.admitted
    assert "safety" in decision.consensus.absent
    assert any("safety" in r for r in decision.reasons)


def test_a_dissenting_safety_stream_also_blocks() -> None:
    verdicts = (*streams("onchain", "dex"),
                StreamVerdict("safety", False, NOW, "security evaluation FAILED"))
    assert not evaluate_entry(verdicts, now=NOW, **CLEAN).admitted


def test_safety_alone_is_not_two_streams() -> None:
    assert not evaluate_entry(streams("safety"), now=NOW, **CLEAN).admitted


def test_a_stale_stream_is_absent_not_confirming() -> None:
    stale = (StreamVerdict("onchain", True, NOW - timedelta(hours=2), "old"),
             StreamVerdict("safety", True, NOW, "fresh"))
    decision = evaluate_entry(stale, now=NOW, **CLEAN)
    assert not decision.admitted
    assert "onchain" in decision.consensus.absent


def test_the_same_stream_twice_is_not_breadth() -> None:
    duplicated = (StreamVerdict("safety", True, NOW, "a"),
                  StreamVerdict("safety", True, NOW, "b"))
    assert not evaluate_entry(duplicated, now=NOW, **CLEAN).admitted


def test_social_can_never_confirm_because_it_cannot_be_observed() -> None:
    """MEMESCOPE has no social source, so `from_feed` cannot build one. This
    holds the gap open rather than letting it quietly disappear."""
    from app.labs.rafiq.adapters import evidence
    from app.labs.rafiq.adapters.safety import SafetyVerdict
    from app.labs.rafiq.feed import Observation

    obs = Observation(
        mint_address="m", observed_at=NOW, price_usd=Decimal(1),
        liquidity_usd=Decimal(100_000), market_cap=Decimal(100_000),
        volume_m5=Decimal(10), liquidity_change_15m=Decimal(0),
        median_price_10m=Decimal(1), buyers=40, sellers=20, buys=120, sells=90,
        top10_tx_share=Decimal("0.2"), safety=SafetyVerdict.PASSED,
        safety_observed_at=NOW)
    built = evidence.from_feed(obs, safety=obs.safety,
                               safety_observed_at=obs.safety_observed_at)
    assert "social" not in {v.stream for v in built}


def test_unknown_safety_produces_no_stream_at_all() -> None:
    """UNKNOWN is absent, never a pass. A check that could not run did not
    pass, and the consensus gate must see the difference."""
    from app.labs.rafiq.adapters import evidence
    from app.labs.rafiq.adapters.safety import SafetyVerdict
    from app.labs.rafiq.feed import Observation

    obs = Observation("m", NOW, Decimal(1), Decimal(100_000), Decimal(100_000),
                      Decimal(10), Decimal(0), Decimal(1), 40, 20, 120, 90,
                      Decimal("0.2"), SafetyVerdict.UNKNOWN, NOW)
    built = evidence.from_feed(obs, safety=obs.safety, safety_observed_at=NOW)
    assert "safety" not in {v.stream for v in built}
    assert not evaluate_entry(built, now=NOW, **CLEAN).admitted


def test_exits_for_unknown_liquidity_is_none() -> None:
    assert exits_for(None) is None
    assert size_for(Decimal(1_000), None, Decimal(50)) == 0


def test_exits_for_derives_the_stop_from_depth() -> None:
    deep, thin = exits_for(Decimal(100_000)), exits_for(Decimal(5_000))
    assert deep.stop_mult == Decimal("0.88")
    assert thin.stop_mult < deep.stop_mult
    assert deep.max_hold == timedelta(hours=8)


def test_e_loosens_bs_time_box_to_eight_hours() -> None:
    assert ENSEMBLE_GUARDED.exits.max_hold == timedelta(hours=8)


def test_the_breaker_wraps_the_whole_strategy() -> None:
    state = DailyState.open_new_day(NOW, Decimal(1_000))
    assert portfolio_halted(state, now=NOW, cash=Decimal(900),
                            open_position_values=[Decimal(40)])
    assert not portfolio_halted(state, now=NOW, cash=Decimal(1_000),
                                open_position_values=[Decimal(40)])
