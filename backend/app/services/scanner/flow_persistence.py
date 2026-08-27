"""Persist wallet-flow snapshots for the mints research actually needs.

The tracker aggregates in scanner memory; this writes a point-in-time row per
research-relevant key every flush interval. Relevance is derived each flush —
nursery members still OBSERVING plus recent Track Record admissions — so the
write volume is bounded by the population that matters (~hundreds), never by
the 4,000 mints the tracker holds.

PumpSwap events name a pool, not a mint, so each relevant mint's latest known
pool address is looked up once per flush and flushed under its own key with
`key_kind='pool'`. Research joins pool->mint at read time; the scanner's socket
loop never pays for that resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.models.research_data import NurseryAdmission, WalletFlowSnapshot
from app.services.scanner.wallet_flow import FlowStats, WalletFlowTracker

logger = get_logger(__name__)

#: Which tracker windows land in columns. 15m exists in the tracker and is
#: deliberately not stored: two windows bound the row width and the 15m answer
#: is reconstructable from consecutive 5m rows at this flush cadence.
STORED = {"5m": "w5m", "1h": "w1h"}


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, 6)))


def _columns(prefix: str, stats: FlowStats) -> dict[str, object]:
    return {
        f"{prefix}_unique_buyers": stats.unique_buyers,
        f"{prefix}_unique_sellers": stats.unique_sellers,
        f"{prefix}_unique_wallets": stats.unique_wallets,
        f"{prefix}_buy_count": stats.buy_count,
        f"{prefix}_sell_count": stats.sell_count,
        f"{prefix}_buy_volume": stats.buy_volume,
        f"{prefix}_sell_volume": stats.sell_volume,
        f"{prefix}_tx_per_wallet": _dec(stats.tx_per_wallet),
        f"{prefix}_repeat_wallet_ratio": _dec(stats.repeat_wallet_ratio),
        f"{prefix}_top5_tx_share": _dec(stats.top5_tx_share),
        f"{prefix}_top10_tx_share": _dec(stats.top10_tx_share),
        f"{prefix}_top5_volume_share": _dec(stats.top5_volume_share),
        f"{prefix}_top10_volume_share": _dec(stats.top10_volume_share),
        f"{prefix}_largest_buyer_share": _dec(stats.largest_buyer_share),
        f"{prefix}_largest_seller_share": _dec(stats.largest_seller_share),
        f"{prefix}_quality": stats.quality,
    }


async def relevant_keys(now: datetime) -> tuple[set[str], set[str]]:
    """(mints, pools) worth persisting this flush. One session, two queries."""
    async with SessionFactory() as session:
        observing = set(
            (
                await session.execute(
                    select(NurseryAdmission.mint_address).where(
                        NurseryAdmission.status == "observing"
                    )
                )
            ).scalars()
        )
        admitted = set(
            (
                await session.execute(
                    select(RadarToken.mint_address).where(
                        RadarToken.first_detected_at >= now - timedelta(hours=24)
                    )
                )
            ).scalars()
        )
        mints = observing | admitted
        pools: set[str] = set()
        if mints:
            rows = await session.execute(
                select(TokenMarketSnapshot.pool_address)
                .distinct()
                .where(
                    TokenMarketSnapshot.mint_address.in_(mints),
                    TokenMarketSnapshot.pool_address.is_not(None),
                    TokenMarketSnapshot.captured_at >= now - timedelta(hours=24),
                )
            )
            pools = set(rows.scalars())
        return mints, pools


async def flush(tracker: WalletFlowTracker, *, now: datetime | None = None) -> int:
    """Write one snapshot row per relevant tracked key. Returns rows written."""
    moment = now or datetime.now(UTC)
    mints, pools = await relevant_keys(moment)
    rows: list[WalletFlowSnapshot] = []
    for key_kind, keys in (("mint", mints), ("pool", pools)):
        for key in keys:
            stats = tracker.stats(key, now=moment)
            if not stats:
                continue
            by_window = {s.window: s for s in stats}
            if all(
                by_window[w].buy_count + by_window[w].sell_count == 0
                for w in STORED
                if w in by_window
            ):
                continue  # nothing traded: no row, no noise
            values: dict[str, object] = {
                "key": key,
                "key_kind": key_kind,
                "captured_at": moment,
            }
            for window, prefix in STORED.items():
                if window in by_window:
                    values.update(_columns(prefix, by_window[window]))
            rows.append(WalletFlowSnapshot(**values))
    if rows:
        async with SessionFactory() as session:
            session.add_all(rows)
            await session.commit()
    return len(rows)
