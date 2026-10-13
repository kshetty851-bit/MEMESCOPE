"use client";
import { useEffect, useState } from "react";
type Analysis = {
  id: number;
  at: string;
  mint: string;
  action: string;
  reason: string;
  score: {
    score: number;
    decision: string;
    feature_completeness: number;
    reasons: string[];
  };
};
type Position = {
  mint: string;
  symbol: string | null;
  closed_at: string | null;
  entry_cost: number;
  proceeds: number;
};
type Status = {
  running: boolean;
  cash_usd: number;
  booked_usd: number;
  realised_usd: number;
  analysis_count: number;
  heartbeat: { at: string; error: string | null; candidates: number } | null;
  positions: Position[];
  analyses: Analysis[];
  trades: {
    id: number;
    at: string;
    mint: string;
    side: string;
    amount: number;
    cost: number;
    analysis_id: number;
  }[];
  cost_assumptions: string;
  limitation: string;
};
const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const when = (s: string) => new Date(s).toLocaleString();
export function LivePaperLab() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const response = await fetch("/api/v1/labs/pretrade-ai/status", {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            response.status === 401
              ? "Sign in to view the paper lab."
              : "Paper service unavailable. Trading status cannot be verified.",
          );
        const data: Status = await response.json();
        if (!controller.signal.aborted) {
          setStatus(data);
          setError("");
        }
      } catch (err) {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : "Could not refresh the lab.");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 15000);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  return (
    <section
      className="space-y-5 rounded-xl border border-line p-5"
      aria-label="Automatic paper trading"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">
            Automatic discovery & paper trading
          </h2>
          <p className="mt-1 text-sm text-ink-dim">
            $100 starting balance · $10 per buy · $20 maximum per order · Two open positions
            at most
          </p>
        </div>
        <span className="rounded-full border border-amber-500/30 px-3 py-1 text-xs text-amber-300">
          {error
            ? "Connection interrupted"
            : !status
              ? "Connecting…"
              : status.running
                ? "Scanner running"
                : "Scanner unavailable"}
        </span>
      </div>
      <p className="text-sm text-ink-dim">
        Discovers newly graduated coins, applies the supplied scoring rules and records an
        assessment before every simulated buy or sell. Accepted candidates exit after five
        minutes using fresh quotes; larger sales are split to respect the $20 limit.
      </p>
      {error && (
        <p role="alert" className="text-sm text-rose-300">
          {error}
          {status ? " Values below are from the last successful refresh." : ""}
        </p>
      )}
      {status && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              ["Available paper cash", money(status.cash_usd)],
              ["Realised net P&L", money(status.realised_usd)],
              ["Profits booked", money(status.booked_usd)],
              ["Retained assessments", String(status.analysis_count)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line p-3">
                <p className="text-xs text-ink-dim">{label}</p>
                <p className="mt-1 text-xl font-semibold text-ink">{value}</p>
              </div>
            ))}
          </div>
          <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-sm leading-6 text-amber-200">
            <strong>Rules-based assessment · Trained AI model pending.</strong>
            <p>{status.limitation}</p>
            <p>
              No profit target is guaranteed. Paper results include estimated costs and are
              not executable quotes.
            </p>
          </div>
          <p className="text-xs text-ink-dim">
            {status.heartbeat
              ? `Last scan: ${when(status.heartbeat.at)} · ${status.heartbeat.candidates} candidates · ${status.heartbeat.error || "Feed connected"}`
              : "Waiting for the first scan."}
          </p>
          <div>
            <h3 className="font-medium text-ink">Positions</h3>
            {status.positions.length === 0 ? (
              <p className="mt-2 text-sm text-ink-dim">
                No entries yet. A coin must pass every required gate before the lab spends
                paper cash.
              </p>
            ) : (
              status.positions.map((p) => (
                <p key={p.mint} className="mt-2 break-all text-sm text-ink-dim">
                  {p.symbol || p.mint} · entry {money(p.entry_cost)} ·{" "}
                  {p.closed_at
                    ? `Closed · P&L ${money(p.proceeds - p.entry_cost)}`
                    : "Open / exit pending — profit unresolved"}
                </p>
              ))
            )}
          </div>
          <div>
            <h3 className="font-medium text-ink">Buy & sell history</h3>
            {status.trades.length === 0 ? (
              <p className="mt-2 text-sm text-ink-dim">No simulated transactions.</p>
            ) : (
              status.trades.map((t) => (
                <p key={t.id} className="mt-2 text-sm text-ink-dim">
                  {when(t.at)} · {t.side} {t.mint.slice(0, 12)} · {money(t.amount)} · costs{" "}
                  {money(t.cost)} · assessment #{t.analysis_id}
                </p>
              ))
            )}
          </div>
          <div>
            <h3 className="font-medium text-ink">Latest coin assessments</h3>
            <p className="mt-1 text-xs text-ink-dim">
              Latest 100 shown. Expand an assessment to inspect the decision.
            </p>
            <div className="mt-3 max-h-96 space-y-2 overflow-y-auto">
              {status.analyses.length === 0 ? (
                <p className="text-sm text-ink-dim">Waiting for newly graduated coins.</p>
              ) : (
                status.analyses.map((a) => (
                  <details key={a.id} className="rounded-lg border border-line p-3 text-sm">
                    <summary className="cursor-pointer text-ink">
                      #{a.id} · {a.action} · {a.mint.slice(0, 12)} ·{" "}
                      {a.score.decision.replaceAll("_", " ")} · {when(a.at)}
                    </summary>
                    <div className="mt-2 space-y-2 break-words text-ink-dim">
                      <p>{a.mint}</p>
                      <p>{a.reason}</p>
                      <p>
                        Score {a.score.score.toFixed(1)}/100 · evidence{" "}
                        {(a.score.feature_completeness * 100).toFixed(0)}%
                      </p>
                      {a.score.reasons.map((reason, i) => (
                        <p key={i}>{reason}</p>
                      ))}
                    </div>
                  </details>
                ))
              )}
            </div>
          </div>
          <p className="text-xs leading-5 text-ink-dim">
            {status.cost_assumptions} Monthly profit above $100 is booked when all positions
            are closed. Losses carry forward; no replacement cash is created.
          </p>
        </>
      )}
    </section>
  );
}
