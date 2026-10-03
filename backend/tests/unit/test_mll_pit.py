"""The point-in-time gate is the Lab's only defence against look-ahead.

Every engine downstream trusts ``InformationState`` blindly, so each rule the
gate enforces is asserted here as a property: something that was not known at
``T`` must not be in the state at ``T``, whatever else is true.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.domain import (
    AliasKind,
    CollectionRun,
    DataClass,
    LinkMethod,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    TokenInfo,
    ValueKind,
)
from app.lifecycle_lab.pit import information_available_at, latest_known

pytestmark = pytest.mark.unit

T = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
MEME = Meme(
    id="m1", slug="dog", display_name="Dog", tracking_started_at=T - timedelta(days=30)
)
MINT = "MintAAA"


def obs(
    *,
    retrieved_at: datetime,
    source: Source = Source.GDELT,
    metric: Metric = Metric.MENTIONS,
    data_class: DataClass = DataClass.FORWARD,
    window_end: datetime | None = None,
    meme_id: str | None = "m1",
    mint: str | None = None,
    value: int = 1,
    kind: ValueKind = ValueKind.WINDOW_COUNT,
) -> Observation:
    end = window_end or retrieved_at
    return Observation(
        source=source,
        metric=metric,
        value_kind=kind,
        data_class=data_class,
        source_timestamp=end - timedelta(minutes=15),
        observed_at=end,
        retrieved_at=retrieved_at,
        raw_value=Decimal(value),
        meme_id=None if mint else meme_id,
        mint_address=mint,
        window_start=end - timedelta(minutes=15),
        window_end=end,
    )


def link(linked_at: datetime, *, unlinked_at: datetime | None = None) -> MemeTokenLink:
    return MemeTokenLink(
        meme_id="m1",
        mint_address=MINT,
        method=LinkMethod.EXACT_NAME,
        confidence=Decimal("0.6"),
        linked_at=linked_at,
        unlinked_at=unlinked_at,
    )


def point(available_at: datetime, *, data_class: DataClass = DataClass.FORWARD) -> MarketPoint:
    return MarketPoint(
        mint_address=MINT,
        observed_at=available_at,
        available_at=available_at,
        data_class=data_class,
        price_usd=Decimal("1"),
    )


def run(
    finished_at: datetime,
    *,
    source: Source = Source.GDELT,
    status: SourceStatus = SourceStatus.AVAILABLE,
    reason: str | None = None,
    meme_id: str | None = "m1",
    data_class: DataClass = DataClass.FORWARD,
) -> CollectionRun:
    return CollectionRun(
        id=f"{source}-{finished_at.isoformat()}",
        source=source,
        status=status,
        started_at=finished_at - timedelta(seconds=5),
        finished_at=finished_at,
        data_class=data_class,
        reason=reason,
        meme_id=meme_id,
    )


def gate(
    *,
    as_of: datetime = T,
    mode: ResearchMode = ResearchMode.AUTHORITATIVE,
    aliases: list[MemeAlias] | None = None,
    links: list[MemeTokenLink] | None = None,
    observations: list[Observation] | None = None,
    market: list[MarketPoint] | None = None,
    runs: list[CollectionRun] | None = None,
    hindsight_links: bool = False,
):
    return information_available_at(
        as_of=as_of,
        mode=mode,
        meme=MEME,
        aliases=aliases or [],
        links=links or [],
        tokens=[TokenInfo(MINT, "Dog", "DOG", None, None)],
        observations=observations or [],
        market=market or [],
        runs=runs or [],
        hindsight_links=hindsight_links,
    )


def test_a_future_observation_is_never_visible() -> None:
    """FORWARD data proves knowledge only by retrieved_at. A row fetched one
    second after T describes a world we had not seen at T."""
    future = obs(retrieved_at=T + timedelta(seconds=1), window_end=T - timedelta(minutes=30))
    present = obs(retrieved_at=T, window_end=T - timedelta(minutes=45))
    state = gate(observations=[future, present])
    assert state.observations == (present,)


@pytest.mark.parametrize("mode", list(ResearchMode))
def test_future_observation_invisible_in_every_mode(mode: ResearchMode) -> None:
    future = obs(retrieved_at=T + timedelta(hours=1), window_end=T - timedelta(hours=5))
    assert gate(mode=mode, observations=[future]).observations == ()


def test_backfill_is_invisible_in_authoritative_mode() -> None:
    """AUTHORITATIVE is the verdict-grade mode: data fetched after the fact,
    however plausible its timestamps, may not count toward it."""
    old = T - timedelta(days=3)
    rows = [
        obs(retrieved_at=T - timedelta(hours=1), window_end=old, data_class=DataClass.BACKFILL)
    ]
    state = gate(
        observations=rows,
        links=[link(T - timedelta(days=10))],
        market=[point(old, data_class=DataClass.BACKFILL)],
    )
    assert state.observations == ()
    assert state.market == ()
    assert state.contains_backfill is False


def test_backfill_visible_in_exploratory_only_after_publication_lag() -> None:
    """BACKFILL rows are placed at window_end + PUBLICATION_LAG; a GDELT
    bucket cannot be known before it closes plus GDELT's 15 minutes."""
    end = T - timedelta(minutes=14)  # + 15 min lag = T + 1 min: not yet known
    late = obs(
        retrieved_at=T + timedelta(days=20), window_end=end, data_class=DataClass.BACKFILL
    )
    end_ok = T - timedelta(minutes=15)
    ok = obs(
        retrieved_at=T + timedelta(days=20), window_end=end_ok, data_class=DataClass.BACKFILL
    )
    state = gate(mode=ResearchMode.EXPLORATORY, observations=[late, ok])
    assert state.observations == (ok,)
    assert state.contains_backfill is True


