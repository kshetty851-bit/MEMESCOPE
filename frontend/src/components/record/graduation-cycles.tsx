"use client";

import { Label, Panel } from "@/components/ui/panel";
import { useGraduationCycles } from "@/hooks/use-graduation";
import type { CycleRound } from "@/types/graduation";

/**
 * $100 compounded hourly: buy the hour's graduations, close everything at
 * +60m, stake the proceeds on the next hour.
 *
 * Compounding is the whole point and also the trap. One hour that multiplies
 * the balance lifts every hour after it, so a final figure can be a single
 * round wearing a sequence's clothes — which is why the balance WITHOUT the
 * best round sits beside it and always will.
 */

function money(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(2)}`;
}

function tone(v: number | null | undefined, base = 100): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function hourLabel(iso: string): string {
  return iso.slice(5, 16).replace("T", " ");
}

function Round({ r }: { r: CycleRound }) {
  const mult = r.round_multiple;
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 pr-3 font-mono text-[10px] text-muted">
        {hourLabel(r.hour)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">
        {r.traded}
        {r.no_mark > 0 ? (
          <span className="text-[9px]"> (+{r.no_mark} pending)</span>
        ) : null}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">
        {r.stake_each ? money(r.stake_each) : "—"}
      </td>
      <td className={`py-1.5 pr-3 text-right font-mono ${tone(mult, 1)}`}>
        {mult === null ? "—" : `${mult.toFixed(2)}x`}
      </td>
      <td className={`py-1.5 text-right font-mono ${tone(r.closed_with)}`}>
        {money(r.closed_with)}
      </td>
    </tr>
  );
}

export function GraduationCyclesPanel() {
  const { data, isLoading, error } = useGraduationCycles();
  if (isLoading) return null;
  if (error || !data) {
    return (
      <Panel density="compact">
        <Label>$100 COMPOUNDED HOURLY</Label>
        <p className="mt-2 text-xs text-muted">
          Not available. The endpoint did not answer — usually the backend
          running an older build than this page.
        </p>
      </Panel>
    );
  }

  const carried =
    data.final_balance > data.start_usd &&
    data.final_balance_without_best_round <= data.start_usd;

  return (
    <Panel density="compact">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Label>${data.start_usd} COMPOUNDED HOURLY — CLOSE EVERYTHING AT +60m</Label>
        <span className="font-mono text-[10px] text-muted">
          {data.rounds_traded} of {data.rounds_total} hours traded
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-muted">balance</p>
          <p className={`font-mono text-xl ${tone(data.final_balance)}`}>
            {money(data.final_balance)}
          </p>
        </div>
        <div>
          <p
            className="text-[10px] uppercase tracking-wide text-muted"
            title="The same sequence with its single best hour removed."
          >
            without best hour
          </p>
          <p
            className={`font-mono text-xl ${tone(data.final_balance_without_best_round)}`}
          >
            {money(data.final_balance_without_best_round)}
          </p>
        </div>
        {data.best_round_multiple ? (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">best hour</p>
            <p className="font-mono text-xl text-ink">
              {data.best_round_multiple.toFixed(2)}x
            </p>
          </div>
        ) : null}
      </div>

      {carried ? (
        <p className="mt-3 text-[11px] text-warn">
          Carried by one hour. Compounding lifts every later round by the same
          factor, so this sequence is that single hour rather than a repeatable
          edge.
        </p>
      ) : null}

      <div className="mt-3 max-h-80 overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="text-[10px] uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">hour</th>
              <th className="py-1 pr-3 text-right font-normal">coins</th>
              <th className="py-1 pr-3 text-right font-normal">stake each</th>
              <th className="py-1 pr-3 text-right font-normal">round</th>
              <th className="py-1 text-right font-normal">closed with</th>
            </tr>
          </thead>
          <tbody>
            {data.rounds.map((r) => (
              <Round key={r.hour} r={r} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
        {data.disclosure}
      </p>
    </Panel>
  );
}
