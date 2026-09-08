"use client";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useDepthBoard } from "@/hooks/use-lab";

import { CellPanel, floorLabel, money } from "../strategy-lab/cell-panel";
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
