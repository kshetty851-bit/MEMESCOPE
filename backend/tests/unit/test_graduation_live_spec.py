"""The graduation arm's registry, and the one thing it must never do.

The failure this guards against is silent and total: adding a strategy to
`app.lab.spec` drifts `SPEC_HASH`, and a drift makes `lab_tick` answer
`{"halted": "spec_hash_drift"}` on every pass — V7 stops, with no error anyone
would see except a board that quietly stops moving.
"""
from __future__ import annotations

from decimal import Decimal

from app.lab import spec as v7
from app.lab.rules import MarkState, evaluate_exit
from app.labs.graduation import live_spec
from app.models.lab import LabDecision, LabStrategy, LabTournament
from app.real_wallet.autotrade import _known_strategy
from app.real_wallet.driver import RealWalletDriver

#: V7's hash as prod stores it on the active `1.2.0` tournament row. Hard-coded
#: rather than recomputed, because a test that recomputes it from the same
#: source it is checking cannot fail.
V7_SPEC_HASH_PREFIX = "ae1627b4ec0d3f9f"


def test_v7_spec_hash_is_untouched() -> None:
    """The whole reason this arm has its own registry."""
    assert v7.SPEC_HASH.startswith(V7_SPEC_HASH_PREFIX)
    assert "G-B3-5M" not in v7.BY_ID


def test_the_two_registries_do_not_overlap() -> None:
    assert not (set(v7.BY_ID) & set(live_spec.BY_ID))
    assert live_spec.SPEC_VERSION != v7.SPEC_VERSION
    assert live_spec.SPEC_HASH != v7.SPEC_HASH


def test_ids_and_versions_fit_their_columns() -> None:
    """String(8) and String(16) truncate silently in some drivers."""
    dec = LabDecision.__table__.c
    strat = LabStrategy.__table__.c
    tour = LabTournament.__table__.c
    for s in live_spec.STRATEGIES:
        assert len(s.id) <= dec.strategy_id.type.length
        assert len(s.id) <= strat.strategy_id.type.length
        assert len(s.name) <= strat.name.type.length
    assert len(live_spec.SPEC_VERSION) <= strat.version.type.length
    assert len(live_spec.SPEC_VERSION) <= tour.spec_version.type.length


def _held(seconds: float) -> MarkState:
    return MarkState(
        exec_multiple=Decimal("1.02"), peak_exec_multiple=Decimal("1.05"),
        # Exactly how `exit_driver` computes it.
        held_hours=seconds / 3600,
        liquidity_usd=Decimal("500000"), entry_liquidity_usd=Decimal("500000"),
        is_dead=False, sell_route_ok=True, break_even_armed=False,
        partial_done=False)


def test_the_clock_fires_exactly_at_five_minutes() -> None:
    """Six seconds of a 28-second margin rides on this boundary.

    The earliest collapse in this arm's own 145 trades landed at 5m28s, and a
    Decimal bound carries more digits than the float `held_hours`, which left
    the position in for one more pass at 5m00s.
    """
    exits = live_spec.STRATEGIES[0].exits
    assert evaluate_exit(exits, _held(299)).action is None
    assert evaluate_exit(exits, _held(300)).action == "CLOSE"


def test_the_four_minute_arm_sells_at_exactly_four_minutes() -> None:
    exits = live_spec.BY_ID["G-B3-4M"].exits
    assert evaluate_exit(exits, _held(239)).action is None
    assert evaluate_exit(exits, _held(240)).action == "CLOSE"


def test_each_live_arm_copies_its_own_paper_book() -> None:
    """The live hold is the paper arm's hold, and each book feeds one arm."""
    from app.labs.graduation.tournament import ARMS

    arms = {a.name: a for a in ARMS}
    assert set(live_spec.PAPER_BOOKS) == {"G-B3-5M", "G-B3-4M", "G-BAS-5M",
                                          "G-QUIET", "G-QUIET4", "G-BAND5",
                                          "G-BANDP"}
    # The band pair differs in the ENTRY only, live as on paper: same band,
    # same lock, same five-minute clock, and the launchpad is what it measures.
    assert live_spec.hold_minutes(live_spec.BY_ID["G-BANDP"]) == 5
    assert live_spec.pool_floor("G-BANDP") == 55_000
    # The band is the one live arm with an UPPER bound. Its reported floor is
    # the band's lower edge; the arm's own rule refuses $75k and above, which a
    # single number cannot express and a reader must not take for a floor.
    assert live_spec.pool_floor("G-BAND5") == 55_000
    assert live_spec.hold_minutes(live_spec.BY_ID["G-BAND5"]) == 5
    # The quiet pair differs ONLY in the clock, live as well as on paper: the
    # four-minute twin exists because AROS drained inside the fifth minute
    # (2026-09-22), so a wrong hold here would silently make them the same arm.
    assert live_spec.hold_minutes(live_spec.BY_ID["G-QUIET"]) == 5
    assert live_spec.hold_minutes(live_spec.BY_ID["G-QUIET4"]) == 4
    assert (live_spec.pool_floor("G-QUIET") == live_spec.pool_floor("G-QUIET4")
            == 75_000)
    for sid, book in live_spec.PAPER_BOOKS.items():
        assert live_spec.hold_minutes(live_spec.BY_ID[sid]) == arms[book].hold
        assert arms[book].clock == "entry", "the live clock starts at the entry"
        assert live_spec.MIRRORS[book] == sid


def test_the_baseline_arm_is_capped_at_ten_dollars(monkeypatch) -> None:
    """Karthik added the board's BASELINE on 2026-09-17. Walked over its own
    week with every rug counted it wiped out a $100 wallet trading $25, so
    Start offers it $10 and $5 and nothing larger — and its floor is the $75k
    that admits the population B3 excludes, not B3's $198k."""
    from app.core.config import settings
    from app.real_wallet.autotrade import ticket_choices

    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("100"))
    assert live_spec.max_ticket("G-BAS-5M") == Decimal("25")
    assert live_spec.max_ticket("G-B3-4M") is None
    assert live_spec.pool_floor("G-BAS-5M") == 75_000
    assert live_spec.pool_floor("G-B3-4M") == live_spec.POOL_FLOOR_USD
    assert [str(t) for t in ticket_choices("G-BAS-5M")] == ["25", "20", "10", "5"]
    assert "100" in [str(t) for t in ticket_choices("G-B3-4M")]


def test_there_is_no_stop_and_no_target() -> None:
    """Both were measured and both were worse; absence here is the finding."""
    for s in live_spec.STRATEGIES:
        assert s.exits.stop_loss is None
        assert s.exits.take_profit is None
        # A deep pool that has not moved must be held, not exited on liquidity.
        assert evaluate_exit(s.exits, _held(60)).action is None


def test_it_is_nominatable_and_nonsense_is_not() -> None:
    assert _known_strategy("G-B3-5M")
    assert _known_strategy("g-b3-4m"), "ids are matched without case, as Start sends them"
    assert _known_strategy("V7-01"), "the V7 registry must still resolve"
    assert not _known_strategy("B3_198k_5m"), "the long paper name is not an id"
    assert not _known_strategy("NOPE-99")


def test_its_decisions_go_stale_in_a_minute_not_ten() -> None:
    """A decision older than the hold buys the token at the cliff."""
    assert RealWalletDriver._decision_age("G-B3-5M").total_seconds() == 60
    assert RealWalletDriver._decision_age("G-B3-4M").total_seconds() == 60
    assert RealWalletDriver._decision_age("V7-01").total_seconds() == 600
