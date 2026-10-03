"""`/api/v1/lifecycle-lab` — the Meme Lifecycle Lab's HTTP surface.

Thin: parse, call ``LifecycleLabService``, shape. No SQL here.

Reads are public and answer truthfully when the lab is switched off
(``lab_enabled: false``, every source DISABLED) rather than 404 — an absent
lab is a state, not a missing page. Curation is admin-only, and every
timestamp a curation request creates (``tracking_started_at``, ``added_at``,
``linked_at``) is the server's clock: a client can never date a fact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.lifecycle_lab.schemas import (
    AliasCreated,
    AliasIn,
    BackfillIn,
    BackfillQueued,
    ExperimentsOut,
    HealthOut,
    LinkCreated,
    ManualLinkIn,
    MemeCreate,
    MemeCreated,
    MemeDetail,
    MemesOut,
    Overview,
    RunDetail,
)
from app.lifecycle_lab.service import LabConflictError, LabNotFoundError, LifecycleLabService

router = APIRouter(prefix="/lifecycle-lab", tags=["lifecycle-lab"])

#: Celery task the backfill POST enqueues (by name, so the API process does
#: not import the scheduler module).
BACKFILL_TASK = "app.lifecycle_lab.scheduler.lifecycle_backfill"
MAX_BACKFILL_SPAN = timedelta(days=90)


def _now() -> datetime:
    return datetime.now(UTC)


def _enqueue_backfill(slug: str, start: datetime, end: datetime) -> None:
    from app.workers.celery_app import celery_app

    celery_app.send_task(
        BACKFILL_TASK,
        kwargs={"slug": slug, "start": start.isoformat(), "end": end.isoformat()},
    )


@router.get("/overview", response_model=Overview, summary="Lab KPIs and source health")
async def overview(session: DbSession) -> Overview:
    return Overview.model_validate(await LifecycleLabService(session).overview(_now()))


@router.get("/health", response_model=HealthOut, summary="Per-source collection status")
async def health(session: DbSession) -> HealthOut:
    return HealthOut.model_validate(await LifecycleLabService(session).health(_now()))


@router.get("/memes", response_model=MemesOut, summary="Radar rows for tracked memes")
async def memes(session: DbSession) -> MemesOut:
    return MemesOut.model_validate(await LifecycleLabService(session).memes(_now()))


@router.get("/memes/{slug}", response_model=MemeDetail, summary="One meme's evidence")
async def meme_detail(
    slug: str,
    session: DbSession,
    include_backfill: bool = Query(
        default=False,
        description="Overlay EXPLORATORY backfill on the chart; the response is "
        "then labelled exploratory.",
    ),
) -> MemeDetail:
    detail = await LifecycleLabService(session).meme_detail(
        slug, _now(), include_backfill=include_backfill
    )
    if detail is None:
        raise NotFoundError(f"No tracked meme {slug!r}.")
    return MemeDetail.model_validate(detail)


@router.get("/experiments", response_model=ExperimentsOut, summary="Experiment registry")
async def experiments(session: DbSession) -> ExperimentsOut:
    return ExperimentsOut.model_validate(await LifecycleLabService(session).experiments())


@router.get("/runs/{run_id}", response_model=RunDetail, summary="One replay run")
async def run_detail(run_id: str, session: DbSession) -> RunDetail:
    detail = await LifecycleLabService(session).run_detail(run_id)
    if detail is None:
        raise NotFoundError(f"No run {run_id!r}.")
    return RunDetail.model_validate(detail)


# --------------------------------------------------------------------------
# Admin curation
# --------------------------------------------------------------------------


@router.post(
    "/memes",
    response_model=MemeCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tracked meme (admin)",
)
async def create_meme(body: MemeCreate, admin: AdminUser, session: DbSession) -> MemeCreated:
    try:
        created = await LifecycleLabService(session).create_meme(
            slug=body.slug,
            display_name=body.display_name,
            description=body.description,
            wikipedia_title=body.wikipedia_title,
            gdelt_query=body.gdelt_query,
            aliases=[(a.alias, a.kind) for a in body.aliases],
            now=_now(),
        )
    except LabConflictError as exc:
        raise ConflictError(str(exc)) from exc
    return MemeCreated.model_validate(created)


@router.post(
    "/memes/{slug}/aliases",
    response_model=AliasCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Add an alias (admin)",
)
async def add_alias(
    slug: str, body: AliasIn, admin: AdminUser, session: DbSession
) -> AliasCreated:
    try:
        row = await LifecycleLabService(session).add_alias(slug, body.alias, body.kind, _now())
    except LabNotFoundError as exc:
        raise NotFoundError(f"No tracked meme {slug!r}.") from exc
    except LabConflictError as exc:
        raise ConflictError(str(exc)) from exc
    return AliasCreated.model_validate(row)


@router.post(
    "/memes/{slug}/links",
    response_model=LinkCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Link a token manually (admin); linked_at is the server's clock",
)
async def add_link(
    slug: str, body: ManualLinkIn, admin: AdminUser, session: DbSession
) -> LinkCreated:
    try:
        row = await LifecycleLabService(session).add_manual_link(
            slug, body.mint, body.confidence, str(admin.id), _now()
        )
    except LabNotFoundError as exc:
        raise NotFoundError(f"No tracked meme {slug!r}.") from exc
    return LinkCreated.model_validate(row)


@router.post(
    "/memes/{slug}/backfill",
    response_model=BackfillQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an exploratory backfill (admin)",
)
async def backfill(
    slug: str, body: BackfillIn, admin: AdminUser, session: DbSession
) -> BackfillQueued:
    """Queued, not run inline: GDELT asks for one request per ~6s and
    GeckoTerminal pages per mint, which is minutes of third-party I/O that
    must not sit inside a request's transaction."""
    now = _now()
    if body.start.tzinfo is None or body.end.tzinfo is None:
        raise ValidationError("start and end must carry a timezone.")
    if not (body.start < body.end <= now):
        raise ValidationError("The window must satisfy start < end <= now.")
    if body.end - body.start > MAX_BACKFILL_SPAN:
        raise ValidationError("The window may span at most 90 days.")
    if await LifecycleLabService(session).get_meme(slug) is None:
        raise NotFoundError(f"No tracked meme {slug!r}.")
    if not settings.FEATURE_LIFECYCLE_LAB_ENABLED:
        raise ConflictError("The lifecycle lab is disabled.", code="lab_disabled")
    _enqueue_backfill(slug, body.start, body.end)
    return BackfillQueued(
        queued=True, slug=slug, start=body.start, end=body.end, data_class="backfill"
    )
