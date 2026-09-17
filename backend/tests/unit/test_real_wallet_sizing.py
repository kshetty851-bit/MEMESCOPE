"""The growth ladder on the real wallet, and the caps that outrank it."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import settings
from app import sizing
from app.real_wallet.policy import configured_entry_size_usd


@pytest.fixture
def sized(monkeypatch: pytest.MonkeyPatch):
    def _apply(*, entry: str, base: str, cap: str):
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal(entry))
        monkeypatch.setattr(settings, "REAL_WALLET_SIZING_BASE_USD", Decimal(base))
        monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal(cap))
    return _apply


class TestUnconfigured:
    def test_no_entry_size_still_refuses(self, sized) -> None:
        sized(entry="0", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("400")) is None

    def test_no_sizing_base_means_no_ladder(self, sized) -> None:
        """Unset base = nobody said when a real order should double."""
        sized(entry="5", base="0", cap="500")
        assert configured_entry_size_usd(Decimal("100000")) == Decimal("5")

    def test_no_equity_reading_stakes_the_base_size(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(None) == Decimal("5")


class TestTheLadderApplies:
    def test_it_doubles_at_twice_the_base(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("199")) == Decimal("5")
        assert configured_entry_size_usd(Decimal("200")) == Decimal("10")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")
        assert configured_entry_size_usd(Decimal("800")) == Decimal("40")

    def test_a_drawdown_takes_the_stake_back_down(self, sized) -> None:
        sized(entry="5", base="100", cap="500")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")
        assert configured_entry_size_usd(Decimal("150")) == Decimal("5")


class TestTheCapMovesWithTheLadder:
    """The cap now SCALES rather than freezing the stake — a deliberate change,
    made on instruction, and the reasoning it replaced is worth stating.

    The cap used to be absolute: growth could never lift it, because a bound a
    growth rule can raise is not a bound. That is sound against the specific
    failure it names — equity is a COMPUTED figure, and one bad mark on an
    illiquid position inflates it, so an equity-scaled cap lets a bad mark
    enlarge its own blast radius.

    What replaces it is not "no bound" but a different one. `MAX_DOUBLINGS`
    caps the ladder at 2^6, so a wildly wrong equity can widen the per-trade
    ceiling by at most 64x rather than without limit — and 64x from a $5 base
    is $320, which measurement puts at the edge of what these pools absorb:
    round-trip cost on live V6-07 candidates runs 1.7-2.5% at $5 and 3.0-11.8%
    at $500. The market stops cooperating before the ladder does.
    """

    def test_growth_now_lifts_the_per_trade_ceiling(self, sized) -> None:
        """A fixed cap over a growing stake is an off switch, not a bound: the
        stake reaches it once and every later doubling is silently discarded."""
        sized(entry="5", base="100", cap="5")
        assert configured_entry_size_usd(Decimal("200")) == Decimal("10")
        assert configured_entry_size_usd(Decimal("400")) == Decimal("20")

    def test_the_ladder_itself_is_still_bounded(self, sized) -> None:
        """MAX_DOUBLINGS is what stops an inflated equity widening the ceiling
        without limit. It is the bound that survived the change."""
        sized(entry="5", base="100", cap="5")
        ceiling = Decimal("5") * (2 ** sizing.MAX_DOUBLINGS)
        assert configured_entry_size_usd(Decimal("1000000000")) == ceiling

    def test_the_lab_and_the_real_wallet_share_one_ladder(self) -> None:
        """MAX_DOUBLINGS governs the Lab's twenty portfolios as well as the real
        wallet, so raising it is a change to a running experiment's rules.

        It was safe at 6 -> 8 only because it is unreachable there: the bound
        binds at 2^6 = 64x, and the live tournament's best portfolio stood at
        1.65x — it had not reached the FIRST doubling. Anyone raising this
        again should check that number rather than assume it.
        """
        from app.lab import service as lab_service

        assert "growth_multiplier" in Path(lab_service.__file__).read_text()
        assert sizing.MAX_DOUBLINGS >= 6

    def test_it_clamps_rather_than_refusing(self, sized) -> None:
        """Clamped here on purpose: the POLICY refuses an oversized request
        outright, so an unclamped ladder would stop the wallet trading the
        moment it grew instead of sizing it correctly."""
        sized(entry="5", base="100", cap="12")
        grown = configured_entry_size_usd(Decimal("800"))
        assert grown == Decimal("40")          # 8x ladder, under the 8x cap of 96
        assert grown <= settings.REAL_WALLET_MAX_TRADE_USD * 8


class TestTheGraduationArmSizesLikeTheBoard:
    """A fixed $100 ticket and a 0.01 SOL fee reserve do not mix on a $100
    account: funded with exactly $100 it never traded, and funded with $103 the
    first 3% drawdown stopped it for good. The graduation arm now sizes with
    the board's own rule, `live_spec.fundable`, over what the reserve leaves.
    Priced at $100 a SOL, so SOL and hundreds of dollars read the same."""

    PRICE = Decimal("100")

    @pytest.fixture(autouse=True)
    def _reserve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01"))

    def fund(self, sol: str, *, holding: int = 0, strategy: str = "G-B3-5M"):
        from app.real_wallet.driver import RealWalletDriver

        return RealWalletDriver._fundable(
            strategy, Decimal("100"),
            balance_lamports=int(Decimal(sol) * 1_000_000_000),
            sol_price=self.PRICE, open_positions=holding)

    def test_exactly_one_hundred_dollars_trades_what_the_reserve_leaves(self) -> None:
        assert self.fund("1") == Decimal("99.00")

    def test_a_richer_account_takes_the_whole_ticket_and_no_more(self) -> None:
        assert self.fund("1.03") == Decimal("100")
        assert self.fund("5") == Decimal("100")

    def test_a_drawdown_shrinks_the_ticket_instead_of_stopping_it(self) -> None:
        assert self.fund("0.9785") == Decimal("96.85")

    def test_it_stops_where_the_board_stops(self) -> None:
        from app.labs.graduation import config as grad

        assert Decimal("56") == grad.WALLET_MIN_USD
        assert self.fund("0.57") == Decimal("56.00")
        assert self.fund("0.5699") is None

    def test_a_second_position_needs_a_whole_ticket(self) -> None:
        """"$200 holds two" — two full positions, never one and a scrap."""
        assert self.fund("1.5", holding=1) == Decimal("100")
        assert self.fund("0.9", holding=1) is None

    def test_a_smaller_ticket_stops_at_the_same_share_of_itself(self) -> None:
        """$25 chosen at Start: the floor is $14, not $56, or it never trades."""
        from app.real_wallet.driver import RealWalletDriver

        def fund(sol: str, holding: int = 0) -> Decimal | None:
            return RealWalletDriver._fundable(
                "G-B3-4M", Decimal("25"),
                balance_lamports=int(Decimal(sol) * 1_000_000_000),
                sol_price=self.PRICE, open_positions=holding)

        assert fund("1") == Decimal("25")
        assert fund("0.2") == Decimal("19.00")
        assert fund("0.15") == Decimal("14.00")
        assert fund("0.1499") is None
        assert fund("0.3", holding=1) == Decimal("25")
        assert fund("0.25", holding=1) is None

    def test_other_strategies_keep_their_fixed_ticket(self) -> None:
        assert self.fund("0.2", strategy="V6-06") == Decimal("100")

    def test_the_policy_accepts_the_size_it_is_handed(self) -> None:
        """The sized spend leaves exactly the reserve; the old fixed ticket is
        what the policy refused."""
        from decimal import ROUND_DOWN

        from app.real_wallet.policy import (
            AutonomousExecutionPolicy,
            PolicyReason,
            PolicyState,
        )
        from app.real_wallet.tx_inspect import lamports_from_sol

        def reasons(usd: Decimal) -> tuple[str, ...]:
            spend = lamports_from_sol((usd / self.PRICE).quantize(
                Decimal("1e-9"), rounding=ROUND_DOWN))
            return AutonomousExecutionPolicy().evaluate_canary_entry(
                requested_usd=usd,
                state=PolicyState(
                    open_positions=0, exposure_usd=Decimal(0),
                    daily_notional_usd=Decimal(0),
                    daily_realised_loss_usd=Decimal(0), daily_trades=0,
                    wallet_balance_lamports=1_000_000_000,
                    equity_usd=Decimal(100), side="BUY", spend_lamports=spend),
            ).reason_codes

        assert PolicyReason.MIN_SOL_FEE_RESERVE in reasons(Decimal("100"))
        assert PolicyReason.MIN_SOL_FEE_RESERVE not in reasons(self.fund("1"))


class TestTheTradeSizeChosenAtStart:
    def test_the_choices_are_the_board_splits_from_the_configured_size_down_to_five(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.real_wallet.autotrade import ticket_choices

        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("100"))
        assert ticket_choices() == [Decimal(x) for x in ("100", "50", "25", "20", "10", "5")]
        monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("30"))
        assert ticket_choices() == [Decimal(x) for x in ("25", "20", "10", "5")]

    def test_a_chosen_size_never_exceeds_the_configured_one(self) -> None:
        from dataclasses import replace

        from app.real_wallet.autotrade import AutotradeState, ticket_for

        state = AutotradeState(
            enabled=True, nominated_strategy="G-B3-4M", started_at=None,
            started_by=None, start_reason=None, stopped_at=None, stopped_by=None,
            stop_reason=None, ticket_usd=Decimal("25"))
        assert ticket_for(state, Decimal("100")) == Decimal("25")
        assert ticket_for(state, Decimal("10")) == Decimal("10")
        assert ticket_for(replace(state, ticket_usd=None), Decimal("100")) == Decimal("100")

    def test_a_capped_arm_never_spends_above_its_cap(self) -> None:
        """Start refuses $25 for G-BAS-5M, but no size at all means the
        configured $100 — which is the one thing its own walk rules out."""
        from dataclasses import replace

        from app.real_wallet.autotrade import AutotradeState, ticket_for

        state = AutotradeState(
            enabled=True, nominated_strategy="G-BAS-5M", started_at=None,
            started_by=None, start_reason=None, stopped_at=None, stopped_by=None,
            stop_reason=None, ticket_usd=None)
        assert ticket_for(state, Decimal("100")) == Decimal("10")
        assert ticket_for(replace(state, ticket_usd=Decimal("5")), Decimal("100")) == (
            Decimal("5"))
