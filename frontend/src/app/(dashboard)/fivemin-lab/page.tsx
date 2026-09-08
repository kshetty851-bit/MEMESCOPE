"use client";

import { FiveMinTradesPanel } from "@/components/fivemin/trades-panel";
import { Label, Panel } from "@/components/ui/panel";
import { Toolbar } from "@/components/ui/toolbar";
import { useFiveMinBoard } from "@/hooks/use-fivemin";
import type { FiveMinWallet } from "@/types/fivemin";

/**
 * THE GRADUATION HOLD LAB.
 *
 * Two wallets buying the pump.fun graduation cohort — the population the
 * five-minute number actually came from — identical in every respect except
 * when they sell: one at five minutes, one at fifteen. They take the same
 * entry object at the same instant and stake the same flat $10, so the gap
 * between their records is the clock and nothing else.
 *
 * The disclosure is rendered FIRST and is not collapsible. The fifteen-minute
 * hold has already measured about -8.5% net per trade on 1,348 real positions,
 * and the five-minute figure that motivated the lab rests on one coin of 138
 * doing 47.97x. A reader who meets the equity numbers before those sentences
 * has already been told what to think about them.
 */

function money(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(Number(v))
    ? "—"
    : `$${Number(v).toFixed(2)}`;
}

function signed(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

function tone(v: number | null | undefined, base: number): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "text-muted";
  return Number(v) > base ? "text-up" : Number(v) < base ? "text-down" : "text-ink";
}

function ArmCard({ w, base }: { w: FiveMinWallet; base: number }) {
  return (
    <Panel density="compact">
      <div className="flex items-baseline justify-between gap-2">
        <Label>{w.hold_minutes ? `SELLS AT ${w.hold_minutes} MIN` : w.name}</Label>
        <span className="font-mono text-[10px] text-muted">{w.strategy_id}</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] uppercase text-muted">Equity</div>
          <div className={`font-mono text-lg ${tone(w.equity, base)}`}>{money(w.equity)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Realised P&amp;L</div>
          <div className={`font-mono text-lg ${tone(w.realised_pnl, 0)}`}>
            {signed(w.realised_pnl)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Cash</div>
          <div className="font-mono text-sm text-ink">{money(w.cash)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-muted">Open book</div>
          <div className="font-mono text-sm text-ink">{money(w.open_value)}</div>
        </div>
      </div>

      <p className="mt-3 text-[11px] text-muted">
        {w.open_positions} open of {w.max_concurrent ?? "—"} · {w.closed_positions} closed ·
        stake {money(w.size_usd)} flat · status {w.status ?? "—"}
      </p>
    </Panel>
  );
}

function GapPanel({ a, b, base }: { a: FiveMinWallet; b: FiveMinWallet; base: number }) {
  const da = Number(a.equity ?? base) - base;
  const db = Number(b.equity ?? base) - base;
  const closed = a.closed_positions + b.closed_positions;
  return (
    <Panel density="compact">
      <Label>THE GAP</Label>
      <p className="mt-2 text-xs text-ink-3">
        {closed === 0
          ? "Neither arm has closed a trade yet. Until both have, any difference between them is noise about which tokens happened to be open, not a result."
          : `${a.hold_minutes} min is ${signed(da)} and ${b.hold_minutes} min is ${signed(db)}, a gap of $${Math.abs(da - db).toFixed(2)} across ${closed} closed trades. Both arms bought the same tokens, so the gap is the horizon — but it is not a finding until the sample can survive its own outliers.`}
      </p>
    </Panel>
  );
}

export default function FiveMinLabPage() {
  const { data, isLoading, isError } = useFiveMinBoard();
  const base = Number(data?.starting_equity ?? 100);
  const wallets = data?.wallets ?? [];
  const [first, second] = [wallets[0], wallets[1]];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Toolbar
        eyebrow="Graduation Hold Lab"
        title="Buy the graduation. Sell at five minutes, or at fifteen."
        description="Two $100 wallets, ten trades of $10 each, buying pump.fun graduations two minutes after they complete. Both take the same coin at the same instant, so the only thing that separates their records is the clock. The $100k liquidity floor is execution fidelity, not a signal. Nothing here is real money."
      />

      {/* Deliberately above the numbers, and deliberately not collapsible. */}
      <Panel density="compact">
        <Label>WHY TO DISTRUST THIS</Label>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">
          {data?.disclosure ??
            "Run as refutation, not expectation. The fifteen-minute hold has already measured about -8.5% net per trade on 1,348 real positions."}
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
          <div className="grid gap-4 lg:grid-cols-2">
            {wallets.map((w) => (
              <ArmCard key={w.strategy_id} w={w} base={base} />
            ))}
          </div>

          {/* The comparison is the experiment, so it is stated rather than left
              for the reader to do in their head from two cards. */}
          {first && second ? <GapPanel a={first} b={second} base={base} /> : null}

          {/* Every trade, open and closed, each with its own P&L. */}
          <FiveMinTradesPanel />
        </>
      )}
    </div>
  );
}
