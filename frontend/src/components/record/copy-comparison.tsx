"use client";

import { Label, Panel } from "@/components/ui/panel";
import { useCopyComparison } from "@/hooks/use-copytrade";
import type { CopyArm, CopyVerdict } from "@/types/copytrade";

/**
 * CPY-01 against CPY-02 — the only live experiment with a control.
 *
 * It sits on the Track Record page because this is where the question "did any
 * of it work?" is asked, and because the honest answer to that question is a
 * comparison rather than a number. An equity curve on its own cannot tell you
 * whether copying the leader beat buying at random at the same moments; that is
 * what put four previous findings on this platform in the bin.
 *
 * The verdict is NOT computed here. It comes from the server so a single
 * implementation owns the bar — 25 paired trades, and a lead that survives
 * removing the single best trade — and so it cannot quietly differ between the
 * page and the API.
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

function tone(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > 0 ? "text-up" : Number(v) < 0 ? "text-down" : "text-ink";
}

const VERDICT_STYLE: Record<CopyVerdict, string> = {
  control_not_started: "text-muted",
  not_enough_data: "text-muted",
  carried_by_one_trade: "text-warn",
  control_matches_or_wins: "text-down",
  signal_beats_control: "text-up",
};

const VERDICT_LABEL: Record<CopyVerdict, string> = {
  control_not_started: "CONTROL NOT STARTED",
  not_enough_data: "TOO EARLY TO SAY",
  carried_by_one_trade: "CARRIED BY ONE TRADE",
  control_matches_or_wins: "NO EDGE — THE CONTROL HELD",
  signal_beats_control: "SIGNAL BEATS ITS CONTROL",
};

function Arm({ arm }: { arm: CopyArm }) {
  const isControl = arm.role === "control";
  const eq = Number(arm.equity);
  return (
    <div className="flex-1">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{isControl ? "CONTROL" : "SIGNAL"}</Label>
        <span className="font-mono text-[10px] text-muted">{arm.strategy_id ?? "—"}</span>
      </div>
      <p className={`mt-1 font-mono text-xl ${tone(eq - 100)}`}>{money(eq)}</p>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-3">
        {isControl
          ? "Buys a RANDOM pump.fun token at the same moments, same size, held exactly as long."
          : "Copies the leader's token. Everything else is identical to the control."}
      </p>
      <dl className="mt-2 space-y-0.5 font-mono text-[10px] text-muted">
        <div className="flex justify-between">
          <dt>closed trades</dt>
          <dd className="text-ink">{arm.closed_trades ?? 0}</dd>
        </div>
        <div className="flex justify-between">
          <dt>realised</dt>
          <dd className={tone(arm.realised_pnl)}>{signed(arm.realised_pnl)}</dd>
        </div>
        <div className="flex justify-between">
          <dt title="The same record with its single best trade removed.">
            without best trade
          </dt>
          <dd className={tone(arm.realised_pnl_excluding_best)}>
            {signed(arm.realised_pnl_excluding_best)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function CopyComparisonPanel() {
  const { data, isLoading, error } = useCopyComparison();
  if (isLoading || error || !data || !data.activated) return null;

  const signal = data.arms.find((a) => a.role === "signal");
  const control = data.arms.find((a) => a.role === "control");
  if (!signal?.present || !control?.present) return null;

  const n = data.paired_closed_trades ?? 0;
  const target = data.bar.min_closed_trades;
  const pct = Math.min(100, target > 0 ? (n / target) * 100 : 0);

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Label>COPY TRADING — SIGNAL vs ITS CONTROL</Label>
        <span className={`font-mono text-[10px] ${VERDICT_STYLE[data.verdict]}`}>
          {VERDICT_LABEL[data.verdict]}
        </span>
      </div>

      <div className="mt-3 flex flex-col gap-6 sm:flex-row sm:gap-8">
        <Arm arm={signal} />
        <div className="hidden w-px shrink-0 bg-line sm:block" />
        <Arm arm={control} />
      </div>

      {/* Progress toward a sample size that can carry a conclusion. The bar was
          fixed before any data arrived; showing it as a target stops the page
          reading like a scoreboard while it is still noise. */}
      <div className="mt-4 border-t border-line pt-3">
        <div className="flex items-baseline justify-between font-mono text-[10px] text-muted">
          <span>paired closed trades</span>
          <span className="text-ink">
            {n} / {target}
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-sm bg-surface-2">
          <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-muted">{data.verdict_detail}</p>
      </div>

      <p className="mt-3 text-[10px] leading-relaxed text-muted">
        Only trades opened after the control started are counted on either side.
        Everything CPY-01 did before that — including its 4.8× — has no control
        and never will, so it is excluded rather than credited.
      </p>
    </Panel>
  );
}
