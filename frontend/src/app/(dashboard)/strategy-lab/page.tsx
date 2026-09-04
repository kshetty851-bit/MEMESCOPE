"use client";

import { useMemo, useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useLabBoard, useLabStrategy, useLabTrades } from "@/hooks/use-lab";
import type { LabBoard, LabRule, LabStrategyRow, LabProjection } from "@/types/lab";
import { SellButton } from "./sell-button";
import { cellTone, generationOf, isCashControl, toneOf } from "./tone";

/**
 * FORWARD STRATEGY LAB
 *
 * A frozen registry of virtual $100 portfolios scored against a
 * cash control, all fed by the one MEMESCOPE scanner. **This is not the Paper
 * Wallet and it is not real money.** The page says so above the fold rather
 * than in a footnote: a reader who confused them would draw a conclusion about
 * money that does not exist.
 *
 * Every figure is served already computed. Nothing here recomputes an
 * expectancy, a profit factor or a rate — a second implementation would be a
 * second answer, and the first time either changed they would disagree.
 *
 * Historical and forward figures are shown in separate columns and are never
 * added together. The entire point of the tournament is to find out whether
 * the historical liquidity effect survives data nobody has seen.
 */

function money(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `$${v.toFixed(digits)}`;
}

function signed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
}

function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `${v.toFixed(digits)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : v.toFixed(digits);
}

function checkpoint(minutes: number | null): string {
  if (minutes === null) return "never";
  return minutes === 0 ? "admission" : `+${minutes}m`;
}

function elapsed(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.floor((hours - h) * 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

const COLUMNS: { key: keyof LabStrategyRow | "rank"; label: string; numeric: boolean }[] = [
  { key: "rank", label: "#", numeric: true },
  { key: "strategy_id", label: "Strategy", numeric: false },
  { key: "status", label: "Status", numeric: false },
  { key: "starting_equity", label: "Start", numeric: true },
  { key: "cash", label: "Cash", numeric: true },
  { key: "open_cost", label: "Open cost", numeric: true },
  { key: "open_value", label: "Open value", numeric: true },
  { key: "equity", label: "Equity", numeric: true },
  { key: "net_pnl", label: "Net P&L", numeric: true },
  { key: "return_pct", label: "Return (wallet)", numeric: true },
  { key: "open_return_pct", label: "Return (open book)", numeric: true },
  { key: "deployed_return_pct", label: "Return (deployed)", numeric: true },
  { key: "capital_at_work_pct", label: "At work", numeric: true },
  { key: "trades", label: "Trades", numeric: true },
  { key: "wins", label: "W", numeric: true },
  { key: "losses", label: "L", numeric: true },
  { key: "win_pct", label: "Win %", numeric: true },
  { key: "expectancy", label: "Expectancy", numeric: true },
  { key: "profit_factor", label: "PF", numeric: true },
  { key: "max_dd_pct", label: "Max DD", numeric: true },
  { key: "avg_position", label: "Avg pos", numeric: true },
  { key: "max_exposure_usd", label: "Max exp", numeric: true },
  { key: "exec_125_pct", label: "Exec 1.25×", numeric: true },
  { key: "exec_150_pct", label: "Exec 1.5×", numeric: true },
  { key: "exec_200_pct", label: "Exec 2×", numeric: true },
];

function cell(row: LabStrategyRow, key: string): string {
  switch (key) {
    case "rank": return String(row.rank);
    case "strategy_id": return `${row.strategy_id} ${row.name}`;
    case "status": return row.status === "failed" ? "FAILED — DRAWDOWN" : "active";
    case "starting_equity": return money(row.starting_equity);
    case "cash": return money(row.cash);
    case "open_cost": return money(row.open_cost);
    case "open_value": return money(row.open_value);
    case "equity": return money(row.equity);
    case "net_pnl": return signed(row.net_pnl);
    case "return_pct": return pct(row.return_pct, 2);
    case "open_return_pct": return pct(row.open_return_pct, 2);
    case "deployed_return_pct": return pct(row.deployed_return_pct, 2);
    case "capital_at_work_pct": return pct(row.capital_at_work_pct, 1);
    case "trades": return String(row.trades);
    case "wins": return String(row.wins);
    case "losses": return String(row.losses);
    case "win_pct": return pct(row.win_pct);
    case "expectancy": return signed(row.expectancy);
    case "profit_factor": return num(row.profit_factor, 3);
    case "max_dd_pct": return pct(row.max_dd_pct);
    case "avg_position": return money(row.avg_position);
    case "max_exposure_usd": return money(row.max_exposure_usd);
    case "exec_125_pct": return pct(row.exec_125_pct);
    case "exec_150_pct": return pct(row.exec_150_pct);
    case "exec_200_pct": return pct(row.exec_200_pct);
    default: return "—";
  }
}

function Header({ board }: { board: LabBoard }) {
  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <Label>
            {generationOf(board.strategies.map((s) => s.strategy_id)) ?? ""} FORWARD
            STRATEGY LAB
          </Label>
          <h1 className="mt-1 text-lg font-medium text-ink">
            {board.strategies.length} STRATEGIES · ${board.starting_equity.toFixed(0)} EACH ·
            SAME MEMESCOPE SCANNER
          </h1>
          <p className="mt-1 text-xs font-medium tracking-wide text-warn">
            PAPER / RESEARCH ONLY — REAL MONEY OFF
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-muted">Start</dt>
            <dd className="font-mono text-ink">
              {new Date(board.valid_from).toISOString().replace("T", " ").slice(0, 16)}Z
            </dd>
          </div>
          <div>
            <dt className="text-muted">24h snapshot</dt>
            <dd className="font-mono text-ink">
              {new Date(board.snapshot_at).toISOString().replace("T", " ").slice(0, 16)}Z
            </dd>
          </div>
          <div>
            <dt className="text-muted">Elapsed</dt>
            <dd className="font-mono text-ink">{elapsed(board.elapsed_hours)}</dd>
          </div>
          <div>
            <dt className="text-muted">Status</dt>
            <dd className="font-mono text-ink">
              {board.snapshot_taken
                ? "24H SNAPSHOT TAKEN — RUNNING ON"
                : `${elapsed(board.hours_to_snapshot)} to snapshot`}
            </dd>
          </div>
        </dl>
      </div>
      <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-muted">
        {board.disclosure}
      </p>
      <p className="mt-2 font-mono text-[10px] text-muted">
        spec {board.spec_version} · hash {board.spec_hash.slice(0, 16)}… ·
        STRATEGY SPEC IMMUTABLE = TRUE · {board.total_closed_trades} closed trades ·
        confidence {board.overall_confidence.replace(/_/g, " ")}
      </p>
    </Panel>
  );
}

/**
 * THIRTY-DAY BAND
 *
 * The most dangerous number this page can show. It is the one a reader turns
 * straight into a funding decision, and the history is unambiguous: V6-07 had a
 * 3.0 profit factor on 23 trades, was nearly funded on it, and ended at -25%.
 *
 * So three rules govern this panel.
 *
 * It renders a REFUSAL as prominently as a number. Below the minimum sample the
 * API sends `projectable: false` and a reason, and that is what appears — not a
 * greyed-out figure, not a dash, a sentence saying why there is no answer.
 *
 * It never shows the leader alone. The random control sits beside it at the
 * same size, because the question is never "will this make money" but "does it
 * beat blind entry from the same pool". Two overlapping bands mean nothing has
 * been shown, and the reader must be able to see that without scrolling.
 *
 * It leads with the SPREAD, not the midpoint. A median is what gets quoted; the
 * p10 is what gets lived through.
 */
function Projection({ board }: { board: LabBoard }) {
  const leader = board.projection?.leader;
  const control = board.projection?.random_control;
  if (!leader) return null;

  const money = (v: string | null) =>
    v === null ? "—" : `$${Number(v).toFixed(0)}`;
  const pct = (v: number | null) =>
    v === null ? "—" : `${(v * 100).toFixed(0)}%`;

  const Band = ({ p, kind }: { p: LabProjection; kind: string }) => (
    <div className="rounded border border-line p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{kind}</Label>
        <span className="font-mono text-[10px] text-muted">
          {p.strategy_id} · {p.trades_observed} trades
        </span>
      </div>
      <p className="mt-1 truncate text-sm text-ink">{p.name}</p>
      {!p.projectable ? (
        <p className="mt-2 text-xs leading-relaxed text-warn">{p.reason}</p>
      ) : (
        <>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-muted text-[10px]">WORST 10%</div>
              <div className="font-mono text-sm text-down">{money(p.p10)}</div>
            </div>
            <div>
              <div className="text-muted text-[10px]">MEDIAN</div>
              <div className="font-mono text-sm text-ink">{money(p.p50)}</div>
            </div>
            <div>
              <div className="text-muted text-[10px]">BEST 10%</div>
              <div className="font-mono text-sm text-up">{money(p.p90)}</div>
            </div>
          </div>
          <p className="mt-2 font-mono text-[11px] text-muted">
            P(profit) {pct(p.p_profit)} · P(ruin) {pct(p.p_ruin)} ·{" "}
            {p.projected_trades} trades at {p.trades_per_day.toFixed(1)}/day
          </p>
        </>
      )}
    </div>
  );

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Label>NEXT {leader.horizon_days} DAYS — RESAMPLED FROM OWN TRADES</Label>
        <span className="font-mono text-[10px] text-warn">
          NOT A FORECAST
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Band p={leader} kind="LEADER" />
        {control ? <Band p={control} kind="RANDOM CONTROL — THE BAR" /> : null}
      </div>
      <p className="mt-3 border-t border-line pt-3 text-xs leading-relaxed text-muted">
        {leader.notes.join(" ")}
      </p>
    </Panel>
  );
}

function Leaders({ board }: { board: LabBoard }) {
  const { profit, risk_adjusted: risk, executable_2x: twoX } = board.leaders;
  const badges = [
    { title: "PROFIT LEADER", id: profit.strategy_id, name: profit.name,
      main: money(profit.equity),
      sub: `${pct(profit.return_pct, 2)} · ${profit.confidence.replace(/_/g, " ")}` },
    { title: "RISK-ADJUSTED LEADER", id: risk.strategy_id, name: risk.name,
      main: pct(risk.return_pct, 2),
      sub: `PF ${num(risk.profit_factor, 2)} · DD ${pct(risk.max_dd_pct)} · ${risk.trades} trades` },
    { title: "EXECUTABLE 2× LEADER", id: twoX.strategy_id, name: twoX.name,
      main: pct(twoX.exec_200_pct),
      sub: `${twoX.trades} trades · ${twoX.confidence.replace(/_/g, " ")}` },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {badges.map((b) => (
        <Panel key={b.title} density="compact">
          <Label>{b.title}</Label>
          <p className="mt-1 font-mono text-sm text-ink">
            {b.id} <span className="text-muted">{b.name}</span>
          </p>
          <p className="mt-1 text-xl font-medium text-ink">{b.main}</p>
          <p className="mt-0.5 text-xs text-muted">{b.sub}</p>
        </Panel>
      ))}
    </div>
  );
}

function Drawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, isLoading } = useLabStrategy(id);
  return (
    <Panel>
      <div className="flex items-start justify-between gap-4">
        <Label>STRATEGY DETAIL — {id}</Label>
        <button onClick={onClose} className="text-xs text-muted hover:text-ink">
          close
        </button>
      </div>
      {isLoading || !data ? (
        <Skeleton className="mt-3 h-40 w-full" />
      ) : (
        <div className="mt-3 space-y-4 text-xs">
          <div>
            <h3 className="text-sm font-medium text-ink">{data.strategy.name}</h3>
            <p className="mt-1 leading-relaxed text-muted">{data.strategy.hypothesis}</p>
          </div>
          {data.historical_warning ? (
            <p className="rounded border border-warn/40 bg-warn/[0.05] p-2 text-warn">
              {data.historical_warning}
            </p>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>FROZEN RULES</Label>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                <li>decision: {checkpoint(data.strategy.checkpoint_minutes)}</li>
                {data.strategy.entry.length === 0 ? (
                  <li>entry: every eligible token (control)</li>
                ) : (
                  data.strategy.entry.map((c, i) => (
                    <li key={i}>
                      entry {i + 1}: {c.feature} {c.op} {c.value}
                    </li>
                  ))
                )}
                <li>size: ${data.strategy.size_usd}</li>
                <li>max concurrent: {data.strategy.max_concurrent}</li>
                <li>max exposure: ${data.strategy.max_exposure_usd}</li>
                {Object.entries(data.strategy.exits).map(([k, v]) => (
                  <li key={k}>
                    {k.replace(/_/g, " ")}: {String(v)}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <Label>
                HISTORICAL CONTEXT{data.strategy.hist_is_proxy ? " — PROXY ONLY" : ""}
              </Label>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted">
                {Object.entries(data.strategy.hist).map(([k, v]) => (
                  <li key={k}>
                    {k}: {String(v)}
                  </li>
                ))}
                <li>evidence: {data.strategy.evidence}</li>
                <li>overfit risk: {data.strategy.overfit_risk}</li>
              </ul>
              {data.strategy.caveats.length > 0 ? (
                <ul className="mt-2 space-y-0.5 text-[11px] text-warn">
                  {data.strategy.caveats.map((c) => (
                    <li key={c}>⚠ {c.replace(/_/g, " ")}</li>
                  ))}
                </ul>
              ) : null}
              {data.strategy.note ? (
                <p className="mt-2 leading-relaxed text-muted">{data.strategy.note}</p>
              ) : null}
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>FORWARD RESULT (this tournament)</Label>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                <li>equity: {money(data.stats?.equity)}</li>
                <li>cash: {money(data.stats?.cash)}</li>
                <li>
                  open: {money(data.stats?.open_value)} value /{" "}
                  {money(data.stats?.open_cost)} cost
                </li>
                <li>closed trades: {data.stats?.trades ?? 0}</li>
                <li>expectancy: <span className={toneOf(data.stats?.expectancy)}>{signed(data.stats?.expectancy)}</span></li>
                <li>PF: {num(data.stats?.profit_factor, 3)}</li>
                <li>max DD: {pct(data.stats?.max_dd_pct)}</li>
                <li>best / worst: <span className={toneOf(data.stats?.best_trade)}>{signed(data.stats?.best_trade)}</span> / <span className={toneOf(data.stats?.worst_trade)}>{signed(data.stats?.worst_trade)}</span></li>
                <li>without best 1: <span className={toneOf(data.stats?.expectancy_ex_best1)}>{signed(data.stats?.expectancy_ex_best1)}</span></li>
                <li>without best 3: <span className={toneOf(data.stats?.expectancy_ex_best3)}>{signed(data.stats?.expectancy_ex_best3)}</span></li>
                <li>top-1 profit share: {pct(data.stats?.top1_profit_share_pct)}</li>
                <li>top-3 profit share: {pct(data.stats?.top3_profit_share_pct)}</li>
                <li>longest losing streak: {data.stats?.losing_streak ?? 0}</li>
              </ul>
            </div>
            <div>
              <Label>SKIP REASONS ({data.decisions_total} decisions)</Label>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted">
                {Object.entries(data.skip_reasons).slice(0, 12).map(([r, n]) => (
                  <li key={r}>
                    {r.replace(/_/g, " ")}: {n}
                  </li>
                ))}
                {Object.keys(data.skip_reasons).length === 0 ? <li>none yet</li> : null}
              </ul>
            </div>
          </div>
          <div>
            <Label>POSITIONS ({data.positions.length})</Label>
            <div className="mt-1 max-h-64 overflow-auto">
              <table className="w-full text-left font-mono text-[11px]">
                <thead className="text-muted">
                  <tr>
                    <th className="py-1 pr-3">mint</th>
                    <th className="py-1 pr-3">opened</th>
                    <th className="py-1 pr-3">status</th>
                    <th className="py-1 pr-3 text-right">value</th>
                    <th className="py-1 pr-3 text-right">P&L</th>
                    <th className="py-1 pr-3">exit</th>
                    <th className="py-1 pr-3">route</th>
                    <th className="py-1 pr-3">marks</th>
                    <th className="py-1">sell</th>
                  </tr>
                </thead>
                <tbody className="text-ink">
                  {data.positions.map((p) => (
                    <tr key={p.mint} className="border-t border-line">
                      <td className="py-1 pr-3">{p.mint.slice(0, 6)}…</td>
                      <td className="py-1 pr-3">{p.opened_at.slice(5, 16).replace("T", " ")}</td>
                      <td className="py-1 pr-3">{p.status}</td>
                      <td className="py-1 pr-3 text-right">
                        {money(p.status === "closed" ? p.exit_proceeds_usd : p.open_value)}
                      </td>
                      <td className={`py-1 pr-3 text-right ${toneOf(p.pnl)}`}>
                        {signed(p.pnl)}
                      </td>
                      <td className="py-1 pr-3">{p.exit_reason ?? "—"}</td>
                      <td className="py-1 pr-3">{p.route_state ?? "—"}</td>
                      <td className="py-1 pr-3">
                        {[p.reached_125 && "1.25×", p.reached_150 && "1.5×",
                          p.reached_200 && "2×"].filter(Boolean).join(" ") || "—"}
                      </td>
                      <td className="py-1">
                        {p.status === "open" ? <SellButton id={p.id} /> : null}
                      </td>
                    </tr>
                  ))}
                  {data.positions.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-2 text-muted">
                        no positions yet
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
          {data.equity_curve.length > 1 ? (
            <div>
              <Label>EQUITY CURVE ({data.equity_curve.length} marks)</Label>
              <Sparkline points={data.equity_curve.map((p) => p.equity)} />
            </div>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

/**
 * Every open position across every wallet, with its sell control.
 *
 * On THIS page rather than only on the trades view because this is the page a
 * reader is on. The leaderboard's rows are strategies, not trades, so there is
 * no row here to hang a sell button from — and a control one navigation step
 * away from where somebody is looking is, in practice, a control they do not
 * have.
 *
 * Its own query rather than a slice of the board: the board carries per-
 * strategy totals, not the individual holdings, and deriving positions from
 * totals is not possible.
 */
function OpenPositions() {
  const { data, isLoading } = useLabTrades(undefined, "open");
  const rows = data?.trades ?? [];

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Label>OPEN POSITIONS ({isLoading ? "…" : rows.length})</Label>
        <p className="text-[10px] text-muted">
          Paper positions. Selling by hand records the exit as{" "}
          <span className="font-mono">manual_close</span> — not a result the
          frozen rules produced.
        </p>
      </div>
      {isLoading ? (
        <Skeleton className="mt-2 h-24 w-full" />
      ) : rows.length === 0 ? (
        <p className="mt-2 text-xs text-muted">Nothing open right now.</p>
      ) : (
        <div className="mt-2 max-h-80 overflow-auto">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">sell</th>
                <th className="py-1 pr-3 font-normal">strategy</th>
                <th className="py-1 pr-3 font-normal">token</th>
                <th className="py-1 pr-3 text-right font-normal">size</th>
                <th className="py-1 pr-3 text-right font-normal">value</th>
                <th className="py-1 pr-3 text-right font-normal">P&L</th>
                <th className="py-1 pr-3 text-right font-normal">exec ×</th>
                <th className="py-1 font-normal">held</th>
              </tr>
            </thead>
            <tbody className="text-ink">
              {rows.map((t) => (
                <tr key={t.id} className="border-t border-line">
                  <td className="py-1 pr-3">
                    <SellButton id={t.id} />
                  </td>
                  <td className="py-1 pr-3">{t.strategy_id}</td>
                  <td className="py-1 pr-3">
                    {t.symbol ?? `${t.mint.slice(0, 6)}…`}
                  </td>
                  <td className="py-1 pr-3 text-right">{money(t.size_usd)}</td>
                  <td className="py-1 pr-3 text-right">
                    {money(t.current_value_usd)}
                  </td>
                  <td className={`py-1 pr-3 text-right ${toneOf(t.unrealised_pnl)}`}>
                    {signed(t.unrealised_pnl)}
                  </td>
                  <td className="py-1 pr-3 text-right">
                    {t.exec_multiple === null ? "—" : `${t.exec_multiple.toFixed(3)}×`}
                  </td>
                  <td className="py-1">{t.held_hours.toFixed(1)}h</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** A curve, not a chart library: one path over the marks the ledger recorded. */
function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const min = Math.min(...points, 1000);
  const max = Math.max(...points, 1000);
  const span = max - min || 1;
  const d = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 30 - ((v - min) / span) * 30;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const baseline = 30 - ((1000 - min) / span) * 30;
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="mt-1 h-16 w-full">
      <line x1="0" x2="100" y1={baseline} y2={baseline}
            stroke="currentColor" strokeWidth="0.3" className="text-muted" />
      <path d={d} fill="none" stroke="currentColor" strokeWidth="0.7"
            className="text-accent" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}


/**
 * The frozen rulebook, in full, at the bottom of the page.
 *
 * Served by the API rather than transcribed here: a TypeScript copy of the
 * thresholds would be a second source of truth, and the first time either
 * changed they would disagree. What a reader sees is what the engine judges
 * with — the same registry, under the same hash shown in the header.
 */
function Rulebook({ rules, specHash }: { rules: LabRule[]; specHash: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <Label>THE FROZEN RULES — ALL {rules.length} STRATEGIES</Label>
          <p className="mt-1 text-xs text-muted">
            Every rule each wallet trades by, exactly as frozen before scoring began.
            Changing any number here would start a new tournament at zero.
          </p>
        </div>
        <button
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded border border-line px-2 py-1 text-xs text-muted hover:text-ink"
        >
          {open ? "collapse all" : "expand all"}
        </button>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {rules.map((r) => (
          <div key={r.id} className="rounded border border-line p-3">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="font-mono text-xs font-medium text-ink">
                {r.id} <span className="text-muted">{r.name}</span>
              </h3>
              <span className="shrink-0 font-mono text-[10px] text-muted">
                {r.checkpoint_label}
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted">{r.hypothesis}</p>

            {r.overfit_risk === "HIGH" ? (
              <p className="mt-2 rounded border border-warn/40 bg-warn/[0.05] px-2 py-1 text-[10px] text-warn">
                HISTORICALLY INTERESTING — HIGH OVERFIT RISK. Historical profit is context,
                not validation.
              </p>
            ) : null}
            {r.evidence === "NONE_HISTORICALLY" ? (
              <p className="mt-2 rounded border border-line px-2 py-1 text-[10px] text-muted">
                NO HISTORICAL EVIDENCE — this hypothesis rests on data that only exists
                going forward.
              </p>
            ) : null}

            <dl className="mt-2 space-y-1 text-[11px]">
              <div>
                <dt className="text-muted">Enters when</dt>
                <dd className="font-mono text-ink">
                  <ul className="mt-0.5 space-y-0.5">
                    {r.entry_text.map((t, i) => (
                      <li key={i}>· {t}</li>
                    ))}
                  </ul>
                </dd>
              </div>
              <div>
                <dt className="text-muted">Sizing</dt>
                <dd className="font-mono text-ink">
                  ${r.size_usd} per position · max {r.max_concurrent} concurrent · max $
                  {r.max_exposure_usd} deployed
                </dd>
              </div>
              <div>
                <dt className="text-muted">Exits, in the order they are checked</dt>
                <dd className="font-mono text-ink">
                  <ol className="mt-0.5 space-y-0.5">
                    {r.exit_text.map((t, i) => (
                      <li key={i}>
                        {i + 1}. {t}
                      </li>
                    ))}
                  </ol>
                </dd>
              </div>
              {open ? (
                <>
                  <div>
                    <dt className="text-muted">Historical context</dt>
                    <dd className="font-mono text-ink">
                      {r.hist_is_proxy ? "PROXY ONLY — " : ""}
                      {Object.entries(r.hist).length === 0
                        ? "—"
                        : Object.entries(r.hist)
                            .map(([k, v]) => `${k} ${v}`)
                            .join(" · ")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">Evidence / overfit risk</dt>
                    <dd className="font-mono text-ink">
                      {r.evidence.replace(/_/g, " ")} / {r.overfit_risk.replace(/_/g, " ")}
                    </dd>
                  </div>
                  {r.caveats.length > 0 ? (
                    <div>
                      <dt className="text-muted">Caveats</dt>
                      <dd className="text-warn">
                        {r.caveats.map((c) => c.replace(/_/g, " ")).join(" · ")}
                      </dd>
                    </div>
                  ) : null}
                  {r.note ? (
                    <div>
                      <dt className="text-muted">Note</dt>
                      <dd className="leading-relaxed text-muted">{r.note}</dd>
                    </div>
                  ) : null}
                </>
              ) : null}
            </dl>
          </div>
        ))}
      </div>

      <div className="mt-3 space-y-1 border-t border-line pt-3 text-[10px] leading-relaxed text-muted">
        <p>
          Shared by all {rules.length}: 30 bps per side · constant-product impact against
          (liquidity ÷ 2) ÷ 12, calibrated on 320 live Jupiter quotes · a real quote is
          preferred where one exists · level exits fill at no better than trigger × 1.15 ·
          prints more than 3× off the 10-minute median never fill in either direction ·
          nothing is acted on across a gap over 15 minutes · a pool the provider reports
          inactive settles at $0.00, never at its last healthy print.
        </p>
        <p>
          There are no conventional stop losses anywhere in{" "}
          {generationOf(rules.map((r) => r.id)) ?? "this registry"}. On 27 days of real series a
          −25% stop filled at a median of $0.03 against a nominal $7.50, so the family is
          omitted on purpose rather than by oversight.
        </p>
        <p className="font-mono">registry hash {specHash}</p>
      </div>
    </Panel>
  );
}

export default function StrategyLabPage() {
  const { data, isLoading, error } = useLabBoard();
  const [sortKey, setSortKey] = useState<string>("rank");
  const [asc, setAsc] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const rows = useMemo(() => {
    if (!data) return [];
    const copy = [...data.strategies];
    copy.sort((a, b) => {
      const x = a[sortKey as keyof LabStrategyRow];
      const y = b[sortKey as keyof LabStrategyRow];
      if (typeof x === "number" && typeof y === "number") return asc ? x - y : y - x;
      return asc
        ? String(x).localeCompare(String(y))
        : String(y).localeCompare(String(x));
    });
    return copy;
  }, [data, sortKey, asc]);

  if (error) return <ErrorState body="The Strategy Lab board is unavailable." />;
  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-4">
      <Header board={data} />
      <Leaders board={data} />
      <Projection board={data} />
      <OpenPositions />
      <Panel density="compact">
        <div className="flex items-baseline justify-between">
          <Label>LIVE LEADERBOARD — {data.strategies.length} STRATEGIES</Label>
          <p className="text-[10px] text-muted">
            historical figures are shown per strategy and are never added to these
          </p>
        </div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="text-muted">
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={String(c.key)}
                    className={`cursor-pointer whitespace-nowrap py-1 pr-3 font-normal hover:text-ink ${
                      c.numeric ? "text-right" : ""
                    }`}
                    onClick={() => {
                      if (sortKey === c.key) setAsc(!asc);
                      else {
                        setSortKey(String(c.key));
                        setAsc(c.key === "rank" || !c.numeric);
                      }
                    }}
                  >
                    {c.label}
                    {sortKey === c.key ? (asc ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono text-ink">
              {rows.map((r) => (
                <tr
                  key={r.strategy_id}
                  onClick={() => setSelected(r.strategy_id)}
                  className={`cursor-pointer border-t border-line hover:bg-surface-2 ${
                    r.status === "failed" ? "text-danger" : ""
                  } ${isCashControl(r) ? "font-medium" : ""}`}
                >
                  {COLUMNS.map((c) => (
                    <td
                      key={String(c.key)}
                      className={`whitespace-nowrap py-1 pr-3 ${
                        c.numeric ? "text-right" : ""
                      } ${cellTone(r, String(c.key))}`}
                    >
                      {cell(r, String(c.key))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] text-muted">
          <span className="text-ink">Return (wallet)</span> is measured on the full
          $1,000 and is mostly idle cash, so it compresses every strategy into the same
          fraction of a percent. <span className="text-ink">Return (open book)</span> is
          how the positions held right now are doing against what they cost;{" "}
          <span className="text-ink">Return (deployed)</span> is how every dollar ever
          committed has done, realised and unrealised — that is the fair comparison
          between strategies that risk different amounts.{" "}
          <span className="text-ink">At work</span> is the share of the wallet currently
          in the market. Equity is cash plus what the open book could be SOLD for, never
          plus what it cost. A row in red has tripped the −20% circuit breaker: it stops opening and
          its open positions still run to their own frozen exits. Cash is allowed to win.
        </p>
      </Panel>
      {selected ? <Drawer id={selected} onClose={() => setSelected(null)} /> : null}
      <Rulebook rules={data.rulebook ?? []} specHash={data.spec_hash} />
    </div>
  );
}
