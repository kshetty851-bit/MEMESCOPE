"use client";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useMomentumBoard } from "@/hooks/use-lab";

import { toneOf } from "../strategy-lab/tone";

/**
 * MOMENTUM V2 — twenty pump.fun wallets, each ratcheting at +10%.
 *
 * The two RANDOM CONTROLS are marked wherever they appear, and the page says
 * what they are for. Every no-edge finding on this platform was produced by a
 * control rather than by a strategy, and the random arm has beaten the designed
 * ones twice — so a reader who cannot tell which rows are controls cannot read
 * the leaderboard at all. The top wallet always looks good; the only question
 * is whether it looks better than buying at random from the same pool under the
 * same rules.
 *
 * Research simulation. No real order was ever placed.
 */

function money(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(d)}`;
}

export default function MomentumLabPage() {
  const { data, isLoading, error } = useMomentumBoard();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !data) return <ErrorState body="Momentum V2 unavailable." />;

  if (!data.activated) {
    return (
      <Panel density="compact">
        <Label>MOMENTUM V2</Label>
        <p className="mt-2 text-sm text-ink">Not started yet.</p>
        <p className="mt-1 text-xs text-muted">
          Twenty wallets open at {money(data.starting_equity, 0)} each and bank
          whenever they are up{" "}
          {((Number(data.target_multiple) - 1) * 100).toFixed(0)}%.
        </p>
      </Panel>
    );
  }

  const controls = data.wallets.filter((w) => w.is_control);
  const best = data.wallets[0];
  const bestControl = controls[0];
  // The comparison that decides whether any of this means anything.
  const beatingControl = bestControl
    ? data.wallets.filter((w) => !w.is_control && w.equity > bestControl.equity).length
    : null;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <Label>MOMENTUM V2</Label>
            <h1 className="mt-1 text-lg font-medium text-ink">
              {data.wallets.length} WALLETS · {money(data.starting_equity, 0)} EACH ·
              BANK AT +{((Number(data.target_multiple) - 1) * 100).toFixed(0)}% ·
              PUMP.FUN ONLY
            </h1>
            <p className="mt-1 text-xs font-medium tracking-wide text-warn">
              PAPER / RESEARCH ONLY — REAL MONEY OFF
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-muted">Best wallet</dt>
              <dd className={`font-mono ${toneOf(Number(best?.equity ?? 0) - Number(data.starting_equity))}`}>
                {money(best?.equity)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Best control</dt>
              <dd className={`font-mono ${toneOf(Number(bestControl?.equity ?? 0) - Number(data.starting_equity))}`}>
                {money(bestControl?.equity)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Beating it</dt>
              <dd className="font-mono text-ink">
                {beatingControl === null ? "—" : `${beatingControl} / 18`}
              </dd>
            </div>
          </dl>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-muted">
          {data.disclosure}
        </p>
      </Panel>

      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <Label>LEADERBOARD</Label>
          <p className="text-[10px] text-muted">
            <span className="text-warn">CONTROL</span> rows buy anything above
            their liquidity floor with no momentum condition. A momentum wallet
            that does not beat them has shown nothing.
          </p>
        </div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">#</th>
                <th className="py-1 pr-3 font-normal">wallet</th>
                <th className="py-1 pr-3 text-right font-normal">equity</th>
                <th className="py-1 pr-3 text-right font-normal">cash</th>
                <th className="py-1 pr-3 text-right font-normal">open</th>
                <th className="py-1 pr-3 text-right font-normal">banked</th>
                <th className="py-1 pr-3 text-right font-normal">cycle</th>
                <th className="py-1 pr-3 text-right font-normal">target</th>
                <th className="py-1 font-normal">buys when</th>
              </tr>
            </thead>
            <tbody className="text-ink">
              {data.wallets.map((w) => (
                <tr
                  key={w.strategy_id}
                  className={`border-t border-line ${
                    w.is_control ? "bg-warn/[0.06]" : ""
                  }`}
                >
                  <td className="py-1 pr-3">{w.rank}</td>
                  <td className="whitespace-nowrap py-1 pr-3">
                    {w.strategy_id} {w.name}
                    {w.is_control ? (
                      <span className="ml-1 text-warn">CONTROL</span>
                    ) : null}
                  </td>
                  <td
                    className={`py-1 pr-3 text-right ${toneOf(
                      Number(w.equity) - Number(data.starting_equity),
                    )}`}
                  >
                    {money(w.equity)}
                  </td>
                  <td className="py-1 pr-3 text-right">{money(w.cash)}</td>
                  <td className="py-1 pr-3 text-right">{w.open_positions}</td>
                  <td className="py-1 pr-3 text-right">{w.cycles_banked}</td>
                  <td className="py-1 pr-3 text-right">{w.cycle_no ?? "—"}</td>
                  <td className="py-1 pr-3 text-right">{money(w.target_usd)}</td>
                  <td className="whitespace-nowrap py-1 text-muted">
                    {w.entry_text.join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
