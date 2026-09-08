"use client";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useSocialBoard } from "@/hooks/use-lab";
import type { SocialCell } from "@/types/social";

import { CellPanel, money, signed } from "../strategy-lab/cell-panel";
import { toneOf } from "../strategy-lab/tone";

/**
 * SOCIAL — the first rule here that reads something other than a price.
 *
 * Twelve experiments varied liquidity, momentum, flow, size, hold time and
 * take-profit. All of those are properties of the MARKET, and the payoff space
 * has since been measured whole: no fat tail, and every exit level negative and
 * monotonically worse the higher it aims. This pair reads how many people are
 * COMMENTING on a coin, which none of them could see.
 *
 * Rendered as a COMPARISON and never as a ranking. The two wallets are one
 * condition apart, and the gap between them — in either direction, including
 * none — is the entire result. Sorting them by equity would float today's
 * winner to the top and invite a reader to take position for finding.
 *
 * Research simulation. No real order was ever placed.
 */

function Arm({ cell, start }: { cell: SocialCell; start: number }) {
  const eq = Number(cell.equity);
  const delta = eq - start;
  return (
    <div className="flex-1">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{cell.is_control ? "CONTROL" : "SIGNAL"}</Label>
        <span className="font-mono text-[10px] text-muted">
          {cell.strategy_id}
        </span>
      </div>
      <p className="mt-1 font-mono text-xl text-ink">
        <span className={toneOf(delta)}>{money(eq)}</span>
      </p>
      <p className={`font-mono text-[11px] ${toneOf(delta)}`}>
        {signed(delta)} from {money(start, 0)}
      </p>
      <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
        {cell.is_control
          ? "Buys any pump.fun coin in the social feed it can price. Does not look at whether comments are rising."
          : "Buys only when the coin's comment rate is going UP. Everything else is identical to the control."}
      </p>
      <p className="mt-2 font-mono text-[10px] text-muted">
        {cell.open_positions} open · {cell.closed_positions} closed ·{" "}
        {cell.cycles_banked} banked
      </p>
    </div>
  );
}

export default function SocialLabPage() {
  const { data, isLoading, error } = useSocialBoard();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !data) return <ErrorState body="Social Lab unavailable." />;

  const pct = ((Number(data.target_multiple) - 1) * 100).toFixed(0);

  if (!data.activated) {
    return (
      <Panel density="compact">
        <Label>SOCIAL</Label>
        <p className="mt-2 text-sm text-ink">Not started yet.</p>
        <p className="mt-1 text-xs text-muted">
          Two wallets open at {money(data.starting_equity, 0)} each and bank
          whenever they are up {pct}%.
        </p>
      </Panel>
    );
  }

  const cells = data.wallets;
  const start = Number(data.starting_equity);
  const signal = cells.find((c) => !c.is_control);
  const control = cells.find((c) => c.is_control);
  const gap =
    signal && control ? Number(signal.equity) - Number(control.equity) : null;
  const traded = cells.reduce(
    (n, c) => n + c.open_positions + c.closed_positions,
    0,
  );

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel density="compact">
        <Label>SOCIAL — ATTENTION AGAINST ITS OWN CONTROL</Label>
        <h1 className="mt-1 text-lg font-medium text-ink">
          2 WALLETS · {money(start, 0)} EACH · ONE CONDITION APART · BANK AT +
          {pct}%
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
          <Label>THE COMPARISON</Label>
          <p className="text-[10px] text-muted">
            Read the GAP, not the winner. Either wallet ahead on a handful of
            trades is noise.
          </p>
        </div>
        <div className="mt-3 flex flex-col gap-6 sm:flex-row sm:gap-8">
          {signal ? <Arm cell={signal} start={start} /> : null}
          <div className="hidden w-px shrink-0 bg-line sm:block" />
          {control ? <Arm cell={control} start={start} /> : null}
        </div>
        <p className="mt-4 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
          {traded === 0 ? (
            <>
              Nothing traded yet. Comment rate needs two readings of the same
              coin ten minutes apart and does not exist until it has them, so
              the signal wallet cannot fire on its first pass — that is the rule
              refusing to guess, not a fault.
            </>
          ) : (
            <>
              Signal is{" "}
              <span className={toneOf(gap)}>{signed(gap)}</span> against its
              control over {traded} trades. If the two finish level, attention
              is not a signal either — and that is a real answer, not a failed
              one. Every no-edge finding on this platform came from a control
              rather than from a strategy.
            </>
          )}
        </p>
      </Panel>

      {cells.map((c) => (
        <CellPanel key={c.strategy_id} cell={c} start={start} />
      ))}
    </div>
  );
}
