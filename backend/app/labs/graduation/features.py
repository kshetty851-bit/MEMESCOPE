"""One row per graduated token: what the curve did on the way up, and what the
price did afterwards.

Reads `grad_curve_samples`, `grad_checkpoints`, `grad_postgrad_samples`,
`grad_tokens` and `grad_migrations`. Writes `grad_features`. Computes nothing
else and decides nothing — no strategy, no entry rule, no paper trade. Phase 3
is what reads this.

## The one thing to get right: samples are change-only

`grad_curve_samples` holds a row only when a reserve MOVED. A gap between two
rows means nothing happened; it does not mean nothing was looked at. So every
time-based feature here reads a FORWARD-FILLED series: the progress at time `t`
is the progress of the last sample at or before `t`, which is exactly what the
curve was doing at `t`.

Getting that wrong would not raise. It would quietly compute velocity over a
series with holes in it, and every number downstream would be wrong in the
direction of "this token looked quiet".

There is one honest extrapolation before the first sample: a pump.fun curve is
at 0% by construction the moment it is created, so a look-back that reaches
past the first sample but not past `first_seen_at` reads 0 rather than null.
That is a property of the protocol, not a guess. A look-back reaching before
the token existed reads null.

## Features are per checkpoint, outcomes are per token

Features are computed at 70/80/90/95 so Phase 3 can test entry levels. 100 is
excluded deliberately: it IS the graduation, so nothing measured there could
inform a decision made before it.

Outcomes are measured from the FIRST post-graduation price sample — the pool
open — because that is the earliest price anything could actually have been
bought at.

## What is NULL, and why NULL is not zero

* A checkpoint that was never reached leaves its whole feature block null. The
  token is still written: "reached 70 but never 90" is a row Phase 3 needs, and
  dropping it would silently condition the sample on success.
* Outcomes are null when post-graduation coverage is under
  `OUTCOME_MIN_COVERAGE_MIN` of `OUTCOME_WINDOW_MIN` minutes.
  `postgrad_minutes_covered` is written either way, so a null outcome always
  says why.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.models import (
    SOURCE_GECKOTERMINAL,
    GradCheckpoint,
    GradCurveSample,
    GradFeature,
    GradMigration,
    GradPostgradSample,
    GradToken,
)

logger = get_logger(__name__)

_MIN_DP = Decimal("0.001")
_VEL_DP = Decimal("0.000001")
_RET_DP = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """One observed reserve change."""

    ts: datetime
    progress_pct: Decimal | None
    market_cap_quote: Decimal | None
    complete: bool


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One post-graduation price observation."""

    ts: datetime
    price_usd: Decimal
    source: str


def _minutes(delta: timedelta) -> Decimal:
    return (Decimal(delta.total_seconds()) / 60).quantize(_MIN_DP)


# --- the forward-filled curve -------------------------------------------------

def progress_at(curve: Sequence[CurvePoint], at: datetime, *,
                launch_at: datetime | None) -> Decimal | None:
    """Forward-filled progress at `at`, or None when it is not knowable.

    The last sample at or before `at`. Before the first sample but at or after
    the launch, the answer is 0 — a curve holds its full allocation the instant
    it is created, and that is the protocol, not an assumption. Before the
    launch there is no answer.
    """
    latest: Decimal | None = None
    found = False
    for point in curve:
        if point.ts > at:
            break
        if point.progress_pct is not None:
            latest, found = point.progress_pct, True
    if found:
        return latest
    if launch_at is not None and at >= launch_at:
        return Decimal(0)
    return None


def velocity(curve: Sequence[CurvePoint], at: datetime, window_min: int, *,
             launch_at: datetime | None) -> Decimal | None:
    """Progress POINTS gained per minute over the `window_min` before `at`.

    Both ends are forward-filled, so a quiet stretch reads as zero velocity
    rather than as a gap. Null when the window reaches back past the launch.
    """
    now_pct = progress_at(curve, at, launch_at=launch_at)
    then = at - timedelta(minutes=window_min)
    then_pct = progress_at(curve, then, launch_at=launch_at)
    if now_pct is None or then_pct is None:
        return None
    return ((now_pct - then_pct) / window_min).quantize(_VEL_DP)


