"""Data-quality report, per-meme audit trail and research-status gate: orchestration.

Owns no rule. Reads through ``QualityRepository`` (SQL) and the Lab's existing
repository/service, hands rows to the pure engines (``research_status`` for the
gate; attention / market / states / divergence for a meme's current reading),
and shapes the result into the API contract (docs/MEME_LIFECYCLE_LAB.md, "NEW
API CONTRACT"). It never commits and never writes.

Two conventions to keep:

* Nothing here looks past ``now``. Every query is bounded by it, so a report
  asked for a past instant describes that instant.
* A figure that could not be measured is null (or a requirement with
  ``met=false`` and a reason), never 0. A source with no runs has no success
  rate; it does not have a rate of 100% or 0%.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lifecycle_lab import attention as attention_engine
from app.lifecycle_lab import divergence as divergence_engine
from app.lifecycle_lab import market as market_engine
from app.lifecycle_lab import priority as priority_engine
from app.lifecycle_lab import research_status as gate
from app.lifecycle_lab import states as states_engine
from app.lifecycle_lab.config import DEFAULT_CONFIG, LabConfig
from app.lifecycle_lab.domain import Arm, ResearchMode, Source, SourceStatus
from app.lifecycle_lab.portfolio import STATUS_CLOSED
from app.lifecycle_lab.quality_repository import (
    MARKET_FIELDS,
    QualityRepository,
    TradeRow,
)
from app.lifecycle_lab.service import (
    DAY,
    FORWARD_HISTORY_LOOKBACK,
    FORWARD_SEGMENT,
    RADAR_MARKET_LOOKBACK,
    SOURCE_LABELS,
    LifecycleLabService,
    _dec_str,
    experiment_key,
    measured,
    parse_forward_start,
    partition,
    primary_link,
)

WEEK = timedelta(days=7)

#: Current-health statuses that mean "this source is not delivering data":
#: refused, errored, or switched off. ``never_collected`` is not here — it has
#: not been attempted, which is a different fact — and neither is ``stale`` or
#: ``partial``, which are listed separately / per source.
UNAVAILABLE_STATUSES = frozenset(
    {SourceStatus.UNAVAILABLE.value, SourceStatus.ERROR.value, SourceStatus.DISABLED.value}
)

#: Control arms the gate requires, by the letter the contract uses.
CONTROL_ARMS: dict[str, Arm] = {
    "B": Arm.CONTROL_B_MARKET_ONLY,
    "C": Arm.CONTROL_C_ATTENTION_ONLY,
    "D": Arm.CONTROL_D_COMBINED,
}


def _rate(numerator: int, denominator: int) -> str | None:
    """A 3-place fraction string; null when nothing could have succeeded."""
    if denominator <= 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_EVEN
    )
    return format(value, "f")


def _requirement_out(r: gate.Requirement) -> dict[str, Any]:
    return {
        "key": r.key,
        "label": r.label,
        "threshold": r.threshold,
        "observed": r.observed,
        "met": r.met,
        "reason": r.reason,
    }


def research_status_out(status: gate.ResearchStatus) -> dict[str, Any]:
    return {
        "state": status.state.value,
        "verdict": status.verdict,
        "verdict_engine_available": status.verdict_engine_available,
        "forward_start": status.forward_start,
        "forward_days": status.forward_days,
        "experiment_key": status.experiment_key,
        "requirements": [_requirement_out(r) for r in status.requirements],
        "explanation": status.explanation,
    }


def _closed(trades: list[TradeRow], now: datetime) -> list[TradeRow]:
    return [
        t
        for t in trades
        if t.status == STATUS_CLOSED and t.exit_at is not None and t.exit_at <= now
    ]


class QualityService:
    def __init__(self, session: AsyncSession, *, cfg: LabConfig = DEFAULT_CONFIG) -> None:
        self.session = session
        self.cfg = cfg
        self.lab = LifecycleLabService(session, cfg=cfg)
        self.repo = QualityRepository(session)

    # ------------------------------------------------------------------
    # GET /quality
    # ------------------------------------------------------------------

    async def report(self, now: datetime) -> dict[str, Any]:
        memes = await self.repo.tracked_meme_refs()
        links = await self.repo.current_links(now)
        mints = sorted({k.mint for k in links})

        midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
        today = await self.repo.observation_split(since=midnight, until=now, mints=mints)
        week = await self.repo.observation_split(since=now - WEEK, until=now, mints=mints)
        oldest, newest = await self.repo.forward_range(until=now, mints=mints)

        health = {s["source"]: s for s in await self.lab._sources(now)}
        counts = await self.repo.run_status_counts(since=now - DAY, until=now)
        by_source: list[dict[str, Any]] = []
        totals = dict.fromkeys(("runs", "available", "disabled", "failures"), 0)
        for source in sorted(Source, key=lambda s: s.value):
            per = {st.value: counts.get((source.value, st.value), 0) for st in SourceStatus}
            runs = sum(counts.get((source.value, st), 0) for st in _statuses(counts, source))
            last = await self.repo.latest_run(source.value, until=now)
            last_ok = await self.repo.latest_run(
                source.value, until=now, status=SourceStatus.AVAILABLE
            )
            by_source.append(
                {
                    "source": source.value,
                    "label": SOURCE_LABELS[source],
                    "runs_24h": runs,
                    "available": per[SourceStatus.AVAILABLE.value],
                    "unavailable": per[SourceStatus.UNAVAILABLE.value],
                    "disabled": per[SourceStatus.DISABLED.value],
                    "error": per[SourceStatus.ERROR.value],
                    "stale": per[SourceStatus.STALE.value],
                    "partial": per[SourceStatus.PARTIAL.value],
                    "success_rate_24h": _rate(
                        per[SourceStatus.AVAILABLE.value],
                        runs - per[SourceStatus.DISABLED.value],
                    ),
                    "last_success_at": None if last_ok is None else last_ok["finished_at"],
                    "last_status": None if last is None else last["status"],
                    "last_reason": None if last is None else last["reason"],
                }
            )
            totals["runs"] += runs
            totals["available"] += per[SourceStatus.AVAILABLE.value]
            totals["disabled"] += per[SourceStatus.DISABLED.value]
            totals["failures"] += (
                per[SourceStatus.UNAVAILABLE.value] + per[SourceStatus.ERROR.value]
            )

        summaries = await self.repo.market_summaries(mints, until=now)
        no_history = [
            {"mint": k.mint, "meme_slug": k.meme_slug}
            for k in links
            if k.mint not in summaries
        ]
        incomplete = [
            {
                "mint": k.mint,
                "meme_slug": k.meme_slug,
                "missing": list(summaries[k.mint].missing_fields),
            }
            for k in links
            if k.mint in summaries
            and summaries[k.mint].has_forward
            and summaries[k.mint].missing_fields
        ]

        return {
            "generated_at": now,
            "tracked_memes": len(memes),
            "tracked_tokens": len(mints),
            "observations_today": {"forward": today["forward"], "backfill": today["backfill"]},
            "observations_week": {"forward": week["forward"], "backfill": week["backfill"]},
            "collection": {
                "runs_24h": totals["runs"],
                "failures_24h": totals["failures"],
                "success_rate_24h": _rate(
                    totals["available"], totals["runs"] - totals["disabled"]
                ),
                "by_source": by_source,
            },
            "unavailable_sources": sorted(
                s for s, h in health.items() if h["status"] in UNAVAILABLE_STATUSES
            ),
            "stale_sources": sorted(
                s for s, h in health.items() if h["status"] == SourceStatus.STALE.value
            ),
            "oldest_forward_observation_at": oldest,
            "newest_forward_observation_at": newest,
            "memes_without_observations": await self.repo.memes_without_observations(now),
            "tokens_without_market_history": no_history,
            "tokens_with_incomplete_market_data": incomplete,
        }

    # ------------------------------------------------------------------
    # GET /memes/{slug}/quality
    # ------------------------------------------------------------------

    async def meme_quality(self, slug: str, now: datetime) -> dict[str, Any] | None:
        record = await self.lab.repo.meme_record(slug)
        meme = await self.lab.repo.get_meme_by_slug(slug)
        if record is None or meme is None:
            return None

        inputs = await self.lab._load(
            [meme],
            until=now,
            since=now - FORWARD_HISTORY_LOOKBACK,
            market_since=now - RADAR_MARKET_LOOKBACK,
            include_backfill=False,
        )
        mi = partition(inputs)[0]
        # The same evaluation the radar makes, at `now`, AUTHORITATIVE: the
        # gate, then the pure engines — nothing is computed here.
        state = mi.state(now, ResearchMode.AUTHORITATIVE, self.cfg)
        attn = attention_engine.attention_features(state, self.cfg.attention)
        primary = primary_link(state.links)
        mf = (
            None
            if primary is None
            else market_engine.market_features(state, primary.mint_address)
        )
        prior = (
            await self.lab._prior_events([meme.id], since=now - FORWARD_HISTORY_LOOKBACK - DAY)
        ).get(meme.id, ())
        lifecycle = states_engine.classify_state(
            state=state, attention=attn, market=mf, prior_events=prior, cfg=self.cfg.events
        )
        divergence = divergence_engine.classify_divergence(attn, mf, self.cfg.events)

        links = [k for k in await self.repo.link_audit(meme.id) if k["linked_at"] <= now]
        mints = sorted({k["mint"] for k in links})
        health = {s["source"]: s for s in await self.lab._sources(now)}
        seen = {
            c.source: c
            for c in await self.repo.source_counts(meme_id=meme.id, mints=mints, until=now)
        }
        sources: list[dict[str, Any]] = []
        for source in sorted(Source, key=lambda s: s.value):
            c = seen.get(source.value)
            h = health[source.value]
            sources.append(
                {
                    "source": source.value,
                    "label": SOURCE_LABELS[source],
                    "status": h["status"],
                    "reason": h["reason"],
                    "first_observation_at": None if c is None else c.first_at,
                    "latest_observation_at": None if c is None else c.latest_at,
                    "observation_count": 0
                    if c is None
                    else c.forward_count + c.backfill_count,
                    "forward_count": 0 if c is None else c.forward_count,
                    "backfill_count": 0 if c is None else c.backfill_count,
                }
            )

        summaries = await self.repo.market_summaries(mints, until=now)
        market: list[dict[str, Any]] = []
        for mint in mints:
            m = summaries.get(mint)
            market.append(
                {
                    "mint": mint,
                    "first_observation_at": None if m is None else m.first_at,
                    "latest_observation_at": None if m is None else m.latest_at,
                    "observation_count": 0 if m is None else m.observation_count,
                    # No forward snapshot at all means every field is unobserved.
                    "missing_fields": (
                        list(MARKET_FIELDS)
                        if m is None or not m.has_forward
                        else list(m.missing_fields)
                    ),
                }
            )

        # Collection frequency only (priority.py); the service owns the
        # point-in-time classification it is derived from.
        prio = (await self.lab.collection_priorities(now, meme_ids=[meme.id]))[meme.id]

        return {
            "meme": {
                "slug": record["slug"],
                "display_name": record["display_name"],
                "description": record["description"],
                "tracking_started_at": record["tracking_started_at"],
                "wikipedia_title": record["wikipedia_title"],
                "gdelt_query": record["gdelt_query"],
            },
            "aliases": [
                {"alias": a.alias, "kind": a.kind.value, "added_at": a.added_at}
                for a in mi.aliases
                if a.added_at <= now
            ],
            "links": [
                {
                    "mint": k["mint"],
                    "method": k["method"],
                    "confidence": _dec_str(k["confidence"]),
                    "linked_at": k["linked_at"],
                    "unlinked_at": k["unlinked_at"],
                    "linked_by": k["linked_by"],
                    "evidence": k["evidence"],
                }
                for k in links
            ],
            "sources": sources,
            "market": market,
            "lifecycle_state": lifecycle.value,
            "attention": {
                "mentions_1h": measured(attn.mentions_1h),
                "velocity": measured(attn.velocity),
                "acceleration": measured(attn.acceleration),
                "baseline_multiple": measured(attn.baseline_multiple),
            },
            "divergence_case": divergence.value,
            "collection_priority": {
                "level": prio.level.value,
                "interval_seconds": int(prio.interval.total_seconds()),
                "reason": priority_reason_text(prio.reason),
            },
        }

    # ------------------------------------------------------------------
    # GET /research-status
    # ------------------------------------------------------------------

    async def research_status(self, now: datetime) -> dict[str, Any]:
        fs = parse_forward_start()
        enabled = bool(settings.FEATURE_LIFECYCLE_LAB_ENABLED)
        bounds = (
            None
            if fs is None
            else await self.repo.experiment_bounds(experiment_key(fs, Arm.BASELINE))
        )
        experiment = (
            None
            if bounds is None
            else gate.ExperimentRef(
                experiment_key=bounds["experiment_key"], data_cutoff=bounds["data_cutoff"]
            )
        )
        facts = (
            gate.GateFacts()
            if fs is None or fs > now or not enabled
            else await self._facts(fs, now, bounds)
        )
        status = gate.evaluate(
            now=now, lab_enabled=enabled, forward_start=fs, experiment=experiment, facts=facts
        )
        return research_status_out(status)

    async def _facts(
        self, fs: datetime, now: datetime, bounds: dict[str, Any] | None
    ) -> gate.GateFacts:
        episodes = await self.repo.episode_events(since=fs, until=now)
        independent = gate.count_independent_events(episodes)
        later = gate.count_later_wave_events(episodes)
        span = now - fs

        no_experiment = "The baseline experiment is not registered yet."
        no_run = "No completed baseline forward run exists yet."
        reasons: dict[str, str] = {}
        base_keys = (
            gate.KEY_BASELINE_TRADES,
            gate.KEY_OOS_TRADES,
            gate.KEY_DISTINCT_MEMES,
            gate.KEY_CONCENTRATION,
            gate.KEY_CONTROL_ARMS,
        )

        def unmeasured(why: str) -> gate.GateFacts:
            return gate.GateFacts(
                forward_span=span,
                independent_events=independent,
                revival_events=later,
                reasons={**dict.fromkeys(base_keys, why), **reasons},
            )

        if bounds is None:
            return unmeasured(no_experiment)
        base = await self.repo.forward_run(bounds["id"], segment=FORWARD_SEGMENT)
        if base is None or base["status"] != "completed":
            return unmeasured(no_run)

        closed = _closed(await self.repo.baseline_trades(base["id"], until=now), now)
        per_meme: dict[str, int] = {}
        for t in closed:
            per_meme[t.meme_id] = per_meme.get(t.meme_id, 0) + 1
        top_share = Decimal(max(per_meme.values())) / Decimal(len(closed)) if closed else None
        if top_share is None:
            reasons[gate.KEY_CONCENTRATION] = "No closed baseline trades to measure."

        oos: int | None = None
        t0, t1 = bounds["test_start"], bounds["test_end"]
        if t0 is None or t1 is None:
            reasons[gate.KEY_OOS_TRADES] = "The experiment has no test segment."
        else:
            oos = sum(1 for t in closed if t0 <= t.entry_at < t1)

        completed: set[str] = set()
        for letter, arm in CONTROL_ARMS.items():
            control = await self.repo.experiment_bounds(experiment_key(fs, arm))
            run = (
                None
                if control is None
                else await self.repo.forward_run(control["id"], segment=FORWARD_SEGMENT)
            )
            if (
                run is not None
                and run["status"] == "completed"
                and run["window_start"] == base["window_start"]
                and run["window_end"] == base["window_end"]
            ):
                completed.add(letter)

        return gate.GateFacts(
            forward_span=span,
            independent_events=independent,
            revival_events=later,
            baseline_trades=len(closed),
            oos_trades=oos,
            distinct_memes=len(per_meme),
            top_meme_share=top_share,
            control_arms_completed=frozenset(completed),
            reasons=reasons,
        )


def _statuses(counts: dict[tuple[str, str], int], source: Source) -> list[str]:
    """Every status seen for ``source``, so a status added to the enum later is
    still counted in ``runs_24h``."""
    return sorted({st for (src, st) in counts if src == source.value})


def priority_reason_text(code: str) -> str:
    """Prose for a ``priority`` reason code, rendered here and never stored."""
    head, _, state = code.partition(":")
    if head == priority_engine.REASON_STATE and state:
        return f"Lifecycle state is {state}."
    if head == priority_engine.REASON_LAST_KNOWN and state:
        return f"No fresh reading; the last known lifecycle state was {state}."
    if code == priority_engine.REASON_UNKNOWN_RECENT:
        return "Lifecycle state is unknown, but a reading arrived within the last 24 hours."
    if code == priority_engine.REASON_UNKNOWN_NO_RECENT:
        return "Lifecycle state is unknown and no reading arrived within the last 24 hours."
    return code
