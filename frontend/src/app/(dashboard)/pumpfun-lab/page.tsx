"use client";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { usePumpfunBoard } from "@/hooks/use-lab";

import { SellButton } from "../strategy-lab/sell-button";
import { toneOf } from "../strategy-lab/tone";

/**
 * PUMPFUN LAB — mirror one on-chain wallet, forward only.
 *
 * The number this page exists to show is NOT the P&L. It is COVERAGE: how many
 * of the leader's trades we were actually able to copy, and how far behind him
 * we were when we did. A copy lab that reported only its own fills would look
 * like a strategy; what decides whether copying works is the gap between what
 * he did and what we could do.
 *
 * Research simulation. No real order was ever placed.
 */

function money(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "—" : `$${v.toFixed(d)}`;
}
function secs(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v < 90 ? `${v.toFixed(0)}s` : `${(v / 60).toFixed(1)}m`;
}

/**
 * The source mark.
 *
 * Drawn here rather than hotlinked: the page's CSP blocks external images, and
 * copying someone's asset onto our own dashboard to identify their platform is
 * worse than naming it plainly. It says where the signal comes from — it does
 * not claim to be them.
 */
function PumpMark() {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-up/40 bg-up/10 px-2 py-0.5"
      title="Signals sourced from a pump.fun trader's on-chain activity"
    >
      <svg viewBox="0 0 16 16" aria-hidden className="h-3 w-3">
        <path
          d="M4 11.5 9.5 6a2.8 2.8 0 1 1 4 4L8 15.5a2.8 2.8 0 0 1-4-4Z"
          fill="none"
          stroke="var(--color-up)"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <path d="M6.2 9.3 10.7 4.8" stroke="var(--color-up)" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="font-mono text-[10px] tracking-wide text-up">pump.fun</span>
    </span>
  );
}