@pytest.mark.parametrize("metric", [Metric.ENGAGEMENT, Metric.REPLIES_TOTAL])
def test_backfilled_accumulating_metric_invisible_until_retrieved(metric: Metric) -> None:
    """Likes keep arriving after a post's window closes: an engagement count
    read today and placed at last week's timestamp would leak today's likes
    into last week. Even EXPLORATORY waits for retrieved_at."""
    row = obs(
        retrieved_at=T + timedelta(hours=1),
        window_end=T - timedelta(days=5),
        metric=metric,
        data_class=DataClass.BACKFILL,
    )
    assert gate(mode=ResearchMode.EXPLORATORY, observations=[row]).observations == ()
    later = gate(
        as_of=T + timedelta(hours=1), mode=ResearchMode.EXPLORATORY, observations=[row]
    )
    assert later.observations == (row,)


def test_link_before_linked_at_is_invisible_and_excludes_its_token() -> None:
    """A link made after a pump does not exist before it. Its token's
    observations and prices stay out, or the pump leaks into the meme's past."""
    lk = link(T + timedelta(hours=1))
    mint_obs = obs(
        retrieved_at=T - timedelta(hours=1), mint=MINT, source=Source.PUMPFUN_REPLIES
    )
    state = gate(links=[lk], observations=[mint_obs], market=[point(T - timedelta(minutes=5))])
    assert state.links == ()
    assert state.tokens == ()
    assert state.observations == ()
    assert state.market == ()

    after = gate(
        as_of=T + timedelta(hours=1),
        links=[lk],
        observations=[mint_obs],
        market=[point(T - timedelta(minutes=5))],
    )
    assert after.links == (lk,)
    assert after.observations == (mint_obs,)
    assert len(after.market) == 1


def test_unlinked_link_disappears_after_unlinked_at() -> None:
    lk = link(T - timedelta(days=2), unlinked_at=T - timedelta(hours=1))
    assert gate(links=[lk]).links == ()


def test_hindsight_links_refused_in_authoritative_mode() -> None:
    with pytest.raises(ValueError, match="EXPLORATORY"):
        gate(hindsight_links=True)


def test_hindsight_links_lift_linked_at_in_exploratory_and_are_stamped() -> None:
    lk = link(T + timedelta(days=1))
    state = gate(mode=ResearchMode.EXPLORATORY, links=[lk], hindsight_links=True)
    assert state.links == (lk,)
    assert state.hindsight_links is True


def test_aliases_gated_on_added_at() -> None:
    known = MemeAlias("m1", "doge", AliasKind.NAME, T - timedelta(days=1))
    later = MemeAlias("m1", "doggo", AliasKind.NAME, T + timedelta(seconds=1))
    other = MemeAlias("m2", "cat", AliasKind.NAME, T - timedelta(days=1))
    assert gate(aliases=[later, known, other]).aliases == (known,)


