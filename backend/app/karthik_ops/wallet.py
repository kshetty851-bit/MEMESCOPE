"""Which wallet Karthik operates — and the honest answer when there is none.

── THE STATE THIS MODULE EXISTS FOR ─────────────────────────────────────

The operator and the wallet were built at the same time on two branches. On a
deployment carrying only this one, the `karthik_*` tables do not exist; on a
deployment carrying both, there is exactly one wallet row. Both are correct
states and neither is an error, so `resolve()` always returns a `Binding` and
never raises — every caller then asks it one question, `readable`, before it
touches a figure.

That is what let the whole operator be built, tested and deployed before the
thing it operates existed, and it is what keeps it correct afterwards: the same
branch that reports NOT DESIGNATED today reports a wallet tomorrow with no code
change at all.

── WHY IT REFUSES TO READ ANYBODY ELSE'S WALLET ─────────────────────────

`tables.py` names three tables and no others, so the isolation §7 asks for is
not a rule this module follows — it is the only data it can reach. The check
below is the second line of that defence: a deployment that somehow points the
operator at a foreign wallet is a misconfiguration that must surface in the
owner queue rather than be read anyway.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik_ops import tables
from app.karthik_ops.authority import FORBIDDEN_STRATEGY_IDS, WALLET_ENV_VAR

#: Four states, not a boolean, because they need four different sentences and
#: two of them need different *treatment*: `unbound` is the expected state of a
#: deployment without the wallet, while `forbidden` is a misconfiguration that
#: must reach the owner-attention queue.
BindingState = Literal["bound", "unbound", "forbidden", "designated_but_missing"]


@dataclass(frozen=True, slots=True)
class Binding:
    """The wallet Karthik operates, or a precise account of why there isn't one."""

    state: BindingState
    #: What the environment asked for, if anything. Normally empty: the wallet
    #: is a singleton and does not need naming.
    designated_strategy_id: str
    #: One sentence, rendered verbatim by every surface that has nothing to show.
    detail: str
    wallet_id: str | None = None
    strategy_version: str | None = None
    generation: int | None = None
    starting_balance: Decimal | None = None
    started_at: datetime | None = None
    archived_at: datetime | None = None
    #: The wallet's own published rules, read so fills can be checked against
    #: them. Never written, and never used to instruct the wallet.
    trade_size: Decimal | None = None
    take_profit_multiple: Decimal | None = None

    @property
    def readable(self) -> bool:
        """True only when there is a real wallet row behind this.

        Every figure-producing surface gates on this. A surface that forgets to
        is a surface that will render `$0.00` for a wallet that does not exist,
        which is the single most misleading thing this feature could do.
        """
        return self.state == "bound"

    @property
    def needs_owner(self) -> bool:
        """True when the binding itself is something only the owner can fix."""
        return self.state in ("forbidden", "designated_but_missing")


UNBOUND = Binding(
    state="unbound",
    designated_strategy_id="",
    detail=(
        "The Karthik Paper Wallet is not present on this deployment: its tables "
        "have not been created. Karthik is running as an operator with nothing "
        "to operate, and every figure below reads NOT DESIGNATED rather than zero."
    ),
)


def designated_strategy_id() -> str:
    """An explicit override, if the deployment sets one. Normally empty."""
    return os.getenv(WALLET_ENV_VAR, "").strip()


async def resolve(session: AsyncSession) -> Binding:
    """Find Karthik's wallet, refusing anyone else's.

    The wallet is a singleton — its table carries a unique index on a constant
    expression, which is the database saying "at most one of these" — so there
    is no selection to make and no generation to choose. If a second row ever
    appears, the `limit(1)` here would hide it, so the count is checked and a
    second row is reported as a misconfiguration rather than silently ignored.
    """
    wanted = designated_strategy_id()
    if wanted and wanted in FORBIDDEN_STRATEGY_IDS:
        return Binding(
            state="forbidden",
            designated_strategy_id=wanted,
            detail=(
                f"{WALLET_ENV_VAR} names {wanted!r}, which belongs to another "
                "wallet Karthik is forbidden to operate. Refused: nothing was "
                "read and no figure below comes from it. Correct the variable."
            ),
        )

    if not await tables.exists(session):
        return UNBOUND

    rows = (
        await session.execute(
            select(
                tables.karthik_wallets.c.id,
                tables.karthik_wallets.c.name,
                tables.karthik_wallets.c.starting_capital,
                tables.karthik_wallets.c.trade_size,
                tables.karthik_wallets.c.take_profit_multiple,
                tables.karthik_wallets.c.activated_at,
            ).limit(2)
        )
    ).all()

    if not rows:
        return Binding(
            state="designated_but_missing",
            designated_strategy_id=wanted,
            detail=(
                "The Karthik Paper Wallet's tables exist but hold no wallet: it "
                "has not been activated. Karthik reads nothing rather than "
                "reporting an empty wallet as a flat one."
            ),
        )

    if len(rows) > 1:
        return Binding(
            state="forbidden",
            designated_strategy_id=wanted,
            detail=(
                f"{len(rows)} Karthik wallets exist where the schema permits one. "
                "Refused: reading either of them would publish half an "
                "experiment as the whole of it. This needs the owner."
            ),
        )

    row = rows[0]
    return Binding(
        state="bound",
        designated_strategy_id=wanted or str(row.name),
        detail=(
            f"Operating {row.name}: ${row.starting_capital} of capital, "
            f"${row.trade_size} a trade, {row.take_profit_multiple}x target, no stop."
        ),
        wallet_id=str(row.id),
        strategy_version=str(row.name),
        generation=1,
        starting_balance=row.starting_capital,
        started_at=row.activated_at,
        archived_at=None,
        trade_size=row.trade_size,
        take_profit_multiple=row.take_profit_multiple,
    )
