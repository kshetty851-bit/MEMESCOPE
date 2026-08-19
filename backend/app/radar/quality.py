"""Forward-only Radar quality instrumentation.

The recorder receives a completed Radar result and writes its own independent
transaction *after* the Radar transaction has committed.  It contains no call
into the scorer or detector and is deliberately unable to return a value to the
ranking path.  That is the failure-isolation boundary for this research ledger.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.models.radar_quality import (
    RadarDecisionOutcome,
    RadarDecisionSnapshot,
    RadarRankEvent,
)
from app.radar import detector, scorer
from app.radar.models import OpportunityResult, RadarDimension, RadarReason, RadarSeries

logger = get_logger(__name__)

FEATURE_SCHEMA_VERSION = "radar_quality_feature_v1"
CONFIGURATION_VERSION = "radar_weights_v1"
CONTROL_SCORE_FLOOR = detector.MIN_RADAR_SCORE - Decimal("5")
TOP_RANK_EVENT_LIMIT = 20

# These are labels, never features.  They are intentionally explicit rather
# than inferred from a mutable peak column at a later date.
OUTCOME_HORIZONS: tuple[tuple[str, timedelta], ...] = (
    ("5m", timedelta(minutes=5)),
    ("15m", timedelta(minutes=15)),
    ("30m", timedelta(minutes=30)),
    ("1h", timedelta(hours=1)),
    ("3h", timedelta(hours=3)),
    ("6h", timedelta(hours=6)),
    ("12h", timedelta(hours=12)),
    ("24h", timedelta(hours=24)),
)
MILESTONE_MULTIPLES: tuple[tuple[str, Decimal], ...] = (
    ("time_to_1_25x_seconds", Decimal("1.25")),
    ("time_to_1_5x_seconds", Decimal("1.5")),
    ("time_to_2x_seconds", Decimal("2")),
    ("time_to_3x_seconds", Decimal("3")),
    ("time_to_5x_seconds", Decimal("5")),
    ("time_to_10x_seconds", Decimal("10")),
)


def _json(value: Any) -> Any:
    """Make frozen JSON payloads exact and portable (not float-coerced)."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _availability(
    value: Any,
    *,
    source: str = "token_market_snapshots",
    observed_at: datetime | None = None,
    provider: str | None = None,
    unavailable_state: str = "NOT_AVAILABLE_FROM_PROVIDER",
) -> dict[str, Any]:
    if value is None:
        return {"state": unavailable_state, "source": source}
    payload: dict[str, Any] = {"state": "AVAILABLE", "source": source}
    if observed_at is not None:
        payload["observed_at"] = _json(observed_at)
    if provider:
        payload["provider"] = provider
    return payload


def _ratio(
    numerator: Decimal | int | None, denominator: Decimal | int | None
) -> tuple[Decimal | None, str]:
    if numerator is None or denominator is None:
        return None, "NOT_AVAILABLE_FROM_PROVIDER"
    if denominator <= 0:
        return None, "NOT_APPLICABLE"
    return Decimal(numerator) / Decimal(denominator), "AVAILABLE"


def _rank_band(rank: int) -> str:
    if rank == 1:
        return "RANK_1"
    if rank <= 3:
        return "RANK_2_3"
    if rank <= 5:
        return "RANK_4_5"
    if rank <= 10:
        return "RANK_6_10"
    if rank <= 20:
        return "RANK_11_20"
    return "OUTSIDE_TOP_20"


def _risk_band(score: Decimal | None) -> str:
    if score is None:
        return "UNKNOWN"
    # The Radar's risk dimension is safety-oriented: higher is safer.
    if score >= Decimal("70"):
        return "LOW"
    if score >= detector.MIN_RISK_FLOOR:
        return "MODERATE"
    return "HIGH"


def _rejection_reasons(result: OpportunityResult, category: str | None) -> list[str]:
    if category is not None:
        return []
    reasons: list[str] = []
    if result.score < detector.MIN_RADAR_SCORE:
        reasons.append("RADAR_SCORE_BELOW_MINIMUM")
    if result.confidence < detector.MIN_RADAR_CONFIDENCE:
        reasons.append("CONFIDENCE_BELOW_MINIMUM")
    risk = result.dimension(RadarDimension.RISK)
    if risk is None or not risk.available or risk.score is None:
        reasons.append("RISK_UNAVAILABLE")
    elif risk.score < detector.MIN_RISK_FLOOR:
        reasons.append("RISK_BELOW_FLOOR")
    return reasons or ["NOT_CATEGORISED"]


