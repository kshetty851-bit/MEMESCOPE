"use client";

/**
 * Long-watch Lab (Karthik, 2026-10-22: "build all"). Reads every graduation for
 * 48 hours and runs two paper books on what happens after the first hour:
 * Runner (still climbing at 60 minutes) and Second Wind (crashed, then back).
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Pos {
  mint: string; symbol: string | null; status: "open" | "closed"; opened_at: string; closed_at: string | null;
  reason: string | null; x: number; peak_x: number; pnl_usd: number; trigger: Record<string, number> | null;
}
interface Book {
  book: "runner" | "secondwind"; started_at: string | null; cash_usd: number; open_value_usd: number;
  equity_usd: number; pnl_usd: number; closed: number; closed_pnl_usd: number; wins: number;
  open: number; max_open: number; trade_usd: number; positions: Pos[];
}
export interface LongwatchBoard {
  note: string;
  collector: { coins_now: number; readings_24h: number; last_at: string | null };
  books: Book[];
}

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const usd = (v: number, signed = false) =>
  `${v < 0 ? "−" : signed ? "+" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const at = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI }) : "—";
const xs = (x: number) => (x >= 10 ? `${x.toFixed(1)}x` : `${x.toFixed(2)}x`);
const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim");

const RULES: Record<Book["book"], { title: string; kicker: string; buys: string; sells: string }> = {
  runner: {
    title: "Runner", kicker: "Switched off 22 Oct · its backtest lost $745 on 181 trades",
    buys: "About an hour after graduating, a coin at 3x+ its first price, its pool 2x+ its first size, and more buyers than sellers in the last hour.",
    sells: "When it falls 40% from its highest reading, or after 6 hours.",
  },
  secondwind: {
    title: "Second Wind", kicker: "Crashed, then came back",
    buys: "A coin 2–48 hours old that fell 80%+ from its first-hour high, has since tripled off its low, traded $50k+ in the last hour with more buyers than sellers.",
    sells: "When it falls 40% from its highest reading, or after 24 hours.",
  },
};

function BookPanel({ b }: { b: Book }) {
  const r = RULES[b.book];
  const winRate = b.closed ? Math.round((100 * b.wins) / b.closed) : null;
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">{r.kicker}</div>
      <h2 className="mt-1 font-brand text-2xl font-semibold text-ink">{r.title} book</h2>
      <dl className="mt-3 grid gap-2 text-sm text-ink-dim sm:grid-cols-2">
        <div><dt className="text-[11px] uppercase tracking-wider text-ink-faint">Buys</dt><dd className="mt-0.5">{r.buys}</dd></div>
        <div><dt className="text-[11px] uppercase tracking-wider text-ink-faint">Sells</dt><dd className="mt-0.5">{r.sells}</dd></div>
      </dl>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Fig label="Balance" value={usd(b.equity_usd)} sub={`started ${at(b.started_at)}`} />
        <Fig label="Profit / loss" value={usd(b.pnl_usd, true)} cls={tone(b.pnl_usd)} sub={`on $500 · $${b.trade_usd} a trade`} />
        <Fig label="Closed trades" value={String(b.closed)} sub={winRate === null ? "none yet" : `${winRate}% won`} />
        <Fig label="Open" value={`${b.open} / ${b.max_open}`} sub={usd(b.open_value_usd) + " held"} />
      </div>
      <div className="mt-4 overflow-x-auto">
        {b.positions.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-sm text-ink-dim">
            No trades yet. It needs a coin to meet every condition; quiet days can pass with none.
          </p>
        ) : (
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
                <th className="py-1.5 pr-3 text-left font-normal">Bought</th>
                <th className="py-1.5 pr-3 text-right font-normal">Now / sold</th>
                <th className="py-1.5 pr-3 text-right font-normal">Best</th>
                <th className="py-1.5 pr-3 text-right font-normal">P/L</th>
                <th className="py-1.5 text-left font-normal">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-subtle">
              {b.positions.map((p) => (
                <tr key={p.mint}>
                  <td className="py-2 pr-3">
                    <a href={`https://dexscreener.com/solana/${p.mint}`} target="_blank" rel="noreferrer"
                       className="font-medium text-ink hover:text-accent">{cleanName(p.symbol) ?? `${p.mint.slice(0, 4)}…`}</a>
                  </td>
                  <td className="py-2 pr-3 text-ink-dim">{at(p.opened_at)}</td>
                  <td className={`py-2 pr-3 text-right font-mono tabular-nums ${tone(p.x - 1)}`}>{xs(p.x)}</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{xs(p.peak_x)}</td>
                  <td className={`py-2 pr-3 text-right font-mono tabular-nums ${tone(p.pnl_usd)}`}>{usd(p.pnl_usd, true)}</td>
                  <td className="py-2 text-[12px] text-ink-dim">
                    {p.status === "open" ? <span className="text-accent">holding</span> : `${(p.reason ?? "").replace("_", " ")} · ${at(p.closed_at)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function Fig({ label, value, sub, cls = "text-ink" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className={`mt-1 font-brand text-xl font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}

export function LongwatchLabPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["longwatch-lab"],
    queryFn: () => api.get<LongwatchBoard>("/labs/longwatch/board"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <p className="p-6 text-sm text-ink-dim">Loading…</p>;
  if (error || !data) return <p className="p-6 text-sm text-down">The Long-watch Lab could not be read.</p>;
  const c = data.collector;
  return (
    <div className="space-y-5 pb-12">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 sm:p-6">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">Paper only · two books</div>
          <h1 className="mt-1 font-brand text-3xl font-bold text-ink sm:text-4xl">Long-watch Lab</h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-dim">
            We used to stop pricing a coin about two hours after it graduated, so we never saw what the big winners did
            next. This lab reads every graduation every 10 minutes for 48 hours, and tests two ideas on what happens after
            the first hour. {data.note}
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-line bg-sunken px-3 py-1 text-ink"><b className="font-mono">{c.coins_now.toLocaleString()}</b> coins being watched</span>
            <span className="rounded-full border border-line bg-sunken px-3 py-1 text-ink"><b className="font-mono">{c.readings_24h.toLocaleString()}</b> readings in 24 h</span>
            <span className="rounded-full border border-line bg-sunken px-3 py-1 text-ink-dim">last read {at(c.last_at)}</span>
          </div>
        </div>
      </header>
      {data.books.map((b) => <BookPanel key={b.book} b={b} />)}
      <p className="text-xs text-ink-faint">A simulation on DexScreener readings with each trade&apos;s price impact and pool fees. No real wallet follows it. Not financial advice.</p>
    </div>
  );
}