def changes_within(curve: Sequence[CurvePoint], at: datetime,
                   window_min: int) -> int:
    """How many reserve changes landed in the `window_min` before `at`.

    Every row in `grad_curve_samples` IS a change, so this is a count — and it
    is the closest thing to a trade count this lab has, since the account
    reports reserves and not who moved them.
    """
    start = at - timedelta(minutes=window_min)
    return sum(1 for p in curve if start < p.ts <= at)


def stall_count(curve: Sequence[CurvePoint], start: datetime, end: datetime, *,
                threshold_min: int) -> int:
    """Quiet runs of `threshold_min` or longer between `start` and `end`.

    Measured from `start` itself, so a token that crosses 70% and then does
    nothing for ten minutes has stalled once, even though no sample marks the
    beginning of the silence. Counting only gaps BETWEEN samples would miss
    exactly the tokens that stall hardest.
    """
    if end <= start:
        return 0
    marks = [start] + [p.ts for p in curve if start < p.ts <= end] + [end]
    threshold = timedelta(minutes=threshold_min)
    return sum(1 for a, b in itertools.pairwise(marks) if b - a >= threshold)


def retraced(curve: Sequence[CurvePoint], start: datetime, end: datetime, *,
             drop_pts: Decimal) -> bool:
    """Whether progress fell `drop_pts` from a running peak between the two.

    Peak-to-trough rather than versus the checkpoint level: a token that runs
    from 70 to 84 and falls back to 78 has given up six points, and reading
    only "is it below 70" would call that a clean run.
    """
    peak: Decimal | None = None
    for point in curve:
        if not (start <= point.ts <= end) or point.progress_pct is None:
            continue
        peak = point.progress_pct if peak is None else max(peak, point.progress_pct)
        if peak - point.progress_pct >= drop_pts:
            return True
    return False


# --- outcomes -----------------------------------------------------------------

def price_at(prices: Sequence[PricePoint], at: datetime) -> Decimal | None:
    """Forward-filled price. The last observation at or before `at`."""
    latest: Decimal | None = None
    for point in prices:
        if point.ts > at:
            break
        latest = point.price_usd
    return latest


