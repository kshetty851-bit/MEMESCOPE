"""Scoring API.

Drives the ASGI app in-process against a real database. The scores under test
are produced by the real engine through `TokenScoringService`, not hand-written,
so these also pin down that the persisted shape survives the round trip to JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TradingStatus
from app.repositories.market import MarketSnapshotRepository
from app.repositories.score import ScoreHistoryRepository
from app.repositories.token import TokenRepository
from app.services.scoring.service import TokenScoringService

pytestmark = pytest.mark.integration

BASE = f"{settings.API_V1_PREFIX}/scores"
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

# Real base58, so the path pattern accepts it.
MINT_A = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
MINT_B = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hs"
MINT_C = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2ht"
UNKNOWN_MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hu"


async def _scored_token(
    session: AsyncSession,
    mint: str,
    *,
    liquidity: str = "50000",
    count: int = 6,
    age_hours: int = 3,
    now: datetime = NOW,
    score_at: datetime | None = None,
    metadata_status: str = "resolved",
    **snapshot_overrides: Any,
) -> Any:
    """A discovered token with market history, scored by the real engine."""
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": now - timedelta(hours=age_hours),
            "block_time": now - timedelta(hours=age_hours),
            "metadata_status": metadata_status,
        }
    )
    assert token is not None

    snapshots = MarketSnapshotRepository(session)
    for index in range(count):
        values: dict[str, Any] = {
            "token_id": token.id,
            "mint_address": mint,
            "captured_at": now - timedelta(seconds=300 * index),
            "price_usd": Decimal("0.001"),
            "liquidity_usd": Decimal(liquidity),
            "market_cap": Decimal("500000"),
            "fully_diluted_valuation": Decimal("550000"),
            "volume_24h": Decimal("20000"),
            "volume_1h": Decimal("2000"),
            "volume_5m": Decimal("200"),
            "buy_count_24h": 300,
            "sell_count_24h": 200,
            "trading_status": TradingStatus.TRADING,
            "provider": "dexscreener",
        }
        values.update(snapshot_overrides)
        await snapshots.add_snapshot(values)

    await TokenScoringService(session).score_mints([mint], now=score_at or now)
    await session.flush()
    return token


# --- GET /scores/{mint} -------------------------------------------------------


async def test_current_score_is_returned_with_its_breakdown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A)

    response = await client.get(f"{BASE}/{MINT_A}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scored"
    assert body["mint_address"] == MINT_A

    score = body["score"]
    assert Decimal(score["score"]) > 0
    assert score["model_version"] == "v1"
    assert score["grade"] in {"critical", "weak", "watch", "strong", "high_conviction"}
    assert len(score["components"]) == 9
    assert score["reasons"]


async def test_decimals_are_serialised_as_strings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A JSON float would round exactly the numbers the waterfall reconciles."""
    await _scored_token(db_session, MINT_A)

    score = (await client.get(f"{BASE}/{MINT_A}")).json()["score"]

    assert isinstance(score["score"], str)
    assert isinstance(score["evidence"]["confidence"], str)
    assert isinstance(score["components"][0]["contribution"], str)


async def test_the_waterfall_reconciles_over_the_wire(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """What the client renders must add up, not just what the engine computed."""
    await _scored_token(db_session, MINT_A)

    score = (await client.get(f"{BASE}/{MINT_A}")).json()["score"]
    contributions = sum(Decimal(entry["contribution"]) for entry in score["components"])

    assert contributions == Decimal(score["opportunity_raw"])
    assert contributions - Decimal(score["risk"]["deduction"]) == Decimal(score["score"])


async def test_confidence_is_derived_at_read_time(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Evidence is stored; confidence is not. A stale row must read as stale.

    The score is written against snapshots from well in the past, so by the time
    the request is served freshness has decayed and confidence sits below the
    stored evidence.
    """
    await _scored_token(db_session, MINT_A)

    evidence = (await client.get(f"{BASE}/{MINT_A}")).json()["score"]["evidence"]

    assert Decimal(evidence["evidence"]) == Decimal("65.00")
    assert Decimal(evidence["freshness"]) == 0
    assert Decimal(evidence["confidence"]) == 0


async def test_reasons_carry_human_explanations(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Codes for branching, prose for rendering - both, from one source."""
    await _scored_token(db_session, MINT_A)

    reasons = (await client.get(f"{BASE}/{MINT_A}")).json()["score"]["reasons"]

    first = reasons[0]
    assert first["code"].isupper()
    assert first["severity"] in {"info", "positive", "caution", "critical"}
    assert first["message"].endswith(".")
    assert first["agent"]


async def _unscored_token(session: AsyncSession, mint: str) -> None:
    await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-unscored-{mint[-4:]}",
            "slot": 1,
            "discovered_at": NOW,
        }
    )
    await session.flush()


