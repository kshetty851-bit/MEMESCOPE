"use client";

import { useMemo } from "react";

import { Label, Panel } from "@/components/ui/panel";

import type { MatrixWallet } from "@/types/matrix";

/**
 * One section of the Matrix Lab: a table whose ROWS are book shapes and whose
 * COLUMNS are holding periods, so two adjacent cells differ in exactly one
 * thing and a whole row or column reads as a dose-response.
 *
 * Shared by the Matrix Lab page and the Movers Lab page, which shows the same
 * two sections beneath its own arms — the operator asked to see every
 * strategy in one place, in sections, and a grid that lived only on a page of
 * its own was a grid nobody found.
 *
 * Nothing here sorts, highlights or ranks by outcome. With twenty-four books
 * the single best line is very probably noise, and a board that put the
 * leader on top would invite precisely the reading this design exists to
 * prevent. The only interaction is picking a cell.
 */

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
}

export function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function clockLabel(m: number | null): string {
  return m === null ? "no clock" : `${m} min`;
}

/** One cell. Deliberately the same size and weight whatever it holds. */
function Cell({
  w,
  starting,
  selected,
  onSelect,
}: {
  w: MatrixWallet | undefined;
  starting: number;
  selected: boolean;
  onSelect: () => void;
}) {
  if (!w) {
    return (
      <td className="border border-line p-2 text-center text-[10px] text-muted">—</td>
    );
  }
  return (
    <td className="border border-line p-0 align-top">
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`flex w-full flex-col gap-0.5 p-2 text-left transition-colors ${
          selected ? "bg-accent/10 ring-1 ring-inset ring-accent/40" : "hover:bg-line/30"
        }`}
      >
        <span className="font-mono text-[10px] uppercase text-muted">{w.strategy_id}</span>
        <span className={`font-mono text-base tabular-nums ${tone(w.equity, starting)}`}>
          {money(w.equity)}
        </span>
        <span className={`font-mono text-[10px] tabular-nums ${tone(w.realised_pnl, 0)}`}>
          real {money(w.realised_pnl)}
        </span>
        <span className="font-mono text-[10px] text-muted tabular-nums">
          {w.open_positions} open · {w.closed_positions} closed
        </span>
      </button>
    </td>
  );
}

export function MatrixSection({
  title,
  blurb,
  wallets,
  starting,
  selected,
  onSelect,
}: {
  title: string;
  blurb: string;
  wallets: MatrixWallet[];
  starting: number;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  // Axes read off the data rather than hardcoded, so the page cannot drift
  // from the spec if an arm is added or a clock changed.
  const clocks = useMemo(() => {
    const seen = new Map<string, number | null>();
    for (const w of wallets) seen.set(String(w.clock_minutes), w.clock_minutes);
    return [...seen.values()].sort((a, b) => {
      if (a === null) return 1;
      if (b === null) return -1;
      return a - b;
    });
  }, [wallets]);

  const shapes = useMemo(() => {
    const seen: string[] = [];
    for (const w of wallets) {
      const s = w.shape ?? "—";
      if (!seen.includes(s)) seen.push(s);
    }
    return seen;
  }, [wallets]);

  const at = (shape: string, clock: number | null) =>
    wallets.find((w) => (w.shape ?? "—") === shape && w.clock_minutes === clock);

  const equity = wallets.reduce((sum, w) => sum + Number(w.equity ?? 0), 0);
  const book = starting * wallets.length;

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Label>{title}</Label>
        <span className="font-mono text-[10px] text-muted tabular-nums">
          {wallets.length} arms · {money(book)} deployed ·{" "}
          <span className={tone(equity, book)}>{money(equity)}</span> now
        </span>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-ink-3">{blurb}</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse">
          <thead>
            <tr>
              <th className="border border-line p-2 text-left text-[10px] uppercase text-muted">
                book shape
              </th>
              {clocks.map((c) => (
                <th
                  key={String(c)}
                  className="border border-line p-2 text-center text-[10px] uppercase text-muted"
                >
                  {clockLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shapes.map((shape) => (
              <tr key={shape}>
                <th className="border border-line p-2 text-left font-mono text-[11px] font-normal text-ink">
                  {shape}
                </th>
                {clocks.map((c) => {
                  const w = at(shape, c);
                  return (
                    <Cell
                      key={`${shape}-${String(c)}`}
                      w={w}
                      starting={starting}
                      selected={!!w && w.strategy_id === selected}
                      onSelect={() => w && onSelect(w.strategy_id)}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/** The two sections' copy, kept beside the grid so both pages say the same thing. */
export const FRESH_BLURB =
  "Drawn from the radar stream and required to carry the launchpad's own mint suffix, which is the filter that removed the impostor pairs from the Movers Lab. These coins are minutes to hours old: across 148 coins the movers labs judged, the median age at the checkpoint was 1.26 hours and the oldest 18.5.";

export const AGED_BLURB =
  "Sampled from deep Raydium, Orca, Meteora and MetaDAO markets, with the age condition enforced rather than assumed. The honest prior: a breakout entry on established tokens has already measured 2.73 percentage points WORSE than a random bar in the same tokens. This section runs to find out whether the CLOCK behaves differently here, not because the population is expected to win.";
