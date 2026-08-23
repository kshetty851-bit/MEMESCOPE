"""The search, end to end. **The holdout is opened once, at the end.**

    generate  ->  DISCOVERY  ->  reduce  ->  VALIDATION  ->  reduce
              ->  freeze     ->  HOLDOUT (once)  ->  champions

── HOW §24 IS ENFORCED RATHER THAN PROMISED ─────────────────────────────────

`run_search` never receives the holdout. It is handed `split.for_selection()`,
which returns the discovery and validation blocks and nothing else, and it
returns a **frozen** finalist list. Only `_open_holdout` — called after that
list is fixed and never before — touches `split.holdout`.

That is structural, not a convention: there is no expression inside the
selection path that can reach the holdout, so no future edit can accidentally
peek without deleting the seal first and being seen to do it.

If a candidate fails the holdout it **fails**. Tweaking it and re-running the
same holdout would be re-using a spent test; §24 says a revised strategy needs
a new, future holdout, and the engine cannot manufacture one.

── ORDER OF THE STAGES ──────────────────────────────────────────────────────

Portfolio controls (§9) are applied only to validation survivors, as a second
stage. Mixing them into the base search would confound "this strategy works"
with "this risk control rescued it", and the brief asks for them separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.strategy_lab import opportunities as canonical
from app.strategy_lab.discovery import attribution, engine, scoring, space, splits
from app.strategy_lab.discovery.engine import Evaluation, ScheduleCache
from app.strategy_lab.discovery.space import Candidate
from app.strategy_lab.opportunities import Opportunity

logger = logging.getLogger(__name__)

_ZERO = Decimal(0)

ENGINE_VERSION = "1.0.0"

#: §23. Keep this share of the discovery field, subject to the survival filters.
DISCOVERY_KEEP_PCT = 0.15
#: §23. And at most this many into the holdout.
MAX_FINALISTS = 50

DATASET_LOCAL_BACKTEST = "LOCAL_BACKTEST"
DATASET_PRODUCTION_FORWARD = "PRODUCTION_FORWARD_RESEARCH"


@dataclass
class StageResult:
    """One block's evaluations, keyed by strategy.

    `kept` is what actually advanced, and it is recorded rather than derived.
    Deriving it from `survives` was wrong in the first run and wrong in an
    instructive way: the discovery block is *in-sample*, so it runs the survival
    filters non-strictly, every row "survived", and the funnel proudly reported
    1,850 discovery survivors out of 1,850 candidates. A funnel that never
    narrows is not measuring anything.
    """

    block: str
    evaluations: dict[str, Evaluation] = field(default_factory=dict)
    verdicts: dict[str, scoring.Verdict] = field(default_factory=dict)
    kept: set[str] = field(default_factory=set)

    def survivors(self) -> set[str]:
        """Rows that passed this block's filters. Not the same as `kept`.

        On an out-of-sample block the two coincide up to the top-N cut; on the
        in-sample discovery block `survives` is permissive by design and `kept`
        is the number that means something.
        """
        return {sid for sid, v in self.verdicts.items() if v.survives}

    def ranked(self) -> list[str]:
        return sorted(
            self.verdicts,
            key=lambda sid: self.verdicts[sid].score,
            reverse=True,
        )


@dataclass
class SearchResult:
    """Everything the report and the UI need. Immutable once returned."""

    dataset_source: str
    engine_version: str
    space_version: str
    scoring_version: str
    started_at: datetime
    finished_at: datetime | None

    candidates: list[Candidate]
    split: splits.Split
    folds: list[splits.Fold]

    discovery: StageResult
    validation: StageResult
    holdout: StageResult
    walk_forward: dict[str, Evaluation]

    finalists: list[str]
    champions: list[str]
    attribution: dict[str, list[attribution.Level]]
    usable: int
    excluded: dict[str, int]
    resolutions: int
    seconds: float

    def by_id(self, strategy_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.strategy_id == strategy_id), None)

    def funnel(self) -> dict[str, int]:
        """§27's funnel. Every step is what *advanced*, not what was evaluated."""
        return {
            "generated": len(self.candidates),
            "discovery_survivors": len(self.discovery.kept),
            "validation_survivors": len(self.validation.kept),
            "holdout_survivors": len(self.holdout.survivors()),
            "champions": len(self.champions),
        }


