"""Paper wallet domain types.

Plain dataclasses and enums, held to the same discipline as `app/radar` and
`app/opportunities`: no I/O, no clock, no randomness. `now` enters as an
explicit parameter wherever it is needed at all.

That discipline is not decoration here — it is the product claim. A simulation
whose result depends on when the worker happened to run is not a track record,
it is an anecdote. Everything in this package is a pure function of stored
market history, so the same rows always produce the same trades.

**This simulates nothing but arithmetic.** No wallet is connected, no order is
routed, no chain is touched. A position is a row saying what a published rule
would have done.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class PositionStatus(enum.StrEnum):
    """Whether a simulated trade is still running.

    Persisted as a string, so append-only. There is no third state: a position
    is open or it is finished, and a finished one is never reopened — the
    default strategy enters a token the *first* time it reaches the Top 10,
    which the unique index on (wallet, mint) enforces.
    """

    OPEN = "open"
    CLOSED = "closed"


class ExitReason(enum.StrEnum):
    """Why a position closed.

    Automated members correspond to rules published in the strategy. `MANUAL`
    is deliberately separate: it is a paper-only override, never evidence that
    the automated strategy chose that exit.
    """

    #: Price reached the target fixed at entry.
    TARGET = "target"
    #: Price reached the stop fixed at entry.
    STOP = "stop"
    #: The holding period published by the strategy elapsed.
    EXPIRY = "expiry"
    #: A paper-only human override closed the position at an observed quote.
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Quote:
    """One observed price, reduced to what the simulation reads.

    A projection of `token_market_snapshots` rather than the ORM row, so the
    engine stays free of SQLAlchemy and can be tested with literals.
    """

    captured_at: datetime
    price_usd: Decimal
    #: Pool depth at this reading, when the venue reports it. `None` on
    #: bonding-curve pairs, which report no liquidity at all (ADR 0002) — the
    #: execution-cost model excludes those trades rather than costing them
    #: against an invented depth.
    liquidity_usd: Decimal | None = None
    #: Market cap at this reading. Carried because the audit log records the
    #: valuation at each end of a trade, and the snapshot that held it is
    #: prunable — a figure read later could be gone.
    market_cap: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """A token the strategy may open, with the facts it is allowed to read.

    Deliberately narrow. A strategy that could see the base rate, the risk band
    or the Radar score would be tempted to weight by them, and the moment
    position size depends on a score the wallet stops measuring the Radar and
    starts measuring a second, unpublished model.

    `liquidity_usd` and `market_cap` are here for the *entry gate* and the audit
    record, not for sizing: liquidity decides whether a token is tradeable at
    all, and both are recorded as observed. Nothing scales a position by them.
    """

    mint_address: str
    rank: int
    price_usd: Decimal
    observed_at: datetime
    liquidity_usd: Decimal | None = None
    market_cap: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Entry:
    """An instruction to open one position, priced and bounded at entry.

    Every exit parameter is computed here and stored once. Fixing them at entry
    is the anti-hindsight guarantee: an exit level that could be recomputed
    later could be recomputed favourably.

    All four bound fields are optional because a strategy publishes only the
    rules it actually has. Trailing Stop 25% — the one operational strategy
    since Sprint 30 — carries `trailing_drawdown` and nothing else; a zeroed
    target would read as a rule that exists and sits at zero.
    """

    mint_address: str
    price_usd: Decimal
    size_usd: Decimal
    quantity: Decimal
    opened_at: datetime
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    expires_at: datetime | None = None
    trailing_drawdown: Decimal | None = None
    #: The market observed at entry, recorded rather than used. Perishable, and
    #: required by the permanent audit record at close.
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Exit:
    """The moment a position's rule was first breached.

    `at` is the timestamp of the *observation* that breached it, not the moment
    the evaluator noticed. A worker that was down for an hour must produce the
    same exit as one that was not.
    """

    price_usd: Decimal
    at: datetime
    reason: ExitReason


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """A running position, as the engine reads it.

    The three bounds are optional for the same reason `Entry`'s are: a strategy
    carries only the rules it published, and a rule that does not exist cannot
    be breached. `peak_price` is not optional — every strategy has a running
    high, and the trailing stop is measured from it.
    """

    mint_address: str
    opened_at: datetime
    entry_price: Decimal
    quantity: Decimal
    size_usd: Decimal
    peak_price: Decimal
    target_price: Decimal | None = None
    stop_price: Decimal | None = None
    expires_at: datetime | None = None
    trailing_drawdown: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """A finished position, reduced to what the metrics read."""

    mint_address: str
    opened_at: datetime
    closed_at: datetime
    size_usd: Decimal
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    reason: ExitReason

    @property
    def proceeds(self) -> Decimal:
        return self.quantity * self.exit_price

    @property
    def pnl(self) -> Decimal:
        return self.proceeds - self.size_usd
