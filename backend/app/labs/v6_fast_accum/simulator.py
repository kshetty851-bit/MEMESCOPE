"""Entry detection and the exit simulator. `RESEARCH_ONLY`. Pure: no I/O.

Everything a decision uses is drawn from the sample AT the decision timestamp
or before it. `features()` attaches the §15 provenance metadata to each one, so
the leakage checker can prove that rather than take it on trust.

## Fills are exact, not assumed

Price impact is computed against the curve's own reserves with the graduation
lab's `curve_fill_buy` / `curve_fill_sell`. Those model pump.fun's fee
asymmetry correctly — a markup on the way in, a deduction on the way out — and
they deepen the curve as the position fills, so a $10 buy at 10% progress costs
what a $10 buy at 10% progress costs. A flat percentage would overstate the
cost early on the curve and understate it late.

`EXTRA_SLIP_BPS` sits on top of that, per leg, for the gap between observing a
sample and landing a transaction. It is adverse on both sides.

## Censored trades are kept

A trade whose observation window closes before the rule resolves it is recorded
with `exit_reason="censored"` and `censored=True`, NOT dropped. Dropping it
would delete, preferentially, the trades the collector stopped watching because
they went quiet — which is to say the losers. That deletion is the single
largest bias available to this experiment, and the only defence is to carry the
censored rows all the way to the report and count them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.graduation.backtest import curve_fill_buy, curve_fill_sell
from app.labs.v6_fast_accum import config
from app.labs.v6_fast_accum.dataset import Dataset, Sample, Token

_BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class Feature:
    """One decision input, with the provenance §15 requires."""

    feature_name: str
    value: Decimal | None
    source_timestamp: datetime
    decision_timestamp: datetime
    availability: str  # OBSERVED | DERIVED | MISSING | UNAVAILABLE

    @property
    def is_observable_at_decision(self) -> bool:
        return self.source_timestamp <= self.decision_timestamp

    @property
    def derived_from_future_data(self) -> bool:
        return not self.is_observable_at_decision


@dataclass(frozen=True, slots=True)
class Trade:
    """One simulated position, resolved or censored."""

    mint: str
    strategy: str
    entry_ts: datetime
    entry_price: Decimal
    entry_progress_pct: Decimal
    entry_mcap_sol: Decimal
    elapsed_s: Decimal
    exit_ts: datetime | None
    exit_price: Decimal | None
    exit_reason: str
    censored: bool
    gross_return: Decimal | None
    net_return: Decimal | None
    net_pnl_usd: Decimal | None
    fees_usd: Decimal
    slippage_usd: Decimal
    mfe: Decimal | None
    mae: Decimal | None
    reached_25: bool
    reached_50: bool
    reached_100: bool
    reached_200: bool
    graduated: bool
    time_to_100_s: Decimal | None
    time_to_peak_s: Decimal | None
    peak_return: Decimal | None
    features: tuple[Feature, ...] = field(default_factory=tuple)


def features(token: Token, s: Sample, decision_ts: datetime) -> tuple[Feature, ...]:
    """The decision inputs, each stamped with where and when it came from."""
    out = [
        Feature("curve_progress_pct", s.progress_pct, s.ts, decision_ts, "OBSERVED"),
        Feature("initial_mcap_sol", s.mcap_quote, s.ts, decision_ts, "OBSERVED"),
        Feature("elapsed_s",
                Decimal((s.ts - token.first_seen_at).total_seconds()),
                s.ts, decision_ts, "DERIVED"),
        Feature("curve_price", s.price, s.ts, decision_ts, "DERIVED"),
    ]
    # Declared, not silently omitted: a missing overlay must be visible in the
    # feature table or its absence cannot be audited.
    for name in config.UNAVAILABLE_OVERLAYS:
        out.append(Feature(f"overlay_{name}", None, decision_ts, decision_ts,
                           "UNAVAILABLE"))
    return tuple(out)


def find_entry(
    token: Token,
    cfg: config.EntryConfig,
    *,
    require_mcap: bool = True,
    require_progress: bool = True,
) -> Sample | None:
    """The FIRST sample satisfying the rule, or None.

    First, not best: a rule that picked the most favourable qualifying sample
    would be choosing with information the moment of the first qualifying
    sample did not have.
    """
    for s in token.samples:
        if s.progress_pct is None or s.price is None or s.price <= 0:
            continue
        elapsed = (s.ts - token.first_seen_at).total_seconds()
        if elapsed > cfg.max_elapsed_s:
            return None  # Series is ordered: past the window, it stays past.
        if require_progress and s.progress_pct < cfg.min_progress_pct:
            continue
        if require_mcap and (s.mcap_quote is None
                             or s.mcap_quote <= cfg.min_mcap_sol):
            continue
        return s
    return None


def _legs(entry: Sample, position_sol: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Tokens bought, the fee paid, and the slippage cost — all in SOL.

    Returns the EXECUTED token quantity, so the exit leg sells exactly what the
    entry leg bought rather than a notional.
    """
    v_quote, v_token = entry.v_quote or Decimal(0), entry.v_token or Decimal(0)
    if v_quote <= 0 or v_token <= 0:
        return Decimal(0), Decimal(0), Decimal(0)
    tokens = curve_fill_buy(v_quote, v_token, position_sol,
                            fee_bps=config.CURVE_FEE_BPS)
    # The fee is the difference between the gross out and what reached the
    # curve — the same form pump.fun's program uses.
    to_curve = position_sol * _BPS / (_BPS + Decimal(config.CURVE_FEE_BPS))
    fee_sol = position_sol - to_curve
    # Impact: what the mid would have bought, less what the curve actually gave.
    mid_tokens = to_curve / (v_quote / v_token)
    impact_sol = max(Decimal(0), (mid_tokens - tokens)) * (v_quote / v_token)
    tokens = tokens * (_BPS - Decimal(config.EXTRA_SLIP_BPS)) / _BPS
    return tokens, fee_sol, impact_sol


