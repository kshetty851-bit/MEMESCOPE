"""The v2 entry gate, as behaviour.

The claims in `entry_gate.py`'s docstring are arithmetic, and arithmetic in a
docstring rots. These pin the ones a reader would otherwise have to take on
trust — above all that `min_liquidity_usd` does NOT bind, which is the first
thing anyone tuning this gate will get wrong.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.labs.rafiq import entry_gate, registry

FIFTY = D(50)
#: Comfortably past every default floor: what an admitted candidate looks like.
DEEP = {"liquidity_usd": D(250_000), "market_cap_usd": D(2_000_000)}


def test_a_missing_reading_is_a_rejection_not_a_pass() -> None:
    """v1's worst fills were on tokens with no reported cap."""
    assert entry_gate.check_entry(
        liquidity_usd=None, market_cap_usd=D(1_000_000),
        notional_usd=FIFTY).reason == "liquidity_unknown"
    assert entry_gate.check_entry(
        liquidity_usd=D(250_000), market_cap_usd=None,
        notional_usd=FIFTY).reason == "market_cap_unknown"
    # Zero is a reading of nothing, not a reading of zero.
    assert entry_gate.check_entry(
        liquidity_usd=D(0), market_cap_usd=D(1_000_000),
        notional_usd=FIFTY).reason == "liquidity_unknown"


def test_a_deep_healthy_market_is_admitted() -> None:
    verdict = entry_gate.check_entry(notional_usd=FIFTY, **DEEP)
    assert verdict.allowed and verdict.reason is None
    assert verdict.entry_impact_pct is not None


def test_the_impact_rule_binds_before_the_liquidity_floor() -> None:
    """THE thing to know before touching a threshold.

    A pool sitting exactly ON `min_liquidity_usd` still fails, because $50 into
    $50,000 costs 2.34% against a 1.5% cap. The liquidity floor is therefore
    dead: the real floor is wherever impact reaches 1.5%, near $78,900.
    """
    at_the_floor = entry_gate.check_entry(
        liquidity_usd=entry_gate.DEFAULT.min_liquidity_usd,
        market_cap_usd=D(2_000_000), notional_usd=FIFTY)
    assert not at_the_floor.allowed
    assert at_the_floor.reason == "price_impact_too_high"

    assert not entry_gate.check_entry(
        liquidity_usd=D(78_000), market_cap_usd=D(2_000_000),
        notional_usd=FIFTY).allowed
    assert entry_gate.check_entry(
        liquidity_usd=D(80_000), market_cap_usd=D(2_000_000),
        notional_usd=FIFTY).allowed


def test_the_pool_share_rule_can_never_fire() -> None:
    """It is kept because it was specified, not because it can bind.

    At 0.5% of a pool the modelled impact is ~10.7%, seven times the cap beside
    it, so impact always rejects first. If this test ever fails, the cost model
    moved and the gate's own docstring is stale.
    """
    for liquidity in (D(50_000), D(100_000), D(1_000_000), D(10_000_000)):
        verdict = entry_gate.check_entry(
            liquidity_usd=liquidity, market_cap_usd=D(50_000_000),
            notional_usd=FIFTY)
        assert verdict.reason != "position_too_large_for_pool", liquidity


def test_impact_excludes_the_swap_fee() -> None:
    """The threshold is a slippage cap, not a round-trip cost cap."""
    from app.labs.rafiq.adapters.costs import side_cost

    liquidity = D(120_000)
    both = side_cost(FIFTY, liquidity, model=entry_gate.MODEL)
    assert both is not None
    assert entry_gate.impact_pct(FIFTY, liquidity) == both.impact_pct
    assert both.impact_pct < both.total_pct


def test_strict_is_strictly_stricter() -> None:
    """E2's override must never admit something the default would refuse."""
    market = {"liquidity_usd": D(120_000), "market_cap_usd": D(300_000)}
    assert entry_gate.check_entry(notional_usd=FIFTY, **market).allowed
    assert not entry_gate.check_entry(
        notional_usd=FIFTY, thresholds=entry_gate.STRICT, **market).allowed


def test_every_reason_the_gate_returns_is_a_countable_one() -> None:
    """A reason missing from `REASONS` would be counted nowhere and read as a
    book that was never refused."""
    seen = {
        entry_gate.check_entry(liquidity_usd=None, market_cap_usd=D(1),
                               notional_usd=FIFTY).reason,
        entry_gate.check_entry(liquidity_usd=D(1_000), market_cap_usd=D(1),
                               notional_usd=FIFTY).reason,
        entry_gate.check_entry(liquidity_usd=D(250_000), market_cap_usd=None,
                               notional_usd=FIFTY).reason,
        entry_gate.check_entry(liquidity_usd=D(250_000), market_cap_usd=D(1_000),
                               notional_usd=FIFTY).reason,
        entry_gate.check_entry(liquidity_usd=D(50_000), market_cap_usd=D(2_000_000),
                               notional_usd=FIFTY).reason,
    }
    assert seen <= set(entry_gate.REASONS), seen - set(entry_gate.REASONS)


def test_the_gate_is_identical_across_the_four_books_that_share_it() -> None:
    """A2's comparison against v1's A only reads if B2-D2 ran the same gate."""
    shared = [s for s in registry.STRATEGIES if s.code != "E2"]
    assert {s.gate for s in shared} == {entry_gate.DEFAULT}
    assert registry.BY_CODE["E2"].gate == entry_gate.STRICT


def test_the_gate_thresholds_are_inside_the_profile_digest() -> None:
    """Changing a threshold must be a new record, not an edit to an old one."""
    import dataclasses

    a2 = registry.BY_CODE["A2"]
    loosened = dataclasses.replace(a2, gate=dataclasses.replace(
        a2.gate, min_liquidity_usd=D(1)))
    assert loosened.digest != a2.digest