def minutes_covered(prices: Sequence[PricePoint], open_at: datetime, *,
                    window_min: int) -> int:
    """Distinct whole minutes of the window carrying at least one sample.

    The coverage test, and the thing `sample_gap_flag` reports. Counted in
    minute buckets rather than by row, because two samples in one minute do not
    cover two minutes.
    """
    buckets = {
        int((p.ts - open_at).total_seconds() // 60)
        for p in prices
        if 0 <= (p.ts - open_at).total_seconds() < window_min * 60
    }
    return len(buckets)


def returns(prices: Sequence[PricePoint], open_price: Decimal, open_at: datetime,
            offsets: Sequence[int]) -> dict[int, Decimal | None]:
    """Forward-filled return at each offset, as a fraction of the open."""
    out: dict[int, Decimal | None] = {}
    for offset in offsets:
        price = price_at(prices, open_at + timedelta(minutes=offset))
        out[offset] = (
            None if price is None or open_price <= 0
            else (price / open_price - 1).quantize(_RET_DP)
        )
    return out


def extremes(prices: Sequence[PricePoint], open_price: Decimal, open_at: datetime,
             *, window_min: int) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Best return, worst peak-to-trough drawdown, and minutes to the peak.

    The drawdown is measured from a RUNNING peak, not from the open: a token
    that doubles and halves has drawn down 50%, and measuring against the open
    would report it as flat.
    """
    window = [p for p in prices
              if 0 <= (p.ts - open_at).total_seconds() <= window_min * 60]
    if not window or open_price <= 0:
        return None, None, None

    best = max(window, key=lambda p: p.price_usd)
    max_return = (best.price_usd / open_price - 1).quantize(_RET_DP)
    minutes_to_peak = _minutes(best.ts - open_at)

    peak = open_price
    drawdown = Decimal(0)
    for point in window:
        peak = max(peak, point.price_usd)
        if peak > 0:
            drawdown = min(drawdown, (point.price_usd / peak - 1))
    return max_return, drawdown.quantize(_RET_DP), minutes_to_peak


# --- the engine ---------------------------------------------------------------

class FeatureEngine:
    """Reads the five recorded tables, writes one `grad_features` row a token."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, *, now: datetime | None = None,
                  recompute: bool = False,
                  limit: int | None = None) -> dict[str, Any]:
        """One pass. Returns what it did, so a beat log is readable."""
        now = now or datetime.now(UTC)
        mints = await self.population(now, recompute=recompute,
                                      limit=limit or config.FEATURES_MAX_PER_RUN)
        rows, with_outcome = [], 0
        for mint in mints:
            row = await self.compute(mint)
            if row is None:
                continue
            rows.append(row)
            with_outcome += bool(row["outcome_ok"])
        if rows:
            await self._write(rows, now)
        return {"considered": len(mints), "written": len(rows),
                "with_outcome": with_outcome}

    async def population(self, now: datetime, *, recompute: bool = False,
                         limit: int = 500) -> list[str]:
        """Graduated tokens whose OUTCOME window has closed.

        A token counts as graduated on EITHER signal — the websocket migration
        message or the chain's own `complete` flag — because they are
        independent and either may arrive alone.

        Readiness is measured from the POOL OPEN, not from the graduation. The
        two are not the same moment: the first post-graduation price lands
        whenever DexScreener first answers, which is minutes later, and the
        outcome window runs from there. Gating on the graduation computes a
        token while its prices are still arriving — it then fails the coverage
        floor and, because a written row is never revisited, stays null for
        ever. That is how a lab ends up with no usable outcomes at all.

        Tokens with no post-graduation prices fall back to the graduation
        time, so a token that never got a single price still ages out instead
        of waiting for an open that will never come.
        """
        ready_after = timedelta(
            minutes=config.OUTCOME_WINDOW_MIN + config.FEATURES_SETTLE_MIN)
        deadline = now - ready_after

        opened = (select(GradPostgradSample.mint.label("mint"),
                         func.min(GradPostgradSample.ts).label("open_at"))
                  .group_by(GradPostgradSample.mint).subquery())

        from_feed = select(GradMigration.mint.label("mint"),
                           GradMigration.ts.label("at"))
        from_chain = select(GradCurveSample.mint.label("mint"),
                            func.min(GradCurveSample.ts).label("at")).where(
            GradCurveSample.complete.is_(True)).group_by(GradCurveSample.mint)
        union = from_feed.union(from_chain).subquery()

        graduated_at = func.min(union.c.at)
        # The clock the window actually runs on.
        starts_at = func.coalesce(func.min(opened.c.open_at), graduated_at)

        query = (select(union.c.mint)
                 .select_from(union.outerjoin(
                     opened, opened.c.mint == union.c.mint))
                 .group_by(union.c.mint)
                 .having(starts_at <= deadline))
        if not recompute:
            # Rows already written are skipped — UNLESS their outcome was
            # rejected for thin coverage and the window has since filled. Those
            # are exactly the rows this gate used to strand.
            stale = select(GradFeature.mint).where(
                GradFeature.outcome_ok.is_(True))
            query = query.where(union.c.mint.not_in(stale))
        query = query.order_by(starts_at).limit(limit)
        return [row.mint for row in (await self._session.execute(query)).all()]

    async def compute(self, mint: str) -> dict[str, Any] | None:
        """Everything known about one graduated token, as one row."""
        token = await self._session.get(GradToken, mint)
        curve = await self._curve(mint)
        checkpoints = await self._checkpoints(mint)
        prices = await self._prices(mint)
        graduated_at = await self._graduated_at(mint, curve)
        if graduated_at is None:
            return None

        launch_at = token.first_seen_at if token else None
        row: dict[str, Any] = {
            "mint": mint,
            "graduated_at": graduated_at,
            "launch_at": launch_at,
            "quote_currency": (token.quote_currency if token else None),
            "curve_sample_count": len(curve),
        }
        row |= self._features(curve, checkpoints, launch_at=launch_at,
                              graduated_at=graduated_at)
        row |= self._outcomes(prices, curve, graduated_at=graduated_at)
        return row

    # --- features -----------------------------------------------------------

    def _features(self, curve: list[CurvePoint], checkpoints: dict[Decimal, GradCheckpoint],
                  *, launch_at: datetime | None,
                  graduated_at: datetime) -> dict[str, Any]:
        """One block per level. A level never reached leaves its block null —
        the token is still written, because "got to 70 and died" is the row
        Phase 3 most needs and dropping it would condition on success."""
        at_70 = checkpoints[Decimal(70)].ts if Decimal(70) in checkpoints else None
        out: dict[str, Any] = {}
        for level in config.FEATURE_LEVELS:
            prefix = f"f{int(level)}_"
            checkpoint = checkpoints.get(level)
            if checkpoint is None:
                out |= {f"{prefix}{name}": None for name in _FEATURE_NAMES}
                continue
            at = checkpoint.ts
            out |= {
                f"{prefix}at": at,
                f"{prefix}minutes_since_launch": (
                    _minutes(at - launch_at) if launch_at else None),
                f"{prefix}minutes_from_70": (
                    _minutes(at - at_70) if at_70 else None),
                f"{prefix}velocity_5m": velocity(curve, at, 5, launch_at=launch_at),
                f"{prefix}velocity_15m": velocity(curve, at, 15, launch_at=launch_at),
                f"{prefix}changes_15m": changes_within(
                    curve, at, config.ACTIVITY_WINDOW_MIN),
                f"{prefix}stall_count": (
                    stall_count(curve, at_70, at, threshold_min=config.STALL_MIN)
                    if at_70 else None),
                f"{prefix}market_cap_quote": checkpoint.market_cap_quote,
                f"{prefix}retrace_flag": retraced(
                    curve, at, graduated_at, drop_pts=config.RETRACE_DROP_PTS),
            }
        return out

    # --- outcomes -----------------------------------------------------------

    def _outcomes(self, prices: list[PricePoint], curve: list[CurvePoint], *,
                  graduated_at: datetime) -> dict[str, Any]:
        """Returns relative to the pool open — the first post-graduation price,
        and the earliest price anything could actually have been bought at."""
        blank = dict.fromkeys(_OUTCOME_NAMES)
        complete_at = next((p.ts for p in curve if p.complete), None)
        if not prices:
            return blank | {"postgrad_minutes_covered": 0, "outcome_ok": False,
                            "sample_gap_flag": True}

        open_point = prices[0]
        covered = minutes_covered(prices, open_point.ts,
                                  window_min=config.OUTCOME_WINDOW_MIN)
        ok = covered >= config.OUTCOME_MIN_COVERAGE_MIN
        out: dict[str, Any] = blank | {
            "open_at": open_point.ts,
            "open_price_usd": open_point.price_usd,
            "postgrad_minutes_covered": covered,
            # "Missing and not backfilled": a GeckoTerminal candle counts as
            # covering its minute, so only a minute nothing filled is a gap.
            "sample_gap_flag": covered < config.OUTCOME_WINDOW_MIN,
            "backfilled_samples": sum(
                1 for p in prices if p.source == SOURCE_GECKOTERMINAL),
            "migration_lag_min": (
                _minutes(open_point.ts - complete_at) if complete_at else None),
            "outcome_ok": ok,
        }
        if not ok:
            # Everything below this line would be a number with no error bar,
            # and Phase 3 would be judged on it.
            return out

        by_offset = returns(prices, open_point.price_usd, open_point.ts,
                            config.RETURN_OFFSETS_MIN)
        out |= {f"return_{offset}m": value for offset, value in by_offset.items()}
        best, drawdown, to_peak = extremes(
            prices, open_point.price_usd, open_point.ts,
            window_min=config.OUTCOME_WINDOW_MIN)
        out |= {"max_return_60m": best, "max_drawdown_60m": drawdown,
                "minutes_to_peak": to_peak}
        return out

    # --- reads --------------------------------------------------------------

    async def _curve(self, mint: str) -> list[CurvePoint]:
        rows = (await self._session.execute(
            select(GradCurveSample.ts, GradCurveSample.progress_pct,
                   GradCurveSample.market_cap_quote, GradCurveSample.complete)
            .where(GradCurveSample.mint == mint)
            .order_by(GradCurveSample.ts))).all()
        return [CurvePoint(ts=r.ts, progress_pct=r.progress_pct,
                           market_cap_quote=r.market_cap_quote,
                           complete=r.complete) for r in rows]

    async def _checkpoints(self, mint: str) -> dict[Decimal, GradCheckpoint]:
        rows = (await self._session.scalars(
            select(GradCheckpoint).where(GradCheckpoint.mint == mint))).all()
        return {row.level_pct: row for row in rows}

    async def _prices(self, mint: str) -> list[PricePoint]:
        rows = (await self._session.execute(
            select(GradPostgradSample.ts, GradPostgradSample.price_usd,
                   GradPostgradSample.source)
            .where(GradPostgradSample.mint == mint,
                   GradPostgradSample.price_usd.is_not(None))
            .order_by(GradPostgradSample.ts))).all()
        return [PricePoint(ts=r.ts, price_usd=r.price_usd, source=r.source)
                for r in rows]

    async def _graduated_at(self, mint: str,
                            curve: list[CurvePoint]) -> datetime | None:
        """The earlier of the two independent signals."""
        candidates = [p.ts for p in curve if p.complete]
        feed = await self._session.scalar(
            select(GradMigration.ts).where(GradMigration.mint == mint))
        if feed is not None:
            candidates.append(feed)
        return min(candidates) if candidates else None

    async def _write(self, rows: list[dict[str, Any]], now: datetime) -> None:
        """Idempotent on the mint. DO UPDATE rather than DO NOTHING: a re-run
        after a post-graduation backfill should correct a row whose outcomes
        were null for want of coverage, not leave the old one standing."""
        for row in rows:
            row["computed_at"] = now
        statement = insert(GradFeature).values(rows)
        updates = {k: getattr(statement.excluded, k) for k in rows[0] if k != "mint"}
        await self._session.execute(
            statement.on_conflict_do_update(index_elements=["mint"], set_=updates))


