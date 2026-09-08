"use client";

import { FiveMinTradesPanel } from "@/components/fivemin/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";
import { useFiveMinBoard } from "@/hooks/use-fivemin";
import type { FiveMinCycle } from "@/types/fivemin";

/**
 * THE FIVE-MINUTE LAB.
 *
 * One wallet testing two changes against the Compound Lab: a five-minute hold
 * instead of six hours, and a stake that never follows the balance.
 *
 * The disclosure is rendered FIRST and is not collapsible. This lab exists
 * because one coin in a graduation cohort of 138 did 47.97x; without that
 * trade the observation it rests on returns +$35 rather than +$505. A reader
 * who meets the equity figure before that sentence has already been told what
 * to think about it.
 */

function money(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(2)}`;
}

function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function when(iso: string): string {
  return iso.slice(5, 16).replace("T", " ");
}

function CycleRow({ c, base }: { c: FiveMinCycle; base: number }) {
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 pr-3 font-mono text-[10px] text-muted">#{c.cycle_no}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{money(c.base_usd)}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{money(c.target_usd)}</td>
      <td className={`py-1.5 pr-3 text-right font-mono ${tone(c.realised_equity, base)}`}>
        {money(c.realised_equity)}
      </td>
      <td className="py-1.5 pr-3 text-right font-mono text-muted">{c.positions_closed ?? "—"}</td>
      <td className="py-1.5 font-mono text-[10px] text-muted">
        {c.reached_at ? when(c.reached_at) : "running"}
      </td>
    </tr>
  );
}

export default function FiveMinLabPage() {
  const { data, isLoading, isError } = useFiveMinBoard();

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Five-Minute Lab"
        title="The wallet ratchet, on a five-minute hold."
        description="One $100 wallet. Same entry and same +10% wallet target as the Compound Lab; the hold is five minutes instead of six hours and the stake never follows the balance. Nothing here is real money."
      />

      {/* Deliberately above the numbers, and deliberately not collapsible. */}
      <Panel density="compact">
        <Label>WHY TO DISTRUST THIS</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "A hypothesis, not a finding. The five-minute hold comes from a graduation cohort where one coin of 138 produced most of the profit."}
        </p>
      </Panel>

      {isLoading ? (
        <Panel density="compact">
          <p className="text-xs text-muted">Loading…</p>
        </Panel>
      ) : isError ? (
        <Panel density="compact">
          <p className="text-xs text-down">The board could not be read.</p>
        </Panel>
      ) : !data?.activated ? (
        <Panel density="compact">
          <Label>NOT ACTIVATED</Label>
          <p className="mt-2 text-xs text-muted">
            The registry exists ({data?.spec_version}) but no tournament has been
            opened, so nothing is trading yet.
          </p>
        </Panel>
      ) : (
        <>
          <Panel density="compact">
            <Label>THE WALLET</Label>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <div className="text-[10px] uppercase text-muted">Equity</div>
                <div className={`font-mono text-lg ${tone(data.equity, Number(data.starting_equity ?? 100))}`}>
                  {money(data.equity)}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-muted">Cash</div>
                <div className="font-mono text-lg text-ink">{money(data.cash)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-muted">Open book</div>
                <div className="font-mono text-lg text-ink">{money(data.open_value)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase text-muted">Cycles banked</div>
                <div className="font-mono text-lg text-ink">{data.cycles_banked ?? 0}</div>
              </div>
            </div>
            <p className="mt-3 text-[11px] text-muted">
              Hold {data.time_exit_minutes ?? 5} minutes · stake{" "}
              {data.sizing_scales === false ? "flat, never scales with the balance" : "scales with equity"} ·
              cycle target {data.target_multiple ? `${Number(data.target_multiple).toFixed(2)}x` : "—"} ·
              status {data.status ?? "—"}
            </p>
          </Panel>

          <Panel density="compact">
            <Label>CYCLES</Label>
            {data.cycles.length === 0 ? (
              <p className="mt-2 text-xs text-muted">No cycle has been opened yet.</p>
            ) : (
              <table className="mt-2 w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase text-muted">
                    <th className="pb-1 pr-3 text-left font-normal">Cycle</th>
                    <th className="pb-1 pr-3 text-right font-normal">Base</th>
                    <th className="pb-1 pr-3 text-right font-normal">Target</th>
                    <th className="pb-1 pr-3 text-right font-normal">Realised</th>
                    <th className="pb-1 pr-3 text-right font-normal">Closed</th>
                    <th className="pb-1 text-left font-normal">Reached</th>
                  </tr>
                </thead>
                <tbody>
                  {data.cycles.map((c) => (
                    <CycleRow key={c.cycle_no} c={c} base={Number(c.base_usd ?? 100)} />
                  ))}
                </tbody>
              </table>
            )}
          </Panel>

          {/* Every trade, open and closed, each with its own P&L. The board's
              `positions` was a display window; this is the record. */}
          <FiveMinTradesPanel />
        </>
      )}
    </div>
  );
}
