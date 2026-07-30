"""Analyst ensemble routes.

Additive. `/analysts/model` publishes the ensemble so its weights and its blind
spots are checkable rather than asserted — the same reason `/scores/model` and
`/radar/categories` exist. `/analysts/{mint}` runs all six against one project.

No existing route changed shape, and nothing here writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Path

from app.analysts import orchestrator
from app.analysts.base import Reading
from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.radar.repository import RadarRepository
from app.repositories.token import TokenRepository
from app.services.identity import assess as assess_identity

router = APIRouter(prefix="/analysts", tags=["analysts"])

MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

#: Scores are Decimal all the way through the analysts, which is correct for the
#: arithmetic and unreadable on the wire — an unquantised weighted mean carries
#: twenty-odd places. Rounded once, here at the serialisation boundary, so the
#: engines keep their precision and the client gets a number it can print.
_PLACES = Decimal("0.01")


def _score(value: Decimal | None) -> str | None:
    return str(value.quantize(_PLACES)) if value is not None else None


_SECONDS_PER_DAY = Decimal(86_400)


def _reading_out(reading: Reading) -> dict[str, Any]:
    return {
        "analyst": reading.analyst.value,
        "score": _score(reading.score),
        "confidence": _score(reading.confidence),
        "available": reading.available,
        "reason": reading.reason,
        "evidence": [
            {"label": e.label, "value": e.value, "detail": e.detail} for e in reading.evidence
        ],
        "warnings": [
            {"code": w.code, "severity": w.severity.value, "message": w.message}
            for w in reading.warnings
        ],
    }


@router.get("/model", summary="The published analyst ensemble")
async def get_model() -> dict[str, Any]:
    """Weights, questions and blind spots, verbatim."""
    return orchestrator.model()


@router.get("/{mint}", summary="Every analyst's reading for one project")
async def assess_token(
    session: DbSession,
    mint: Annotated[str, Path(pattern=MINT_PATTERN)],
) -> dict[str, Any]:
    repository = RadarRepository(session)
    series = await repository.load_series(mint)
    if series is None:
        raise NotFoundError(f"{mint} has no observed market history.")

    entry = await repository.get(mint)

    collisions = await TokenRepository(session).name_collisions([mint])
    found = collisions.get(mint)
    identity = (
        assess_identity(sharing_name=found[0], discovered_before=found[1])
        if found is not None
        else None
    )

    # Real elapsed time, not a placeholder. Hardcoding zero made every token
    # read as Launch Window regardless of when it was actually detected.
    now = datetime.now(UTC)
    days_since = (
        Decimal((now - entry.first_detected_at).total_seconds()) / _SECONDS_PER_DAY
        if entry is not None
        else Decimal(0)
    )

    verdict = orchestrator.assess(
        series,
        current_multiple=entry.current_multiple if entry else None,
        peak_multiple=entry.peak_multiple if entry else None,
        days_since_detection=days_since,
        exit_severity=None,
        has_veto=False,
        clone_risk=identity.clone_risk.value if identity else None,
        sharing_name=identity.sharing_name if identity else 1,
    )

    return {
        "mint_address": verdict.mint_address,
        "score": _score(verdict.score),
        "confidence": _score(verdict.confidence),
        "coverage": _score(verdict.coverage),
        "days_since_detection": _score(days_since),
        "mission_state": verdict.mission_state.value,
        "research_priority": verdict.priority.value,
        "summary": verdict.summary,
        "unavailable_analysts": list(verdict.unavailable),
        "warnings": [
            {"code": w.code, "severity": w.severity.value, "message": w.message}
            for w in verdict.warnings
        ],
        "readings": [_reading_out(r) for r in verdict.readings.values()],
        "disclaimer": (
            "LETZMOON reports what it can observe. Nothing here is a "
            "recommendation, and research priority ranks where investigation is "
            "likely to be worthwhile — not what to hold."
        ),
    }