#: The per-level feature block, so a missing checkpoint can null all of it
#: without listing the names twice.
_FEATURE_NAMES = (
    "at", "minutes_since_launch", "minutes_from_70", "velocity_5m",
    "velocity_15m", "changes_15m", "stall_count", "market_cap_quote",
    "retrace_flag",
)
_OUTCOME_NAMES = (
    "open_at", "open_price_usd", "postgrad_minutes_covered", "sample_gap_flag",
    "backfilled_samples", "migration_lag_min", "outcome_ok",
    "max_return_60m", "max_drawdown_60m", "minutes_to_peak",
    *(f"return_{offset}m" for offset in config.RETURN_OFFSETS_MIN),
)


# --- the summary Phase 3 is judged against -----------------------------------

#: One row per metric. Deliberately plain SQL and not an ORM expression: this is
#: meant to be copied into psql and run by hand, and a query you cannot paste is
#: a query nobody checks.
#:
#: `outcome_ok` is the whole point of the WHERE clause. Rows whose coverage was
#: too thin carry NULL returns; including them would not bias the percentiles
#: (NULLs are skipped) but WOULD make `n` a lie about how much was measured.
SUMMARY_SQL = """
SELECT
    metric,
    count(*)                                                   AS n,
    round(avg(value)::numeric, 4)                              AS mean,
    round(stddev_samp(value)::numeric, 4)                      AS stdev,
    round(min(value)::numeric, 4)                              AS min,
    round((percentile_cont(0.10) WITHIN GROUP (ORDER BY value))::numeric, 4) AS p10,
    round((percentile_cont(0.25) WITHIN GROUP (ORDER BY value))::numeric, 4) AS p25,
    round((percentile_cont(0.50) WITHIN GROUP (ORDER BY value))::numeric, 4) AS median,
    round((percentile_cont(0.75) WITHIN GROUP (ORDER BY value))::numeric, 4) AS p75,
    round((percentile_cont(0.90) WITHIN GROUP (ORDER BY value))::numeric, 4) AS p90,
    round((percentile_cont(0.99) WITHIN GROUP (ORDER BY value))::numeric, 4) AS p99,
    round(max(value)::numeric, 4)                              AS max,
    round(avg((value > 0)::int)::numeric, 4)                   AS share_positive,
    round(avg((value >= 0.25)::int)::numeric, 4)               AS share_ge_25pct,
    round(avg((value >= 1.0)::int)::numeric, 4)                AS share_ge_2x
FROM (
    SELECT 'return_5m'      AS metric, return_5m      AS value FROM grad_features
     WHERE outcome_ok AND return_5m IS NOT NULL
    UNION ALL
    SELECT 'max_return_60m' AS metric, max_return_60m AS value FROM grad_features
     WHERE outcome_ok AND max_return_60m IS NOT NULL
) AS m
GROUP BY metric
ORDER BY metric DESC
"""

