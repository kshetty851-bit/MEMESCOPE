"""Loading the lab's dataset, once, and replaying every rule over it.

The dataset is built **once per request and shared by every strategy** — that
sharing is not an optimisation, it is the guarantee. Two strategies given two
separately-loaded datasets could differ because a snapshot landed between the
loads, and the comparison would silently be measuring a race.

I/O only. Every decision lives in `lab.py` and `exits.py`, which are pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar import RadarToken
from app.paper import exits, lab
from app.paper.models import Quote
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository

#: How far before a detection to look for its entry price. A detection recorded
#: at 12:00 was scored from a snapshot taken moments earlier, so the entry is the
#: first reading at or after that moment — not one an hour later.
_ENTRY_LOOKBACK = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class LabDataset:
    """Every detection and its price history, as replayed."""

    detections: tuple[lab.Detection, ...]
    #: Detections that were never priced, so never entered by any rule.
    unpriced: int
    loaded_at: datetime


async def load_dataset(session: AsyncSession, *, now: datetime) -> LabDataset:
    """Every Radar detection with its observed prices, in two queries.

    Ordered by detection time with a mint tiebreak so the replay input — and
    therefore its output — is identical across runs.
    """
    entries = list(
        (
            await session.scalars(
                select(RadarToken).order_by(
                    RadarToken.first_detected_at.asc(), RadarToken.mint_address.asc()
                )
            )
        ).all()
    )
    if not entries:
        return LabDataset(detections=(), unpriced=0, loaded_at=now)

    oldest = min(entry.first_detected_at for entry in entries) - _ENTRY_LOOKBACK
    series = await MarketSnapshotRepository(session).series_for_mints(
        [entry.mint_address for entry in entries], since=oldest
    )
    names = await RadarRepository(session).names_for([entry.mint_address for entry in entries])

    detections: list[lab.Detection] = []
    unpriced = 0
    for entry in entries:
        cutoff = entry.first_detected_at - _ENTRY_LOOKBACK
        quotes = tuple(
            Quote(
                captured_at=row.captured_at,
                price_usd=row.price_usd,
                liquidity_usd=row.liquidity_usd,
            )
            for row in series.get(entry.mint_address, [])
            if row.price_usd is not None and row.price_usd > 0 and row.captured_at >= cutoff
        )
        if not quotes:
            unpriced += 1
            continue
        _, symbol = names.get(entry.mint_address, (None, None))
        detections.append(
            lab.Detection(
                mint_address=entry.mint_address,
                symbol=symbol,
                detected_at=entry.first_detected_at,
                quotes=quotes,
            )
        )

    return LabDataset(detections=tuple(detections), unpriced=unpriced, loaded_at=now)


def replay_all(dataset: LabDataset) -> dict[str, lab.LabResult]:
    """Every published rule over the one dataset.

    Keyed by strategy id and built in declaration order, so iteration is stable.
    """
    return {
        strategy.id: lab.replay(dataset.detections, strategy)
        for strategy in exits.LAB_STRATEGIES
    }
