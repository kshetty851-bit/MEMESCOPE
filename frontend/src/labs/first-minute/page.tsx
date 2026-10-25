"use client";

/**
 * First-minute recorder (Karthik, 2026-10-25: "option 1 with own page"). Shows
 * that the recorder is working: every new pumpswap pool priced from its own
 * vaults from graduation on, how soon the first real price lands, and the room
 * it takes. Research only; the results page comes after about 10 days of data.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Day { day: string; pools: number; graduations: number; median_s: number | null; p10_s: number | null; p90_s: number | null; rows: number }
interface Recent { mint: string; symbol: string | null; graduated_at: string; first_after_s: number; readings: number; pool_sol: number | null; move: number | null }
export interface FirstMinuteStatus { enabled: boolean; window_s: number; size_mb: number; last_at: string | null; days: Day[]; recent: Recent[] }

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const at = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI }) : "—";
const secs = (s: number | null) => (s === null ? "—" : `${s.toFixed(1)} s`);
const dayLabel = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

function Fig({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className="mt-1 font-brand text-xl font-semibold tabular-nums text-ink">{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}

export function FirstMinuteLabPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["first-minute-lab"],
    queryFn: () => api.get<FirstMinuteStatus>("/labs/graduation/first-minute"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <p className="p-6 text-sm text-ink-dim">Loading…</p>;
  if (error || !data) return <p className="p-6 text-sm text-down">The First-minute recorder could not be read.</p>;
  const today = data.days[0];
  const total = data.days.reduce((n, d) => n + d.pools, 0);
  const live = data.enabled && data.last_at !== null && Date.now() - new Date(data.last_at).getTime() < 15 * 60_000;
  return (
    <div className="space-y-5 pb-12">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 sm:p-6">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">Research only · never trades</div>
          <h1 className="mt-1 font-brand text-3xl font-bold text-ink sm:text-4xl">First-minute recorder</h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-dim">
            DexScreener shows a new coin&apos;s price 35–50 seconds after it graduates, and often an old copy of it. This
            reads every new pool&apos;s price straight from the blockchain from the moment it graduates, and keeps every
            change for the first {Math.round(data.window_s / 60)} minutes. After about 10 days we test buying 1, 3, 5 and
            10 seconds after graduation, on real prices.
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <span className={`rounded-full border px-3 py-1 ${live ? "border-up/40 text-up" : "border-down/40 text-down"}`}>
              {live ? "● recording" : data.enabled ? "● no new readings for 15 min" : "● switched off"}
            </span>
            <span className="rounded-full border border-line bg-sunken px-3 py-1 text-ink-dim">last reading {at(data.last_at)}</span>
          </div>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Fig label="Pools today" value={today ? today.pools.toLocaleString() : "0"}
             sub={today ? `of ${today.graduations.toLocaleString()} graduations` : "none yet"} />
        <Fig label="First real price" value={secs(today?.median_s ?? null)} sub="after graduation, median today" />
        <Fig label="Pools so far" value={total.toLocaleString()} sub={`${data.days.filter((d) => d.pools > 0).length} days recorded · goal ~10`} />
        <Fig label="Space used" value={`${data.size_mb.toLocaleString()} MB`} sub="deleted after the test" />
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Day by day</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="py-1.5 pr-3 text-left font-normal">Dubai day</th>
                <th className="py-1.5 pr-3 text-right font-normal">Pools recorded</th>
                <th className="py-1.5 pr-3 text-right font-normal">Graduations</th>
                <th className="py-1.5 pr-3 text-right font-normal">First price (fastest 10% · median · slowest 10%)</th>
                <th className="py-1.5 text-right font-normal">Readings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-subtle">
              {data.days.map((d) => (
                <tr key={d.day}>
                  <td className="py-2 pr-3 text-ink">{dayLabel(d.day)}</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink">{d.pools.toLocaleString()}</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{d.graduations.toLocaleString()}</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{secs(d.p10_s)} · {secs(d.median_s)} · {secs(d.p90_s)}</td>
                  <td className="py-2 text-right font-mono tabular-nums text-ink-dim">{d.rows.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Latest pools</h2>
        {data.recent.length === 0 ? (
          <p className="mt-3 rounded-lg border border-dashed border-line px-3 py-6 text-center text-sm text-ink-dim">No pools in the last 2 hours.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
                <tr>
                  <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
                  <th className="py-1.5 pr-3 text-left font-normal">Graduated</th>
                  <th className="py-1.5 pr-3 text-right font-normal">First price after</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Pool at first price</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Price changes</th>
                  <th className="py-1.5 text-right font-normal">First → latest</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-subtle">
                {data.recent.map((r) => (
                  <tr key={r.mint}>
                    <td className="py-2 pr-3">
                      <a href={`https://dexscreener.com/solana/${r.mint}`} target="_blank" rel="noreferrer"
                         className="font-medium text-ink hover:text-accent">{cleanName(r.symbol) ?? `${r.mint.slice(0, 4)}…`}</a>
                    </td>
                    <td className="py-2 pr-3 text-ink-dim">{at(r.graduated_at)}</td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink">{secs(r.first_after_s)}</td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{r.pool_sol === null ? "—" : `${r.pool_sol.toFixed(0)} SOL`}</td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{r.readings.toLocaleString()}</td>
                    <td className={`py-2 text-right font-mono tabular-nums ${r.move === null ? "text-ink-dim" : r.move >= 1 ? "text-up" : "text-down"}`}>
                      {r.move === null ? "—" : `${r.move.toFixed(2)}x`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="text-xs text-ink-faint">Prices read from each pool&apos;s own reserves on the Solana blockchain. Nothing here buys or sells. Not financial advice.</p>
    </div>
  );
}
