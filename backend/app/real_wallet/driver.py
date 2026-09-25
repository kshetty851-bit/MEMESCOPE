"""Turn a nominated V6 strategy into at most one real BUY intent per tick.

The binding is deliberately narrow: the real wallet trades **what the Lab
strategy already decided to trade**, read from `lab_decisions`. It does not
re-derive candidates, re-evaluate features, or hold a rule of its own. That
matters for two reasons — the paper record and the real record then describe the
same decisions, and there is exactly one place where entry logic lives.

## Everything here is a refusal

The driver's job is mostly to decline. It runs only when the operator's switch
is on, only on the strategy they nominated, only within the canary bounds the
server owns, and only on a mint this wallet has never traded. `AutonomousExecutionPolicy`
remains the authority on size and count; this asks it rather than reimplementing
it, because two places that both decide how much to spend will eventually
disagree.

It creates intents. It does not assemble orders, sign, or submit — those are the
lifecycle's, and each has its own barrier.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.lab import LabDecision
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet import family, family_wallets, sol_price
from app.real_wallet.autotrade import AutotradeSwitchService, ticket_for
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.policy import (
    AutonomousExecutionPolicy,
    PolicyState,
    configured_entry_size_usd,
)
from app.real_wallet.tx_inspect import lamports_from_sol

#: Lamports in one SOL. Named rather than inline so the conversion in
#: `equity_usd` reads as a unit change and not a magic number.
_LAMPORTS_PER_SOL = Decimal(1_000_000_000)

logger = get_logger(__name__)

#: How far back a Lab decision may be and still be actionable. A decision the
#: Lab made an hour ago describes a market that no longer exists, and acting on
#: it would be trading a stale opinion rather than a current one.
MAX_DECISION_AGE = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class DriverOutcome:
    created: int
    skipped: str | None = None
    mint: str | None = None
    #: Per family member's own wallet: "created:<mint>" or why it skipped.
    #: Empty when no member has a wallet. `created` counts the owner's only.
    family: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {"created": self.created, "skipped": self.skipped, "mint": self.mint}
        if self.family:
            out["family"] = self.family
        return out


class RealWalletDriver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tick(self, *, now: datetime | None = None) -> DriverOutcome:
        """The owner's wallet first, exactly as before; then each family
        member's own wallet, each on its own balance, switch and limits."""
        now = now or datetime.now(UTC)
        owner = await self._owner_tick(now)
        family_outcomes = await self._family_ticks(now)
        return replace(owner, family=family_outcomes) if family_outcomes else owner

    async def _family_ticks(self, now: datetime) -> dict[str, str]:
        """One pass per family member's OWN wallet (stage 2, 2026-09-25).

        Independent of the owner's on/off: each wallet has its own switch,
        which only Karthik can turn on. It trades the strategy he nominated at
        Start — there is one strategy on this platform worth real money at a
        time — and every bound is that wallet's own: its balance, its open
        positions, today's trades and losses. The kill switches still stop
        everything.
        """
        accounts = await family_wallets.accounts(self._session)
        if not accounts:
            return {}
        out: dict[str, str] = {}
        switch = await AutotradeSwitchService(self._session).state()
        repo = LiveIntentRepository(self._session)
        halted = bool(await repo.active_kill_switches())
        for account in accounts:
            if not account.enabled:
                out[account.member] = "own_wallet_off"
            elif not switch.nominated_strategy:
                out[account.member] = "no_strategy_nominated"
            elif halted:
                out[account.member] = "kill_switch_active"
            else:
                out[account.member] = await self._family_tick(
                    account, strategy_id=switch.nominated_strategy, now=now)
        return out

    async def _family_tick(self, account: family_wallets.Account, *,
                           strategy_id: str, now: datetime) -> str:
        """At most one BUY for one family wallet. Every refusal is a string."""
        wallet = account.wallet
        repo = LiveIntentRepository(self._session)
        candidate = await self._next_candidate(strategy_id=strategy_id, now=now, wallet=wallet)
        if candidate is None:
            return "no_fresh_candidate"
        balance_lamports = await self._wallet_lamports(wallet)
        if balance_lamports is None:
            return "wallet_balance_unreadable"
        price = await self._sol_usd(now)
        if price is None:
            return "sol_price_unavailable"
        open_positions = await repo.open_positions_count(wallet)
        # Their own ticket, never above the platform's per-trade ceiling. No
        # growth ladder: the member chose a size, and it is the size.
        ticket = min(account.ticket_usd, settings.REAL_WALLET_MAX_TRADE_USD)
        entry_usd = self._fundable(strategy_id, ticket, balance_lamports=balance_lamports,
                                   sol_price=price, open_positions=open_positions)
        if entry_usd is None or entry_usd <= 0:
            return "entry_not_fundable"
        lamports = lamports_from_sol(
            (entry_usd / price).quantize(Decimal("1e-9"), rounding=ROUND_DOWN))
        if lamports <= 0:
            return "entry_size_rounds_to_zero_lamports"
        equity_usd = (Decimal(balance_lamports) / _LAMPORTS_PER_SOL * price
                      + await repo.open_exposure_usd(wallet))
        decision = AutonomousExecutionPolicy().evaluate_canary_entry(
            requested_usd=entry_usd,
            state=PolicyState(
                open_positions=open_positions,
                exposure_usd=Decimal(open_positions) * entry_usd,
                daily_notional_usd=await self._notional_today(now, wallet),
                daily_realised_loss_usd=await repo.realised_loss_today(now, wallet),
                daily_trades=await self._trades_today(now, wallet),
                wallet_balance_lamports=balance_lamports,
                equity_usd=equity_usd,
                side="BUY",
                spend_lamports=lamports,
            ),
        )
        if not decision.allowed:
            return "policy:" + ",".join(decision.reason_codes)
        intent = await repo.create_intent(
            # The member in the key: the owner's key for the same coin is
            # `v6:<strategy>:<mint>`, and the two must not collide.
            idempotency_key=f"v6:{strategy_id}:{candidate}:{account.member}",
            mint_address=candidate,
            side="BUY",
            strategy_id=strategy_id,
            strategy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            wallet_public_key=wallet,
            requested_usd=entry_usd,
            input_mint=settings.EXECUTION_SOL_MINT,
            output_mint=candidate,
            actual_input_amount_raw=lamports,
        )
        if intent is None:
            return "already_traded"
        logger.warning("real_wallet_family_intent_created", member=account.member,
                       mint=candidate, strategy=strategy_id, usd=str(entry_usd))
        return f"created:{candidate}"

    async def _owner_tick(self, now: datetime) -> DriverOutcome:
        switch = await AutotradeSwitchService(self._session).state()
        if not switch.enabled:
            return DriverOutcome(0, "autotrade_switch_off")
        if not switch.nominated_strategy:
            return DriverOutcome(0, "no_strategy_nominated")

        wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
        if not wallet:
            return DriverOutcome(0, "wallet_not_configured")

        if settings.REAL_WALLET_ENTRY_SIZE_USD <= 0:
            # Zero means nobody decided. A fallback size is a size that ships
            # whatever the fallback was.
            return DriverOutcome(0, "entry_size_not_configured")

        repo = LiveIntentRepository(self._session)
        if await repo.active_kill_switches():
            return DriverOutcome(0, "kill_switch_active")

        # Asked before anything costly. While the graduation arm is nominated
        # the fast loop calls this every few seconds, and with no fresh
        # decision there is nothing to size: the balance read below is an RPC
        # call and the SOL price an HTTP one, neither of which a no-op needs.
        candidate = await self._next_candidate(
            strategy_id=switch.nominated_strategy, now=now, wallet=wallet
        )
        if candidate is None:
            return DriverOutcome(0, "no_fresh_candidate")

        # Measured, not assumed. `evaluate_canary_entry` refuses an unreadable
        # balance on purpose — the ceiling exists to keep the canary tiny, and a
        # wallet nobody measured has not been shown to be tiny. An RPC failure
        # is therefore a skip, never a trade.
        balance_lamports = await self._wallet_lamports(wallet)
        if balance_lamports is None:
            return DriverOutcome(0, "wallet_balance_unreadable")

        # Priced here rather than after the policy check, because the size the
        # policy judges has to be the size actually intended. The growth ladder
        # is denominated in dollars and the wallet holds SOL, so there is no
        # equity figure — and therefore no stake — without this reading.
        sol_price = await self._sol_usd(now)
        if sol_price is None:
            # An unpriced entry is an entry nobody sized. Refuse rather than
            # guess: every limit this wallet has is written in dollars.
            return DriverOutcome(0, "sol_price_unavailable")

        open_positions = await repo.open_positions_count(wallet)

        # --- GROWTH LADDER -------------------------------------------------
        # What the account is worth right now: the SOL it holds, plus what is
        # already committed to open positions. `configured_entry_size_usd`
        # turns that into a stake and clamps it to REAL_WALLET_MAX_TRADE_USD,
        # so the ladder can raise the stake but never the ceiling.
        #
        # Inert until an operator sets REAL_WALLET_SIZING_BASE_USD. Unset means
        # nobody has said at what balance a real order should double, and this
        # is not the place to assume one.
        equity_usd = (
            Decimal(balance_lamports) / _LAMPORTS_PER_SOL * sol_price
            + await repo.open_exposure_usd(wallet)
        )
        entry_usd = configured_entry_size_usd(equity_usd)
        if entry_usd is None or entry_usd <= 0:
            return DriverOutcome(0, "entry_size_not_configured")

        # FAMILY SHARES. The order is the owner's ticket plus every member who
        # is on and can pay for theirs (`family.split`); with nobody on it is
        # the owner's ticket exactly, as it always was. If the wallet cannot
        # fund the whole order, the members sit this one out and the owner's
        # own order is tried alone, so a family setting can never cost the
        # owner a trade they would have taken.
        own = ticket_for(switch, entry_usd)
        order = family.split(own, await family.seats(self._session))
        fundable = self._fundable(
            switch.nominated_strategy, order.total,
            balance_lamports=balance_lamports, sol_price=sol_price,
            open_positions=open_positions)
        if fundable is None and order.members:
            order = family.split(own, ())
            fundable = self._fundable(
                switch.nominated_strategy, order.total,
                balance_lamports=balance_lamports, sol_price=sol_price,
                open_positions=open_positions)
        if fundable is None:
            return DriverOutcome(0, "entry_not_fundable")
        # A wallet holding nothing may spend less than the ticket when that is
        # all its cash is; every share shrinks with it, in proportion.
        order = family.scale(order, fundable)
        entry_usd = order.total

        # Price the entry in the asset the wallet actually holds, and store it.
        #
        # This used to name USDC as the input mint and set no amount at all. The
        # wallet holds SOL and zero USDC, so the swap would have tried to spend
        # a token that is not there — and the order factory refuses first
        # anyway, on `buy_intent_missing_lamports`, because a BUY's spend is
        # taken from the ROW rather than recomputed at assembly. A price that
        # moves between authorisation and assembly must not change what gets
        # spent, which is exactly why it is stored here.
        # Quantised DOWN to whole lamports before conversion. `lamports_from_sol`
        # refuses anything inexact by design — a limit that rounds is a limit
        # that can be crossed by rounding — and $5 at any real SOL price is not
        # a whole number of lamports. Rounding down means the entry is at most
        # the authorised size, never a lamport over it.
        sol_amount = (entry_usd / sol_price).quantize(
            Decimal("1e-9"), rounding=ROUND_DOWN
        )
        lamports = lamports_from_sol(sol_amount)
        if lamports <= 0:
            return DriverOutcome(0, "entry_size_rounds_to_zero_lamports")

        # The server-owned bounds, asked rather than reimplemented.
        #
        # Sized BEFORE this call, not after. The fee-reserve floor is a bound on
        # what the wallet keeps, so the policy cannot judge it without knowing
        # what leaves — and a bound evaluated after the decision is not a bound.
        decision = AutonomousExecutionPolicy().evaluate_canary_entry(
            requested_usd=entry_usd,
            state=PolicyState(
                open_positions=open_positions,
                exposure_usd=Decimal(open_positions) * entry_usd,
                daily_notional_usd=await self._notional_today(now, wallet),
                daily_realised_loss_usd=await repo.realised_loss_today(now, wallet),
                daily_trades=await self._trades_today(now, wallet),
                wallet_balance_lamports=balance_lamports,
                equity_usd=equity_usd,
                side="BUY",
                spend_lamports=lamports,
            ),
        )
        if not decision.allowed:
            return DriverOutcome(0, "policy:" + ",".join(decision.reason_codes))

        # One intent per tick, deliberately. A loop here would turn a single
        # bad minute into a whole book.
        intent = await repo.create_intent(
            idempotency_key=f"v6:{switch.nominated_strategy}:{candidate}",
            mint_address=candidate,
            side="BUY",
            strategy_id=switch.nominated_strategy,
            strategy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            wallet_public_key=wallet,
            requested_usd=entry_usd,
            input_mint=settings.EXECUTION_SOL_MINT,
            output_mint=candidate,
            actual_input_amount_raw=lamports,
        )
        if intent is None:
            return DriverOutcome(0, "already_traded", candidate)
        # Same session, same commit as the intent: an order and the record of
        # whose money is in it cannot exist one without the other.
        family.record(self._session, intent.id, order)
        if order.members:
            # Written now, not at the caller's commit: this session does not
            # autoflush, and a share that fails to write must fail HERE, beside
            # its order, not later where the two could be separated.
            await self._session.flush()

        logger.warning("real_wallet_intent_created", mint=candidate,
                       strategy=switch.nominated_strategy, usd=str(entry_usd),
                       family={k: str(v) for k, v in order.members.items()} or None)
        return DriverOutcome(1, None, candidate)

    async def _sol_usd(self, now: datetime) -> Decimal | None:
        """The wallet's own SOL/USD reading, or None. Never a guessed rate."""
        return await sol_price.current_usd(now)

    async def _wallet_lamports(self, wallet: str) -> int | None:
        """Chain balance in lamports, or None when it could not be read."""
        from app.real_wallet.balance import ExecutionWalletBalanceService
        from app.real_wallet.network import verify_wallet_network
        from app.real_wallet.tx_inspect import lamports_from_sol
        from app.services.rpc.standard import StandardSolanaRPC

        try:
            rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
            async with rpc:
                status = await verify_wallet_network(
                    rpc, network=settings.REAL_WALLET_NETWORK
                )
                if not status.verified:
                    return None
                got = await ExecutionWalletBalanceService(rpc).get_sol_balance(wallet)
                return lamports_from_sol(Decimal(str(got.sol)))
        except Exception as exc:  # pragma: no cover - unreadable chain is a skip
            logger.warning("real_wallet_balance_unreadable", error=str(exc)[:80])
            return None

    @staticmethod
    def _decision_age(strategy_id: str) -> timedelta:
        """How stale a decision may be, per strategy rather than globally.

        Ten minutes is right for a V6/V7 strategy holding for hours. It is
        wrong by an order of magnitude for the graduation arm, whose hold is
        five minutes: a decision acted on nine minutes late buys the token at
        the edge of the collapse the strategy exists to stay in front of.
        """
        from app.labs.graduation.live_spec import BY_ID as GRAD_BY_ID
        from app.labs.graduation.live_spec import MAX_DECISION_AGE_SECONDS

        if strategy_id.upper() in GRAD_BY_ID:
            return timedelta(seconds=MAX_DECISION_AGE_SECONDS)
        return MAX_DECISION_AGE

    @staticmethod
    def _fundable(strategy_id: str, configured: Decimal, *,
                  balance_lamports: int, sol_price: Decimal,
                  open_positions: int) -> Decimal | None:
        """What this entry may spend. For the graduation arm, exactly what the
        board's $100 account would.

        A fixed ticket and a fee-reserve floor do not mix on a small account.
        Funded with $100, a $100 ticket left nothing for the 0.01 SOL reserve
        and every entry was refused; funded with $103, the first 3% drawdown
        refused every entry after it, for good — while the board went on
        trading whatever its cash allowed. `live_spec.fundable` is now the rule
        for both, applied to the SOL the wallet can spend once the reserve is
        kept, and it stops where the board does.

        Other strategies keep their fixed ticket: how they size is the Paper
        position-size work's decision, not this one.

        The floor scales with the ticket (`grad.wallet_floor`): $56 on the
        board's $100, $14 on a $25 ticket chosen at Start. A fixed $56 refused
        every trade smaller than itself.
        """
        from app.labs.graduation import config as grad
        from app.labs.graduation import live_spec

        if strategy_id.upper() not in live_spec.BY_ID:
            return configured
        reserve = lamports_from_sol(
            Decimal(str(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE)))
        # Cents, rounded DOWN: the spend is priced back into lamports, also
        # rounded down, so it can never reach into the reserve.
        cash = (Decimal(max(balance_lamports - reserve, 0)) / _LAMPORTS_PER_SOL
                * sol_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return live_spec.fundable(cash, holding=open_positions > 0,
                                  ticket=configured,
                                  floor=grad.wallet_floor(configured))

    async def _next_candidate(self, *, strategy_id: str, now: datetime,
                              wallet: str) -> str | None:
        """The most recent mint this strategy chose and THIS wallet has not traded.

        Per wallet since 2026-09-25: a coin the owner bought is still a coin a
        family wallet may buy, and the other way round.
        """
        cutoff = now - self._decision_age(strategy_id)
        traded = select(RealWalletLiveIntent.mint_address).where(
            RealWalletLiveIntent.wallet_public_key == wallet)
        rows = await self._session.execute(
            select(LabDecision.mint_address)
            .where(
                LabDecision.strategy_id == strategy_id.upper(),
                LabDecision.eligible.is_(True),
                LabDecision.checkpoint_at >= cutoff,
                LabDecision.mint_address.not_in(traded),
            )
            .order_by(LabDecision.checkpoint_at.desc())
            .limit(1)
        )
        return rows.scalars().first()

    async def _trades_today(self, now: datetime, wallet: str) -> int:
        """This wallet's entries today. Sells are not counted: each would take a
        buy's place, and an exit asked for again would take several."""
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._session.execute(
            select(RealWalletLiveIntent.id).where(
                RealWalletLiveIntent.created_at >= start,
                RealWalletLiveIntent.side == "BUY",
                RealWalletLiveIntent.wallet_public_key == wallet,
            )
        )
        return len(rows.scalars().all())

    async def _notional_today(self, now: datetime, wallet: str) -> Decimal:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._session.execute(
            select(RealWalletLiveIntent.requested_usd).where(
                RealWalletLiveIntent.created_at >= start,
                RealWalletLiveIntent.wallet_public_key == wallet,
            )
        )
        return sum((v for v in rows.scalars() if v), Decimal(0))
