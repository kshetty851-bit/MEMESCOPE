"""Detection time: the earliest discovery record, and nothing standing in for it.

The Track Record shows when MEMESCOPE first *saw* a mint beside when the paper
wallet entered it, and the gap between the two is published as the entry delay.
That figure is only worth printing if the first number is the real one, so every
tempting substitute is asserted against here:

  - `radar_tokens.first_detected_at` is admission to the Radar, which happens
    after enrichment and scoring. It is later — often by hours — and using it
    would silently shrink every delay measured against it.
  - the paper position's own `opened_at` would make each delay read `+0s`.
  - a missing discovery record yields no value at all, not `now()` and not the
    nearest timestamp lying around.

Two tables record a discovery and the answer is the minimum across both:
`discovered_tokens.discovered_at` is stamped when the canonical scanner writes
the row, and `discovery_source_observations.observed_at` when a transport's
socket received it. The observation is the earlier of the two wherever it
exists, so it must win — but it is partial by design, so its absence must not
remove the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discovery import DiscoveryObservationSource, DiscoverySourceObservation
from app.radar.repository import RadarRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)

CANONICAL = "DetectTimeMint111111111111111111111111111111"
EARLIER_OBS = "DetectTimeMint222222222222222222222222222222"
MANY_OBS = "DetectTimeMint333333333333333333333333333333"
LATER_OBS = "DetectTimeMint444444444444444444444444444444"
UNDISCOVERED = "DetectTimeMint555555555555555555555555555555"


async def _discover(session: AsyncSession, mint: str, *, at: datetime) -> None:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": at,
            "block_time": at,
            "name": "Detection Probe",
            "symbol": "DTP",
        }
    )
    assert token is not None


async def _observe(session: AsyncSession, mint: str, *, at: datetime, seq: int) -> None:
    session.add(
        DiscoverySourceObservation(
            source=DiscoveryObservationSource.YELLOWSTONE_GRPC,
            provider_name="probe",
            mint_address=mint,
            signature=f"obs-{mint}-{seq}",
            slot=1,
            event_type="create",
            observed_at=at,
        )
    )
    await session.flush()


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, datetime]:
    canonical = NOW - timedelta(hours=6)

    await _discover(db_session, CANONICAL, at=canonical)

    await _discover(db_session, EARLIER_OBS, at=canonical)
    await _observe(db_session, EARLIER_OBS, at=canonical - timedelta(seconds=3), seq=1)

    await _discover(db_session, MANY_OBS, at=canonical)
    await _observe(db_session, MANY_OBS, at=canonical - timedelta(seconds=1), seq=1)
    await _observe(db_session, MANY_OBS, at=canonical - timedelta(seconds=9), seq=2)
    await _observe(db_session, MANY_OBS, at=canonical - timedelta(seconds=5), seq=3)

    await _discover(db_session, LATER_OBS, at=canonical)
    await _observe(db_session, LATER_OBS, at=canonical + timedelta(minutes=30), seq=1)

    await db_session.flush()
    return {"canonical": canonical}


class TestDetectionTimes:
    async def test_canonical_row_is_the_answer_when_it_is_the_only_record(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        times = await RadarRepository(db_session).detection_times_for([CANONICAL])
        assert times[CANONICAL] == seeded["canonical"]

    async def test_an_earlier_observation_wins(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        times = await RadarRepository(db_session).detection_times_for([EARLIER_OBS])
        assert times[EARLIER_OBS] == seeded["canonical"] - timedelta(seconds=3)

    async def test_many_observations_collapse_to_the_minimum(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        """Requirement three, in one assertion: MIN, not first-written, not last."""
        times = await RadarRepository(db_session).detection_times_for([MANY_OBS])
        assert times[MANY_OBS] == seeded["canonical"] - timedelta(seconds=9)

    async def test_a_later_observation_cannot_push_detection_forward(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        """A replayed or reconnecting transport must not overwrite the earlier truth."""
        times = await RadarRepository(db_session).detection_times_for([LATER_OBS])
        assert times[LATER_OBS] == seeded["canonical"]

    async def test_a_mint_with_no_discovery_record_is_absent_not_guessed(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        times = await RadarRepository(db_session).detection_times_for(
            [CANONICAL, UNDISCOVERED]
        )
        assert UNDISCOVERED not in times
        assert times[CANONICAL] == seeded["canonical"]

    async def test_empty_input_makes_no_query(self, db_session: AsyncSession) -> None:
        assert await RadarRepository(db_session).detection_times_for([]) == {}

    async def test_duplicate_mints_resolve_once(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        times = await RadarRepository(db_session).detection_times_for(
            [CANONICAL, CANONICAL, MANY_OBS]
        )
        assert set(times) == {CANONICAL, MANY_OBS}

    async def test_every_answer_is_utc_aware(
        self, db_session: AsyncSession, seeded: dict[str, datetime]
    ) -> None:
        """The backend keeps the authoritative zone; the client converts, not guesses."""
        times = await RadarRepository(db_session).detection_times_for(
            [CANONICAL, EARLIER_OBS, MANY_OBS, LATER_OBS]
        )
        assert times
        for value in times.values():
            assert value.tzinfo is not None
            assert value.utcoffset() == timedelta(0)
