"""The rules without a database: the six configs, the exit order, the lock's
learned give-back, and the learner's audit line."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.rafiqv2 import config, learning
from app.labs.rafiqv2.engine import LOCK, SCALE_OUT, decide
from app.labs.rafiqv2.strategy_common import (
    LOCK_LADDER,
    RUG_LADDER,
    DeathRateBreaker,
    ProfitLock,
)

T0 = datetime(2026, 9, 19, 12, tzinfo=UTC)
A2, D2 = config.BY_CODE["A2"], config.BY_CODE["D2"]


def at(book, price, *, seconds=300, peak=None, scaled_out=False, strictness=0,
       giveback="0.15"):
    """One decision for a position entered at 1.0 `seconds` ago."""
    price = Decimal(str(price))
    return decide(book, entry_price=Decimal(1), opened_at=T0,
                  peak_price=max(price, Decimal(str(peak or 1))), scaled_out=scaled_out,
                  fraction_open=Decimal("0.2") if scaled_out else Decimal(1),
                  rug_strictness=Decimal(str(strictness)),
                  lock_giveback=Decimal(giveback), price=price,
                  now=T0 + timedelta(seconds=seconds))


def test_six_books_and_every_shared_rule_is_the_published_one() -> None:
    assert [b.code for b in config.BOOKS] == ["A2", "B2", "C2", "D2", "E2", "G2"]
    for book in config.BOOKS:
        # The delivered tests exercise the defaults, so the defaults must BE
        # every book's ladders.
        assert book.rug_ladder == RUG_LADDER and book.lock_ladder == LOCK_LADDER
        assert (book.death_window, book.death_rate, book.death_min_sample) == \
            (20, Decimal("0.6"), 8)
        learns = book.rules["learning"]["learns"]
        assert learns["rug_strictness"]["bounded"] == [
            float(learning.RUG_STRICTNESS_MIN), float(learning.RUG_STRICTNESS_MAX)]
        assert learns["lock_giveback"]["bounded"] == [
            float(learning.LOCK_GIVEBACK_MIN), float(learning.LOCK_GIVEBACK_MAX)]
        assert book.rules["learning"]["safety"]["min_sample_before_any_change"] == \
            learning.MIN_SAMPLE


def test_the_digest_is_the_rules_not_the_prose(tmp_path) -> None:
    raw = json.loads((config.Path(config.__file__).parent / "books" /
                      "strategy_A2.json").read_text())
    raw["_identity"] = "reworded"
    (tmp_path / "prose.json").write_text(json.dumps(raw))
    assert config.load(tmp_path / "prose.json").digest == A2.digest
    raw["exits"]["stop"] = 0.9
    (tmp_path / "rule.json").write_text(json.dumps(raw))
    assert config.load(tmp_path / "rule.json").digest != A2.digest


def test_a_setting_the_engine_does_not_implement_is_refused(tmp_path) -> None:
    raw = json.loads((config.Path(config.__file__).parent / "books" /
                      "strategy_A2.json").read_text())
    raw["profit_lock"]["enabled"] = False
    (tmp_path / "off.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match=r"profit_lock\.enabled"):
        config.load(tmp_path / "off.json")


def test_the_stop_is_checked_before_everything() -> None:
    """A gap from +30% to -20% is a stop, though it also breached the lock."""
    assert at(A2, "0.80", peak="1.30").reason == "stop"


def test_a_winner_is_sold_at_its_lock_floor_not_ridden_back_to_red() -> None:
    assert at(A2, "1.15", peak="1.29") is None          # floor 1.14 holds
    d = at(A2, "1.14", peak="1.29")
    assert (d.reason, d.fill) == (LOCK, Decimal("1.14"))


def test_the_scale_out_sells_eighty_percent_at_a_capped_fill() -> None:
    d = at(A2, "2.0")
    assert (d.reason, d.fraction) == (SCALE_OUT, Decimal("0.8"))
    assert d.fill == Decimal("1.3") * Decimal("1.15")    # never the whole gap-up
    assert at(A2, "1.35", peak="1.35", scaled_out=True) is None


def test_the_runner_trail_binds_only_on_a_runner() -> None:
    # Below a ~3x peak the lock's floor sits above the trail's, so a 4x peak is
    # where the trail can be seen: 2.19 is under 4.0 x 0.55 and over the 1.70
    # the top rung locks.
    assert at(A2, "2.19", peak="4.0", scaled_out=True).reason == "runner_trail"
    assert at(A2, "2.19", peak="4.0", scaled_out=False).reason == SCALE_OUT
    # D2 never scales out: its whole position is the runner from entry.
    assert at(D2, "2.19", peak="4.0").reason == "runner_trail"


def test_the_rug_ladder_and_its_learned_strictness() -> None:
    assert at(A2, "0.96", seconds=30).reason == "rug_30s"
    assert at(A2, "0.975", seconds=30) is None
    assert at(A2, "0.975", seconds=30, strictness="0.01").reason == "rug_30s"
    assert at(A2, "0.965", seconds=30, strictness="-0.01") is None
    # The latest checkpoint governs: +9% is fine at 10m and not at 30m.
    assert at(A2, "1.09", seconds=600) is None
    assert at(A2, "1.09", seconds=1800).reason == "abandon_20m"


def test_the_box() -> None:
    assert at(A2, "1.20", seconds=720 * 60 - 1, peak="1.20") is None
    assert at(A2, "1.20", seconds=720 * 60, peak="1.20").reason == "max_hold"


def test_lock_giveback_moves_every_rung_and_never_below_friction() -> None:
    def floor(giveback, peak):
        return ProfitLock(giveback=Decimal(giveback)).observe(Decimal(peak))

    assert floor("0.15", "1.30") == Decimal("1.14")      # as published
    assert floor("0.40", "1.30") == Decimal("1.0775")    # 14% - 0.25 x 25%
    assert floor("0.05", "1.30") == Decimal("1.165")     # 14% + 0.10 x 25%
    assert floor("0.40", "1.05") == Decimal("1.01")      # clamped at friction


def test_an_adjustment_records_the_sample_it_was_made_on() -> None:
    """The delivered file cleared its evidence before reading its size, so
    every audit line said n=0."""
    lrn = learning.Learning(book="E2")
    for i in range(40):
        lrn.on_exit(f"m{i}", closed_at=T0, exit_reason="rug_30s" if i % 2 else "stop",
                    net_return=Decimal("-0.1"), peak_multiple=Decimal(1),
                    token_died=not i % 2)
    assert [a.sample_size for a in lrn.adjustments] == [40]


def test_a_death_breaker_state_round_trips() -> None:
    b = DeathRateBreaker(recent=[True] * 7)
    assert b.record(token_died=True, now=T0) is not None
    again = replace(b, recent=list(b.recent))
    assert again.check(T0 + timedelta(hours=5))[0]
    assert not again.check(T0 + timedelta(hours=6))[0]
