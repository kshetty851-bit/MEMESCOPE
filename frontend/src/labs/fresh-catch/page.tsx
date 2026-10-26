"use client";

/**
 * Fresh Catch Lab (Karthik, 2026-10-26): $10k-$30k pools seen within 30 s of
 * graduating with 65%+ buys, bought at the next reading, sold at 4 minutes,
 * $1,000 at $50 a trade from 1 Oct. Paper only. Every figure is the API's.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Trade { mint: string; symbol: string | null; pool: number; seen_s: number; buys: number; sells: number;
  entry_at: string; exit_at: string; net: number; how: string; pnl_usd: number }
interface Day { day: string; trades: number; pnl_usd: number; rugs: number }
export interface FreshCatch {
  started_at: string; as_of: string; capital_usd: number; ticket_usd: number; balance_usd: number; pnl_usd: number;
  lowest_usd: number; worst_drop_usd: number; trades: number; skipped_cash: number; wins: number; rugs: number;
  unpriced: number; without_best_usd: number; without_best5_usd: number; best: { symbol: string | null; pnl_usd: number }[];
  graduations_checked: number; refused: Record<string, number>; days: Day[]; trades_list: Trade[];
}

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const usd = (v: number, signed = false) =>
  `${v < 0 ? "−" : signed ? "+" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const at = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI });
const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim");
const WHY: Record<string, string> = {
  pool: "pool not $10k-$30k", not_fresh: "seen after 30 s", buys_under_65: "under 65% buys",
  not_sol_pool: "not a token/SOL pool", no_reading: "no price reading", no_next_reading: "no second reading", morning: "08:00-12:00 Dubai",
};

function Fig({ label, value, sub, cls = "text-ink" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className={`mt-1 font-brand text-xl font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}

export function FreshCatchLabPage() {
  const { data: d, isLoading, error } = useQuery({
    queryKey: ["fresh-catch-lab"],
    queryFn: () => api.get<FreshCatch>("/labs/graduation/fresh-catch"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <p className="p-6 text-sm text-ink-dim">Loading…</p>;
  if (error || !d) return <p className="p-6 text-sm text-down">The Fresh Catch Lab could not be read.</p>;
  const winRate = d.trades ? Math.round((100 * d.wins) / d.trades) : 0;
  return (
    <div className="space-y-5 pb-12">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 sm:p-6">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">Paper only · from 1 Oct · {usd(d.capital_usd)} at {usd(d.ticket_usd)} a trade</div>
          <h1 className="mt-1 font-brand text-3xl font-bold text-ink sm:text-4xl">Fresh Catch Lab</h1>
          <dl className="mt-3 grid max-w-3xl gap-2 text-sm text-ink-dim sm:grid-cols-2">
            <div><dt className="text-[11px] uppercase tracking-wider text-ink-faint">Buys</dt>
              <dd className="mt-0.5">A coin whose pool is $10k-$30k the first time DexScreener shows it, seen within 30 seconds of graduating, with at least 65% of its trades buys. Not between 08:00 and 12:00 Dubai. Bought at the next price reading.</dd></div>
            <div><dt className="text-[11px] uppercase tracking-wider text-ink-faint">Sells</dt>
              <dd className="mt-0.5">4 minutes after the buy. Fees and price impact are counted. A trade with no price to sell at is counted as a total loss.</dd></div>
          </dl>
          <p className="mt-3 max-w-3xl rounded-lg border border-down/30 bg-down/5 px-3 py-2 text-xs text-ink-dim">
            Warning: almost all of this profit is one coin. Without its best trade it made {usd(d.without_best_usd, true)}; without its best five, {usd(d.without_best5_usd, true)}. The rule was chosen after looking at October, so only trades from 26 Oct on are a fair test.
          </p>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Fig label="Balance" value={usd(d.balance_usd)} sub={`started ${usd(d.capital_usd)}`} />
        <Fig label="Profit / loss" value={usd(d.pnl_usd, true)} cls={tone(d.pnl_usd)} sub={`lowest ${usd(d.lowest_usd)} · worst drop ${usd(d.worst_drop_usd)}`} />
        <Fig label="Trades" value={d.trades.toLocaleString()} sub={`${winRate}% won${d.skipped_cash ? ` · ${d.skipped_cash} skipped, no cash` : ""}`} />
        <Fig label="Rugs (−50% or worse)" value={d.rugs.toLocaleString()} cls="text-down" sub={`${d.unpriced} with no price to sell at`} />
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Best trades</h2>
        <div className="mt-3 flex flex-wrap gap-2 text-sm">
          {d.best.map((b, i) => (
            <span key={i} className="rounded-full border border-line bg-sunken px-3 py-1"><b className="text-ink">{cleanName(b.symbol) ?? "no name"}</b> <span className="text-up">{usd(b.pnl_usd, true)}</span></span>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Day by day (Dubai)</h2>
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-7">
          {[...d.days].reverse().map((x) => (
            <div key={x.day} className="rounded-lg border border-line bg-sunken px-2.5 py-2">
              <div className="text-[11px] text-ink-faint">{new Date(`${x.day}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</div>
              <div className={`font-mono text-sm font-semibold tabular-nums ${tone(x.pnl_usd)}`}>{usd(x.pnl_usd, true)}</div>
              <div className="text-[10px] text-ink-faint">{x.trades} trades · {x.rugs} rugs</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Latest trades</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
                <th className="py-1.5 pr-3 text-left font-normal">Bought</th>
                <th className="py-1.5 pr-3 text-right font-normal">Pool</th>
                <th className="py-1.5 pr-3 text-right font-normal">Seen after</th>
                <th className="py-1.5 pr-3 text-right font-normal">Buys/sells</th>
                <th className="py-1.5 pr-3 text-right font-normal">Result</th>
                <th className="py-1.5 text-right font-normal">P/L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-subtle">
              {d.trades_list.map((t) => (
                <tr key={`${t.mint}${t.entry_at}`}>
                  <td className="py-2 pr-3">
                    <a href={`https://dexscreener.com/solana/${t.mint}`} target="_blank" rel="noreferrer" className="font-medium text-ink hover:text-accent">
                      {cleanName(t.symbol) ?? `${t.mint.slice(0, 4)}…`}</a>
                  </td>
                  <td className="py-2 pr-3 text-ink-dim">{at(t.entry_at)}</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">${(t.pool / 1000).toFixed(1)}k</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{t.seen_s.toFixed(0)}s</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{t.buys}/{t.sells}</td>
                  <td className={`py-2 pr-3 text-right font-mono tabular-nums ${tone(t.net)}`}>{t.how === "unpriced" ? "no price" : `${(100 * t.net).toFixed(1)}%`}</td>
                  <td className={`py-2 text-right font-mono tabular-nums ${tone(t.pnl_usd)}`}>{usd(t.pnl_usd, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5 text-sm text-ink-dim">
        <h2 className="font-brand text-lg font-semibold text-ink">Coins checked</h2>
        <p className="mt-1">{d.graduations_checked.toLocaleString()} graduations checked since 1 Oct. Not bought:</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          {Object.entries(d.refused).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
            <span key={k} className="rounded-full border border-line bg-sunken px-3 py-1">{WHY[k] ?? k}: <b className="font-mono text-ink">{n.toLocaleString()}</b></span>
          ))}
        </div>
      </section>
      <p className="text-xs text-ink-faint">A simulation on DexScreener readings with fees and price impact. No real wallet follows it. Not financial advice.</p>
    </div>
  );
}
