"""Independent hard limits for autonomous execution decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app import sizing
from app.core.config import settings
from app.real_wallet.tx_inspect import lamports_from_sol


class EntryMode(StrEnum):
    ENTRIES_AND_EXITS = "entries_and_exits"
    NO_NEW_ENTRIES_BUT_ALLOW_EXITS = "no_new_entries_but_allow_exits"


class PolicyReason(StrEnum):
    MODE_DISABLED = "MODE_DISABLED"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    MAX_TOTAL_EXPOSURE = "MAX_TOTAL_EXPOSURE"
    MAX_DAILY_NOTIONAL = "MAX_DAILY_NOTIONAL"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    MAX_DAILY_TRADES = "MAX_DAILY_TRADES"
    MAX_TRADE_SIZE = "MAX_TRADE_SIZE"
    MAX_WALLET_BALANCE = "MAX_WALLET_BALANCE"
    ENTRY_SIZE_NOT_CONFIGURED = "ENTRY_SIZE_NOT_CONFIGURED"
    MIN_SOL_FEE_RESERVE = "MIN_SOL_FEE_RESERVE"
    SPEND_NOT_MEASURED = "SPEND_NOT_MEASURED"


@dataclass(frozen=True, slots=True)
class PolicyState:
    open_positions: int
    exposure_usd: Decimal
    daily_notional_usd: Decimal
    daily_realised_loss_usd: Decimal
    #: Submitted real trades in the current day, both sides. A notional cap
    #: alone cannot bound how many times a bug can fire; a trade count can.
    daily_trades: int = 0
    #: Observed wallet balance in **lamports**, from chain. `None` when the
    #: balance could not be read — which refuses, because a canary bound that
    #: cannot be measured has not been satisfied.
    wallet_balance_lamports: int | None = None
    #: "BUY" or "SELL". The distinction matters for the fee-reserve floor and
    #: nowhere else: a BUY spends SOL, a SELL spends the token and RETURNS SOL.
    #: Defaulting to BUY keeps the floor engaged for any caller that has not
    #: thought about it, which is the safe direction to be wrong in.
    side: str = "BUY"
    #: Lamports this entry will take out of the wallet. Required for a BUY —
    #: `None` refuses rather than skipping the floor, because a spend nobody
    #: measured has not been shown to leave the reserve behind. Ignored for a
    #: SELL, which spends no SOL.
    spend_lamports: int | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_codes: tuple[str, ...]


def configured_entry_size_usd(equity_usd: Decimal | None = None) -> Decimal | None:
    """The size one real entry may spend, or `None` when nobody has decided.

    Deliberately **not** the final $100/$50/$25 ladder. That decision belongs to
    the Paper position-size evidence work and has not been made; hardcoding a
    number here would quietly pre-empt it, and a number in code is exactly the
    thing nobody re-reads before a canary.

    Zero — the default — means unconfigured, and unconfigured refuses. An entry
    size that falls back to something sensible is an entry size that ships
    whatever the fallback was.

    Growth ladder: when `equity_usd` is supplied and a sizing base is
    configured, the stake doubles at each doubling of the account, exactly as
    it does for the Strategy Lab — one rule, in `app.sizing`, for both.

    `REAL_WALLET_MAX_TRADE_USD` is applied last and always wins. That ordering
    is the point: the per-trade cap bounds the blast radius of a mistake, and a
    growth rule permitted to raise its own ceiling would not be a bound. It
    also has to be clamped HERE rather than left to the policy, because the
    policy REFUSES an oversized request outright — an unclamped ladder would
    stop the wallet trading the moment it grew instead of sizing it correctly.
    """
    size = settings.REAL_WALLET_ENTRY_SIZE_USD
    if size <= 0:
        return None
    multiplier = sizing.growth_multiplier(
        equity_usd, base=settings.REAL_WALLET_SIZING_BASE_USD
    )
    return sizing.scaled(size, multiplier, cap=settings.REAL_WALLET_MAX_TRADE_USD)


class AutonomousExecutionPolicy:
    """Server-owned limits. Strategy and frontend cannot override this policy."""

    def evaluate_entry(
        self, *, requested_usd: Decimal, state: PolicyState
    ) -> PolicyDecision:
        reasons: list[str] = []
        if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
            reasons.append(PolicyReason.MODE_DISABLED)
        reasons.extend(self._size_and_count_reasons(requested_usd, state))
        return PolicyDecision(allowed=not reasons, reason_codes=tuple(reasons))

    def evaluate_canary_entry(
        self, *, requested_usd: Decimal, state: PolicyState
    ) -> PolicyDecision:
        """Every bound a *real* entry must satisfy, with no mode assertion.

        Mode, enablement, autotrade and the release switch are checked by
        `LiveSubmissionGuard` and `ExecutionTransportPolicy`, which are the
        authorities on them. Repeating those here would give two places the
        power to say yes; this one only ever says how big and how many.

        The wallet-balance ceiling lives only on this path. The dry run has no
        wallet to read and never spends anything, so requiring a balance there
        would refuse every simulated entry for a reason that does not apply.
        """
        reasons = self._size_and_count_reasons(requested_usd, state)
        # Integer lamports, never floating SOL: a ceiling that rounds is a
        # ceiling that can be crossed by rounding. An unreadable balance is a
        # refusal, not a pass — the bound exists to keep the canary tiny, and an
        # unmeasured wallet has not been shown to be tiny.
        ceiling = lamports_from_sol(settings.REAL_WALLET_MAX_BALANCE_SOL)
        if (
            state.wallet_balance_lamports is None
            or state.wallet_balance_lamports > ceiling
        ):
            reasons.append(PolicyReason.MAX_WALLET_BALANCE)
        reasons.extend(self._fee_reserve_reasons(state))
        return PolicyDecision(allowed=not reasons, reason_codes=tuple(reasons))

    @staticmethod
    def _fee_reserve_reasons(state: PolicyState) -> list[str]:
        """A BUY must leave enough SOL behind to pay for its own exit.

        The balance bound above is a CEILING — it keeps the canary small. There
        was no floor, and on 2026-08-27 a $5 entry against a $5.04 wallet priced
        out at 0.049435 of 0.049802 SOL: 99.3% of the wallet, leaving 0.000367
        SOL against a 0.01 reserve. Not enough to open the token account, and
        nowhere near enough to sell afterwards. The policy allowed it.

        A position that cannot pay its exit fee is not a loss, it is a position
        that cannot be closed at any price — the one outcome no stop, no time
        exit and no kill switch can rescue, because every one of them has to
        submit a transaction to work.

        SELLs are exempt, and that exemption is the point rather than an
        oversight. A sell spends the token and pays SOL back in, so applying a
        floor there would refuse exactly the transaction that ENDS the stranded
        state — turning a temporary shortfall into a permanent one.

        The test is `== "SELL"`, not `!= "BUY"`. Those differ on every third
        value, and `side` is a free-form `String(8)` with no enum and no CHECK
        constraint behind it, so third values are ordinary data rather than a
        hypothetical: `"BUY "` with a trailing space is not equal to `"BUY"`,
        and under the inverted test it would have skipped the floor — the exact
        case the floor exists to catch. Exempting only an explicit SELL means
        anything unrecognised is treated as something that spends SOL, so the
        unknown case fails closed.
        """
        if state.side.upper().strip() == "SELL":
            return []
        reserve = lamports_from_sol(
            Decimal(str(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE))
        )
        if state.spend_lamports is None or state.wallet_balance_lamports is None:
            return [PolicyReason.SPEND_NOT_MEASURED]
        if state.wallet_balance_lamports - state.spend_lamports < reserve:
            return [PolicyReason.MIN_SOL_FEE_RESERVE]
        return []

    @staticmethod
    def _size_and_count_reasons(
        requested_usd: Decimal, state: PolicyState
    ) -> list[str]:
        reasons: list[str] = []
        if requested_usd <= 0:
            reasons.append(PolicyReason.ENTRY_SIZE_NOT_CONFIGURED)
        # The per-trade cap is enforced here as well as at sizing, so a caller
        # that computes its own amount cannot exceed it by not asking.
        if requested_usd > settings.REAL_WALLET_MAX_TRADE_USD:
            reasons.append(PolicyReason.MAX_TRADE_SIZE)
        if state.open_positions >= settings.REAL_WALLET_MAX_OPEN_POSITIONS:
            reasons.append(PolicyReason.MAX_OPEN_POSITIONS)
        if state.exposure_usd + requested_usd > settings.REAL_WALLET_MAX_TOTAL_EXPOSURE_USD:
            reasons.append(PolicyReason.MAX_TOTAL_EXPOSURE)
        if (
            state.daily_notional_usd + requested_usd
            > settings.REAL_WALLET_MAX_DAILY_NOTIONAL_USD
        ):
            reasons.append(PolicyReason.MAX_DAILY_NOTIONAL)
        if state.daily_trades >= settings.REAL_WALLET_MAX_DAILY_TRADES:
            reasons.append(PolicyReason.MAX_DAILY_TRADES)
        if state.daily_realised_loss_usd >= settings.REAL_WALLET_MAX_DAILY_LOSS_USD:
            reasons.append(PolicyReason.MAX_DAILY_LOSS)
        return reasons
