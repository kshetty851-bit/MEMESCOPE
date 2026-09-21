"""The real wallet's money checks, as the lab applies them to its own buys."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core import rug_money
from app.labs.graduation import moneyblock

BLOCKED = "DyaESzDfBLtbvKz7iM5Th6nsbsGSpjt5NLXuieigRcZX"   # live from 18 Sep 14:54
LIVE_FROM = rug_money.BLOCKED_SINCE[BLOCKED]


def test_blocked_money_counts_only_from_the_moment_it_went_live() -> None:
    assert moneyblock.refused({BLOCKED, "X"}, LIVE_FROM, set()) == moneyblock.KNOWN
    # A trade restated after the fact never uses a block from its future.
    assert moneyblock.refused({BLOCKED}, LIVE_FROM - timedelta(seconds=1), set()) is None


def test_a_coin_behind_a_recent_rug_is_refused_and_a_stranger_is_not() -> None:
    at = datetime(2026, 9, 19, 12, tzinfo=UTC)
    assert moneyblock.refused({"FunderT", "W"}, at, {"FunderT"}) == moneyblock.LINKED
    assert moneyblock.refused({"W"}, at, {"FunderT"}) is None
    assert moneyblock.refused(set(), at, {"FunderT"}) is None   # nothing recorded


def test_the_wallet_and_the_lab_share_one_list() -> None:
    from app.real_wallet_safety import sources

    assert sources.ALWAYS_BLOCKED is rug_money.ALWAYS_BLOCKED
    assert frozenset(rug_money.BLOCKED_SINCE) == rug_money.ALWAYS_BLOCKED


def test_the_repeat_rugger_thresholds_are_the_measured_ones() -> None:
    """Pinned because both numbers were chosen against a negative control and
    a blunter rule was measured and rejected (see the constants' comment). A
    silent move here would change what the live books and the real wallet buy,
    since the wallet only ever buys a coin a paper arm already opened."""
    from app.labs.graduation import config

    assert (config.REPEAT_MIN_COINS, config.REPEAT_MIN_RUG_PCT) == (10, 10)
    # Whole per cent: a fraction here arrives at the driver as 0 and refuses
    # every address on the list.
    assert isinstance(config.REPEAT_MIN_RUG_PCT, int)
