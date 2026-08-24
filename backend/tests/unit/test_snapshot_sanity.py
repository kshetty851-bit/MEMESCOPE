"""The ingest firewall: annotate, never delete; persistence beats surprise.

Every rule here mirrors a production incident: the 4e11 print that booked a
fake TP (V1), the pair switch that moved liquidity 31k->1.9k->256k across a
gap (V1), and the 304,776x print that reached peak_multiple unchallenged (V4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.market.sanity import (
    REASON_LIQUIDITY_JUMP,
    REASON_PAIR_SWITCH,
    REASON_PRICE_HIGH,
    REASON_PRICE_LOW,
    PriorPoint,
    classify,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
BAND = Decimal("3.0")
JUMP = Decimal("10.0")


def prior(prices, *, liq="10000", pool="pool-A", suspect=None):
    suspect = suspect or [False] * len(prices)
    return [
        PriorPoint(
            captured_at=T0 + timedelta(seconds=10 * i),
            price_usd=Decimal(p),
            liquidity_usd=Decimal(liq),
            pool_address=pool,
            suspect=s,
        )
        for i, (p, s) in enumerate(zip(prices, suspect, strict=True))
    ]


def judge(price, prior_points, *, liq="10000", pool="pool-A"):
    return classify(
        price_usd=Decimal(price),
        liquidity_usd=Decimal(liq),
        pool_address=pool,
        prior=prior_points,
        band=BAND,
        liquidity_jump=JUMP,
        min_prior=3,
    )


def test_lone_impossible_print_is_flagged_with_its_baseline():
    v = judge("400000", prior(["1.00", "1.02", "0.98", "1.01"]))
    assert v.suspect and v.reason == REASON_PRICE_HIGH
    assert v.baseline_price_usd == Decimal("1.005")


def test_flash_crash_print_is_flagged_low():
    v = judge("0.01", prior(["1.00", "1.02", "0.98", "1.01"]))
    assert v.suspect and v.reason == REASON_PRICE_LOW


def test_persistent_new_level_is_accepted_as_a_real_move():
    # Three consecutive prints already sit at ~5x; the fourth is the market.
    history = prior(
        ["1.00", "1.02", "0.98", "5.10", "5.00", "4.90"],
        suspect=[False, False, False, True, True, True],
    )
    v = judge("5.05", history)
    assert not v.suspect


def test_first_prints_of_a_step_change_are_quarantined():
    history = prior(["1.00", "1.02", "0.98", "5.10"], suspect=[False, False, False, True])
    v = judge("5.05", history)  # only ONE recent print agrees so far
    assert v.suspect and v.reason == REASON_PRICE_HIGH


def test_pair_switch_outranks_price_judgement():
    v = judge("1.00", prior(["1.00", "1.01", "0.99"]), pool="pool-B")
    assert v.suspect and v.reason == REASON_PAIR_SWITCH


def test_liquidity_discontinuity_is_flagged():
    v = judge("1.00", prior(["1.00", "1.01", "0.99", "1.00"]), liq="250000")
    assert v.suspect and v.reason == REASON_LIQUIDITY_JUMP


def test_too_little_history_passes_through_unjudged():
    v = judge("400000", prior(["1.00", "1.02"]))
    assert not v.suspect and v.reason is None


def test_dead_or_unpriced_rows_are_never_flagged():
    v = classify(
        price_usd=None,
        liquidity_usd=None,
        pool_address=None,
        prior=prior(["1.00", "1.01", "0.99"]),
        band=BAND,
        liquidity_jump=JUMP,
        min_prior=3,
    )
    assert not v.suspect


def test_suspect_priors_do_not_poison_the_baseline():
    history = prior(
        ["1.00", "1.02", "0.98", "400000"],
        suspect=[False, False, False, True],
    )
    v = judge("1.01", history)
    assert not v.suspect