def simulate(
    token: Token,
    entry: Sample,
    strategy: str,
    *,
    now_limit: datetime,
) -> Trade:
    """Run the pre-registered exit rule over one token's observed series."""
    position_sol = config.NOTIONAL_USD / config.SOL_USD_FROZEN
    entry_price = entry.price or Decimal(0)
    tokens_held, fee_in, slip_in = _legs(entry, position_sol)
    deadline = entry.ts + timedelta(minutes=config.MAX_HOLD_MIN)
    path = token.window(entry.ts, deadline)

    mfe = mae = peak_return = None
    t100 = t_peak = None
    exit_s: Sample | None = None
    reason = "censored"
    #: The most recent sample that could actually be priced. A completed curve
    #: ZEROES all four reserves, so the graduation sample itself has no price —
    #: exiting "at" it produced a trade with no return that was still labelled
    #: a graduation, which is what the leakage audit rejected. The position
    #: leaves at the last pre-migration print, which is also what a seller gets.
    last_priced: Sample | None = None

    for s in path:
        px = s.price
        if s.complete:
            # Graduation outranks every price condition in this interval: the
            # position must be out BEFORE migration, and a post-migration print
            # is information the rule is not allowed to use.
            exit_s, reason = (last_priced or entry), "graduation"
            break
        if px is not None and px > 0:
            last_priced = s
        if px is None or entry_price <= 0:
            continue
        mult = px / entry_price
        ret = mult - 1
        if mfe is None or mult > mfe:
            mfe, t_peak, peak_return = mult, Decimal((s.ts - entry.ts).total_seconds()), ret
        if mae is None or mult < mae:
            mae = mult
        if t100 is None and mult >= config.TP_MULT:
            t100 = Decimal((s.ts - entry.ts).total_seconds())
        # Worst-first within one interval: a single reserve reading cannot say
        # whether the low or the high came first, so the stop is assumed to
        # have been touched before the target.
        if mult <= config.SL_MULT:
            exit_s, reason = s, "stop_loss"
            break
        if mult >= config.TP_MULT:
            exit_s, reason = s, "take_profit"
            break

    if exit_s is None:
        last = token.last_observed_at()
        if last is not None and last >= deadline:
            # The horizon closed with the series still live: a real time stop.
            held = token.at(deadline)
            if held is not None and held.price:
                exit_s, reason = held, "time_stop"
        elif now_limit >= deadline and last is not None and last < deadline:
            reason = "censored"  # The collector stopped before the rule did.

    if exit_s is None or exit_s.price is None or entry_price <= 0 or tokens_held <= 0:
        return Trade(
            mint=token.mint, strategy=strategy, entry_ts=entry.ts,
            entry_price=entry_price, entry_progress_pct=entry.progress_pct or Decimal(0),
            entry_mcap_sol=entry.mcap_quote or Decimal(0),
            elapsed_s=Decimal((entry.ts - token.first_seen_at).total_seconds()),
            exit_ts=None, exit_price=None, exit_reason=reason, censored=True,
            gross_return=None, net_return=None, net_pnl_usd=None,
            fees_usd=Decimal(0), slippage_usd=Decimal(0),
            mfe=mfe, mae=mae,
            reached_25=bool(mfe and mfe >= Decimal("1.25")),
            reached_50=bool(mfe and mfe >= Decimal("1.5")),
            reached_100=bool(mfe and mfe >= Decimal(2)),
            reached_200=bool(mfe and mfe >= Decimal(3)),
            graduated=token.graduated, time_to_100_s=t100,
            time_to_peak_s=t_peak, peak_return=peak_return,
            features=features(token, entry, entry.ts),
        )

    # Exit leg, priced on the reserves in force at the exit sample.
    v_quote, v_token = exit_s.v_quote or Decimal(0), exit_s.v_token or Decimal(0)
    if v_quote > 0 and v_token > 0:
        sol_out = curve_fill_sell(v_quote, v_token, tokens_held,
                                  fee_bps=config.CURVE_FEE_BPS)
        raw_out = tokens_held * (v_quote / v_token)
        fee_out = max(Decimal(0), raw_out * Decimal(config.CURVE_FEE_BPS) / _BPS)
        slip_out = max(Decimal(0), raw_out - sol_out - fee_out)
        sol_out = sol_out * (_BPS - Decimal(config.EXTRA_SLIP_BPS)) / _BPS
    else:
        sol_out = fee_out = slip_out = Decimal(0)

    sol_out -= config.PRIORITY_FEE_SOL * 2  # Both legs pay it.
    gross = (exit_s.price / entry_price) - 1
    net_sol = sol_out - position_sol
    net_ret = net_sol / position_sol if position_sol else None
    usd = config.SOL_USD_FROZEN

    return Trade(
        mint=token.mint, strategy=strategy, entry_ts=entry.ts,
        entry_price=entry_price, entry_progress_pct=entry.progress_pct or Decimal(0),
        entry_mcap_sol=entry.mcap_quote or Decimal(0),
        elapsed_s=Decimal((entry.ts - token.first_seen_at).total_seconds()),
        exit_ts=exit_s.ts, exit_price=exit_s.price, exit_reason=reason, censored=False,
        gross_return=gross, net_return=net_ret, net_pnl_usd=net_sol * usd,
        fees_usd=(fee_in + fee_out + config.PRIORITY_FEE_SOL * 2) * usd,
        slippage_usd=(slip_in + slip_out) * usd,
        mfe=mfe, mae=mae,
        reached_25=bool(mfe and mfe >= Decimal("1.25")),
        reached_50=bool(mfe and mfe >= Decimal("1.5")),
        reached_100=bool(mfe and mfe >= Decimal(2)),
        reached_200=bool(mfe and mfe >= Decimal(3)),
        graduated=token.graduated, time_to_100_s=t100,
        time_to_peak_s=t_peak, peak_return=peak_return,
        features=features(token, entry, entry.ts),
    )


