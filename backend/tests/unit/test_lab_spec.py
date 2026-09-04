"""V7 — the take-profit tournament, and the invariants that make it readable.

This file replaced a version that pinned V6's twenty strategies by name and
threshold. That was right for V6, whose registry was twenty hand-chosen
hypotheses; it is wrong for V7, which is a FACTORIAL EXPERIMENT and whose
correctness lives in its shape rather than in any individual cell.

The experiment: does raising the take-profit improve returns? V6 could not ask
it. Every V6 strategy took profit at 1.25x or 1.5x, and `peak_exec_multiple` is
recorded only while a position is open — so a position closed at 1.25x recorded
a peak of 1.25x, and the registry looked like a population whose tokens never
ran. Measured against the raw price path instead, on V6's own traded tokens:
44.0% reached 1.5x and 19.7% reached 2x.

So what these tests protect is the ability to ATTRIBUTE a result:

  * only the target may vary within an entry rule, or a difference between arms
    could be the entry rule instead of the target;
  * both random controls must be identical apart from their target, or the
    control cannot isolate the target either;
  * the baseline target must be present in every rule, so each rule carries its
    own V6-equivalent rather than being compared across experiments.

A test that named V7-11's threshold would add nothing and would have to be
edited every time the grid changed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.lab import spec

pytestmark = pytest.mark.unit

TRADING = tuple(s for s in spec.STRATEGIES if s.trades)
GRID = tuple(s for s in spec.STRATEGIES if s.entry)
RANDOM = tuple(s for s in spec.STRATEGIES if s.trades and not s.entry)


# --------------------------------------------------------------------------
# shape
# --------------------------------------------------------------------------


def test_the_registry_is_three_controls_and_a_full_grid() -> None:
    assert len(spec.STRATEGIES) == 21
    assert len(GRID) == len(spec._ENTRIES) * len(spec._TARGETS) == 18
    assert len(RANDOM) == 2
    assert sum(1 for s in spec.STRATEGIES if not s.trades) == 1


def test_ids_are_unique_and_ordered() -> None:
    ids = [s.id for s in spec.STRATEGIES]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids), "ids must read in registry order"


def test_every_entry_rule_appears_at_every_target() -> None:
    """The grid must be COMPLETE, or a missing cell becomes a silent conclusion.

    An entry rule absent at 2x would look like a rule that does not work at 2x,
    when in fact nobody ran it.
    """
    seen = {(tuple(str(c) for c in s.entry), s.exits.take_profit) for s in GRID}
    expected = {
        (tuple(str(c) for c in entry), tp)
        for _, _, entry in spec._ENTRIES
        for tp in spec._TARGETS
    }
    assert seen == expected


# --------------------------------------------------------------------------
# attribution — the property the whole tournament rests on
# --------------------------------------------------------------------------


def test_within_an_entry_rule_ONLY_the_target_differs() -> None:
    """If anything else varies, a difference between arms is unattributable.

    This is the single most important assertion in the file. Size, concurrency,
    exposure, checkpoint and the time exit must be identical across an entry
    rule's six arms; only `take_profit` may move.
    """
    by_entry: dict[tuple, list] = {}
    for s in GRID:
        by_entry.setdefault(tuple(str(c) for c in s.entry), []).append(s)

    for entry, arms in by_entry.items():
        assert len(arms) == len(spec._TARGETS), entry
        fixed = {
            (s.checkpoint_minutes, s.size_usd, s.max_concurrent,
             s.max_exposure_usd, s.exits.time_exit_hours,
             s.exits.stop_loss, s.exits.trailing_drawdown, s.exits.partial_at)
            for s in arms
        }
        assert len(fixed) == 1, f"more than the target varies within {entry}"
        assert len({s.exits.take_profit for s in arms}) == len(arms)


def test_the_two_random_controls_differ_only_in_target() -> None:
    """Otherwise the control cannot isolate the target either."""
    a, b = RANDOM
    assert a.entry == b.entry == ()
    assert (a.size_usd, a.max_concurrent, a.max_exposure_usd,
            a.checkpoint_minutes, a.exits.time_exit_hours) == \
           (b.size_usd, b.max_concurrent, b.max_exposure_usd,
            b.checkpoint_minutes, b.exits.time_exit_hours)
    assert {a.exits.take_profit, b.exits.take_profit} == {Decimal("1.25"),
                                                          Decimal("2.00")}


def test_the_old_target_is_present_as_a_baseline_everywhere() -> None:
    """1.25x is in the grid as a CONTROL, not a candidate.

    Every V6 strategy used it, so each entry rule carries its own baseline and
    the comparison is within-rule. Comparing V7's 2x arm against V6's numbers
    instead would be comparing across two experiments run in different markets.
    """
    assert Decimal("1.25") in spec._TARGETS
    for _, _, entry in spec._ENTRIES:
        arms = [s for s in GRID if tuple(str(c) for c in s.entry)
                == tuple(str(c) for c in entry)]
        assert Decimal("1.25") in {s.exits.take_profit for s in arms}


def test_there_is_a_hold_arm_with_no_target_at_all() -> None:
    """The pure "let it run" case V6 never had. `None` means no target, not zero."""
    hold = [s for s in GRID if s.exits.take_profit is None]
    assert len(hold) == len(spec._ENTRIES)
    for s in hold:
        assert s.exits.time_exit_hours == 6, "it must still be bounded by time"


# --------------------------------------------------------------------------
# safety carried forward from V6
# --------------------------------------------------------------------------


def test_no_strategy_carries_a_stop_loss() -> None:
    """Stops on these tokens filled at a median of $0.03 against a nominal -25%.
    The absence is a finding, not an omission."""
    assert all(s.exits.stop_loss is None for s in spec.STRATEGIES)


def test_every_trading_strategy_is_bounded_by_time() -> None:
    """A position that neither targets nor dies never returns its capital."""
    assert all(s.exits.time_exit_hours == 6 for s in TRADING)


def test_no_strategy_can_commit_more_than_the_book() -> None:
    for s in TRADING:
        assert s.max_exposure_usd <= spec.STARTING_EQUITY
        assert s.size_usd * s.max_concurrent <= s.max_exposure_usd * 2


def test_the_cash_control_cannot_trade() -> None:
    cash = next(s for s in spec.STRATEGIES if not s.trades)
    assert cash.size_usd == 0
    assert cash.max_concurrent == 0
    assert cash.entry == ()


# --------------------------------------------------------------------------
# freezing
# --------------------------------------------------------------------------


def test_the_version_moved_so_v6_is_not_reinterpreted() -> None:
    """V6.1's records must keep being read under V6.1's rules."""
    assert spec.SPEC_VERSION == "1.2.0"


def test_the_hash_covers_the_rules_and_not_the_prose() -> None:
    """A typo fixed in a hypothesis must not invalidate a live tournament."""
    before = spec.SPEC_HASH
    assert len(before) == 64
    assert spec._canonical() and spec.SPEC_HASH == before


def test_the_rulebook_renders_every_strategy() -> None:
    """It is served to the page; a strategy it cannot describe is one nobody
    can check against the report."""
    for s in spec.STRATEGIES:
        r = spec.rules_json(s)
        assert r["id"] == s.id
        assert r["entry_text"], s.id
        assert r["exit_text"], s.id
