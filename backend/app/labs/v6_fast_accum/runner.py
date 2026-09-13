"""Orchestration: load, simulate, control, fold, test, gate, persist.

`RESEARCH_ONLY`. The only module here that touches the database, and it writes
to `v6lab_*` and nothing else.

## The order matters

Quality and leakage run BEFORE the gate, and a leakage finding aborts the run
rather than annotating it. A result computed from leaked features is not a
weaker result, it is a different experiment, and the gate would be scoring the
leak.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.v6_fast_accum import analysis, config, dataset, leakage, quality
from app.labs.v6_fast_accum.models import V6LabRun, V6LabTrade
from app.labs.v6_fast_accum.simulator import Trade, apply_position_limits, run_strategy


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def _experiment_id(now: datetime, seq: int = 1) -> str:
    return f"V6_FAST_ACCUM_{now:%Y_%m_%d}_{seq:03d}"


def _dec(v) -> float | None:
    return float(v) if isinstance(v, Decimal) else v


async def run(session: AsyncSession, *, now: datetime | None = None,
              lookback_hours: int = 24 * 14, persist: bool = True) -> dict:
    """Execute the whole experiment and return the result document."""
    started = now or datetime.now(UTC)
    ds = await dataset.load(session, now=started, lookback_hours=lookback_hours)

    # --- data quality, before anything is measured ---------------------------
    qr = quality.inspect(ds)

    # --- the three pre-registered candidates ---------------------------------
    by_cfg: dict[str, list[Trade]] = {
        c.name: apply_position_limits(run_strategy(ds, c)) for c in config.CANDIDATES
    }

    # --- leakage audit; a finding aborts -------------------------------------
    all_trades = [t for ts in by_cfg.values() for t in ts]
    leak_ok, findings = leakage.audit(all_trades)
    if not leak_ok:
        return {
            "experiment_id": _experiment_id(started),
            "verdict": "RUN ABORTED — LEAKAGE DETECTED",
            "leakage_passed": False,
            "leakage_findings": [f.__dict__ for f in findings[:50]],
        }

    # --- controls, on the primary candidate ----------------------------------
    # The candidate with the most trades is used as the control anchor. This is
    # a presentation choice only: the gate reads walk-forward selection, which
    # is made on train folds alone.
    anchor = max(config.CANDIDATES, key=lambda c: len(by_cfg[c.name]))
    controls = analysis.build_controls(ds, anchor)

    # With the Telegram overlay UNAVAILABLE the control design partly collapses,
    # and saying so is the difference between four controls and two. The base
    # rule already runs without Telegram, so base is CONTROL-B; and CONTROL-C
    # (curve + telegram, no mcap) is CONTROL-D (curve alone). Reported, not
    # quietly presented as four independent arms.
    degenerate = {
        "telegram_unavailable": True,
        "base_equals_control_b": True,
        "control_c_equals_control_d": True,
        "distinct_arms": ["curve+mcap (base, =CONTROL-B)",
                          "curve only (CONTROL-C = CONTROL-D)",
                          "random timing in region (CONTROL-A)"],
        "why": config.UNAVAILABLE_OVERLAYS[config.OVERLAY_TELEGRAM],
    }

    # --- walk-forward: the pre-registered weekly split, then daily -----------
    folds, status = analysis.walk_forward(ds, by_cfg, fold=config.FOLD)
    d_folds, d_status = analysis.walk_forward(ds, by_cfg, fold=config.SECONDARY_FOLD)

    oos: list[Trade] = []
    for f in folds:
        if f.selected_config:
            oos.extend(t for t in by_cfg[f.selected_config]
                       if f.test_start <= t.entry_ts < f.test_end)

    conc = analysis.concentration(oos)
    boot = analysis.bootstrap_ci(oos)

    # --- statistics, with multiple-comparison control ------------------------
    pvals: dict[str, float] = {}
    effects: dict[str, float] = {}
    for name, trades in {**by_cfg, **controls}.items():
        p, d = analysis.one_sample_p(trades)
        pvals[name], effects[name] = p, d
    bh = analysis.benjamini_hochberg(pvals, float(config.GATE_ALPHA))

    gate = analysis.gate(folds, status, oos, conc, boot, bh)

    result = {
        "experiment_id": _experiment_id(started),
        "spec_version": config.SPEC_VERSION,
        "config_hash": config.config_hash(),
        "dataset_version": ds.dataset_version,
        "git_sha": _git_sha(),
        "random_seed": config.RANDOM_SEED,
        "research_only": True,
        "started_at": started.isoformat(),
        "window": {"start": ds.window_start.isoformat(),
                   "end": ds.window_end.isoformat(),
                   "span_hours": round(ds.span_hours, 2),
                   "tokens": len(ds.tokens)},
        "data_quality": qr.as_dict(),
        "censoring": quality.censoring_report(ds, all_trades),
        "strategies": {n: analysis.compute(t).as_dict() for n, t in by_cfg.items()},
        "controls": {n: analysis.compute(t).as_dict() for n, t in controls.items()},
        "control_design": degenerate,
        "walk_forward": {"fold": config.FOLD, "status": status,
                         "folds": [f.as_dict() for f in folds]},
        "walk_forward_secondary": {
            "fold": config.SECONDARY_FOLD, "status": d_status,
            "exploratory_only": True,
            "note": "Not gating. The acceptance gate reads the weekly folds.",
            "folds": [f.as_dict() for f in d_folds]},
        "oos": analysis.compute(oos).as_dict(),
        "concentration": conc,
        "bootstrap": boot,
        "statistics": {n: {**bh[n], "effect_size_d": effects[n]} for n in bh},
        "leakage": {"passed": True, "findings": [],
                    "scope": "feature timestamps, exit ordering and graduation "
                             "carry only. Retention and sampling bias act before "
                             "a feature exists and are measured in `censoring`."},
        "gate": gate,
        "verdict": gate["verdict"],
        "unavailable_overlays": config.UNAVAILABLE_OVERLAYS,
    }

    if persist:
        await _persist(session, result, {**by_cfg, **controls}, started)
    return result


async def _persist(session: AsyncSession, result: dict,
                   trades: dict[str, list[Trade]], started: datetime) -> None:
    run_row = V6LabRun(
        experiment_id=result["experiment_id"],
        spec_version=result["spec_version"],
        config_hash=result["config_hash"],
        dataset_version=result["dataset_version"],
        git_sha=result["git_sha"],
        random_seed=result["random_seed"],
        started_at=started,
        finished_at=datetime.now(UTC),
        window_start=datetime.fromisoformat(result["window"]["start"]),
        window_end=datetime.fromisoformat(result["window"]["end"]),
        verdict=result["verdict"],
        gate_passed=result["gate"]["passed"],
        leakage_passed=True,
        result=result,
    )
    session.add(run_row)
    await session.flush()
    for name, ts in trades.items():
        for t in ts:
            session.add(V6LabTrade(
                run_id=run_row.id, strategy=name, mint=t.mint,
                entry_ts=t.entry_ts, exit_ts=t.exit_ts, exit_reason=t.exit_reason,
                censored=t.censored,
                entry_progress_pct=t.entry_progress_pct,
                entry_mcap_sol=t.entry_mcap_sol, elapsed_s=t.elapsed_s,
                gross_return=t.gross_return, net_return=t.net_return,
                net_pnl_usd=t.net_pnl_usd, fees_usd=t.fees_usd,
                slippage_usd=t.slippage_usd, mfe=t.mfe, mae=t.mae,
                reached_100=t.reached_100, graduated=t.graduated))
    await session.commit()