def run_strategy(
    ds: Dataset,
    cfg: config.EntryConfig,
    *,
    strategy: str | None = None,
    require_mcap: bool = True,
    require_progress: bool = True,
    randomise_in_region: bool = False,
    seed: int = config.RANDOM_SEED,
) -> list[Trade]:
    """Every trade one rule produces over the frozen dataset.

    `randomise_in_region` is CONTROL-A: instead of the first qualifying sample,
    pick a uniformly random one from the same eligible region. It answers "is
    the timing doing any work, or just the region?" — which a random control
    over the whole token universe could not, because it would differ from the
    base strategy in the population as well as the rule.
    """
    name = strategy or cfg.name
    rng = random.Random(seed)
    trades: list[Trade] = []
    for t in ds.tokens:
        if t.pruned or not t.samples:
            continue
        if randomise_in_region:
            region = [
                s for s in t.samples
                if s.progress_pct is not None and s.price and s.price > 0
                and (s.ts - t.first_seen_at).total_seconds() <= cfg.max_elapsed_s
                and s.progress_pct >= cfg.min_progress_pct
            ]
            entry = rng.choice(region) if region else None
        else:
            entry = find_entry(t, cfg, require_mcap=require_mcap,
                               require_progress=require_progress)
        if entry is None:
            continue
        trades.append(simulate(t, entry, name, now_limit=ds.window_end))
    return trades


def apply_position_limits(trades: list[Trade]) -> list[Trade]:
    """Drop signals the book had no slot for, in strict arrival order.

    §6 caps the book at 5 concurrent positions and $50 deployed. A backtest
    that took every signal would be reporting a strategy nobody could run, and
    would do it by silently assuming unlimited capital.
    """
    taken: list[Trade] = []
    open_until: list[datetime] = []
    for tr in sorted(trades, key=lambda x: x.entry_ts):
        open_until = [d for d in open_until if d > tr.entry_ts]
        if len(open_until) >= config.MAX_CONCURRENT:
            continue
        taken.append(tr)
        open_until.append(tr.exit_ts or
                          tr.entry_ts + timedelta(minutes=config.MAX_HOLD_MIN))
    return taken
