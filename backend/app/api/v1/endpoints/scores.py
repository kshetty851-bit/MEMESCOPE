"""AI scoring routes.

Public, matching the rest of the token and market API: this is derived from
public chain data.

The router does no work beyond binding request shapes to `ScoreQueryService`.
Filtering, sorting, pagination, derivation, and DTO assembly all live in the
service, so a second client - a bot, a mobile app - gets identical behaviour
without going through HTTP.

Route order matters here: `/top` and `/model` are literal segments and must be
declared before `/{mint}`, or FastAPI would match them as mint addresses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.models.score import ScoreGrade, ScoreTrigger
from app.schemas.common import ErrorResponse
from app.schemas.score import (
    ModelMetadataRead,
    ScoreHistoryPage,
    ScoreSortField,
    SortOrder,
    TokenScoreEnvelope,
    TopScorePage,
)
from app.services.scoring.query_service import ScoreQueryService

# Base58 pubkeys are 32-44 characters. Rejecting junk in the path keeps
# malformed input out of the database and turns it into a 422 with the same
# envelope as any other validation failure.
MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"

MintPath = Annotated[
    str,
    Path(
        pattern=MINT_PATTERN,
        description="Base58 SPL mint address.",
        examples=["7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"],
    ),
]

ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No such discovered token."},
    422: {"model": ErrorResponse, "description": "Malformed mint or invalid parameters."},
}

router = APIRouter(prefix="/scores", tags=["scores"])


def get_score_service(session: DbSession) -> ScoreQueryService:
    return ScoreQueryService(session)


ScoreServiceDep = Annotated[ScoreQueryService, Depends(get_score_service)]


class TopScoreQuery(BaseModel):
    """Query contract for the ranking endpoint.

    A model rather than a wall of `Query(...)` arguments: the constraints are
    declared once, validated by pydantic, and rendered into OpenAPI without the
    router doing any parsing of its own.
    """

    page: int = Field(default=1, ge=1, description="1-indexed page number.")
    page_size: int = Field(default=20, ge=1, le=100, description="Rows per page.")
    sort: ScoreSortField = Field(default="score", description="Column to order by.")
    order: SortOrder = Field(default="desc", description="Sort direction.")

    min_score: Decimal | None = Field(
        default=None, ge=0, le=100, description="Only scores at or above this value."
    )
    min_confidence: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Only tokens whose evidence is at or above this value. Confidence is "
            "evidence discounted by freshness and so never exceeds it, which makes "
            "this an upper-bound filter: it can exclude no token that would have "
            "qualified on true confidence, and it is applied in the database."
        ),
    )
    max_risk: Decimal | None = Field(
        default=None, ge=0, le=100, description="Only tokens at or below this risk."
    )
    grade: ScoreGrade | None = Field(default=None, description="Exact grade band.")
    trigger: ScoreTrigger | None = Field(
        default=None,
        description="What earned the token its most recent history entry.",
    )
    model_version: str | None = Field(
        default=None,
        max_length=32,
        description="Restrict to one model version. Scores from different versions "
        "are not comparable.",
    )
    elite_only: bool = Field(default=False, description="Only Elite-certified tokens.")
    include_vetoed: bool = Field(
        default=False,
        description="Include tokens the risk gate vetoed. Excluded by default.",
    )


@router.get(
    "/top",
    response_model=TopScorePage,
    responses=ERRORS,
    summary="Ranked tokens by AI score",
    description=(
        "Tokens ranked by their current AI score, filtered and sorted in the "
        "database.\n\n"
        "Vetoed tokens are excluded unless `include_vetoed` is set: a veto means "
        "the risk gate capped the score outright, and such tokens do not belong "
        "in a ranking of opportunities by default.\n\n"
        "`applied_filters` echoes what was actually applied and `candidate_total` "
        "reports the unfiltered population, so an empty page caused by a strict "
        "filter is distinguishable from an empty table.\n\n"
        "**Pagination note.** Pages are offset-based over a ranking that changes "
        "as tokens are re-scored, so a row may shift between pages while a client "
        "is walking them. Ordering is total (the sort column plus `mint_address`), "
        "so results are deterministic for any single request."
    ),
)
async def top_scores(
    service: ScoreServiceDep, params: Annotated[TopScoreQuery, Query()]
) -> TopScorePage:
    return await service.top(
        now=datetime.now(UTC),
        page=params.page,
        page_size=params.page_size,
        sort=params.sort,
        order=params.order,
        min_score=params.min_score,
        min_confidence=params.min_confidence,
        max_risk=params.max_risk,
        grade=str(params.grade) if params.grade else None,
        trigger=str(params.trigger) if params.trigger else None,
        model_version=params.model_version,
        elite_only=params.elite_only,
        include_vetoed=params.include_vetoed,
    )


@router.get(
    "/model",
    response_model=ModelMetadataRead,
    summary="Active scoring model",
    description=(
        "The weight vector and thresholds currently in use, including components "
        "that are declared but whose data source does not exist yet.\n\n"
        "These weights are priors, not fitted parameters. Publishing them is what "
        "makes that claim checkable. `available_weight_total` is the ceiling on "
        "coverage, and therefore on evidence, for every token scored by this "
        "model - which is why `elite_gate.reachable` can be false."
    ),
)
async def scoring_model(service: ScoreServiceDep) -> ModelMetadataRead:
    return service.model_metadata()


@router.get(
    "/{mint}",
    response_model=TokenScoreEnvelope,
    responses=ERRORS,
    summary="Current AI score for a token",
    description=(
        "The token's current score with its full component breakdown and "
        "explanation.\n\n"
        "A token that exists but has no score returns 200 with `score: null` and "
        "a `status` explaining why - the absence is meaningful state, not an "
        "error. A mint that was never discovered returns 404.\n\n"
        "`confidence` and `freshness` are computed per request from the age of "
        "the underlying snapshot, so this response is never stale even when the "
        "stored row is."
    ),
)
async def token_score(service: ScoreServiceDep, mint: MintPath) -> TokenScoreEnvelope:
    return await service.current(mint, now=datetime.now(UTC))


@router.get(
    "/{mint}/history",
    response_model=ScoreHistoryPage,
    responses=ERRORS,
    summary="Score history for a token, newest first",
    description=(
        "Recorded score changes for one token.\n\n"
        "History is written on material change plus a periodic heartbeat, so this "
        "is a record of events rather than a sample of every evaluation. The "
        "table is append-only, so offset pagination is stable here."
    ),
)
async def token_score_history(
    service: ScoreServiceDep,
    mint: MintPath,
    page: Annotated[int, Query(ge=1, description="1-indexed page number.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500, description="Rows per page.")] = 50,
    since: Annotated[
        datetime | None, Query(description="Lower bound on `evaluated_at`.")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Upper bound on `evaluated_at`.")
    ] = None,
) -> ScoreHistoryPage:
    return await service.history_page(
        mint, page=page, page_size=page_size, since=since, until=until
    )
