"use client";

import { useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Toolbar } from "@/components/ui/toolbar";
import { useArenaBoard, useArenaDecisions } from "@/hooks/use-arena";
import type { ArenaCandidate } from "@/types/arena";

/**
 * V5 FORWARD STRATEGY ARENA
 *
 * Five virtual $1,000 portfolios scoring frozen entry hypotheses against a
 * cash control. **This is not the Paper Wallet.** Arena equity and Paper
 * Wallet equity are different numbers about different things, and the page
 * says so above the fold rather than in a footnote — a reader who confuses
 * them would draw a conclusion about money that does not exist.
 *
 * Every figure is served already computed. Nothing here recomputes a rate, a
 * profit factor or an interval: a second implementation would be a second
 * answer, and the first time either changed they would disagree.
 */

function money(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : "—";
}

function pct(value: string | null, digits = 1): string {
  if (value === null) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
}

function signed(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

/** Sample-size honesty, in the words the protocol uses. */
function confidenceLabel(trades: number): string {
  if (trades === 0) return "NO CLOSED TRADES";
  if (trades < 25) return "EXTREMELY LOW CONFIDENCE";
  if (trades < 50) return "EARLY — EXTREMELY LOW CONFIDENCE";
  if (trades < 100) return "EARLY";
  if (trades < 200) return "PRELIMINARY";
  if (trades < 500) return "INTERMEDIATE";
  return "SUBSTANTIAL FORWARD SAMPLE";
}

function CandidateCard({ c, cash }: { c: ArenaCandidate; cash: number }) {
  const equity = Number(c.equity);
  const vsCash = equity - cash;
  const isCash = c.code === "A";
  const failed = c.status === "failed";

  return (
    <Panel
      density="compact"
      className={failed ? "border-danger/30 bg-danger/[0.03]" : undefined}
    >
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <Label>{c.code}</Label>
          <h3 className="mt-1 text-sm font-medium text-ink">{c.name}</h3>
        </div>
        <div className="text-right">
          <p data-numeric className="text-lg font-semibold text-ink">
            {money(c.equity)}
          </p>
          {!isCash ? (
            <p
              data-numeric
              className={`text-xs ${vsCash >= 0 ? "text-good" : "text-danger"}`}
            >
              {vsCash >= 0 ? "+" : "−"}${Math.abs(vsCash).toFixed(2)} vs cash
            </p>
          ) : (
            <p className="text-xs text-ink-3">baseline</p>
          )}
        </div>
      </div>

      {failed ? (
        <p className="mt-2 text-xs font-medium text-danger">
          ARENA CANDIDATE FAILED — {c.failed_reason}
        </p>
      ) : null}

      {isCash ? (
        <p className="mt-3 text-xs leading-relaxed text-ink-3">
          Never trades. The number every other candidate has to beat.
        </p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <div className="flex justify-between">
              <dt className="text-ink-3">Trades</dt>
              <dd data-numeric className="text-ink-2">{c.trades}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Win rate</dt>
              <dd data-numeric className="text-ink-2">{pct(c.win_rate)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Expectancy</dt>
              <dd data-numeric className="text-ink-2">{signed(c.expectancy)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Profit factor</dt>
              <dd data-numeric className="text-ink-2">
                {c.profit_factor === null ? "—" : Number(c.profit_factor).toFixed(2)}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Max DD</dt>
              <dd data-numeric className="text-ink-2">{pct(c.max_drawdown)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Open</dt>
              <dd data-numeric className="text-ink-2">
                {c.open_positions} ({money(c.deployed)})
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Skipped</dt>
              <dd data-numeric className="text-ink-2">{c.skipped}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-3">Sell failures</dt>
              <dd data-numeric className="text-ink-2">{c.sell_failures}</dd>
            </div>
          </dl>
          {c.win_rate_ci_low !== null ? (
            <p className="mt-2 text-[11px] text-ink-3">
              95% interval on win rate {pct(c.win_rate_ci_low)} – {pct(c.win_rate_ci_high)}
            </p>
          ) : null}
          <p className="mt-1 text-[11px] font-medium tracking-wide text-warn">
            {confidenceLabel(c.trades)}
          </p>
        </>
      )}
    </Panel>
  );
}

export default function ForwardArenaPage() {
  const board = useArenaBoard();
  const [focus, setFocus] = useState<string | undefined>(undefined);
  const decisions = useArenaDecisions(focus);

  if (board.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 rounded-md" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-56 rounded-md" />
          ))}
        </div>
      </div>
    );
  }
  if (board.isError || !board.data) {
    return (
      <ErrorState
        title="The Arena could not be read"
        body="The research simulation is unavailable right now. Production wallets are unaffected — the Arena is isolated from them by design."
      />
    );
  }

  const data = board.data;
  const cash = Number(data.candidates.find((c) => c.code === "A")?.equity ?? 1000);

  return (
    <div className="flex flex-col gap-5 pb-8">
      <Toolbar
        eyebrow="Strategy lab"
        title="Forward Strategy Arena"
        description="Five virtual $1,000 portfolios scoring frozen entry hypotheses against a cash control, on tokens that arrived after the rules were sealed."
      />

      <Panel density="compact" className="border-warn/30 bg-warn/[0.05]">
        <p className="text-sm font-medium text-ink">RESEARCH SIMULATION — NOT THE OFFICIAL PAPER WALLET</p>
        <p className="mt-1 text-xs leading-relaxed text-ink-3">
          {data.disclosure} Rules v{data.rules_version}, decided at the{" "}
          {data.checkpoint_minutes}-minute checkpoint
          {data.valid_from
            ? `, scoring only tokens whose checkpoint fell after ${new Date(data.valid_from).toLocaleString()}`
            : ""}
          . Observed profit is not evidence of edge.
        </p>
      </Panel>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.candidates.map((c) => (
          <CandidateCard key={c.code} c={c} cash={cash} />
        ))}
      </div>

      <section className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-medium text-ink">Decision ledger</h2>
          <span className="text-xs text-ink-3">
            what each candidate bought — and what it refused, with the reason
          </span>
          <div className="ml-auto flex gap-1">
            {[undefined, "B", "C", "D", "E"].map((code) => (
              <button
                key={code ?? "all"}
                type="button"
                onClick={() => setFocus(code)}
                className={`rounded px-2 py-0.5 text-xs ${
                  focus === code
                    ? "bg-raised text-ink"
                    : "text-ink-3 hover:text-ink-2"
                }`}
              >
                {code ?? "All"}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-numeric>
            <thead>
              <tr className="text-left text-ink-3">
                <th className="py-1.5 pr-3 font-medium">Candidate</th>
                <th className="py-1.5 pr-3 font-medium">Token</th>
                <th className="py-1.5 pr-3 font-medium">Checkpoint</th>
                <th className="py-1.5 pr-3 font-medium">Verdict</th>
                <th className="py-1.5 pr-3 font-medium">Reason</th>
                <th className="py-1.5 font-medium">Route</th>
              </tr>
            </thead>
            <tbody>
              {(decisions.data ?? []).map((d, i) => (
                <tr key={`${d.code}-${d.mint_address}-${i}`} className="border-t border-line">
                  <td className="py-1.5 pr-3 text-ink-2">{d.code}</td>
                  <td className="py-1.5 pr-3 font-mono text-ink-3">
                    {d.mint_address.slice(0, 6)}…{d.mint_address.slice(-4)}
                  </td>
                  <td className="py-1.5 pr-3 text-ink-3">
                    {new Date(d.checkpoint_at).toLocaleTimeString()}
                  </td>
                  <td className={`py-1.5 pr-3 ${d.eligible ? "text-good" : "text-ink-3"}`}>
                    {d.eligible ? "ENTERED" : "SKIPPED"}
                  </td>
                  <td className="py-1.5 pr-3 text-ink-3">{d.skip_reason ?? "—"}</td>
                  <td className="py-1.5 text-ink-3">{d.route_state ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(decisions.data ?? []).length === 0 ? (
            <p className="py-3 text-xs text-ink-3">
              No decisions recorded yet. The Arena judges a token thirty minutes after it
              enters the nursery.
            </p>
          ) : null}
        </div>
      </section>
    </div>
  );
}