#: The denominator the percentiles above do NOT show: how much was thrown away,
#: and why. A distribution over survivors reads well and means little.
COVERAGE_SQL = """
SELECT
    count(*)                                        AS graduates,
    count(*) FILTER (WHERE outcome_ok)              AS with_outcome,
    count(*) FILTER (WHERE NOT outcome_ok)          AS dropped_thin_coverage,
    count(*) FILTER (WHERE sample_gap_flag)         AS any_gap,
    count(*) FILTER (WHERE launch_at IS NULL)       AS never_watched_pre_grad,
    count(*) FILTER (WHERE f70_at IS NOT NULL)      AS reached_70,
    count(*) FILTER (WHERE f80_at IS NOT NULL)      AS reached_80,
    count(*) FILTER (WHERE f90_at IS NOT NULL)      AS reached_90,
    count(*) FILTER (WHERE f95_at IS NOT NULL)      AS reached_95,
    round(avg(postgrad_minutes_covered)::numeric, 1) AS mean_minutes_covered
FROM grad_features
"""


async def summary(session: AsyncSession) -> dict[str, Any]:
    """The distribution of `return_5m` and `max_return_60m`, plus what it omits.

    This is the number Phase 3 is judged against, so it ships with its own
    denominator: a percentile table over the rows that happened to have clean
    coverage, with no count of the rows that did not, is the shape of every
    fake edge this platform has already found.
    """
    coverage = (await session.execute(text(COVERAGE_SQL))).mappings().one()
    rows = (await session.execute(text(SUMMARY_SQL))).mappings().all()
    return {"coverage": dict(coverage),
            "distribution": [dict(row) for row in rows]}