export default function PumpfunLabPage() {
  const { data, isLoading, error } = usePumpfunBoard();

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !data) return <ErrorState body="PumpFun Lab unavailable." />;

  const cov = data.coverage ?? {};
  const open = data.positions.filter((p) => p.status === "open");

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Label>PUMPFUN LAB</Label>
              <PumpMark />
            </div>
            <h1 className="mt-1 text-lg font-medium text-ink">
              COPYING @{data.leader_label} · {money(data.starting_equity, 0)} ·{" "}
              {data.rules ? `${money(Number(data.rules.size_usd), 0)} × ${data.rules.max_concurrent}` : ""}
            </h1>
            <p className="mt-1 font-mono text-[10px] text-muted">
              {data.leader_address}
            </p>
            <p className="mt-1 text-xs font-medium tracking-wide text-warn">
              PAPER / RESEARCH ONLY — REAL MONEY OFF
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs sm:grid-cols-4">
            <div>
              <dt className="text-muted">Equity</dt>
              <dd className={`font-mono ${toneOf((data.equity ?? 0) - data.starting_equity)}`}>
                {money(data.equity)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Cash</dt>
              <dd className="font-mono text-ink">{money(data.cash)}</dd>
            </div>
            <div>
              <dt className="text-muted">Open</dt>
              <dd className="font-mono text-ink">{open.length}</dd>
            </div>
            <div>
              <dt className="text-muted">Watching since</dt>
              <dd className="font-mono text-ink">
                {data.watching_from
                  ? data.watching_from.slice(5, 16).replace("T", " ")
                  : "not started"}
              </dd>
            </div>
          </dl>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-muted">{data.disclosure}</p>
      </Panel>

      {/* Coverage before P&L, deliberately: it is the number that decides
          whether copying is even possible, and it is the one a reader would
          otherwise never think to ask for. */}
      <Panel density="compact">
        <Label>CAN WE ACTUALLY COPY HIM?</Label>
        <div className="mt-2 grid gap-4 sm:grid-cols-4">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">Copied</p>
            <p className="font-mono text-lg text-ink">
              {cov.copied ?? 0}
              <span className="text-muted"> / {cov.actionable ?? 0}</span>
            </p>
            <p className="text-[10px] text-muted">
              {cov.copied_pct === null || cov.copied_pct === undefined
                ? "no actionable signals yet"
                : `${cov.copied_pct}% of what he did after we started`}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">Mean lag</p>
            <p className="font-mono text-lg text-ink">{secs(cov.mean_lag_seconds)}</p>
            <p className="text-[10px] text-muted">his median hold is 8.5 min</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">Signals seen</p>
            <p className="font-mono text-lg text-ink">{cov.signals_seen ?? 0}</p>
            <p className="text-[10px] text-muted">including his pre-start history</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">Why we missed</p>
            <ul className="mt-0.5 space-y-0.5 font-mono text-[10px] text-muted">
              {Object.entries(cov.by_outcome ?? {})
                .filter(([k]) => k !== "opened" && k !== "closed")
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(([k, n]) => (
                  <li key={k}>
                    {n} {k.replace(/_/g, " ")}
                  </li>
                ))}
              {Object.keys(cov.by_outcome ?? {}).length === 0 ? <li>—</li> : null}
            </ul>
          </div>
        </div>
      </Panel>

      <Panel density="compact">
        <Label>OPEN POSITIONS ({open.length})</Label>
        {open.length === 0 ? (
          <p className="mt-2 text-xs text-muted">Nothing open right now.</p>
        ) : (
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-left font-mono text-[11px]">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-normal">sell</th>
                  <th className="py-1 pr-3 font-normal">mint</th>
                  <th className="py-1 pr-3 text-right font-normal">size</th>
                  <th className="py-1 pr-3 text-right font-normal">value</th>
                  <th className="py-1 pr-3 text-right font-normal">exec ×</th>
                  <th className="py-1 font-normal">opened</th>
                </tr>
              </thead>
              <tbody className="text-ink">
                {open.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-1 pr-3">
                      <SellButton id={p.id} />
                    </td>
                    <td className="py-1 pr-3">{p.mint.slice(0, 8)}…</td>
                    <td className="py-1 pr-3 text-right">{money(p.size_usd)}</td>
                    <td className="py-1 pr-3 text-right">{money(p.open_value)}</td>
                    <td className="py-1 pr-3 text-right">
                      {p.exec_multiple === null ? "—" : `${p.exec_multiple.toFixed(3)}×`}
                    </td>
                    <td className="py-1">{p.opened_at.slice(5, 16).replace("T", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel density="compact">
        <Label>HIS TRADES, AND WHAT WE DID ({data.signals.length})</Label>
        <p className="mt-1 text-[10px] text-muted">
          Every trade of his we saw, acted on or not. The refusals are the
          evidence — a record of only our own fills could not say how much of
          him we were able to follow.
        </p>
        <div className="mt-2 max-h-96 overflow-auto">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">his trade</th>
                <th className="py-1 pr-3 font-normal">side</th>
                <th className="py-1 pr-3 font-normal">mint</th>
                <th className="py-1 pr-3 text-right font-normal">his SOL</th>
                <th className="py-1 pr-3 text-right font-normal">our lag</th>
                <th className="py-1 font-normal">we</th>
              </tr>
            </thead>
            <tbody className="text-ink">
              {data.signals.map((s) => (
                <tr key={s.signature} className="border-t border-line">
                  <td className="py-1 pr-3">{s.leader_at.slice(5, 16).replace("T", " ")}</td>
                  <td className={`py-1 pr-3 ${s.side === "buy" ? "text-up" : "text-down"}`}>
                    {s.side}
                  </td>
                  <td className="py-1 pr-3">{s.mint.slice(0, 8)}…</td>
                  <td className="py-1 pr-3 text-right">
                    {s.leader_sol === null ? "—" : s.leader_sol.toFixed(2)}
                  </td>
                  <td className="py-1 pr-3 text-right">{s.acted ? secs(s.lag_seconds) : "—"}</td>
                  <td className={`py-1 ${s.acted ? "text-ink" : "text-muted"}`}>
                    {s.outcome.replace(/_/g, " ")}
                  </td>
                </tr>
              ))}
              {data.signals.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-2 text-muted">
                    Nothing seen yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