async def test_a_known_but_unscored_token_is_not_an_error(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence is meaningful state the client should render.

    The flag takes precedence: when the engine is switched off, "no score" is
    explained by that rather than by anything about the token. Pinned here
    rather than inherited from the environment, so the assertion does not depend
    on how the deployment happens to be configured.
    """
    monkeypatch.setattr(
        "app.services.scoring.query_service.settings.FEATURE_AI_SCORING_ENABLED", False
    )
    await _unscored_token(db_session, MINT_B)

    response = await client.get(f"{BASE}/{MINT_B}")

    assert response.status_code == 200
    body = response.json()
    assert body["score"] is None
    assert body["status"] == "scoring_disabled"


async def test_an_unscored_token_awaiting_market_data_says_so(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the engine on, the status distinguishes "no pool yet" from "not run"."""
    monkeypatch.setattr(
        "app.services.scoring.query_service.settings.FEATURE_AI_SCORING_ENABLED", True
    )
    await _unscored_token(db_session, MINT_B)

    body = (await client.get(f"{BASE}/{MINT_B}")).json()

    assert body["score"] is None
    assert body["status"] == "awaiting_market"


async def test_a_token_with_market_data_but_no_score_reads_as_not_scored(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.scoring.query_service.settings.FEATURE_AI_SCORING_ENABLED", True
    )
    await _unscored_token(db_session, MINT_C)
    token = await TokenRepository(db_session).get_by_mint(MINT_C)
    assert token is not None
    await MarketSnapshotRepository(db_session).add_snapshot(
        {
            "token_id": token.id,
            "mint_address": MINT_C,
            "captured_at": NOW,
            "price_usd": Decimal("0.001"),
            "trading_status": TradingStatus.TRADING,
            "provider": "dexscreener",
        }
    )
    await db_session.flush()

    body = (await client.get(f"{BASE}/{MINT_C}")).json()

    assert body["status"] == "not_scored"


async def test_an_unrecognised_reason_code_does_not_break_the_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Codes are append-only by contract, but history outliving one is a bad
    reason to fail a request. The code passes through rather than raising."""
    await _scored_token(db_session, MINT_A)
    latest = await ScoreHistoryRepository(db_session).latest_for_mint(MINT_A)
    assert latest is not None
    latest.reasons = ["A_CODE_FROM_A_FUTURE_MODEL"]
    await db_session.flush()

    response = await client.get(f"{BASE}/{MINT_A}")

    assert response.status_code == 200
    reason = response.json()["score"]["reasons"][0]
    assert reason["code"] == "A_CODE_FROM_A_FUTURE_MODEL"
    assert reason["severity"] == "info"
    assert reason["message"] == "A_CODE_FROM_A_FUTURE_MODEL"


async def test_an_undiscovered_mint_is_a_404(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/{UNKNOWN_MINT}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_malformed_mint_is_rejected_before_the_database(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{BASE}/not-a-valid-mint")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- GET /scores/{mint}/history ----------------------------------------------


async def test_history_is_returned_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A)
    service = TokenScoringService(db_session)
    for minutes in (10, 20, 30):
        await service.score_mints([MINT_A], now=NOW + timedelta(minutes=minutes))
    await db_session.flush()

    body = (await client.get(f"{BASE}/{MINT_A}/history")).json()

    assert body["total"] >= 2
    stamps = [entry["evaluated_at"] for entry in body["items"]]
    assert stamps == sorted(stamps, reverse=True)


async def test_history_entries_expose_the_trigger_and_delta(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A)

    body = (await client.get(f"{BASE}/{MINT_A}/history")).json()

    first = body["items"][0]
    assert first["trigger"] == "first"
    assert first["delta"] is None
    assert first["reasons"]


async def test_history_paginates(client: AsyncClient, db_session: AsyncSession) -> None:
    await _scored_token(db_session, MINT_A)
    service = TokenScoringService(db_session)
    for minutes in (10, 20, 30):
        await service.score_mints([MINT_A], now=NOW + timedelta(minutes=minutes))
    await db_session.flush()

    page = (await client.get(f"{BASE}/{MINT_A}/history?page=1&page_size=1")).json()

    assert len(page["items"]) == 1
    assert page["page_size"] == 1
    assert page["pages"] == page["total"]


async def test_history_of_a_token_with_none_is_an_empty_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await TokenRepository(db_session).insert_if_absent(
        {
            "mint_address": MINT_B,
            "signature": "sig-empty",
            "slot": 1,
            "discovered_at": NOW,
        }
    )
    await db_session.flush()

    body = (await client.get(f"{BASE}/{MINT_B}/history")).json()

    assert body["items"] == []
    assert body["total"] == 0
    assert body["pages"] == 0


async def test_history_time_bounds_are_validated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A)

    response = await client.get(
        f"{BASE}/{MINT_A}/history",
        params={"since": "2026-07-28T00:00:00Z", "until": "2026-07-27T00:00:00Z"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_history_for_an_unknown_mint_is_a_404(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/{UNKNOWN_MINT}/history")
    assert response.status_code == 404


# --- GET /scores/top ----------------------------------------------------------


async def test_top_ranks_by_score_descending(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A, liquidity="500000")
    await _scored_token(db_session, MINT_B, liquidity="800")

    body = (await client.get(f"{BASE}/top")).json()

    scores = [Decimal(entry["score"]["score"]) for entry in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert body["items"][0]["token"]["mint_address"] == MINT_A


async def test_top_entries_carry_token_identity(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """So a feed can render a row without a follow-up request per token."""
    await _scored_token(db_session, MINT_A)

    entry = (await client.get(f"{BASE}/top")).json()["items"][0]

    assert entry["token"]["mint_address"] == MINT_A
    assert "name" in entry["token"]


async def test_top_omits_the_breakdown_from_list_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Kilobytes per token; a ranking is scanned, not read in detail."""
    await _scored_token(db_session, MINT_A)

    entry = (await client.get(f"{BASE}/top")).json()["items"][0]

    assert entry["score"]["components"] == []
    assert entry["score"]["reasons"] == []


async def test_top_paginates(client: AsyncClient, db_session: AsyncSession) -> None:
    await _scored_token(db_session, MINT_A, liquidity="500000")
    await _scored_token(db_session, MINT_B, liquidity="300000")
    await _scored_token(db_session, MINT_C, liquidity="100000")

    first = (await client.get(f"{BASE}/top?page=1&page_size=2")).json()
    second = (await client.get(f"{BASE}/top?page=2&page_size=2")).json()

    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert first["total"] == 3
    assert first["pages"] == 2

    seen = {entry["token"]["mint_address"] for entry in first["items"] + second["items"]}
    assert len(seen) == 3


async def test_top_sorts_ascending_when_asked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A, liquidity="500000")
    await _scored_token(db_session, MINT_B, liquidity="800")

    body = (await client.get(f"{BASE}/top?sort=score&order=asc")).json()

    scores = [Decimal(entry["score"]["score"]) for entry in body["items"]]
    assert scores == sorted(scores)


