"""Whether the execution rail is moving, and whether the wallet adds up.

Three questions, each with a way of failing that the existing guards cannot
report because they are all guards on the WAY IN:

  STUCK       an intent sitting in a non-terminal state. The executor advances
              one step per tick, so anything older than a few minutes is not
              being advanced at all — and the intent that is stuck is invisible
              from outside, because the beat keeps ticking.

  REPEATED    the same block reason over and over. Every intent ending
              `safety:` with nothing after it was a real failure that ran for
              hours: fail-closed, so nothing unsafe happened, and completely
              broken. One rejection is the system working; forty identical ones
              is a wall nobody can see.

  BALANCE     money that left without going through the rail at all. Read from
              `balance_watch`, and the only signal here that is security rather
              than operations.

Reports measurements. The thresholds live in `hq_ops` with every other one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet import balance_watch

logger = get_logger(__name__)

#: States an intent should pass THROUGH, never rest in.
IN_FLIGHT = ("created", "safety_approved", "order_created", "signed")

#: How long a non-terminal intent may sit before it is stuck. The executor
#: advances one state per tick at one tick a minute, so five minutes is several
#: passes with no movement — a stall, not a slow step.
STUCK_AFTER = timedelta(minutes=5)

#: Window for counting repeated refusals. An hour: long enough that a pattern
#: is a pattern, short enough that yesterday's fixed problem is not still
#: being reported.
REPEAT_WINDOW = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class WalletHealth:
    measured: bool
    detail: str
    stuck_intents: int | None = None
    oldest_stuck_minutes: float | None = None
    repeated_reason: str | None = None
    repeated_count: int | None = None
    balance_lamports: int | None = None
    balance_delta_lamports: int | None = None
    balance_unexplained: bool | None = None
    balance_observed_minutes_ago: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "measured": self.measured, "detail": self.detail,
            "stuck_intents": self.stuck_intents,
            "oldest_stuck_minutes": self.oldest_stuck_minutes,
            "repeated_reason": self.repeated_reason,
            "repeated_count": self.repeated_count,
            "balance_lamports": self.balance_lamports,
            "balance_delta_lamports": self.balance_delta_lamports,
            "balance_unexplained": self.balance_unexplained,
            "balance_observed_minutes_ago": self.balance_observed_minutes_ago,
        }


async def read(session: AsyncSession, *, now: datetime | None = None) -> WalletHealth:
    now = now or datetime.now(UTC)
    wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not wallet:
        return WalletHealth(measured=False, detail="No execution wallet configured.")
    try:
        stuck_rows = list((await session.execute(
            select(RealWalletLiveIntent.created_at)
            .where(RealWalletLiveIntent.wallet_public_key == wallet,
                   RealWalletLiveIntent.state.in_(IN_FLIGHT),
                   RealWalletLiveIntent.created_at <= now - STUCK_AFTER)
        )).scalars())
        oldest = (round((now - _aware(min(stuck_rows))).total_seconds() / 60, 1)
                  if stuck_rows else None)

        repeated = (await session.execute(
            select(RealWalletLiveIntent.failure_reason, func.count())
            .where(RealWalletLiveIntent.wallet_public_key == wallet,
                   RealWalletLiveIntent.state == "blocked",
                   RealWalletLiveIntent.failure_reason.is_not(None),
                   RealWalletLiveIntent.created_at >= now - REPEAT_WINDOW)
            .group_by(RealWalletLiveIntent.failure_reason)
            .order_by(func.count().desc())
            .limit(1)
        )).first()

        observation = await balance_watch.latest(session)
    except Exception as exc:  # noqa: BLE001 - unmeasurable is not healthy
        logger.warning("wallet_health_unreadable", error=str(exc))
        return WalletHealth(measured=False, detail=f"Wallet health unreadable: {exc}")

    return WalletHealth(
        measured=True,
        detail=(f"{len(stuck_rows)} in-flight beyond {STUCK_AFTER}, "
                f"balance {'unexplained' if observation and observation.unexplained else 'accounted for'}."),
        stuck_intents=len(stuck_rows),
        oldest_stuck_minutes=oldest,
        repeated_reason=(repeated[0] if repeated else None),
        repeated_count=(int(repeated[1]) if repeated else None),
        balance_lamports=(int(observation.lamports) if observation else None),
        balance_delta_lamports=(
            int(observation.delta_lamports)
            if observation and observation.delta_lamports is not None else None
        ),
        balance_unexplained=(observation.unexplained if observation else None),
        balance_observed_minutes_ago=(
            round((now - _aware(observation.observed_at)).total_seconds() / 60, 1)
            if observation else None
        ),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = ["IN_FLIGHT", "REPEAT_WINDOW", "STUCK_AFTER", "WalletHealth", "read"]
