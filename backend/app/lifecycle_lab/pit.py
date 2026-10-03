"""The point-in-time gate: what MEMESCOPE knew at ``as_of``, and nothing else.

``information_available_at`` is the only place raw rows are admitted to a
decision (design rule 2). Every engine downstream takes the
``InformationState`` it returns, so look-ahead can only enter through here —
and this module is small enough to be read in one sitting for exactly that
reason.

The rules, in the order they are applied:

* **Mode.** AUTHORITATIVE admits FORWARD rows only, gated on ``retrieved_at``.
  EXPLORATORY also admits BACKFILL rows at
  ``max(source_timestamp, window_end) + PUBLICATION_LAG[source]`` — except
  accumulating metrics (engagement, cumulative replies), whose backfilled value
  describes *today*, not the period, and so are never visible before their own
  ``retrieved_at``.
* **Links.** A meme↔token link is a fact with a time: invisible before
  ``linked_at``. ``hindsight_links`` (EXPLORATORY only) lifts that; asking for
  it in AUTHORITATIVE mode is a programming error and raises.
* **Subjects.** Token-level observations and market points are admitted only
  for mints whose link is visible — a token nobody had connected to the meme
  yet contributes nothing, however loud it was.
* **Sources.** Every member of ``Source`` gets a ``SourceAvailability``, so a
  source that never ran shows up as UNAVAILABLE("never_collected") instead of
  silently contributing zero.

Pure: no I/O, no clock, no randomness. Output tuples are sorted on explicit
keys so shuffled inputs yield an identical state.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from app.lifecycle_lab.domain import (
    ACCUMULATING_METRICS,
    PUBLICATION_LAG,
    CollectionRun,
    DataClass,
    InformationState,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeTokenLink,
    Observation,
    ResearchMode,
    Source,
    SourceAvailability,
    SourceStatus,
    TokenInfo,
)

#: Reason for a source with no visible collection run at all.
NEVER_COLLECTED = "never_collected"
#: Reason for a source whose latest run succeeded but too long ago.
STALE_REASON = "no_available_run_within_max_age"
#: Reason stamped on an EXPLORATORY availability derived from backfilled rows.
BACKFILL_REASON = "backfill"


def knowable_at(obs: Observation) -> datetime:
    """When a BACKFILL row may be treated as known on the EXPLORATORY timeline.

    The later of the source timestamp and the window end — a window cannot be
    published before it closes — plus the source's publication lag.
    """
    described = obs.source_timestamp
    if obs.window_end is not None and obs.window_end > described:
        described = obs.window_end
    return described + PUBLICATION_LAG.get(obs.source, timedelta(0))


def _observation_visible(obs: Observation, as_of: datetime, mode: ResearchMode) -> bool:
    if obs.data_class is DataClass.FORWARD:
        return obs.retrieved_at <= as_of
    if mode is ResearchMode.AUTHORITATIVE:
        return False
    if obs.metric in ACCUMULATING_METRICS:
        # A backfilled engagement count read today includes likes that arrived
        # after the period; placing it at source_timestamp would leak them.
        return obs.retrieved_at <= as_of
    return knowable_at(obs) <= as_of


def _market_visible(point: MarketPoint, as_of: datetime, mode: ResearchMode) -> bool:
    if point.data_class is DataClass.BACKFILL and mode is ResearchMode.AUTHORITATIVE:
        return False
    return point.available_at <= as_of


def _subject_visible(obs: Observation, meme_id: str, mints: frozenset[str]) -> bool:
    if obs.meme_id is not None:
        return obs.meme_id == meme_id
    return obs.mint_address is not None and obs.mint_address in mints


def _run_relevant(run: CollectionRun, meme_id: str, mints: frozenset[str]) -> bool:
    if run.meme_id is not None:
        return run.meme_id == meme_id
    if run.mint_address is not None:
        return run.mint_address in mints
    # A global run (one sweep over every subject) speaks for this meme too.
    return True


def observation_key(obs: Observation) -> tuple[Any, ...]:
    """Total order on observations: every field of ``dedupe_key`` takes part,
    so two distinct stored rows never tie and input order cannot leak into
    the output.

    Native values rather than ISO strings or the SHA-256 dedupe key: this runs
    on every admitted row at every replay tick, and formatting dominated the
    replay's cost. A missing window bound sorts before any present one.
    """
    return (
        obs.observed_at,
        obs.source,
        obs.metric,
        obs.meme_id or "",
        obs.mint_address or "",
        obs.query or "",
        obs.window_start is not None,
        obs.window_start or obs.observed_at,
        obs.window_end is not None,
        obs.window_end or obs.observed_at,
        obs.data_class,
        obs.retrieved_at,
        obs.raw_value,
    )


def market_key(point: MarketPoint) -> tuple[Any, ...]:
    return (
        point.mint_address,
        point.observed_at,
        point.available_at,
        point.source,
        point.data_class,
        point.price_usd is not None,
        point.price_usd or 0,
    )


def latest_known(points: Iterable[MarketPoint], as_of: datetime) -> MarketPoint | None:
    """The newest market point available at ``as_of`` (by observed_at, then
    available_at), or None. Ties break on the full sort key, never on input
    order."""
    best: MarketPoint | None = None
    for point in points:
        if point.available_at > as_of:
            continue
        if best is None or (point.observed_at, market_key(point)) > (
            best.observed_at,
            market_key(best),
        ):
            best = point
    return best


def _run_availability(
    source: Source,
    latest: CollectionRun | None,
    as_of: datetime,
    max_observation_age: timedelta,
) -> SourceAvailability:
    if latest is None:
        return SourceAvailability(source, SourceStatus.UNAVAILABLE, NEVER_COLLECTED, None)
    if latest.status is SourceStatus.AVAILABLE:
        if as_of - latest.finished_at > max_observation_age:
            return SourceAvailability(
                source, SourceStatus.STALE, STALE_REASON, latest.finished_at
            )
        return SourceAvailability(source, SourceStatus.AVAILABLE, None, latest.finished_at)
    return SourceAvailability(
        source, latest.status, latest.reason or latest.status.value, latest.finished_at
    )


def _backfill_availability(
    source: Source,
    observations: list[Observation],
    as_of: datetime,
    max_observation_age: timedelta,
) -> SourceAvailability | None:
    """EXPLORATORY only: a source whose history was backfilled is "available"
    on the replay timeline when its latest backfilled row became knowable
    recently enough.

    Backfill runs finish weeks after the period they describe, so the run
    table alone would call every historical instant ``never_collected`` and an
    exploratory replay would be all-Unavailable. The freshness budget is
    widened by the row's own window length: a daily Wikipedia row is not stale
    an hour after it was published.
    """
    rows = [
        o for o in observations if o.source is source and o.data_class is DataClass.BACKFILL
    ]
    if not rows:
        return None
    latest = max(rows, key=lambda o: (knowable_at(o), observation_key(o)))
    at = knowable_at(latest)
    span = timedelta(0)
    if latest.window_start is not None and latest.window_end is not None:
        span = max(latest.window_end - latest.window_start, timedelta(0))
    if as_of - at > max_observation_age + span:
        return None
    return SourceAvailability(source, SourceStatus.AVAILABLE, BACKFILL_REASON, at)


def information_available_at(
    *,
    as_of: datetime,
    mode: ResearchMode,
    meme: Meme,
    aliases: Iterable[MemeAlias],
    links: Iterable[MemeTokenLink],
    tokens: Iterable[TokenInfo],
    observations: Iterable[Observation],
    market: Iterable[MarketPoint],
    runs: Iterable[CollectionRun],
    hindsight_links: bool = False,
    max_observation_age: timedelta = timedelta(hours=2),
) -> InformationState:
    """Everything known at ``as_of`` in ``mode``. See the module docstring."""
    if hindsight_links and mode is ResearchMode.AUTHORITATIVE:
        raise ValueError(
            "hindsight_links is EXPLORATORY-only: an authoritative result may not "
            "use a link before its linked_at"
        )

    visible_aliases = sorted(
        (a for a in aliases if a.meme_id == meme.id and a.added_at <= as_of),
        key=lambda a: (a.kind, a.alias, a.added_at),
    )

    def _link_visible(link: MemeTokenLink) -> bool:
        if link.meme_id != meme.id:
            return False
        if hindsight_links:
            # Hindsight lifts linked_at, not a known unlink.
            return link.unlinked_at is None or link.unlinked_at > as_of
        return link.visible_at(as_of)

    visible_links = sorted(
        (link for link in links if _link_visible(link)),
        key=lambda link: (link.mint_address, link.linked_at, link.method),
    )
    mints = frozenset(link.mint_address for link in visible_links)

    visible_tokens = sorted(
        (t for t in tokens if t.mint_address in mints), key=lambda t: t.mint_address
    )
    # One TokenInfo per mint, even if the caller passed duplicates.
    deduped_tokens: dict[str, TokenInfo] = {}
    for token in visible_tokens:
        deduped_tokens.setdefault(token.mint_address, token)

    visible_obs = sorted(
        (
            o
            for o in observations
            if _subject_visible(o, meme.id, mints) and _observation_visible(o, as_of, mode)
        ),
        key=observation_key,
    )
    visible_market = sorted(
        (p for p in market if p.mint_address in mints and _market_visible(p, as_of, mode)),
        key=market_key,
    )

    # One pass: only the latest visible run per source matters.
    latest_runs: dict[Source, CollectionRun] = {}
    for r in runs:
        if r.finished_at > as_of or not _run_relevant(r, meme.id, mints):
            continue
        if mode is ResearchMode.AUTHORITATIVE and r.data_class is DataClass.BACKFILL:
            continue
        held = latest_runs.get(r.source)
        if held is None or (r.finished_at, r.started_at, r.id) > (
            held.finished_at,
            held.started_at,
            held.id,
        ):
            latest_runs[r.source] = r
    sources: list[SourceAvailability] = []
    for source in sorted(Source, key=lambda s: s.value):
        availability = _run_availability(
            source,
            latest_runs.get(source),
            as_of,
            max_observation_age,
        )
        if (
            mode is ResearchMode.EXPLORATORY
            and availability.status is not SourceStatus.AVAILABLE
        ):
            backfilled = _backfill_availability(
                source, visible_obs, as_of, max_observation_age
            )
            if backfilled is not None:
                availability = backfilled
        sources.append(availability)

    contains_backfill = any(o.data_class is DataClass.BACKFILL for o in visible_obs) or any(
        p.data_class is DataClass.BACKFILL for p in visible_market
    )

    return InformationState(
        as_of=as_of,
        mode=mode,
        meme=meme,
        aliases=tuple(visible_aliases),
        links=tuple(visible_links),
        tokens=tuple(deduped_tokens.values()),
        observations=tuple(visible_obs),
        market=tuple(visible_market),
        sources=tuple(sources),
        contains_backfill=contains_backfill,
        hindsight_links=hindsight_links,
    )