def _control_sampled(mint_address: str) -> bool:
    digest = hashlib.sha256(mint_address.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    return value % settings.RADAR_QUALITY_CONTROL_SAMPLE_MODULUS == 0


def should_capture(*, selected: bool, result: OpportunityResult) -> bool:
    """Bound control volume without selectively retaining only winners.

    Every Radar-selected evaluation is retained.  Non-selected candidates retain
    all near-admission evaluations plus a deterministic 1/N sample of the rest;
    the mint hash makes the control policy stable across retries and workers.
    """

    return (
        selected
        or result.score >= CONTROL_SCORE_FLOOR
        or _control_sampled(result.mint_address)
    )


def _latest_market_state(series: RadarSeries) -> tuple[dict[str, Any], dict[str, Any]]:
    latest = series.latest
    if latest is None:
        unavailable = {"state": "NOT_YET_ENRICHED", "source": "radar_input"}
        return {}, {"market_snapshot": unavailable}

    observed_at = latest.captured_at
    source = latest.provider or "unknown_provider"
    market_state = {
        "price_usd": latest.price_usd,
        "liquidity_usd": latest.liquidity_usd,
        "volume_5m": latest.volume_5m,
        "volume_1h": latest.volume_1h,
        "volume_6h": None,
        "volume_24h": latest.volume_24h,
        # The current provider model does not persist price-change windows.
        "price_change_5m": None,
        "price_change_1h": None,
        "price_change_6h": None,
        "price_change_24h": None,
        "buys_5m": None,
        "sells_5m": None,
        "buys_1h": None,
        "sells_1h": None,
        "buys_6h": None,
        "sells_6h": None,
        "buys_24h": latest.buy_count_24h,
        "sells_24h": latest.sell_count_24h,
        "transaction_count_24h": (
            latest.buy_count_24h + latest.sell_count_24h
            if latest.buy_count_24h is not None and latest.sell_count_24h is not None
            else None
        ),
        "dex": latest.dex_name,
        "pool": latest.pool_address,
        "trading_pair": latest.trading_pair,
        "provider": latest.provider,
        "provider_latency_ms": latest.provider_latency_ms,
        "market_status": latest.trading_status,
        "verification_status": latest.is_verified,
        "quote_age_seconds": None,
        "observed_at": observed_at,
    }
    availability = {
        name: _availability(value, observed_at=observed_at, provider=source)
        for name, value in market_state.items()
        if name not in {"observed_at", "quote_age_seconds"}
    }
    for absent in (
        "volume_6h",
        "price_change_5m",
        "price_change_1h",
        "price_change_6h",
        "price_change_24h",
        "buys_5m",
        "sells_5m",
        "buys_1h",
        "sells_1h",
        "buys_6h",
        "sells_6h",
    ):
        availability[absent] = _availability(None, source="provider_schema")
    return _json(market_state), availability


def _predecision_features(
    series: RadarSeries, evaluated_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derived features whose inputs are strictly at or before evaluation time."""

    usable = [item for item in series.observations if item.captured_at <= evaluated_at]
    latest = usable[-1] if usable else None
    features: dict[str, Any] = {}
    availability: dict[str, Any] = {}

    if latest is None:
        return features, {"predecision_observations": {"state": "NOT_YET_ENRICHED"}}

    for name, ratio in (
        ("volume_5m_to_liquidity", _ratio(latest.volume_5m, latest.liquidity_usd)),
        ("volume_1h_to_liquidity", _ratio(latest.volume_1h, latest.liquidity_usd)),
        ("volume_6h_to_liquidity", _ratio(None, latest.liquidity_usd)),
        ("volume_24h_to_liquidity", _ratio(latest.volume_24h, latest.liquidity_usd)),
        ("buy_sell_ratio_5m", _ratio(None, None)),
        ("buy_sell_ratio_1h", _ratio(None, None)),
        ("buy_sell_ratio_6h", _ratio(None, None)),
        ("buy_sell_ratio_24h", _ratio(latest.buy_count_24h, latest.sell_count_24h)),
    ):
        ratio_value, state = ratio
        features[name] = ratio_value
        availability[name] = {"state": state, "source": "predecision_market_state"}

    features["radar_input_snapshot_count"] = len(usable)
    availability["radar_input_snapshot_count"] = {
        "state": "AVAILABLE",
        "source": "radar_input_window",
    }

    if len(usable) >= 2:
        previous = usable[-2]
        elapsed = (latest.captured_at - previous.captured_at).total_seconds()
        features["time_since_previous_valid_observation_seconds"] = elapsed
        availability["time_since_previous_valid_observation_seconds"] = {
            "state": "AVAILABLE",
            "source": "radar_input_window",
        }
    else:
        features["time_since_previous_valid_observation_seconds"] = None
        availability["time_since_previous_valid_observation_seconds"] = {
            "state": "NOT_YET_ENRICHED",
            "source": "radar_input_window",
        }

    cadences = [
        (right.captured_at - left.captured_at).total_seconds()
        for left, right in pairwise(usable)
        if right.captured_at > left.captured_at
    ]
    if cadences:
        ordered = sorted(cadences)
        midpoint = len(ordered) // 2
        median = (
            ordered[midpoint]
            if len(ordered) % 2
            else (ordered[midpoint - 1] + ordered[midpoint]) / 2
        )
        features["median_observation_cadence_seconds"] = median
        availability["median_observation_cadence_seconds"] = {
            "state": "AVAILABLE",
            "source": "radar_input_window",
        }
    else:
        features["median_observation_cadence_seconds"] = None
        availability["median_observation_cadence_seconds"] = {
            "state": "NOT_YET_ENRICHED",
            "source": "radar_input_window",
        }

    # Short-window slopes/accelerations use the final three *pre-decision*
    # observations.  They are deliberately omitted when cadence/value support
    # is inadequate instead of silently using a later snapshot.
    if len(usable) >= 3:
        first, middle, last = usable[-3:]
        dt_one = (middle.captured_at - first.captured_at).total_seconds()
        dt_two = (last.captured_at - middle.captured_at).total_seconds()
        if dt_one > 0 and dt_two > 0:
            for name, attr in (
                ("volume_24h_acceleration_per_second", "volume_24h"),
                ("transaction_24h_acceleration_per_second", None),
                ("liquidity_acceleration_per_second", "liquidity_usd"),
            ):
                if attr is None:
                    values = [
                        (item.buy_count_24h + item.sell_count_24h)
                        if item.buy_count_24h is not None and item.sell_count_24h is not None
                        else None
                        for item in (first, middle, last)
                    ]
                else:
                    values = [getattr(item, attr) for item in (first, middle, last)]
                if all(value is not None for value in values):
                    prior_velocity = (values[1] - values[0]) / Decimal(str(dt_one))  # type: ignore[operator]
                    current_velocity = (values[2] - values[1]) / Decimal(str(dt_two))  # type: ignore[operator]
                    features[name] = current_velocity - prior_velocity
                    availability[name] = {"state": "AVAILABLE", "source": "radar_input_window"}
                else:
                    features[name] = None
                    availability[name] = {
                        "state": "NOT_AVAILABLE_FROM_PROVIDER",
                        "source": "radar_input_window",
                    }

            if (
                first.price_usd is not None
                and middle.price_usd is not None
                and last.price_usd is not None
                and first.price_usd > 0
                and middle.price_usd > 0
            ):
                prior_velocity = ((middle.price_usd / first.price_usd) - 1) / Decimal(
                    str(dt_one)
                )
                current_velocity = ((last.price_usd / middle.price_usd) - 1) / Decimal(
                    str(dt_two)
                )
                features["price_acceleration_per_second"] = current_velocity - prior_velocity
                features["price_velocity_per_second"] = current_velocity
                availability["price_acceleration_per_second"] = {
                    "state": "AVAILABLE",
                    "source": "radar_input_window",
                }
                availability["price_velocity_per_second"] = {
                    "state": "AVAILABLE",
                    "source": "radar_input_window",
                }
            else:
                for name in ("price_acceleration_per_second", "price_velocity_per_second"):
                    features[name] = None
                    availability[name] = {
                        "state": "NOT_AVAILABLE_FROM_PROVIDER",
                        "source": "radar_input_window",
                    }
    else:
        for name in (
            "volume_24h_acceleration_per_second",
            "transaction_24h_acceleration_per_second",
            "liquidity_acceleration_per_second",
            "price_acceleration_per_second",
            "price_velocity_per_second",
        ):
            features[name] = None
            availability[name] = {"state": "NOT_YET_ENRICHED", "source": "radar_input_window"}

    return _json(features), availability


def _component_state(result: OpportunityResult) -> dict[str, Any]:
    weights = scorer.effective_weights(result.dimensions)
    payload: dict[str, Any] = {}
    for dimension in result.dimensions:
        weight = weights.get(dimension.id)
        contribution = (
            weight * dimension.score
            if weight is not None and dimension.score is not None
            else None
        )
        payload[dimension.id.value] = {
            "raw_inputs": dimension.raw,
            "normalized_score": dimension.score,
            "declared_weight": scorer.WEIGHTS[dimension.id],
            "effective_weight": weight,
            "weighted_contribution": contribution,
            "evidence": [reason.value for reason in dimension.reasons],
            "vetoes": [],
            "availability_state": "AVAILABLE"
            if dimension.available
            else "NOT_AVAILABLE_FROM_PROVIDER",
        }
    return cast(dict[str, Any], _json(payload))


@dataclass(frozen=True, slots=True)
class PendingDecision:
    evaluation_id: uuid.UUID
    evaluation_key: str
    series: RadarSeries
    result: OpportunityResult
    category: str | None
    selected: bool
    evaluated_at: datetime


def build_pending(
    *,
    series: RadarSeries,
    result: OpportunityResult,
    category: str | None,
    selected: bool,
    evaluated_at: datetime,
) -> PendingDecision | None:
    if not should_capture(selected=selected, result=result):
        return None
    latest_id = (
        series.latest.snapshot_id if series.latest is not None else "no_market_snapshot"
    )
    key = (
        f"{FEATURE_SCHEMA_VERSION}:{series.mint_address}:"
        f"{evaluated_at.isoformat()}:{latest_id}"
    )
    return PendingDecision(
        evaluation_id=uuid.uuid5(uuid.NAMESPACE_URL, key),
        evaluation_key=key,
        series=series,
        result=result,
        category=category,
        selected=selected,
        evaluated_at=evaluated_at,
    )


class RadarQualityRecorder:
    """Persistence seam for decision records, rank events, and future labels."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _ranked_state(self, mints: Sequence[str]) -> dict[str, tuple[int, uuid.UUID]]:
        if not mints:
            return {}
        ranked = (
            select(
                RadarToken.mint_address.label("mint_address"),
                RadarToken.id.label("radar_token_id"),
                func.row_number()
                .over(
                    order_by=(
                        RadarToken.current_opportunity_score.desc(),
                        RadarToken.mint_address,
                    )
                )
                .label("radar_rank"),
            )
            .where(RadarToken.is_active.is_(True))
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    ranked.c.mint_address, ranked.c.radar_rank, ranked.c.radar_token_id
                ).where(ranked.c.mint_address.in_(list(dict.fromkeys(mints))))
            )
        ).all()
        return {row.mint_address: (int(row.radar_rank), row.radar_token_id) for row in rows}

    async def _snapshot_counts(self, decisions: Sequence[PendingDecision]) -> dict[str, int]:
        # Refresh and sweep pass one explicit common moment. Grouping by that
        # timestamp retains the <= evaluated_at boundary without N queries.
        counts: dict[str, int] = {}
        groups: dict[datetime, list[str]] = {}
        for decision in decisions:
            groups.setdefault(decision.evaluated_at, []).append(decision.series.mint_address)
        for moment, mints in groups.items():
            rows = (
                await self._session.execute(
                    select(TokenMarketSnapshot.mint_address, func.count().label("count"))
                    .where(
                        TokenMarketSnapshot.mint_address.in_(list(dict.fromkeys(mints))),
                        TokenMarketSnapshot.captured_at <= moment,
                    )
                    .group_by(TokenMarketSnapshot.mint_address)
                )
            ).all()
            counts.update({row.mint_address: int(row[1]) for row in rows})
        return counts

    async def _top_rank_events(
        self,
        *,
        observed_at: datetime,
        decision_ids: dict[str, uuid.UUID],
    ) -> list[dict[str, Any]]:
        top = (
            await self._session.execute(
                select(
                    RadarToken.mint_address,
                    func.row_number()
                    .over(
                        order_by=(
                            RadarToken.current_opportunity_score.desc(),
                            RadarToken.mint_address,
                        )
                    )
                    .label("radar_rank"),
                )
                .where(RadarToken.is_active.is_(True))
                .order_by(RadarToken.current_opportunity_score.desc(), RadarToken.mint_address)
                .limit(TOP_RANK_EVENT_LIMIT)
            )
        ).all()
        mints = [row.mint_address for row in top]
        if not mints:
            return []
        latest = (
            select(
                RadarRankEvent.mint_address,
                RadarRankEvent.radar_rank,
                func.row_number()
                .over(
                    partition_by=RadarRankEvent.mint_address,
                    order_by=RadarRankEvent.observed_at.desc(),
                )
                .label("rank"),
            )
            .where(RadarRankEvent.mint_address.in_(mints))
            .subquery()
        )
        previous = {
            row.mint_address: int(row.radar_rank)
            for row in (
                await self._session.execute(
                    select(latest.c.mint_address, latest.c.radar_rank).where(
                        latest.c.rank == 1
                    )
                )
            ).all()
        }
        return [
            {
                "event_key": (
                    f"{FEATURE_SCHEMA_VERSION}:top-rank:{mint}:{observed_at.isoformat()}"
                ),
                "decision_id": decision_ids.get(mint),
                "mint_address": mint,
                "radar_rank": int(rank),
                "rank_band": _rank_band(int(rank)),
                "event_source": "TOP_20_RANK_CHANGE",
                "observed_at": observed_at,
            }
            for mint, rank in top
            if previous.get(mint) != int(rank)
        ]

    async def prepare(
        self, decisions: Sequence[PendingDecision]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read the committed canonical state once, then build immutable rows."""

        if not decisions:
            return [], []
        observed_at = datetime.now(UTC)
        mints = [decision.series.mint_address for decision in decisions]
        ranks = await self._ranked_state(mints)
        counts = await self._snapshot_counts(decisions)

        decision_rows: list[dict[str, Any]] = []
        rank_events: list[dict[str, Any]] = []
        decision_ids: dict[str, uuid.UUID] = {}
        for decision in decisions:
            series = decision.series
            result = decision.result
            latest = series.latest
            rank, radar_token_id = ranks.get(series.mint_address, (None, None))
            risk = result.dimension(RadarDimension.RISK)
            risk_score = risk.score if risk and risk.available else None
            market_state, market_availability = _latest_market_state(series)
            derived, derived_availability = _predecision_features(
                series, decision.evaluated_at
            )
            derived["snapshot_count_since_discovery"] = counts.get(series.mint_address, 0)
            derived_availability["snapshot_count_since_discovery"] = {
                "state": "AVAILABLE",
                "source": "token_market_snapshots",
                "through": _json(decision.evaluated_at),
            }

            age = None
            if series.discovered_at is not None:
                age = Decimal(
                    max((decision.evaluated_at - series.discovered_at).total_seconds(), 0)
                )
            rejection = _rejection_reasons(result, decision.category)
            reasons = [reason.value for reason in result.reasons]
            vetoes = [reason for reason in rejection if reason.startswith("RISK_")]
            component_state = _component_state(result)
            availability = {
                "market": market_availability,
                "derived": derived_availability,
                "components": {
                    name: value["availability_state"]
                    for name, value in component_state.items()
                },
            }
            row = {
                # Keep primary and evaluation identifiers identical.  This makes
                # retry-safe rank events linkable without a read-after-write.
                "id": decision.evaluation_id,
                "evaluation_id": decision.evaluation_id,
                "evaluation_key": decision.evaluation_key,
                "mint_address": series.mint_address,
                "token_id": series.token_id,
                "radar_token_id": radar_token_id,
                "market_snapshot_id": latest.snapshot_id if latest else None,
                "evaluated_at": decision.evaluated_at,
                "rank_observed_at": observed_at,
                "first_discovered_at": series.discovered_at,
                "time_since_discovery_seconds": age,
                "radar_rank": rank,
                "rank_state": "RANKED" if rank is not None else "NOT_RANKED",
                "radar_score": result.score,
                "confidence_score": result.confidence,
                "risk_score": risk_score,
                "risk_band": _risk_band(risk_score),
                "eligibility_state": "ELIGIBLE"
                if decision.category is not None
                else "INELIGIBLE",
                "selected": decision.selected,
                "selection_reasons": [str(decision.category), *reasons]
                if decision.category
                else [],
                "rejection_reasons": rejection,
                "vetoes": vetoes,
                "evidence": _json(
                    {
                        "reasons": reasons,
                        "coverage": result.coverage,
                        "observations": result.observations,
                    }
                ),
                "why_now": [
                    reason
                    for reason in reasons
                    if reason
                    not in {
                        RadarReason.INSUFFICIENT_HISTORY.value,
                        RadarReason.SIGNAL_NOT_AVAILABLE.value,
                        RadarReason.COMMUNITY_DATA_UNAVAILABLE.value,
                    }
                ],
                "radar_algorithm_version": result.model_version,
                "radar_configuration_version": CONFIGURATION_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "token_identity": _json(
                    {
                        "mint_address": series.mint_address,
                        "name": series.token_name,
                        "symbol": series.token_symbol,
                        "decimals": series.token_decimals,
                        "discovered_at": series.discovered_at,
                    }
                ),
                "component_state": component_state,
                "market_state": market_state,
                "derived_features": derived,
                "availability": availability,
                "provenance": {
                    "market_snapshot_id": _json(latest.snapshot_id) if latest else None,
                    "market_observed_at": _json(latest.captured_at) if latest else None,
                    "market_provider": latest.provider if latest else None,
                    "rank_observed_after_radar_commit": True,
                    "control_policy": (
                        "ALL_SELECTED"
                        if decision.selected
                        else "NEAR_ADMISSION_OR_DETERMINISTIC_SAMPLE"
                    ),
                },
            }
            decision_rows.append(row)
            decision_ids[series.mint_address] = decision.evaluation_id
            if rank is not None:
                event_key = (
                    f"{FEATURE_SCHEMA_VERSION}:evaluation-rank:{decision.evaluation_id}"
                )
                rank_events.append(
                    {
                        "event_key": event_key,
                        "decision_id": decision.evaluation_id,
                        "mint_address": series.mint_address,
                        "radar_rank": rank,
                        "rank_band": _rank_band(rank),
                        "event_source": "EVALUATION",
                        "observed_at": observed_at,
                    }
                )
        rank_events.extend(
            await self._top_rank_events(observed_at=observed_at, decision_ids=decision_ids)
        )
        return decision_rows, rank_events

    async def persist(
        self, decision_rows: Sequence[dict[str, Any]], rank_events: Sequence[dict[str, Any]]
    ) -> tuple[int, int]:
        inserted_decisions = 0
        inserted_events = 0
        if decision_rows:
            result = await self._session.execute(
                insert(RadarDecisionSnapshot)
                .values(list(decision_rows))
                .on_conflict_do_nothing(index_elements=[RadarDecisionSnapshot.evaluation_id])
                .returning(RadarDecisionSnapshot.id)
            )
            inserted_decisions = len(result.scalars().all())
        if rank_events:
            result = await self._session.execute(
                insert(RadarRankEvent)
                .values(list(rank_events))
                .on_conflict_do_nothing(index_elements=[RadarRankEvent.event_key])
                .returning(RadarRankEvent.id)
            )
            inserted_events = len(result.scalars().all())
        return inserted_decisions, inserted_events

    async def capture_outcomes(self, *, now: datetime, limit: int) -> dict[str, int]:
        """Append horizon labels and a 24-hour path summary for ready decisions."""

        decisions = (
            await self._session.scalars(
                select(RadarDecisionSnapshot)
                .where(RadarDecisionSnapshot.evaluated_at <= now - OUTCOME_HORIZONS[0][1])
                .order_by(RadarDecisionSnapshot.evaluated_at.asc())
                .limit(limit)
            )
        ).all()
        written = 0
        paths = 0
        for decision in decisions:
            existing = set(
                (
                    await self._session.execute(
                        select(
                            RadarDecisionOutcome.outcome_kind, RadarDecisionOutcome.horizon
                        ).where(RadarDecisionOutcome.decision_id == decision.id)
                    )
                ).all()
            )
            reference = _decimal_from_json(decision.market_state.get("price_usd"))
            for horizon, delta in OUTCOME_HORIZONS:
                due_at = decision.evaluated_at + delta
                if due_at > now or ("HORIZON", horizon) in existing:
                    continue
                snapshot = await self._first_snapshot_after(decision.mint_address, due_at, now)
                if snapshot is None:
                    continue
                await self._insert_outcome(
                    decision=decision,
                    outcome_kind="HORIZON",
                    horizon=horizon,
                    due_at=due_at,
                    observed_at=snapshot.captured_at,
                    snapshot=snapshot,
                    reference=reference,
                    payload={
                        "market_state": _outcome_market_state(snapshot),
                        "observation_delay_seconds": Decimal(
                            max((snapshot.captured_at - due_at).total_seconds(), 0)
                        ),
                    },
                )
                written += 1

            final_due = decision.evaluated_at + timedelta(hours=24)
            if final_due <= now and ("PATH_SUMMARY", "24h") not in existing:
                snapshots = (
                    await self._session.scalars(
                        select(TokenMarketSnapshot)
                        .where(
                            TokenMarketSnapshot.mint_address == decision.mint_address,
                            TokenMarketSnapshot.captured_at >= decision.evaluated_at,
                            TokenMarketSnapshot.captured_at <= final_due,
                        )
                        .order_by(TokenMarketSnapshot.captured_at.asc())
                    )
                ).all()
                await self._insert_path_summary(
                    decision=decision,
                    due_at=final_due,
                    snapshots=snapshots,
                    reference=reference,
                )
                paths += 1
        return {
            "decisions_examined": len(decisions),
            "horizons_written": written,
            "paths_written": paths,
        }

    async def _first_snapshot_after(
        self, mint_address: str, due_at: datetime, now: datetime
    ) -> TokenMarketSnapshot | None:
        snapshot = await self._session.scalar(
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.mint_address == mint_address,
                TokenMarketSnapshot.captured_at >= due_at,
                TokenMarketSnapshot.captured_at <= now,
            )
            .order_by(TokenMarketSnapshot.captured_at.asc())
            .limit(1)
        )
        return snapshot

    async def _insert_outcome(
        self,
        *,
        decision: RadarDecisionSnapshot,
        outcome_kind: str,
        horizon: str,
        due_at: datetime,
        observed_at: datetime,
        snapshot: TokenMarketSnapshot | None,
        reference: Decimal | None,
        payload: dict[str, Any],
        availability: dict[str, Any] | None = None,
    ) -> None:
        observed_price = snapshot.price_usd if snapshot is not None else None
        multiple = (
            observed_price / reference
            if observed_price is not None and reference is not None and reference > 0
            else None
        )
        await self._session.execute(
            insert(RadarDecisionOutcome)
            .values(
                decision_id=decision.id,
                outcome_kind=outcome_kind,
                horizon=horizon,
                due_at=due_at,
                observed_at=observed_at,
                market_snapshot_id=snapshot.id if snapshot else None,
                reference_price=reference,
                observed_price=observed_price,
                future_multiple=multiple,
                payload=_json(payload),
                availability=availability
                or {
                    "reference_price": _availability(
                        reference, source="radar_decision_snapshots"
                    ),
                    "outcome_price": _availability(
                        observed_price,
                        observed_at=observed_at,
                        provider=snapshot.provider if snapshot else None,
                    ),
                },
                provenance={
                    "label_only": True,
                    "market_snapshot_id": _json(snapshot.id) if snapshot else None,
                    "market_observed_at": _json(snapshot.captured_at) if snapshot else None,
                    "provider": snapshot.provider if snapshot else None,
                },
            )
            .on_conflict_do_nothing(constraint="uq_radar_decision_outcome")
        )

    async def _insert_path_summary(
        self,
        *,
        decision: RadarDecisionSnapshot,
        due_at: datetime,
        snapshots: Sequence[TokenMarketSnapshot],
        reference: Decimal | None,
    ) -> None:
        priced = [
            item for item in snapshots if item.price_usd is not None and item.price_usd > 0
        ]
        if reference is None or reference <= 0:
            await self._insert_outcome(
                decision=decision,
                outcome_kind="PATH_SUMMARY",
                horizon="24h",
                due_at=due_at,
                observed_at=due_at,
                snapshot=None,
                reference=reference,
                payload={"observations": len(snapshots), "reason": "NO_DECISION_PRICE"},
                availability={
                    "path": {"state": "NOT_APPLICABLE", "reason": "NO_DECISION_PRICE"}
                },
            )
            return
        if not priced:
            await self._insert_outcome(
                decision=decision,
                outcome_kind="PATH_SUMMARY",
                horizon="24h",
                due_at=due_at,
                observed_at=due_at,
                snapshot=None,
                reference=reference,
                payload={
                    "observations": len(snapshots),
                    "market_disappearance_suspected": True,
                    "reason": "NO_PRICED_MARKET_OBSERVATION_WITHIN_24H",
                },
                availability={"path": {"state": "NOT_AVAILABLE_FROM_PROVIDER"}},
            )
            return

        multiples = [
            (item, item.price_usd / reference) for item in priced if item.price_usd is not None
        ]
        peak, max_multiple = max(multiples, key=lambda item: (item[1], item[0].captured_at))
        trough, min_multiple = min(multiples, key=lambda item: (item[1], item[0].captured_at))
        thresholds: dict[str, Decimal | None] = {}
        for name, threshold in MILESTONE_MULTIPLES:
            hit = next((item for item, multiple in multiples if multiple >= threshold), None)
            thresholds[name] = (
                Decimal(max((hit.captured_at - decision.evaluated_at).total_seconds(), 0))
                if hit
                else None
            )
        decision_liquidity = _decimal_from_json(decision.market_state.get("liquidity_usd"))
        liquidities = [
            item.liquidity_usd for item in snapshots if item.liquidity_usd is not None
        ]
        min_liquidity = min(liquidities) if liquidities else None
        collapse = (
            decision_liquidity is not None
            and decision_liquidity > 0
            and min_liquidity is not None
            and min_liquidity <= decision_liquidity * Decimal("0.20")
        )
        await self._insert_outcome(
            decision=decision,
            outcome_kind="PATH_SUMMARY",
            horizon="24h",
            due_at=due_at,
            observed_at=due_at,
            snapshot=peak,
            reference=reference,
            payload={
                "observations": len(snapshots),
                "priced_observations": len(priced),
                "maximum_future_multiple": max_multiple,
                "mfe_multiple": max_multiple - Decimal(1),
                "mae_multiple": min_multiple - Decimal(1),
                "time_to_peak_seconds": Decimal(
                    max((peak.captured_at - decision.evaluated_at).total_seconds(), 0)
                ),
                "peak_observed_at": peak.captured_at,
                "trough_observed_at": trough.captured_at,
                "liquidity_survived": not collapse and min_liquidity is not None,
                "liquidity_collapse": collapse,
                "minimum_liquidity_usd": min_liquidity,
                "market_disappearance_suspected": False,
                **thresholds,
            },
        )


async def capture_pending(decisions: Sequence[PendingDecision]) -> None:
    """Best-effort decision/rank recording; never raises into the Radar path."""

    if not decisions or not settings.FEATURE_RADAR_QUALITY_DATASET:
        return
    started = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            recorder = RadarQualityRecorder(session)
            decision_rows, rank_events = await recorder.prepare(decisions)
            inserted_decisions, inserted_events = await recorder.persist(
                decision_rows, rank_events
            )
            await session.commit()
        logger.info(
            "radar_quality_capture_completed",
            candidates=len(decisions),
            decisions=inserted_decisions,
            rank_events=inserted_events,
            duration_ms=round((datetime.now(UTC) - started).total_seconds() * 1000, 3),
        )
    except Exception:
        # Deliberately no re-raise.  This is the explicit failure-isolation
        # guarantee: the Radar has already committed at this point.
        logger.exception(
            "radar_quality_capture_failed",
            candidates=len(decisions),
            duration_ms=round((datetime.now(UTC) - started).total_seconds() * 1000, 3),
        )


def _decimal_from_json(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _outcome_market_state(snapshot: TokenMarketSnapshot) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _json(
            {
                "price_usd": snapshot.price_usd,
                "liquidity_usd": snapshot.liquidity_usd,
                "volume_5m": snapshot.volume_5m,
                "volume_1h": snapshot.volume_1h,
                "volume_24h": snapshot.volume_24h,
                "buys_24h": snapshot.buy_count_24h,
                "sells_24h": snapshot.sell_count_24h,
                "dex": snapshot.dex_name,
                "pool": snapshot.pool_address,
                "provider": snapshot.provider,
                "provider_latency_ms": snapshot.provider_latency_ms,
                "market_status": snapshot.trading_status,
                "verification_status": snapshot.is_verified,
                "observed_at": snapshot.captured_at,
            }
        ),
    )