def test_other_memes_observations_never_admitted() -> None:
    mine = obs(retrieved_at=T, meme_id="m1")
    theirs = obs(retrieved_at=T, meme_id="m2")
    assert gate(observations=[mine, theirs]).observations == (mine,)


def test_backfill_market_points_only_in_exploratory() -> None:
    p = point(T - timedelta(hours=2), data_class=DataClass.BACKFILL)
    links = [link(T - timedelta(days=5))]
    assert gate(links=links, market=[p]).market == ()
    state = gate(mode=ResearchMode.EXPLORATORY, links=links, market=[p])
    assert state.market == (p,)
    assert state.contains_backfill is True


def test_every_source_reported_and_missing_ones_say_never_collected() -> None:
    """Absence is never zero: a source that never ran is a named UNAVAILABLE,
    not a silent hole a feature could read as 'no mentions'."""
    state = gate(runs=[run(T - timedelta(minutes=10))])
    by_source = {s.source: s for s in state.sources}
    assert set(by_source) == set(Source)
    assert by_source[Source.GDELT].status is SourceStatus.AVAILABLE
    for source in set(Source) - {Source.GDELT}:
        assert by_source[source].status is SourceStatus.UNAVAILABLE
        assert by_source[source].reason == "never_collected"


def _status(state, source: Source):
    return next(s for s in state.sources if s.source is source)


def test_old_available_run_is_stale() -> None:
    """GDELT's budget is 7h (LOW priority collects every 6h)."""
    assert _status(gate(runs=[run(T - timedelta(hours=6))]), Source.GDELT).status is (
        SourceStatus.AVAILABLE
    )
    stale = _status(gate(runs=[run(T - timedelta(hours=8))]), Source.GDELT)
    assert stale.status is SourceStatus.STALE
    assert stale.reason == "no_available_run_within_max_age"


def test_daily_wikipedia_stays_available_between_daily_collections() -> None:
    """Wikipedia is collected once per UTC day. Calling it STALE two hours
    later would make platform_count follow the scheduler, not attention: it
    stays AVAILABLE at +20h and goes STALE only past its 30h budget."""
    runs = [run(T, source=Source.WIKIPEDIA)]
    at_20h = gate(as_of=T + timedelta(hours=20), runs=runs)
    assert _status(at_20h, Source.WIKIPEDIA).status is SourceStatus.AVAILABLE
    at_31h = gate(as_of=T + timedelta(hours=31), runs=runs)
    assert _status(at_31h, Source.WIKIPEDIA).status is SourceStatus.STALE


def test_pumpfun_replies_budget_is_tighter_than_the_global_default() -> None:
    runs = [run(T - timedelta(minutes=45), source=Source.PUMPFUN_REPLIES)]
    assert _status(gate(runs=runs), Source.PUMPFUN_REPLIES).status is SourceStatus.STALE


def test_explicit_budgets_replace_the_default_and_fall_back_to_max_age() -> None:
    """``source_max_age`` wins per source; ``max_observation_age`` covers the
    sources it omits, so ``{}`` restores the single global budget."""
    runs = [run(T - timedelta(hours=3), source=Source.WIKIPEDIA)]

    def wiki(**kw: object) -> SourceStatus:
        state = information_available_at(
            as_of=T,
            mode=ResearchMode.AUTHORITATIVE,
            meme=MEME,
            aliases=[],
            links=[],
            tokens=[],
            observations=[],
            market=[],
            runs=runs,
            **kw,  # type: ignore[arg-type]
        )
        return _status(state, Source.WIKIPEDIA).status

    assert wiki() is SourceStatus.AVAILABLE
    assert wiki(source_max_age={}) is SourceStatus.STALE
    assert wiki(source_max_age={}, max_observation_age=timedelta(hours=4)) is (
        SourceStatus.AVAILABLE
    )
    assert wiki(source_max_age={Source.WIKIPEDIA: timedelta(hours=1)}) is SourceStatus.STALE


def test_gate_records_the_budgets_it_applied() -> None:
    budgets = dict(gate().source_max_age)
    assert set(budgets) == set(Source)
    assert budgets[Source.WIKIPEDIA] == timedelta(hours=30)


