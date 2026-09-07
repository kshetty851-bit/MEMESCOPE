"use client";

import { useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useDepthBoard } from "@/hooks/use-lab";
import type { DepthCell } from "@/types/depth";

import { toneOf } from "../strategy-lab/tone";

/**
 * DEPTH — twenty wallets that differ in one number.
 *
 * Rendered as a CURVE and never as a leaderboard. One cell beating another can
 * be luck — that is precisely what the Momentum V2 result which prompted this
 * experiment might have been, a $1M control at $126.50 beside a $300k twin at
 * zero. Only a monotonic trend across twenty points means anything, and sorting
 * these rows by outcome would put the winner on top and destroy the only thing
 * being measured.
 *
 * Research simulation. No real order was ever placed.
 */

function money(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(d)}`;
}

function signed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

function floorLabel(v: number): string {
  return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(v % 1_000_000 ? 2 : 0)}M`
                        : `$${Math.round(v / 1000)}k`;
}

/**
 * One cell: the rule it trades, and every trade it has made.
 *
 * Collapsed by default. Twenty cells with their full ledgers open at once is a
 * page nobody reads, and the curve above is the result — this is the evidence
 * underneath it, for when a cell looks interesting and the next question is
 * "on what".
 */
function CellPanel({ cell, start }: { cell: DepthCell; start: number }) {
  const [open, setOpen] = useState(false);
  const eq = Number(cell.equity);
  const trades = cell.trades ?? [];
  const shown = trades.length;
  const total = cell.open_positions + cell.closed_positions;

  return (
    <Panel density="compact">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-baseline justify-between gap-3 text-left"
      >
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] text-muted">{open ? "▾" : "▸"}</span>
          <Label>
            {cell.strategy_id} · {cell.name}
          </Label>
        </span>
        <span className="flex flex-wrap items-baseline gap-x-5 font-mono text-[11px]">
          <span className={toneOf(eq - start)}>{money(eq)}</span>
          <span className="text-muted">{cell.open_positions} open</span>
          <span className="text-muted">{cell.closed_positions} closed</span>
          <span className={toneOf(Number(cell.realised_pnl))}>
            {signed(cell.realised_pnl)} realised
          </span>
          <span className="text-muted">{cell.cycles_banked} banked</span>
        </span>
      </button>

      {open ? (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          <p className="text-xs text-ink-3">{cell.hypothesis}</p>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">
                Buys when, at {cell.checkpoint_label}
              </p>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                {cell.entry_text.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">
                Sells when
              </p>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-ink">
                {/* The wallet target is not in `exit_text` — no position
                    carries it — and it is the exit that defines this lab. */}
                <li className="text-accent">
                  · the WALLET reaches its target ({money(cell.target_usd)}) —
                  sells everything
                </li>
                {cell.exit_text.map((t) => (
                  <li key={t}>· {t}</li>
                ))}
              </ul>
            </div>
          </div>

          <p className="font-mono text-[10px] text-muted">
            {money(Number(cell.size_usd), 0)} per position · max{" "}
            {cell.max_concurrent} open · cycle {cell.cycle_no ?? "—"} from{" "}
            {money(cell.base_usd)} to {money(cell.target_usd)}
          </p>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">
              Trades ({shown === total ? total : `${shown} of ${total}`})
            </p>
            {trades.length === 0 ? (
              <p className="mt-1 text-xs text-muted">
                This cell has not traded yet.
              </p>
            ) : (
              <div className="mt-1 max-h-72 overflow-auto">
                <table className="w-full text-left font-mono text-[11px]">
                  <thead className="text-muted">
                    <tr>
                      <th className="py-1 pr-3 font-normal">status</th>
                      <th className="py-1 pr-3 font-normal">mint</th>
                      <th className="py-1 pr-3 font-normal">opened</th>
                      <th className="py-1 pr-3 font-normal">closed</th>
                      <th className="py-1 pr-3 text-right font-normal">size</th>
                      <th className="py-1 pr-3 text-right font-normal">value</th>
                      <th className="py-1 pr-3 text-right font-normal">P&L</th>
                      <th className="py-1 font-normal">exit</th>
                    </tr>
                  </thead>
                  <tbody className="text-ink">
                    {trades.map((t) => (
                      <tr key={t.id} className="border-t border-line">
                        <td
                          className={`py-1 pr-3 ${
                            t.status === "open" ? "text-accent" : "text-muted"
                          }`}
                        >
                          {t.status}
                        </td>
                        <td className="py-1 pr-3">{t.mint.slice(0, 8)}…</td>
                        <td className="py-1 pr-3">
                          {t.opened_at.slice(5, 16).replace("T", " ")}
                        </td>
                        <td className="py-1 pr-3">
                          {t.closed_at
                            ? t.closed_at.slice(5, 16).replace("T", " ")
                            : "—"}
                        </td>
                        <td className="py-1 pr-3 text-right">
                          {money(t.size_usd)}
                        </td>
                        <td className="py-1 pr-3 text-right">{money(t.value)}</td>
                        <td className={`py-1 pr-3 text-right ${toneOf(t.pnl)}`}>
                          {signed(t.pnl)}
                        </td>
                        <td className="py-1 text-muted">
                          {t.exit_reason ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

export default function DepthLabPage() {
  const { data, isLoading, error } = useDepthBoard();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !data) return <ErrorState body="Depth Lab unavailable." />;

  if (!data.activated) {
    return (
      <Panel density="compact">
        <Label>DEPTH</Label>
        <p className="mt-2 text-sm text-ink">Not started yet.</p>
        <p className="mt-1 text-xs text-muted">
          Twenty wallets open at {money(data.starting_equity, 0)} each, from a
          $25k liquidity floor to $1M, and bank whenever they are up{" "}
          {((Number(data.target_multiple) - 1) * 100).toFixed(0)}%.
        </p>
      </Panel>
    );
  }

  const cells = data.wallets;
  const start = Number(data.starting_equity);
  const max = Math.max(start, ...cells.map((c) => Number(c.equity)));
  const traded = cells.filter((c) => c.open_positions > 0 || c.cycles_banked > 0);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel density="compact">
        <Label>DEPTH — LIQUIDITY IS THE ONLY VARIABLE</Label>
        <h1 className="mt-1 text-lg font-medium text-ink">
          20 WALLETS · {money(start, 0)} EACH · $25k → $1M FLOOR · BANK AT +
          {((Number(data.target_multiple) - 1) * 100).toFixed(0)}%
        </h1>
        <p className="mt-1 text-xs font-medium tracking-wide text-warn">
          PAPER / RESEARCH ONLY — REAL MONEY OFF
        </p>
        <p className="mt-2 text-[10px] leading-relaxed text-muted">
          {data.disclosure}
        </p>
      </Panel>

      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <Label>THE CURVE</Label>
          <p className="text-[10px] text-muted">
            Read the SHAPE, not the winner. A single cell above the rest is
            noise; a rise across the ladder is a result.
          </p>
        </div>
        <div className="mt-3 space-y-1">
          {cells.map((c) => {
            const eq = Number(c.equity);
            const pct = max > 0 ? (eq / max) * 100 : 0;
            const startPct = max > 0 ? (start / max) * 100 : 0;
            return (
              <div key={c.strategy_id} className="flex items-center gap-2">
                <span className="w-14 shrink-0 text-right font-mono text-[10px] text-muted">
                  {floorLabel(c.floor_usd)}
                </span>
                <div className="relative h-4 flex-1 overflow-hidden rounded-sm bg-surface-2">
                  <div
                    className={`h-full ${eq >= start ? "bg-up/40" : "bg-down/40"}`}
                    style={{ width: `${Math.max(pct, 0.5)}%` }}
                  />
                  {/* The $100 start line: above it is a gain, below it a loss. */}
                  <div
                    className="absolute inset-y-0 w-px bg-ink-3"
                    style={{ left: `${startPct}%` }}
                  />
                </div>
                <span
                  className={`w-20 shrink-0 text-right font-mono text-[11px] ${toneOf(eq - start)}`}
                >
                  {money(eq)}
                </span>
                <span className="w-24 shrink-0 font-mono text-[10px] text-muted">
                  {c.cycles_banked} banked
                </span>
              </div>
            );
          })}
        </div>
        <p className="mt-3 border-t border-line pt-2 text-[10px] text-muted">
          {traded.length} of {cells.length} cells have traded. The vertical line
          is the {money(start, 0)} start. Above $500k there were 29 pump.fun
          tokens in three days and above $1M only ten, so the top cells trade
          rarely and repeatedly — a gain up there is an effect over about ten
          names, which is a watchlist rather than a strategy.
        </p>
      </Panel>

      {cells.map((c) => (
        <CellPanel key={c.strategy_id} cell={c} start={start} />
      ))}

    </div>
  );
}