@pytest.mark.parametrize(
    "sort_field", ["score", "evidence", "market_risk", "opportunity_raw", "evaluated_at"]
)
async def test_every_declared_sort_field_works(
    client: AsyncClient, db_session: AsyncSession, sort_field: str
) -> None:
    await _scored_token(db_session, MINT_A)

    response = await client.get(f"{BASE}/top?sort={sort_field}")

    assert response.status_code == 200, response.text
    assert response.json()["applied_filters"]["sort"] == sort_field


async def test_min_score_filters_in_the_database(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _scored_token(db_session, MINT_A, liquidity="500000")
    await _scored_token(db_session, MINT_B, liquidity="800")

    body = (await client.get(f"{BASE}/top?min_score=60")).json()

    assert all(Decimal(e["score"]["score"]) >= 60 for e in body["items"])
    assert body["total"] < body["candidate_total"]


async def test_min_confidence_filters_on_evidence(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Documented behaviour: evidence is an upper bound on confidence.

    v1 evidence tops out at 65, so a threshold above that empties the page while
    the candidate count shows the rows are there.
    """
    await _scored_token(db_session, MINT_A)

    body = (await client.get(f"{BASE}/top?min_confidence=70")).json()

    assert body["items"] == []
    assert body["candidate_total"] >= 1
    assert body["applied_filters"]["min_confidence"] == "70"


async def test_max_risk_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    """Unresolved metadata earns a risk penalty, so this pair straddles any bound."""
    await _scored_token(db_session, MINT_A)
    await _scored_token(db_session, MINT_B, metadata_status="pending")

    unrestricted = (await client.get(f"{BASE}/top")).json()
    filtered = (await client.get(f"{BASE}/top?max_risk=0")).json()

    assert unrestricted["total"] == 2
    assert filtered["total"] == 1
    assert all(Decimal(e["score"]["risk"]["market_risk"]) <= 0 for e in filtered["items"])


async def test_grade_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    await _scored_token(db_session, MINT_A, liquidity="500000")

    graded = (await client.get(f"{BASE}/{MINT_A}")).json()["score"]["grade"]
    body = (await client.get(f"{BASE}/top?grade={graded}")).json()

    assert body["items"]
    assert all(entry["score"]["grade"] == graded for entry in body["items"])


async def test_trigger_filters_on_the_latest_history_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`trigger` lives on history, so this asks what earned the newest entry."""
    await _scored_token(db_session, MINT_A)

    matching = (await client.get(f"{BASE}/top?trigger=first")).json()
    other = (await client.get(f"{BASE}/top?trigger=heartbeat")).json()

    assert MINT_A in {e["token"]["mint_address"] for e in matching["items"]}
    assert MINT_A not in {e["token"]["mint_address"] for e in other["items"]}


async def test_model_version_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    await _scored_token(db_session, MINT_A)

    current = (await client.get(f"{BASE}/top?model_version=v1")).json()
    absent = (await client.get(f"{BASE}/top?model_version=v99")).json()

    assert current["items"]
    assert absent["items"] == []


async def test_vetoed_tokens_are_excluded_by_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A veto means the score was capped outright; it is not an opportunity."""
    await _scored_token(db_session, MINT_A, trading_status=TradingStatus.INACTIVE)

    default = (await client.get(f"{BASE}/top")).json()
    included = (await client.get(f"{BASE}/top?include_vetoed=true")).json()

    assert default["items"] == []
    assert MINT_A in {e["token"]["mint_address"] for e in included["items"]}
    assert included["items"][0]["score"]["risk"]["has_veto"] is True


async def test_elite_only_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    """Unreachable in v1 by design, so this must return nothing."""
    await _scored_token(db_session, MINT_A, liquidity="900000")

    body = (await client.get(f"{BASE}/top?elite_only=true")).json()

    assert body["items"] == []
    assert body["candidate_total"] >= 1


async def test_applied_filters_are_echoed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An empty page caused by a filter must be distinguishable from an empty table."""
    await _scored_token(db_session, MINT_A)

    body = (await client.get(f"{BASE}/top?min_score=99&order=asc")).json()

    applied = body["applied_filters"]
    assert applied["min_score"] == "99"
    assert applied["order"] == "asc"
    assert body["candidate_total"] >= 1


async def test_top_of_an_empty_table(client: AsyncClient) -> None:
    body = (await client.get(f"{BASE}/top")).json()

    assert body["items"] == []
    assert body["total"] == 0
    assert body["candidate_total"] == 0
    assert body["pages"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page=-1",
        "page_size=0",
        "page_size=101",
        "sort=nonsense",
        "order=sideways",
        "min_score=-1",
        "min_score=101",
        "min_confidence=101",
        "max_risk=-5",
        "grade=legendary",
        "trigger=whenever",
    ],
)
async def test_invalid_query_parameters_are_rejected(client: AsyncClient, query: str) -> None:
    response = await client.get(f"{BASE}/top?{query}")

    assert response.status_code == 422, query
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["errors"]


# --- GET /scores/model --------------------------------------------------------


async def test_model_metadata_is_served(client: AsyncClient) -> None:
    body = (await client.get(f"{BASE}/model")).json()

    assert body["version"] == "v1"
    assert len(body["components"]) == 9
    assert Decimal(body["declared_weight_total"]) == 1
    assert Decimal(body["available_weight_total"]) == Decimal("0.65")


async def test_model_metadata_marks_undelivered_components(
    client: AsyncClient,
) -> None:
    """Their declared weight is what caps evidence, so it must be visible."""
    body = (await client.get(f"{BASE}/model")).json()

    unavailable = {c["id"] for c in body["components"] if not c["available"]}
    assert unavailable == {
        "contract_safety",
        "holder_distribution",
        "smart_money",
        "narrative",
    }


async def test_model_metadata_reports_elite_as_unreachable(
    client: AsyncClient,
) -> None:
    """65 evidence against a 70 gate. Gold stays dark, and the API says so."""
    body = (await client.get(f"{BASE}/model")).json()

    assert body["elite_gate"]["reachable"] is False
    assert Decimal(body["elite_gate"]["min_evidence"]) == 70


async def test_model_metadata_exposes_contiguous_grade_bands(
    client: AsyncClient,
) -> None:
    body = (await client.get(f"{BASE}/model")).json()

    bands = body["grade_bands"]
    assert len(bands) == 5
    assert bands[-1]["upper_bound"] is None
    for lower, upper in pairwise(bands):
        assert lower["upper_bound"] == upper["lower_bound"]


# --- OpenAPI ------------------------------------------------------------------


async def test_every_endpoint_is_documented(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    expected = {
        f"{settings.API_V1_PREFIX}/scores/top",
        f"{settings.API_V1_PREFIX}/scores/model",
        f"{settings.API_V1_PREFIX}/scores/{{mint}}",
        f"{settings.API_V1_PREFIX}/scores/{{mint}}/history",
    }
    assert expected <= set(schema["paths"])

    for path in expected:
        operation = schema["paths"][path]["get"]
        assert operation["summary"]
        assert operation["description"]
        assert operation["tags"] == ["scores"]
        assert "200" in operation["responses"]


async def test_error_responses_are_documented(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"][f"{settings.API_V1_PREFIX}/scores/{{mint}}"]["get"]

    assert "404" in operation["responses"]
    assert "422" in operation["responses"]


async def test_query_parameters_are_documented(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"][f"{settings.API_V1_PREFIX}/scores/top"]["get"]

    documented = {param["name"] for param in operation["parameters"]}
    assert {
        "page",
        "page_size",
        "sort",
        "order",
        "min_score",
        "min_confidence",
        "grade",
        "trigger",
        "model_version",
    } <= documented

    described = [p for p in operation["parameters"] if p["name"] == "min_confidence"]
    assert "evidence" in described[0]["schema"].get("description", "").lower()
