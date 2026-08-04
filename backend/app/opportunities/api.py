"""`GET /api/v1/opportunities` — the live board, and one opportunity in full.

Its own namespace rather than reshaping `/radar`. Sprint 4 gave opportunities
their own tables, so the Radar's read model no longer holds them, and `/radar`
has an established response shape driven by `radar_tokens` and a different
scoring model. Overloading it would change existing product behaviour; a new
namespace is additive and breaks nothing.

Gated on `FEATURE_OPPORTUNITY_ENGINE_ENABLED`. While the engine is off the
board is empty rather than absent — a 404 would read as "this platform has no
such feature", and the honest answer is "it is not switched on here".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.market import TokenMarketSnapshot
from app.models.opportunity import Opportunity, OpportunitySignal
from app.opportunities.analytics import ProviderTotals, summarise
from app.opportunities.explain import explain
from app.opportunities.models import OpportunityStage, SignalType
from app.opportunities.outcomes import PREDICTIVE_SIGNALS
from app.opportunities.providers.registry import registry as provider_registry
from app.opportunities.repository import OpportunityRepository
from app.opportunities.schemas import (
    EvidenceOut,
    ExplanationOut,
    MarketOut,
    OpportunityBoard,
    OpportunityOut,
    ProviderAnalyticsOut,
    ProviderAnalyticsReport,
    SignalOut,
)
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityBoard, summary="The live opportunity board")
async def list_opportunities(
    session: DbSession,
    signal_type: Annotated[str | None, Query()] = None,
    stage: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> OpportunityBoard:
    """Opportunities that are live *right now*.

    An empty board means nothing changed. That is information, not a fault, and
    it must not be resolved by relaxing admission — `/health/pipeline` is where
    a reader distinguishes "nothing happened" from "the pipeline stopped".
    """
    now = datetime.now(UTC)
    filters: dict[str, object] = {"signal_type": signal_type, "stage": stage}

    if not settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED:
        return OpportunityBoard(
            items=[],
            page=page,
            page_size=page_size,
            has_more=False,
            applied_filters={**filters, "engine_enabled": False},
            observed_at=now,
        )

    # Validated here rather than by an enum in the signature: an unknown value
    # should return an empty page with the filter echoed, not a 422 that reads
    # as though the board itself is broken.
    resolved_signal = _valid_signal_type(signal_type)
    resolved_stage = _valid_stage(stage)

    repository = OpportunityRepository(session)
    offset = (page - 1) * page_size

    rows = await repository.live_board(
        now=now,
        limit=page_size,
        offset=offset,
        signal_type=resolved_signal,
        stage=resolved_stage,
    )
    signals = await repository.live_signals_for([row.id for row in rows], now=now)
    context = await _context_for(session, [row.mint_address for row in rows], now=now)
    has_more = await repository.board_has_more(
        now=now,
        offset=offset,
        page_size=page_size,
        signal_type=resolved_signal,
        stage=resolved_stage,
    )

    return OpportunityBoard(
        items=[
            _to_card(row, signals.get(row.id, []), context=context, now=now)
            for row in rows
        ],
        page=page,
        page_size=page_size,
        has_more=has_more,
        applied_filters={**filters, "engine_enabled": True},
        observed_at=now,
    )


@router.get(
    "/providers",
    response_model=ProviderAnalyticsReport,
    summary="Provider performance (internal)",
)
async def provider_analytics(session: DbSession) -> ProviderAnalyticsReport:
    """How each registered provider has actually performed.

    Declared before `/{mint}`: FastAPI matches in registration order, and a
    literal path registered after a parameterised one is unreachable — the
    request would arrive as a token whose mint is "providers".

    Internal. Nothing here is a claim about a token, so it is not part of the
    board and no frontend consumes it; it exists so a provider that stopped
    producing, or never produced, is visible without reading the database.
    """
    totals = await OpportunityRepository(session).provider_totals(
        required_confirmations=settings.OPPORTUNITY_REQUIRED_CONFIRMATIONS
    )
    measured = [
        summarise(
            totals.get(provider.provider_id, ProviderTotals(provider.provider_id)),
            name=provider.meta.name,
            operational=provider.meta.operational,
            unavailable_reason=provider.meta.unavailable_reason,
            # Read from what the provider declares it emits, not from whether
            # outcomes happen to exist yet. "Never forecasts anything" and
            # "has not resolved a forecast yet" are different facts.
            predictive=bool(set(provider.meta.emits) & PREDICTIVE_SIGNALS),
        )
        for provider in provider_registry.all()
    ]
    return ProviderAnalyticsReport(
        providers=[ProviderAnalyticsOut(**asdict(record)) for record in measured],
        engine_enabled=settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED,
        observed_at=datetime.now(UTC),
    )


@router.get(
    "/{mint}", response_model=OpportunityOut, summary="One opportunity in full"
)
async def get_opportunity(
    session: DbSession,
    mint: str,
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> OpportunityOut:
    """The live opportunity for a token, or a named past generation.

    Addressing a past generation is what keeps the permanent record readable: a
    closed call must stay retrievable after the same token opens a new one.
    """
    now = datetime.now(UTC)
    repository = OpportunityRepository(session)

    opportunity = await repository.by_mint(mint, generation=generation)
    if opportunity is None:
        raise NotFoundError(f"No opportunity for {mint}")

    signals = await repository.live_signals_for([opportunity.id], now=now)
    context = await _context_for(session, [opportunity.mint_address], now=now)
    return _to_card(
        opportunity, signals.get(opportunity.id, []), context=context, now=now
    )


# --- Rendering ---------------------------------------------------------------


def _valid_signal_type(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in {member.value for member in SignalType} else "__unknown__"


def _valid_stage(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in {member.value for member in OpportunityStage} else "__unknown__"


@dataclass(frozen=True, slots=True)
class CardContext:
    """Everything a card needs beyond the opportunity row itself.

    Gathered once per page in three batched queries rather than per card. Each
    field is independently optional: a token can have a name and no market, or
    a market and no age, and the card renders whichever facts exist.
    """

    names: dict[str, tuple[str | None, str | None]]
    markets: dict[str, TokenMarketSnapshot]
    prior_prices: dict[str, Decimal]
    ages: dict[str, datetime]


async def _context_for(session: DbSession, mints: list[str], *, now: datetime) -> CardContext:
    """Identity, market and age for a page of cards, in three queries.

    A trader cannot evaluate a signal without price, liquidity, volume and age;
    before this the board carried none of them and the card was unactionable.
    Joined at read time rather than copied onto `opportunities`, for the same
    reason identity is: a snapshot that lands later is reflected without a
    backfill, and the opportunity row stays the immutable record of a detection.
    """
    if not mints:
        return CardContext(names={}, markets={}, prior_prices={}, ages={})

    tokens = await TokenRepository(session).get_many_by_mints(mints)
    market_repository = MarketSnapshotRepository(session)
    markets = await market_repository.latest_for_mints(mints)
    prior_prices = await market_repository.price_as_of_for_mints(
        mints, as_of=now - timedelta(hours=24)
    )
    return CardContext(
        names={mint: (token.name, token.symbol) for mint, token in tokens.items()},
        markets=markets,
        prior_prices=prior_prices,
        ages={
            mint: (token.block_time or token.discovered_at)
            for mint, token in tokens.items()
        },
    )


def _to_market(
    snapshot: TokenMarketSnapshot | None, *, prior_price: Decimal | None
) -> MarketOut | None:
    """Render the market strip, or `None` when the token has never been priced.

    The 24-hour change is omitted rather than zeroed when there is no reading
    from far enough back — a token four minutes old has not been flat for a
    day, it simply did not exist.
    """
    if snapshot is None:
        return None

    change: Decimal | None = None
    price = snapshot.price_usd
    if price is not None and price > 0 and prior_price is not None and prior_price > 0:
        change = ((price - prior_price) / prior_price * 100).quantize(Decimal("0.01"))

    return MarketOut(
        price_usd=price,
        market_cap=snapshot.market_cap,
        liquidity_usd=snapshot.liquidity_usd,
        volume_24h=snapshot.volume_24h,
        change_24h_pct=change,
        captured_at=snapshot.captured_at,
        dex_name=snapshot.dex_name,
    )


def _to_card(
    opportunity: Opportunity,
    signals: list[OpportunitySignal],
    *,
    context: CardContext,
    now: datetime,
) -> OpportunityOut:
    mint = opportunity.mint_address
    name, symbol = context.names.get(mint, (None, None))
    origin = context.ages.get(mint)
    return OpportunityOut(
        mint_address=opportunity.mint_address,
        name=name,
        symbol=symbol,
        market=_to_market(
            context.markets.get(mint), prior_price=context.prior_prices.get(mint)
        ),
        age_seconds=_age(origin, now=now) if origin is not None else None,
        generation=opportunity.generation,
        status=opportunity.status,
        stage=opportunity.stage,
        priority=opportunity.priority,
        priority_band=opportunity.priority_band,
        confidence=opportunity.confidence,
        detected_at=opportunity.detected_at,
        last_confirmed_at=opportunity.last_confirmed_at,
        confirmed_age_seconds=_age(opportunity.last_confirmed_at, now=now),
        signals=[_to_signal(signal, now=now) for signal in signals],
    )


def _to_signal(signal: OpportunitySignal, *, now: datetime) -> SignalOut:
    signal_type = SignalType(signal.signal_type)
    evidence = tuple(signal.evidence or ())
    rendered = explain(
        signal_type=signal_type,
        reason_codes=tuple(signal.reason_codes or ()),
        evidence=evidence,
    )
    return SignalOut(
        signal_type=signal.signal_type,
        provider=signal.provider_id,
        status=signal.status,
        severity=signal.severity,
        strength=signal.strength,
        confidence=signal.confidence,
        confirmations=signal.confirmations,
        observations=signal.observations,
        detected_at=signal.detected_at,
        last_confirmed_at=signal.last_confirmed_at,
        expires_at=signal.expires_at,
        expires_in_seconds=max(0, int((signal.expires_at - now).total_seconds())),
        reason_codes=list(signal.reason_codes or ()),
        evidence=[
            EvidenceOut(
                label=str(item.get("label", "")),
                value=str(item.get("value", "")),
                detail=item.get("detail"),
            )
            for item in evidence
        ],
        explanation=ExplanationOut(
            headline=rendered.headline,
            trigger=rendered.trigger,
            boundary=rendered.boundary,
            delta=list(rendered.delta),
            corroboration=list(rendered.corroboration),
            limits=list(rendered.limits),
        ),
    )


def _age(moment: datetime, *, now: datetime) -> int:
    """Seconds since `moment`, floored at zero.

    Container clock skew would otherwise produce a negative age that reads as
    impossibly fresh — the same guard `health/service.py` applies.
    """
    return max(0, int((now - moment).total_seconds()))
