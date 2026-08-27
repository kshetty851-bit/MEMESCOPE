"""What a Radar row carries, and what it refuses to carry.

Sprint 23. Before this the Radar ranked tokens and published a base rate but
told a reader nothing about what the token was trading at, how old it was, how
risky the sweep found it, or how much of the model actually had data. The list
was a leaderboard; a trader could not act on a row without leaving it.

Most of what is asserted here is about *absence*, because that is where a
ranking product is tempted to lie:

  - a token nobody has priced has no market, not a market worth zero;
  - a dimension the sweep could not assess has no risk score, not a risk of 0;
  - a token with nothing live has no signal, and is still a complete row;
  - `evidence` is published beside the score, because a 90 scored on a third of
    the model is not the same claim as a 90 scored on all of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.opportunity import Opportunity, OpportunitySignal
from app.models.radar import RadarSnapshot, RadarToken
from app.models.opportunity import (
    OpportunityStage,
    OpportunityStatus,
    SignalStatus,
)

#: The engine's SignalType enum is gone with the engine; historical rows carry
#: plain strings, which is also all the fixtures ever needed.
FRESH_GRADUATION = "fresh_graduation"
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
MINT = "RadarRowMint1111111111111111111111111111111"
OTHER = "RadarRowMint2222222222222222222222222222222"


async def _token(session: AsyncSession, mint: str, *, age: timedelta) -> object:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - age,
            "block_time": NOW - age,
            "name": "Radar Probe",
            "symbol": "RRP",
        }
    )
    assert token is not None
    return token


async def _entry(session: AsyncSession, token: object, mint: str) -> RadarToken:
    entry = RadarToken(
        token_id=token.id,  # type: ignore[attr-defined]
        mint_address=mint,
        first_detected_at=NOW - timedelta(days=2),
        first_market_cap=Decimal("10000"),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["probe"],
        category="early_momentum",
        current_opportunity_score=Decimal(70),
        current_confidence=Decimal(40),
        current_category="early_momentum",
        current_multiple=Decimal("2.0"),
        peak_multiple=Decimal("3.0"),
        peak_market_cap=Decimal("30000"),
        is_active=True,
        model_version="v1",
    )
    session.add(entry)
    await session.flush()
    return entry


async def _snapshot(
    session: AsyncSession,
    entry: RadarToken,
    mint: str,
    *,
    dimensions: dict[str, object],
    coverage: str = "85",
    at: datetime | None = None,
) -> None:
    session.add(
        RadarSnapshot(
            radar_token_id=entry.id,
            mint_address=mint,
            captured_at=at or NOW,
            opportunity_score=Decimal(70),
            confidence=Decimal(40),
            coverage=Decimal(coverage),
            category="early_momentum",
            dimensions=dimensions,
            reasons=["probe"],
            model_version="v1",
        )
    )
    await session.flush()


async def _market(
    session: AsyncSession, token: object, mint: str, *, at: datetime, price: str
) -> None:
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": at,
            "price_usd": Decimal(price),
            "market_cap": Decimal("124000"),
            "liquidity_usd": Decimal("18000"),
            "volume_24h": Decimal("89000"),
            "dex_name": "pumpswap",
            "trading_status": TradingStatus.TRADING,
            "provider": "test",
        }
    )


async def _live_signal(
    session: AsyncSession,
    token: object,
    mint: str,
    *,
    signal_type: str = FRESH_GRADUATION,
) -> None:
    opportunity = Opportunity(
        token_id=token.id,  # type: ignore[attr-defined]
        mint_address=mint,
        generation=1,
        status=OpportunityStatus.ACTIVE.value,
        stage=OpportunityStage.FRESH_GRADUATION.value,
        detected_at=NOW,
        last_confirmed_at=NOW,
    )
    session.add(opportunity)
    await session.flush()
    session.add(
        OpportunitySignal(
            opportunity_id=opportunity.id,
            mint_address=mint,
            signal_type=signal_type,
            provider_id="fresh_graduation",
            status=SignalStatus.ACTIVE.value,
            severity="major",
            strength=Decimal(100),
            confidence=Decimal(30),
            confirmations=2,
            observations=12,
            detected_at=NOW,
            last_confirmed_at=NOW,
            expires_at=NOW + timedelta(hours=48),
        )
    )
    await session.flush()


def _row(body: dict, mint: str) -> dict:
    found = [item for item in body["items"] if item["mint_address"] == mint]
    assert found, f"{mint} missing from the Radar page"
    return found[0]


class TestTheRowCarriesWhatActingRequires:
    async def test_market_strip_is_the_same_object_the_board_serves(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """One definition, two surfaces. The Radar and the board must never
        disagree about what a token is trading at."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await _market(db_session, token, MINT, at=NOW, price="0.000021")
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        market = row["market"]
        assert Decimal(market["price_usd"]) == Decimal("0.000021")
        assert Decimal(market["liquidity_usd"]) == Decimal("18000")
        assert Decimal(market["volume_24h"]) == Decimal("89000")
        assert market["dex_name"] == "pumpswap"
        assert isinstance(market["market_cap"], str)

    async def test_age_comes_from_the_chain_not_from_detection(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A Radar row detected today may be a token from last week. The age a
        trader needs is the token's, not ours."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert 21_000 < row["age_seconds"] < 22_500  # ~6h, not the 2 days since detection

    async def test_risk_and_evidence_come_from_the_recorded_sweep(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Read from the stored snapshot, not recomputed: the risk shown beside
        a score must be the one the sweep that produced that score measured."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(
            db_session,
            entry,
            MINT,
            coverage="62.5",
            dimensions={
                "risk": {
                    "score": "20",
                    "available": True,
                    "reasons": ["liquidity_thin_for_size"],
                }
            },
        )
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert Decimal(row["risk_score"]) == Decimal("20.00")
        assert row["risk_reasons"] == ["liquidity_thin_for_size"]
        assert Decimal(row["evidence"]) == Decimal("62.5")

    async def test_the_newest_snapshot_wins(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Batched with `DISTINCT ON`; a stale snapshot must not outrank a fresh
        one just because it was inserted first."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(
            db_session,
            entry,
            MINT,
            coverage="10",
            at=NOW - timedelta(hours=3),
            dimensions={"risk": {"score": "5", "available": True, "reasons": []}},
        )
        await _snapshot(
            db_session,
            entry,
            MINT,
            coverage="90",
            at=NOW,
            dimensions={"risk": {"score": "80", "available": True, "reasons": []}},
        )
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert Decimal(row["evidence"]) == Decimal("90")
        assert Decimal(row["risk_score"]) == Decimal("80.00")



    async def test_an_unlabelled_signal_type_renders_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A provider shipping ahead of its label leaves the row without a
        signal, never with `accumulation` printed as though it were English."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await _live_signal(db_session, token, MINT, signal_type="__unlabelled__")
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["signal"] is None


class TestWhyNow:
    async def test_every_row_gets_a_sentence(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Measured on the live board, nine of the top ten carried no signal. A
        why-now derived from signals alone left nine rows silent."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["signal"] is None
        assert row["why_now"]["sentence"].endswith(".")
        assert row["why_now"]["code"]


    async def test_the_sentence_never_names_a_raw_code(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`volume_expanding` is a contract between modules, not a sentence."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await db_session.commit()

        sentence = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)[
            "why_now"
        ]["sentence"]

        assert "_" not in sentence


class TestRiskBand:
    async def test_the_band_is_cut_on_the_server(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Banded beside the number that produced it, so the cuts are auditable
        rather than invented in a component."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(
            db_session,
            entry,
            MINT,
            dimensions={"risk": {"score": "20", "available": True, "reasons": []}},
        )
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["risk_band"] == "extreme"

    async def test_an_unassessed_risk_has_no_band(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`None` is an absence, not a fifth band. On this scale an invented
        zero would read as the most dangerous token on the page."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["risk_band"] is None

    async def test_the_detail_view_carries_the_same_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`/radar/{mint}` extends the list row rather than answering
        differently. Two surfaces disagreeing about one token is the failure
        this shares a renderer to prevent."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(
            db_session,
            entry,
            MINT,
            coverage="62.5",
            dimensions={"risk": {"score": "20", "available": True, "reasons": []}},
        )
        await _market(db_session, token, MINT, at=NOW, price="0.000021")
        await db_session.commit()

        listed = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)
        detail = (await client.get(f"/api/v1/radar/{MINT}")).json()

        assert detail["market"] == listed["market"]
        assert detail["risk_score"] == listed["risk_score"]
        assert detail["evidence"] == listed["evidence"]


class TestAbsence:
    async def test_an_unpriced_token_has_no_market_rather_than_a_zero(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A token nobody has priced is not a token worth $0."""
        token = await _token(db_session, MINT, age=timedelta(minutes=5))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(db_session, entry, MINT, dimensions={})
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["market"] is None

    async def test_an_unassessed_risk_is_absent_rather_than_zero(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`available: false` means the sweep had no source. Rendering that as a
        risk score of 0 would invent the most consequential number on the row —
        and on this model, 0 reads as maximum danger."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        entry = await _entry(db_session, token, MINT)
        await _snapshot(
            db_session,
            entry,
            MINT,
            dimensions={
                "risk": {
                    "score": None,
                    "available": False,
                    "reasons": ["liquidity_data_unavailable"],
                }
            },
        )
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["risk_score"] is None
        # The reason survives even though the score does not: "not checked" is
        # itself worth displaying.
        assert row["risk_reasons"] == ["liquidity_data_unavailable"]

    async def test_a_row_with_no_snapshot_still_renders(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A detection recorded before its first sweep is a real state. It is a
        row without risk or evidence, not a missing row."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        await _entry(db_session, token, MINT)
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), MINT)

        assert row["risk_score"] is None
        assert row["evidence"] is None
        assert row["risk_reasons"] == []
        assert Decimal(row["opportunity_score"]) == Decimal(70)

    async def test_no_live_signal_is_a_complete_row_not_a_hidden_one(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The signal answers "why now", not "is this worth ranking". Most Radar
        entries have nothing live at any moment, and they still rank."""
        token = await _token(db_session, OTHER, age=timedelta(hours=6))
        entry = await _entry(db_session, token, OTHER)
        await _snapshot(db_session, entry, OTHER, dimensions={})
        await db_session.commit()

        row = _row((await client.get("/api/v1/radar?page_size=100")).json(), OTHER)

        assert row["signal"] is None
        assert Decimal(row["opportunity_score"]) == Decimal(70)