def test_a_memes_own_run_outranks_a_later_global_run() -> None:
    """A meme that was not due keeps its own last result. A later global
    sweep that went PARTIAL because some *other* due meme errored says
    nothing about this one."""
    own = run(T - timedelta(hours=1))
    sweep = run(
        T - timedelta(minutes=5),
        status=SourceStatus.PARTIAL,
        reason="some_failed",
        meme_id=None,
    )
    gdelt = _status(gate(runs=[own, sweep]), Source.GDELT)
    assert gdelt.status is SourceStatus.AVAILABLE
    assert gdelt.last_run_at == own.finished_at


def test_a_global_run_speaks_for_a_meme_without_its_own() -> None:
    sweep = run(
        T - timedelta(minutes=5),
        status=SourceStatus.PARTIAL,
        reason="some_failed",
        meme_id=None,
    )
    other = run(T - timedelta(minutes=1), status=SourceStatus.ERROR, meme_id="m2")
    gdelt = _status(gate(runs=[sweep, other]), Source.GDELT)
    assert (gdelt.status, gdelt.reason) == (SourceStatus.PARTIAL, "some_failed")


def test_a_linked_mints_run_counts_as_the_memes_own() -> None:
    mint_run = replace(
        run(T - timedelta(hours=1), source=Source.PUMPFUN_REPLIES, meme_id=None),
        mint_address=MINT,
        finished_at=T - timedelta(minutes=10),
    )
    sweep = run(
        T - timedelta(minutes=2),
        source=Source.PUMPFUN_REPLIES,
        status=SourceStatus.ERROR,
        reason="http_500",
        meme_id=None,
    )
    state = gate(runs=[mint_run, sweep], links=[link(T - timedelta(days=1))])
    assert _status(state, Source.PUMPFUN_REPLIES).status is SourceStatus.AVAILABLE


def test_latest_run_wins_and_carries_its_reason() -> None:
    runs = [
        run(T - timedelta(minutes=30)),
        run(T - timedelta(minutes=5), status=SourceStatus.ERROR, reason="http_429"),
        run(T + timedelta(minutes=5)),  # not finished at T
        run(T - timedelta(minutes=1), meme_id="m2"),  # another meme
    ]
    gdelt = next(s for s in gate(runs=runs).sources if s.source is Source.GDELT)
    assert gdelt.status is SourceStatus.ERROR
    assert gdelt.reason == "http_429"


def test_backfill_run_does_not_make_a_source_available_in_authoritative() -> None:
    runs = [run(T - timedelta(minutes=5), data_class=DataClass.BACKFILL)]
    gdelt = next(s for s in gate(runs=runs).sources if s.source is Source.GDELT)
    assert gdelt.status is SourceStatus.UNAVAILABLE


def test_exploratory_backfilled_history_counts_as_available() -> None:
    """Backfill runs finish weeks after the period, so on a historical
    timeline the run table alone would make every exploratory replay
    all-Unavailable. Recently-knowable backfilled rows stand in for it."""
    row = obs(
        retrieved_at=T + timedelta(days=20),
        window_end=T - timedelta(minutes=30),
        data_class=DataClass.BACKFILL,
    )
    state = gate(mode=ResearchMode.EXPLORATORY, observations=[row])
    gdelt = next(s for s in state.sources if s.source is Source.GDELT)
    assert gdelt.status is SourceStatus.AVAILABLE
    assert gdelt.reason == "backfill"


def test_shuffled_inputs_give_an_identical_state() -> None:
    """Replays must be byte-for-byte reproducible; database row order is not a
    contract."""
    links = [link(T - timedelta(days=3))]
    rows = [
        obs(retrieved_at=T - timedelta(minutes=m), window_end=T - timedelta(minutes=m))
        for m in range(0, 300, 15)
    ] + [obs(retrieved_at=T - timedelta(minutes=m), mint=MINT) for m in range(1, 100, 7)]
    points = [point(T - timedelta(minutes=m)) for m in range(0, 200, 5)]
    runs = [run(T - timedelta(minutes=m)) for m in range(0, 120, 10)]
    first = gate(links=links, observations=rows, market=points, runs=runs)
    rng = random.Random(7)
    for _ in range(5):
        rng.shuffle(rows)
        rng.shuffle(points)
        rng.shuffle(runs)
        assert gate(links=links, observations=rows, market=points, runs=runs) == first


def test_latest_known_respects_available_at() -> None:
    a = point(T - timedelta(minutes=10))
    b = replace(point(T - timedelta(minutes=2)), available_at=T + timedelta(minutes=1))
    assert latest_known([b, a], T) == a
    assert latest_known([], T) is None
