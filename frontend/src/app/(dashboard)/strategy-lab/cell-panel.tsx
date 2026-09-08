"use client";

import { useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import type { LabCell } from "@/types/lab-cell";

import { toneOf } from "./tone";

/**
 * One ratchet wallet: the rule it trades, and every trade it has made.
 *
 * Shared by the Depth curve and the Social pair — it was written for the first
 * and copied to the second before it was shared. What differs between those
 * boards is the x-axis and the ORDER, and neither belongs in here.
 *
 * Collapsed by default. Twenty ledgers open at once is a page nobody reads;
 * the board above is the result and this is the evidence underneath it, for
 * when a wallet looks interesting and the next question is "on what".
 */
export function money(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(d)}`;
}

export function signed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

export function floorLabel(v: number): string {
  return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(v % 1_000_000 ? 2 : 0)}M`
                        : `$${Math.round(v / 1000)}k`;
}

export function CellPanel({ cell, start }: { cell: LabCell; start: number }) {
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

