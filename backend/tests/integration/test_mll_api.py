"""`/api/v1/lifecycle-lab` over HTTP: the contract the frontend codes against.

What is pinned here is what a reader of the page would be misled by if it
broke: a switched-off lab answering 404 instead of "disabled", a ratio
arriving as a percent, a client able to date its own link, or a curation
route open to anyone.

(A refused request rolls the test's outer transaction back — see
``tests/conftest.py`` — so each refusal is its own test, or the last request.)
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab import api as lab_api
from app.lifecycle_lab.config import DEFAULT_CONFIG
from app.lifecycle_lab.domain import (
    AgeBucket,
    Arm,
    DivergenceCase,
    ExitReason,
    LifecycleState,
    ResearchMode,
)
from app.lifecycle_lab.exits import ExitSignal
from app.lifecycle_lab.metrics import compute_metrics
from app.lifecycle_lab.portfolio import EntryRequest, PaperTrade, Portfolio
from app.lifecycle_lab.replay import ReplayResult
from app.lifecycle_lab.service import LifecycleLabService
from app.models import User
from app.models.user import UserRole

pytestmark = pytest.mark.integration

API = f"{settings.API_V1_PREFIX}/lifecycle-lab"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def mint() -> str:
    return "".join(random.choice(B58) for _ in range(44))


@pytest.fixture
async def admin_headers(
    auth_headers: dict[str, str], user: User, db_session: AsyncSession
) -> dict[str, str]:
    user.role = UserRole.ADMIN
    await db_session.flush()
    return auth_headers


def _meme_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "slug": f"mll-{uuid.uuid4().hex[:10]}",
        "display_name": "Frog CEO",
        "aliases": [{"alias": "$FROGCEO", "kind": "symbol"}],
    }
    body.update(over)
    return body


def _link_body(mint_address: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mint": mint_address,
        "confidence": "0.9",
        "evidence_url": "https://example.com/proof",
        "evidence_note": "Official account pinned this contract address.",
    }
    body.update(over)
    return body


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


async def test_overview_with_the_flag_off_answers_disabled_not_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", "")
    response = await client.get(f"{API}/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lab_enabled"] is False
    assert body["real_trading"] is False
    assert {s["status"] for s in body["sources"]} == {"disabled"}
    assert body["portfolio"]["starting_capital"] == "1000"
    assert body["portfolio"]["unavailable_reason"] == "forward_start_not_set"
    assert body["experiment"] is None
    for path in ("/health", "/memes", "/experiments"):
        assert (await client.get(f"{API}{path}")).status_code == 200


async def test_health_reports_reddit_and_x_disabled_with_null_counts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "MLL_REDDIT_ENABLED", False)
    monkeypatch.setattr(settings, "MLL_X_ENABLED", False)
    body = (await client.get(f"{API}/health")).json()
    by = {s["source"]: s for s in body["sources"]}
    assert set(by) == {
        "dexscreener",
        "gdelt",
        "geckoterminal",
        "pumpfun_replies",
        "reddit",
        "wikipedia",
        "x",
    }
    for name in ("reddit", "x"):
        assert by[name]["status"] == "disabled"
        assert by[name]["observations_24h"] is None
    assert set(by["gdelt"]) == {
        "source",
        "label",
        "status",
        "reason",
        "last_run_at",
        "data_class",
        "observations_24h",
    }


async def test_unknown_meme_and_run_are_404(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/memes/nope")).status_code == 404
    assert (await client.get(f"{API}/runs/{uuid.uuid4()}")).status_code == 404
    assert (await client.get(f"{API}/runs/not-a-uuid")).status_code == 404


# --------------------------------------------------------------------------
# Admin-only writes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/memes", _meme_body()),
        ("/memes/some-meme/aliases", {"alias": "pepe", "kind": "name"}),
        ("/memes/some-meme/links", _link_body("1" * 44)),
        (
            "/memes/some-meme/backfill",
            {"start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z"},
        ),
    ],
)
async def test_curation_without_a_token_is_401(
    client: AsyncClient, path: str, body: dict[str, Any]
) -> None:
    assert (await client.post(f"{API}{path}", json=body)).status_code == 401


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/memes", _meme_body()),
        ("/memes/some-meme/aliases", {"alias": "pepe", "kind": "name"}),
        ("/memes/some-meme/links", _link_body("1" * 44)),
        (
            "/memes/some-meme/backfill",
            {"start": "2026-09-01T00:00:00Z", "end": "2026-09-02T00:00:00Z"},
        ),
    ],
)
async def test_curation_by_a_non_admin_is_403(
    client: AsyncClient, auth_headers: dict[str, str], path: str, body: dict[str, Any]
) -> None:
    response = await client.post(f"{API}{path}", json=body, headers=auth_headers)
    assert response.status_code == 403


async def test_admin_curation_and_server_dated_links(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The admin creates a meme and links a token; `linked_at` is the server's
    clock. A body that tries to supply its own `linked_at` is refused."""
    body = _meme_body(description="A frog in a suit.")
    created = await client.post(f"{API}/memes", json=body, headers=admin_headers)
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    assert [a["kind"] for a in created.json()["aliases"]] == ["symbol"]

    alias = await client.post(
        f"{API}/memes/{slug}/aliases",
        json={"alias": "frogceo.xyz", "kind": "domain"},
        headers=admin_headers,
    )
    assert alias.status_code == 201 and alias.json()["created"] is True

    m = mint()
    before = datetime.now(UTC)
    link = await client.post(
        f"{API}/memes/{slug}/links",
        json=_link_body(m),
        headers=admin_headers,
    )
    after = datetime.now(UTC)
    assert link.status_code == 201, link.text
    linked_at = datetime.fromisoformat(link.json()["linked_at"].replace("Z", "+00:00"))
    assert before <= linked_at <= after
    assert link.json()["method"] == "manual"
    assert link.json()["confidence"] == "0.9"

    rows = (await client.get(f"{API}/memes")).json()["items"]
    row = next(r for r in rows if r["slug"] == slug)
    assert row["primary_mint"] == m
    assert row["attention"]["mentions_1h"]["value"] is None
    assert row["attention"]["mentions_1h"]["unavailable_reason"]
    assert row["paper_status"] == "none"
    assert row["contains_backfill"] is False

    detail = await client.get(f"{API}/memes/{slug}")
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["meme"]["description"] == "A frog in a suit."
    assert [k["mint"] for k in d["links"]] == [m]
    assert set(d["series"]) == {
        "attention",
        "price",
        "volume",
        "per_source",
        "backfill_before",
    }
    assert d["data_label"] == "authoritative"

    # Last, because a refused request rolls the test transaction back.
    forged = await client.post(
        f"{API}/memes/{slug}/links",
        json={**_link_body(mint()), "linked_at": "2020-01-01T00:00:00Z"},
        headers=admin_headers,
    )
    assert forged.status_code == 422