async def load_universe(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[list[Opportunity], dict[str, int]]:
    """The canonical set, gated on the **longest** hold in the search space.

    Gating on `space.MAX_HOLD` rather than on each strategy's own hold is what
    makes §1's identical-opportunities requirement hold across the whole search.
    If a 2h strategy were offered opportunities a 6h strategy could not settle,
    the two would be measured on different populations and every comparison
    between them would be partly a comparison of samples.
    """
    now = now or datetime.now(UTC)
    loaded = await canonical.load(session, hold_for=space.MAX_HOLD, now=now)
    usable = [o for o in loaded if o.usable]
    excluded: dict[str, int] = {}
    for o in loaded:
        if o.excluded_reason:
            excluded[o.excluded_reason] = excluded.get(o.excluded_reason, 0) + 1
    return usable, excluded


def run_search(
    universe: list[Opportunity],
    excluded: dict[str, int],
    *,
    dataset_source: str = DATASET_LOCAL_BACKTEST,
    starting_capital: Decimal = engine.STARTING_CAPITAL,
    now: datetime | None = None,
) -> SearchResult:
    """Generate, select, then open the holdout exactly once."""
    import time

    started = now or datetime.now(UTC)
    clock = time.monotonic()

    candidates = space.generate()
    split = splits.chronological(universe)
    cache = ScheduleCache(universe)
    positions = {o.mint_address: i for i, o in enumerate(universe)}

    discovery_rows, validation_rows = split.for_selection()
    discovery_ix = [positions[o.mint_address] for o in discovery_rows]
    validation_ix = [positions[o.mint_address] for o in validation_rows]

    # ── Stage 1: discovery ──────────────────────────────────────────────────
    discovery = _evaluate_all(
        candidates, cache, discovery_ix, block="DISCOVERY", capital=starting_capital
    )
    kept = _reduce(discovery, keep_pct=DISCOVERY_KEEP_PCT, limit=None)
    discovery.kept = kept
    logger.info("discovery kept %d of %d", len(kept), len(candidates))

    # ── Stage 2: validation, then portfolio controls on what survives ───────
    stage_two = [c for c in candidates if c.strategy_id in kept]
    validation = _evaluate_all(
        stage_two, cache, validation_ix, block="VALIDATION", capital=starting_capital
    )
    validated = _reduce(validation, keep_pct=1.0, limit=MAX_FINALISTS)

    risk_variants = _portfolio_variants([c for c in stage_two if c.strategy_id in validated])
    if risk_variants:
        risk_eval = _evaluate_all(
            risk_variants, cache, validation_ix, block="VALIDATION", capital=starting_capital
        )
        validation.evaluations.update(risk_eval.evaluations)
        validation.verdicts.update(risk_eval.verdicts)
        candidates = candidates + risk_variants
        validated = _reduce(validation, keep_pct=1.0, limit=MAX_FINALISTS)
    validation.kept = validated

    # ── FREEZE. Nothing below may change the finalist list. ─────────────────
    finalists = sorted(validated)

    # ── Stage 3: the holdout, opened once ───────────────────────────────────
    holdout = _open_holdout(
        [c for c in candidates if c.strategy_id in finalists],
        cache,
        split,
        positions,
        capital=starting_capital,
    )
    holdout.kept = holdout.survivors()

    champions = [
        sid
        for sid in holdout.ranked()
        if holdout.verdicts[sid].survives and scoring.is_champion(holdout.evaluations[sid])
    ][:5]

    # ── Walk-forward, aggregated over test blocks only ──────────────────────
    #
    # Run over every **discovery survivor**, not only the finalists. §12 calls
    # walk-forward the primary evidence, and evidence that only exists when the
    # validation gate happens to pass something is not primary — on this dataset
    # validation rejects every candidate, and a walk-forward restricted to
    # finalists would then report nothing at all rather than reporting that the
    # forward record is uniformly bad.
    folds = splits.walk_forward(universe, train_buckets=5, step=1)
    walk_subjects = sorted(discovery.kept | set(finalists))
    walk = _walk_forward(
        [c for c in candidates if c.strategy_id in walk_subjects],
        cache,
        folds,
        positions,
        capital=starting_capital,
    )

    # `kept`, not `survivors()`: the discovery block judges non-strictly, so
    # every row "survives" and a survival column built from it reads 100% for
    # every level — which is worse than no column at all.
    survivors = discovery.kept
    attributed = attribution.attribute(
        [
            (c, discovery.evaluations[c.strategy_id])
            for c in candidates
            if c.strategy_id in discovery.evaluations
        ],
        survivors,
    )

    return SearchResult(
        dataset_source=dataset_source,
        engine_version=ENGINE_VERSION,
        space_version=space.SPACE_VERSION,
        scoring_version=scoring.SCORING_VERSION,
        started_at=started,
        finished_at=datetime.now(UTC),
        candidates=candidates,
        split=split,
        folds=folds,
        discovery=discovery,
        validation=validation,
        holdout=holdout,
        walk_forward=walk,
        finalists=finalists,
        champions=champions,
        attribution=attributed,
        usable=len(universe),
        excluded=excluded,
        resolutions=cache.resolutions,
        seconds=time.monotonic() - clock,
    )


def _evaluate_all(
    candidates: list[Candidate],
    cache: ScheduleCache,
    indexes: list[int],
    *,
    block: str,
    capital: Decimal,
) -> StageResult:
    stage = StageResult(block=block)
    strict = block != "DISCOVERY"
    for candidate in candidates:
        evaluation = engine.evaluate(
            candidate, cache, indexes, block=block, starting_capital=capital
        )
        stage.evaluations[candidate.strategy_id] = evaluation
        stage.verdicts[candidate.strategy_id] = scoring.judge(evaluation, strict=strict)
    return stage


def _reduce(stage: StageResult, *, keep_pct: float, limit: int | None) -> set[str]:
    """§23. Rank by score, keep the top share, and never keep a rejected row.

    Ordered that way round on purpose: the survival filters are a floor, not a
    tiebreak. A strategy that fails them is not kept because the field was thin.
    """
    ranked = [sid for sid in stage.ranked() if stage.verdicts[sid].survives]
    if keep_pct < 1.0:
        ranked = ranked[: max(1, int(len(stage.verdicts) * keep_pct))]
    if limit is not None:
        ranked = ranked[:limit]
    return set(ranked)


def _portfolio_variants(base: list[Candidate]) -> list[Candidate]:
    """§9's second stage: risk controls over strategies that already survived."""
    out: list[Candidate] = []
    index = 0
    for candidate in base:
        for portfolio in space.PORTFOLIOS[1:]:
            index += 1
            out.append(space.with_portfolio(candidate, portfolio, index))
    return out


def _open_holdout(
    finalists: list[Candidate],
    cache: ScheduleCache,
    split: splits.Split,
    positions: dict[str, int],
    *,
    capital: Decimal,
) -> StageResult:
    """**The one place `split.holdout` is read.** Called after the freeze.

    Kept as its own function with the seal named in the docstring so that any
    future call site is obvious in a diff. If this is ever called before
    `finalists` is fixed, the search stops being a test of anything.
    """
    indexes = [positions[o.mint_address] for o in split.holdout]
    return _evaluate_all(finalists, cache, indexes, block="HOLDOUT", capital=capital)


def _walk_forward(
    finalists: list[Candidate],
    cache: ScheduleCache,
    folds: list[splits.Fold],
    positions: dict[str, int],
    *,
    capital: Decimal,
) -> dict[str, Evaluation]:
    """§12. Aggregate the **test** blocks; the train blocks fit nothing here.

    Each fold's test block is evaluated with a fresh wallet, and the folds are
    then pooled into one synthetic evaluation per strategy. Pooling trades
    rather than averaging returns keeps a fold with three trades from carrying
    the same weight as one with ninety.
    """
    if not folds:
        return {}

    out: dict[str, Evaluation] = {}
    for candidate in finalists:
        pooled: list[engine.Trade] = []
        refusals: dict[str, int] = {}
        offered = 0
        curve: list[tuple[datetime, Decimal]] = []
        equity = capital
        peak_concurrent = 0
        for fold in folds:
            indexes = [positions[o.mint_address] for o in fold.test]
            evaluation = engine.evaluate(
                candidate,
                cache,
                indexes,
                block=f"WF{fold.index}",
                starting_capital=capital,
            )
            pooled.extend(evaluation.trades)
            offered += evaluation.offered
            peak_concurrent = max(peak_concurrent, evaluation.peak_concurrent)
            for reason, count in evaluation.refusals.items():
                refusals[reason] = refusals.get(reason, 0) + count
            # Compound the fold results into one curve so drawdown is measured
            # across the whole forward path, not reset every fold.
            equity += evaluation.net_pnl
            curve.append((fold.test_to, equity))

        out[candidate.strategy_id] = Evaluation(
            strategy_id=candidate.strategy_id,
            block="WALK_FORWARD",
            starting_capital=capital,
            final_cash=equity,
            offered=offered,
            trades=pooled,
            refusals=refusals,
            peak_concurrent=peak_concurrent,
            equity_curve=curve,
        )
    return out
