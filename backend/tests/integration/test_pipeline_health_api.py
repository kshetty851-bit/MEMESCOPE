"""`GET /api/v1/health/pipeline` against real rows.

The point of this endpoint is that it reads what the pipeline *wrote*, so
these tests write rows and assert the verdict rather than mocking the service.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.models.market import EnrichmentStatus
from app.models.radar import RadarToken
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
PIPELINE = f"{API}/health/pipeline"

MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"


async def _seed(session: AsyncSession, *, discovered_at: datetime, captured_at: datetime):
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": MINT,
            "signature": "sig-health",
            "slot": 1,
            "name": "Health Probe",
            "symbol": "HEALTH",
            "discovered_at": discovered_at,
        }
    )
    assert token is not None

    await MarketSnapshotRepository(session).add_many(
        [
            {
                "token_id": token.id,
                "mint_address": MINT,
                "captured_at": captured_at,
                "price_usd": Decimal("0.0001"),
                "liquidity_usd": Decimal("1000"),
                "provider": "test",
            }
        ]
    )
    await EnrichmentStateRepository(session).ensure_state(
        token_id=token.id,
        mint_address=MINT,
        next_refresh_at=captured_at,
    )
    await session.flush()
    return token


@pytest.fixture(autouse=True)
async def _isolated_pipeline(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """Give every test a known starting point.

    Two things leak otherwise. The scanner state lives in Redis rather than in
    the rolled-back transaction, so it survives into the next test — cleared on
    setup rather than teardown because the `client` fixture closes Redis first.

    Feature flags come from the container environment, where the whole pipeline
    is switched on, which would make `overall` depend on how the developer's
    stack happens to be configured. Every stage starts disabled here and each
    test enables exactly what it asserts on.
    """
    await get_redis().delete(settings.scanner_state_key)
    for flag in (
        "FEATURE_SCANNER_ENABLED",
        "FEATURE_ENRICHMENT_ENABLED",
        "FEATURE_AI_SCORING_ENABLED",
        "FEATURE_RADAR_ENABLED",
    ):
        monkeypatch.setattr(settings, flag, False)
    yield


class TestStageVerdicts:
    async def test_fresh_pipeline_reports_healthy_stages(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)

        body = (await client.get(PIPELINE)).json()

        assert body["scanner"]["status"] == "healthy"
        assert body["market_enrichment"]["status"] == "healthy"
        assert body["scanner"]["minutes_since_last_token"] == pytest.approx(0.0, abs=1.0)

    async def test_stale_discovery_reports_scanner_down(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The exact production failure: enrichment alive, discovery dead.

        Four days of this went unnoticed because no surface distinguished the
        two. Here it must.
        """
        now = datetime.now(UTC)
        await _seed(
            db_session,
            discovered_at=now - timedelta(days=4),
            captured_at=now,
        )

        response = await client.get(PIPELINE)
        body = response.json()

        assert body["scanner"]["status"] == "down"
        assert body["market_enrichment"]["status"] == "healthy"
        assert body["scanner"]["minutes_since_last_token"] > 60

    async def test_degraded_sits_between_the_thresholds(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        stale = settings.HEALTH_SCANNER_DEGRADED_MINUTES + 1
        await _seed(
            db_session,
            discovered_at=now - timedelta(minutes=stale),
            captured_at=now,
        )

        body = (await client.get(PIPELINE)).json()
        assert body["scanner"]["status"] == "degraded"

    async def test_reports_enrichment_backlog_and_dead_letters(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        token = await _seed(db_session, discovered_at=now, captured_at=now)

        states = EnrichmentStateRepository(db_session)
        state = await states.get_by_mint(MINT)
        assert state is not None
        # Due in the past: this is what "queue depth" counts.
        state.next_refresh_at = now - timedelta(minutes=5)
        await db_session.flush()

        body = (await client.get(PIPELINE)).json()
        assert body["market_enrichment"]["queue_depth"] >= 1
        assert body["market_enrichment"]["dead_lettered"] == 0

        state.status = EnrichmentStatus.DEAD_LETTER
        await db_session.flush()

        body = (await client.get(PIPELINE)).json()
        assert body["market_enrichment"]["dead_lettered"] == 1
        # A parked token is not backlog — it will never be claimed.
        assert body["market_enrichment"]["queue_depth"] == 0
        assert token is not None

    async def test_scoring_pending_counts_only_scorable_tokens(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A token with no snapshot is not a scoring backlog.

        Counting it would report a permanent queue that no amount of working
        scoring could ever clear.
        """
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)
        await TokenRepository(db_session).insert_if_absent(
            {
                "mint_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                "signature": "sig-nosnap",
                "slot": 2,
                "discovered_at": now,
            }
        )
        await db_session.flush()

        body = (await client.get(PIPELINE)).json()
        # The seeded token has a snapshot and no score; the other has neither.
        assert body["scoring"]["pending"] == 1

    async def test_radar_cycle_comes_from_last_evaluated_not_snapshots(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A quiet market writes no radar snapshots but still sweeps.

        Reading `radar_snapshots` would report a working Radar as dead.
        """
        now = datetime.now(UTC)
        token = await _seed(db_session, discovered_at=now, captured_at=now)
        db_session.add(
            RadarToken(
                token_id=token.id,
                mint_address=MINT,
                first_detected_at=now - timedelta(days=1),
                last_evaluated_at=now,
                first_opportunity_score=Decimal("50"),
                first_confidence=Decimal("80"),
                category="breakout",
                current_opportunity_score=Decimal("50"),
                current_confidence=Decimal("80"),
                current_category="breakout",
                model_version="v1",
            )
        )
        await db_session.flush()

        body = (await client.get(PIPELINE)).json()
        assert body["radar"]["status"] == "healthy"
        assert body["radar"]["tracked_tokens"] == 1


class TestScannerState:
    async def test_a_disconnected_scanner_degrades_even_with_fresh_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Staleness alone cannot see a scanner that just lost its connection.

        A token discovered a minute ago says nothing about whether the socket
        is still up, so the scanner's own report has to be able to make the
        verdict worse.
        """
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)
        await get_redis().set(
            settings.scanner_state_key,
            json.dumps(
                {"connected": False, "reconnect_attempts": 1, "failure_reason": "HTTP 429"}
            ),
        )

        body = (await client.get(PIPELINE)).json()
        assert body["scanner"]["status"] == "degraded"
        assert body["scanner"]["failure_reason"] == "HTTP 429"
        assert body["scanner"]["reconnect_attempts"] == 1

    async def test_persistent_reconnect_failure_reports_down(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)
        await get_redis().set(
            settings.scanner_state_key,
            json.dumps(
                {
                    "connected": False,
                    "reconnect_attempts": settings.SCANNER_RECONNECT_ERROR_ATTEMPTS,
                    "failure_reason": "HTTP 429",
                }
            ),
        )

        body = (await client.get(PIPELINE)).json()
        assert body["scanner"]["status"] == "down"

    async def test_a_connected_scanner_never_improves_a_stale_verdict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Connected is not healthy. It was connected for four days.

        Only produced rows can make the scanner healthy.
        """
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now - timedelta(days=4), captured_at=now)
        await get_redis().set(
            settings.scanner_state_key,
            json.dumps({"connected": True, "reconnect_attempts": 0}),
        )

        body = (await client.get(PIPELINE)).json()
        assert body["scanner"]["status"] == "down"

    async def test_garbage_state_does_not_break_the_endpoint(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)
        await get_redis().set(settings.scanner_state_key, "}{ not json")

        response = await client.get(PIPELINE)
        assert response.status_code == 200
        assert response.json()["scanner"]["reconnect_attempts"] is None


class TestRollUp:
    async def test_disabled_stages_are_excluded_from_overall(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A deployment that runs no scanner is not permanently down."""
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now - timedelta(days=4), captured_at=now)

        monkeypatch.setattr(settings, "FEATURE_SCANNER_ENABLED", False)
        monkeypatch.setattr(settings, "FEATURE_ENRICHMENT_ENABLED", True)
        monkeypatch.setattr(settings, "FEATURE_AI_SCORING_ENABLED", False)
        monkeypatch.setattr(settings, "FEATURE_RADAR_ENABLED", False)

        response = await client.get(PIPELINE)
        assert response.status_code == 200
        body = response.json()
        # Still reported honestly on its own...
        assert body["scanner"]["status"] == "down"
        # ...but not held against a deployment that never enabled it.
        assert body["overall"] == "healthy"

    async def test_a_down_enabled_stage_returns_503(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """So an external monitor can page without parsing the body."""
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now - timedelta(days=4), captured_at=now)
        monkeypatch.setattr(settings, "FEATURE_SCANNER_ENABLED", True)

        response = await client.get(PIPELINE)
        assert response.status_code == 503
        assert response.json()["overall"] == "down"

    async def test_degraded_still_returns_200(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Degraded is a warning. Paging on it trains the reader to ignore it."""
        now = datetime.now(UTC)
        stale = settings.HEALTH_SCANNER_DEGRADED_MINUTES + 1
        await _seed(db_session, discovered_at=now - timedelta(minutes=stale), captured_at=now)
        monkeypatch.setattr(settings, "FEATURE_SCANNER_ENABLED", True)
        monkeypatch.setattr(settings, "FEATURE_ENRICHMENT_ENABLED", True)
        monkeypatch.setattr(settings, "FEATURE_AI_SCORING_ENABLED", False)
        monkeypatch.setattr(settings, "FEATURE_RADAR_ENABLED", False)

        response = await client.get(PIPELINE)
        assert response.status_code == 200
        assert response.json()["overall"] == "degraded"


class TestContract:
    async def test_response_carries_every_documented_field(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        now = datetime.now(UTC)
        await _seed(db_session, discovered_at=now, captured_at=now)

        body: dict[str, Any] = (await client.get(PIPELINE)).json()

        assert set(body) >= {
            "scanner",
            "market_enrichment",
            "scoring",
            "radar",
            "overall",
        }
        assert set(body["scanner"]) >= {
            "status",
            "last_discovery",
            "minutes_since_last_token",
        }
        assert set(body["market_enrichment"]) >= {
            "status",
            "last_snapshot",
            "queue_depth",
        }
        assert set(body["scoring"]) >= {"status", "last_score", "pending"}
        assert set(body["radar"]) >= {"status", "last_cycle", "tracked_tokens"}

    async def test_an_empty_pipeline_reports_down_not_healthy(
        self, client: AsyncClient
    ) -> None:
        """Nothing written yet is not proof of health."""
        body = (await client.get(PIPELINE)).json()

        assert body["scanner"]["status"] == "down"
        assert body["scanner"]["last_discovery"] is None
        assert body["scanner"]["minutes_since_last_token"] is None