async def test_a_duplicate_slug_is_409(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    body = _meme_body()
    assert (
        await client.post(f"{API}/memes", json=body, headers=admin_headers)
    ).status_code == 201
    assert (
        await client.post(f"{API}/memes", json=body, headers=admin_headers)
    ).status_code == 409


async def test_backfill_is_queued_not_run_inline(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[tuple[str, datetime, datetime]] = []
    monkeypatch.setattr(lab_api, "_enqueue_backfill", lambda *a: queued.append(a))
    monkeypatch.setattr(settings, "FEATURE_LIFECYCLE_LAB_ENABLED", True)
    slug = (
        await client.post(f"{API}/memes", json=_meme_body(), headers=admin_headers)
    ).json()["slug"]
    response = await client.post(
        f"{API}/memes/{slug}/backfill",
        json={"start": "2026-08-01T00:00:00Z", "end": "2026-08-15T00:00:00Z"},
        headers=admin_headers,
    )
    assert response.status_code == 202, response.text
    assert response.json()["data_class"] == "backfill"
    assert [q[0] for q in queued] == [slug]


# --------------------------------------------------------------------------
# Ratios are fractions
# --------------------------------------------------------------------------


async def test_ratios_are_fractions_not_percents(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paper trade that doubles in price: return is ~0.94 (fees and flat
    slippage included), roi is that pnl over $1,000 (~0.0094). Neither may
    arrive as 94 or 0.94 — the frontend formats fractions."""
    now = datetime.now(UTC).replace(microsecond=0)
    fs = now - timedelta(hours=6)
    monkeypatch.setattr(settings, "MLL_FORWARD_START", fs.isoformat())
    svc = LifecycleLabService(db_session)
    slug = f"mll-{uuid.uuid4().hex[:10]}"
    await svc.create_meme(slug=slug, display_name="Frog CEO", now=fs)
    meme = await svc.get_meme(slug)
    assert meme is not None
    ids = await svc.ensure_baseline_experiment(now)

    book = Portfolio(DEFAULT_CONFIG.portfolio)
    m = mint()
    opened = book.try_open(
        EntryRequest(
            at=now - timedelta(hours=2),
            arm=Arm.BASELINE,
            meme_id=meme.id,
            mint_address=m,
            price=Decimal("0.01"),
            liquidity_usd=None,
            market_cap=None,
            token_age_seconds=None,
            age_bucket=AgeBucket.UNKNOWN,
            lifecycle_state=LifecycleState.ACTIVE,
            divergence_case=DivergenceCase.NONE,
            entry_reason="conditions_met",
        )
    )
    assert isinstance(opened, PaperTrade)
    closed = book.close(
        opened.trade_key,
        ExitSignal(
            reason=ExitReason.TAKE_PROFIT,
            at=now - timedelta(hours=1),
            fill_price=Decimal("0.02"),
            observed_price=Decimal("0.02"),
            trigger_price=Decimal("0.02"),
            liquidity_usd=None,
        ),
    )
    snap = book.snapshot(now - timedelta(hours=1), {})
    metrics = compute_metrics([closed], [snap], starting_capital=Decimal(1000))
    result = ReplayResult(
        mode=ResearchMode.AUTHORITATIVE,
        arm=Arm.BASELINE,
        start=fs,
        end=now,
        hindsight_links=False,
        contains_backfill=False,
        input_fingerprint="f" * 64,
        ticks=72,
        trades=(closed,),
        snapshots=(snap,),
        events=(),
        decisions=(),
        rejection_counts={},
        metrics=metrics,
    )
    run_id = await svc._persist_forward(
        experiment_id=ids[Arm.BASELINE],
        result=result,
        now=now,
        memes=1,
        capped=False,
        duration=0.0,
    )

    overview = (await client.get(f"{API}/overview")).json()
    p = overview["portfolio"]
    assert p["run_id"] == run_id
    roi = Decimal(p["roi"])
    assert metrics.roi is not None and roi == metrics.roi
    assert Decimal("0") < roi < Decimal("0.05")
    assert p["trades"] == 1 and p["sample_label"] == "insufficient (<25)"

    detail = (await client.get(f"{API}/memes/{slug}")).json()
    trade = detail["trades"][0]
    ret = Decimal(trade["return_pct"])
    assert closed.pnl_usd is not None
    expected = closed.pnl_usd / closed.cost_basis
    assert abs(ret - expected) < Decimal("0.000001")
    assert Decimal("0.5") < ret < Decimal("1")
    assert trade["exit_reason_text"] == "take-profit level reached"
    assert trade["evidence_timeline"][-1]["detail"].startswith("Paper exit")
    kinds = {mk["kind"] for mk in detail["markers"]}
    assert {"paper_entry", "paper_exit"} <= kinds

    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert Decimal(run["trades"][0]["return_pct"]) == ret
    assert abs(Decimal(run["metrics"]["return_percentiles"]["max"]) - ret) < Decimal(
        "0.000001"
    )
    assert Decimal(run["metrics"]["roi"]) == roi


# --------------------------------------------------------------------------
# Link evidence
# --------------------------------------------------------------------------


async def _new_slug(client: AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post(f"{API}/memes", json=_meme_body(), headers=headers)
    return str(created.json()["slug"])


async def test_a_link_stores_its_evidence_as_an_audit_trail(
    client: AsyncClient, admin_headers: dict[str, str], user: User
) -> None:
    slug = await _new_slug(client, admin_headers)
    m = mint()
    response = await client.post(
        f"{API}/memes/{slug}/links",
        json=_link_body(m, method="website_match", evidence_note=None),
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["method"] == "website_match"
    audit = (await client.get(f"{API}/memes/{slug}/quality")).json()
    (link,) = audit["links"]
    assert link["method"] == "website_match"
    assert link["evidence"] == {
        "url": "https://example.com/proof",
        "note": None,
        "submitted_by": str(user.id),
    }
    assert link["linked_by"] == f"manual:{user.id}"


async def test_method_defaults_to_manual_and_keeps_the_note(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    slug = await _new_slug(client, admin_headers)
    response = await client.post(
        f"{API}/memes/{slug}/links", json=_link_body(mint()), headers=admin_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["method"] == "manual"
    audit = (await client.get(f"{API}/memes/{slug}/quality")).json()
    assert (
        audit["links"][0]["evidence"]["note"]
        == "Official account pinned this contract address."
    )


@pytest.mark.parametrize("method", ["exact_name", "exact_symbol", "alias_match", "telepathy"])
async def test_a_text_match_is_never_sufficient_evidence_for_a_curated_link(
    client: AsyncClient, admin_headers: dict[str, str], method: str
) -> None:
    slug = await _new_slug(client, admin_headers)
    response = await client.post(
        f"{API}/memes/{slug}/links",
        json=_link_body(mint(), method=method),
        headers=admin_headers,
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "over",
    [
        {"evidence_url": None},
        {"evidence_url": "not a url"},
        {"evidence_url": "ftp://example.com/x"},
        {"evidence_note": None},
        {"evidence_note": "   "},
    ],
)
async def test_a_link_without_evidence_is_refused(
    client: AsyncClient, admin_headers: dict[str, str], over: dict[str, Any]
) -> None:
    """The URL is always required; a manual link also needs the note."""
    slug = await _new_slug(client, admin_headers)
    body = _link_body(mint(), **over)
    if over.get("evidence_url", "x") is None:
        del body["evidence_url"]
    response = await client.post(f"{API}/memes/{slug}/links", json=body, headers=admin_headers)
    assert response.status_code == 422, response.text