def format_summary(payload: dict[str, Any]) -> str:
    """The same thing as a table, for the CLI."""
    coverage = payload["coverage"]
    lines = [
        "coverage",
        "--------",
        f"  graduates                {coverage['graduates']}",
        f"  with a usable outcome    {coverage['with_outcome']}",
        f"  dropped, thin coverage   {coverage['dropped_thin_coverage']}",
        f"  had at least one gap     {coverage['any_gap']}",
        f"  never watched pre-grad   {coverage['never_watched_pre_grad']}",
        f"  reached 70/80/90/95      {coverage['reached_70']}/{coverage['reached_80']}"
        f"/{coverage['reached_90']}/{coverage['reached_95']}",
        f"  mean minutes covered     {coverage['mean_minutes_covered']}",
        "",
    ]
    if not payload["distribution"]:
        lines.append("no rows with a usable outcome yet")
        return "\n".join(lines)

    header = (f"{'metric':<16}{'n':>6}{'mean':>10}{'p10':>10}{'p25':>10}"
              f"{'median':>10}{'p75':>10}{'p90':>10}{'p99':>10}{'max':>12}"
              f"{'>0':>8}{'>=+25%':>9}{'>=2x':>8}")
    lines += [header, "-" * len(header)]
    for row in payload["distribution"]:
        lines.append(
            f"{row['metric']:<16}{row['n']:>6}{_f(row['mean']):>10}"
            f"{_f(row['p10']):>10}{_f(row['p25']):>10}{_f(row['median']):>10}"
            f"{_f(row['p75']):>10}{_f(row['p90']):>10}{_f(row['p99']):>10}"
            f"{_f(row['max']):>12}{_f(row['share_positive']):>8}"
            f"{_f(row['share_ge_25pct']):>9}{_f(row['share_ge_2x']):>8}")
    lines += [
        "",
        "Returns are FRACTIONS of the pool-open price: 0.25 is +25%, 1.0 is a 2x.",
        "`max_return_60m` is the best price in the window, which nothing can",
        "systematically capture — it is the ceiling on any exit rule, not a result.",
    ]
    return "\n".join(lines)


def _f(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"
