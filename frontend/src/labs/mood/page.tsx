"use client";

/**
 * Mood Lab (Karthik, 2026-11-12): the crowd's mood on 25 big meme-coin futures,
 * and two paper books that trade it, each beside Ref's random-entry control.
 * Paper only. Every figure is the API's (`/labs/mood`).
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

interface Book { trades: number; open: number; wins: number; pnl_usd: number; open_pnl_usd: number; balance_usd: number; skipped_cash: number }
interface Trade {
  book: string; sym: string; side: number; day: string; opened_at: string; due_at: string; closed_at: string | null;
  entry: number; exit: number | null; funding: number | null; ret: number | null; pnl_usd: number | null; now: number | null;
  top: number | null; retail: number | null;
}
interface Pulse { sym: string; day: string; mood: number | null; gap: number | null; shadow: number; contra: number; price: number | null;
  buzz?: { now: number | null; h24: number; d7: number } }
interface Trending { t: string; coins: { symbol: string; name: string; rank: number; mcap_rank: number | null }[] }
interface Backtest { name: string; hold: number; select: string; test: string; test_trades: number; test_usd: number; verdict: string }
export interface MoodLab {
  enabled: boolean; start_day: string; capital_usd: number; ticket_usd: number; holds: Record<string, number>;
  updated_at: string | null; books: Record<string, Book>; open: Trade[]; closed: Trade[]; pulse: Pulse[];
  fng: { d: string; v: number; label: string }[]; backtest: Backtest[];
  trending?: Trending | null; buzz_hours?: number;
}

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const usd = (v: number, signed = false) =>
  `${v < 0 ? "−" : signed && v > 0 ? "+" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const at = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...DUBAI });
const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim");
const coin = (s: string) => s.replace(/USDT$/, "").replace(/^1000+/, "");
const side = (s: number) => (s > 0 ? "Long" : "Short");

const TEAM = [
  ["Pulse", "Mood score for every coin, from funding and retail positioning"],
  ["Shadow", "Bets with top traders when they disagree with retail · 3 days"],
  ["Contra", "Bets against a crowd that is too greedy · 1 day (watch only)"],
  ["Ref", "Same trades on random coins, so luck has a number"],
  ["Orca", "Top traders vs retail (coming)"],
  ["Buzz", "Retail hype: CoinGecko trending, recording (Reddit coming)"],
  ["Herald", "Daily WhatsApp summary (coming)"],
] as const;

function Fig({ label, value, sub, cls = "text-ink" }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className={`mt-1 font-brand text-xl font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-ink-faint">{sub}</div> : null}
    </div>
  );
}

function BookCard({ name, b, ref_, hold }: { name: string; b: Book; ref_: Book; hold: number }) {
  const total = b.pnl_usd + b.open_pnl_usd;
  const refTotal = ref_.pnl_usd + ref_.open_pnl_usd;
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="font-brand text-lg font-semibold text-ink">{name}</h3>
        <span className="text-xs text-ink-faint">holds {hold} day{hold > 1 ? "s" : ""}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Fig label={name} value={usd(total, true)} cls={tone(total)} sub={`${b.trades} closed · ${b.open} open · ${b.wins} won`} />
        <Fig label="Ref (random)" value={usd(refTotal, true)} cls={tone(refTotal)} sub={`${ref_.trades} closed · ${ref_.open} open`} />
      </div>
      <p className="mt-2 text-xs text-ink-dim">
        {b.trades + b.open === 0 ? "No trades yet."
          : total > refTotal ? `Ahead of luck by ${usd(total - refTotal)}.` : `Behind luck by ${usd(refTotal - total)}.`}
        {" "}Balance {usd(b.balance_usd)} closed{b.skipped_cash ? ` · ${b.skipped_cash} skipped, no cash` : ""}.
      </p>
    </div>
  );
}

export function MoodLabPage() {
  const { data: d, isLoading, error } = useQuery({
    queryKey: ["mood-lab"],
    queryFn: () => api.get<MoodLab>("/labs/mood"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <p className="p-6 text-sm text-ink-dim">Loading…</p>;
  if (error || !d) return <p className="p-6 text-sm text-down">The Mood Lab could not be read.</p>;
  const empty: Book = { trades: 0, open: 0, wins: 0, pnl_usd: 0, open_pnl_usd: 0, balance_usd: d.capital_usd, skipped_cash: 0 };
  const bk = (k: string) => d.books[k] ?? empty;
  const fng = d.fng[0];
  return (
    <div className="space-y-5 pb-12">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 sm:p-6">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 size-72 rounded-full bg-accent/15 blur-3xl" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">
            Paper only · from {new Date(`${d.start_day}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })} · {usd(d.capital_usd)} a book at {usd(d.ticket_usd)} a trade
          </div>
          <h1 className="mt-1 font-brand text-3xl font-bold text-ink sm:text-4xl">Mood Lab</h1>
          <p className="mt-2 max-w-3xl text-sm text-ink-dim">
            Reads the crowd on 25 big meme-coin futures (Binance: funding, top-trader and retail long/short ratios) and paper trades it.
            Each book trades beside Ref, who places the same trades on random coins: a rule only counts if it beats Ref.
            {d.enabled ? "" : " Switched off: no new trades."}
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            {TEAM.map(([n, job]) => (
              <span key={n} className="rounded-full border border-line bg-sunken px-3 py-1" title={job}><b className="text-ink">{n}</b> <span className="text-ink-dim">· {job}</span></span>
            ))}
          </div>
        </div>
      </header>

      <section className="grid gap-3 lg:grid-cols-2">
        <BookCard name="Shadow" b={bk("shadow")} ref_={bk("ref_shadow")} hold={d.holds.shadow ?? 3} />
        <BookCard name="Contra" b={bk("contra")} ref_={bk("ref_contra")} hold={d.holds.contra ?? 1} />
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-brand text-lg font-semibold text-ink">Pulse · today&apos;s mood</h2>
          {fng ? <span className="text-sm text-ink-dim">Fear &amp; Greed: <b className={fng.v < 40 ? "text-down" : fng.v > 60 ? "text-up" : "text-ink"}>{fng.v} · {fng.label}</b></span> : null}
        </div>
        {d.trending ? (
          <div className="mt-3 rounded-xl border border-line bg-sunken px-3 py-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-dim">Buzz · trending on CoinGecko now</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
              {d.trending.coins.map((c) => (
                <span key={c.symbol + c.rank} className="rounded-full border border-line bg-surface px-2.5 py-0.5"><span className="text-ink-faint">#{c.rank}</span> <b className="text-ink">{c.symbol}</b></span>
              ))}
            </div>
            <div className="mt-1.5 text-[11px] text-ink-faint">Recorded hourly ({d.buzz_hours ?? 0} hours so far). Recording only: no trades on it until there are weeks of history to test fairly.</div>
          </div>
        ) : null}
        <p className="mt-1 text-xs text-ink-faint">Mood runs from −100 (panic) to +100 (greed), against each coin&apos;s own last 90 days. The gap is top traders minus retail: positive means the big players are more bullish than the crowd.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
                <th className="py-1.5 pr-3 text-left font-normal">Mood</th>
                <th className="py-1.5 pr-3 text-right font-normal">Gap</th>
                <th className="py-1.5 pr-3 text-left font-normal">Shadow says</th>
                <th className="py-1.5 pr-3 text-left font-normal">Contra says</th>
                <th className="py-1.5 text-left font-normal">Buzz</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-subtle">
              {d.pulse.map((p) => (
                <tr key={p.sym}>
                  <td className="py-2 pr-3 font-medium text-ink">{coin(p.sym)}</td>
                  <td className="py-2 pr-3">
                    {p.mood === null ? <span className="text-ink-faint">filling history</span> : (
                      <div className="flex items-center gap-2">
                        <div className="relative h-1.5 w-24 rounded-full bg-sunken">
                          <div className={`absolute top-0 h-1.5 rounded-full ${p.mood >= 0 ? "left-1/2 bg-up" : "right-1/2 bg-down"}`} style={{ width: `${Math.abs(p.mood) / 2}%` }} />
                        </div>
                        <span className={`font-mono tabular-nums ${tone(p.mood)}`}>{p.mood > 0 ? "+" : ""}{p.mood}</span>
                      </div>
                    )}
                  </td>
                  <td className={`py-2 pr-3 text-right font-mono tabular-nums ${tone(p.gap ?? 0)}`}>{p.gap === null ? "–" : p.gap.toFixed(2)}</td>
                  <td className={`py-2 pr-3 ${p.shadow ? tone(p.shadow) : "text-ink-faint"}`}>{p.shadow ? side(p.shadow) : "–"}</td>
                  <td className={`py-2 pr-3 ${p.contra ? tone(p.contra) : "text-ink-faint"}`}>{p.contra ? side(p.contra) : "–"}</td>
                  <td className="py-2 text-ink-dim">
                    {p.buzz?.now ? <span className="font-semibold text-accent">#{p.buzz.now} trending</span>
                      : p.buzz?.d7 ? `${p.buzz.h24}h today · ${p.buzz.d7}h this week` : <span className="text-ink-faint">–</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {[["Open trades", d.open], ["Closed trades", d.closed]].map(([title, rows]) => (
        <section key={title as string} className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="font-brand text-lg font-semibold text-ink">{title as string}</h2>
          {(rows as Trade[]).length === 0 ? <p className="mt-2 text-sm text-ink-dim">None yet. Signals come once Binance publishes a day&apos;s positioning, the next morning.</p> : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[40rem] text-sm">
                <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
                  <tr>
                    <th className="py-1.5 pr-3 text-left font-normal">Book</th>
                    <th className="py-1.5 pr-3 text-left font-normal">Coin</th>
                    <th className="py-1.5 pr-3 text-left font-normal">Side</th>
                    <th className="py-1.5 pr-3 text-left font-normal">Opened</th>
                    <th className="py-1.5 pr-3 text-left font-normal">{title === "Open trades" ? "Closes" : "Closed"}</th>
                    <th className="py-1.5 text-right font-normal">P/L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-subtle">
                  {(rows as Trade[]).map((t) => {
                    const pnl = t.pnl_usd ?? (t.now ? d.ticket_usd * (t.side * (t.now / t.entry - 1) - 0.002) : 0);
                    return (
                      <tr key={`${t.book}${t.sym}${t.opened_at}`}>
                        <td className="py-2 pr-3 capitalize text-ink-dim">{t.book}</td>
                        <td className="py-2 pr-3 font-medium text-ink">{coin(t.sym)}</td>
                        <td className={`py-2 pr-3 ${tone(t.side)}`}>{side(t.side)}</td>
                        <td className="py-2 pr-3 text-ink-dim">{at(t.opened_at)}</td>
                        <td className="py-2 pr-3 text-ink-dim">{at(t.closed_at ?? t.due_at)}</td>
                        <td className={`py-2 text-right font-mono tabular-nums ${tone(pnl)}`}>{usd(pnl, true)}{t.closed_at ? "" : " now"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="font-brand text-lg font-semibold text-ink">Why these two: the 2-year backtest</h2>
        <p className="mt-1 text-xs text-ink-faint">Rules written down before looking, picked on Nov 2024 – Dec 2025, then tested on 2026, which they never saw. $50 a trade, fees and funding counted.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ink-faint">
              <tr>
                <th className="py-1.5 pr-3 text-left font-normal">Rule</th>
                <th className="py-1.5 pr-3 text-right font-normal">Picking period</th>
                <th className="py-1.5 pr-3 text-right font-normal">2026 test</th>
                <th className="py-1.5 pr-3 text-right font-normal">2026 at $50</th>
                <th className="py-1.5 text-left font-normal">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-subtle">
              {d.backtest.map((b) => (
                <tr key={`${b.name}${b.hold}`}>
                  <td className="py-2 pr-3 text-ink">{b.name} · {b.hold}d</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{b.select}/trade</td>
                  <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink-dim">{b.test}/trade</td>
                  <td className={`py-2 pr-3 text-right font-mono tabular-nums ${tone(b.test_usd)}`}>{usd(b.test_usd, true)} · {b.test_trades}</td>
                  <td className={`py-2 ${b.verdict === "pass" ? "text-up" : b.verdict === "fail" ? "text-down" : "text-ink-dim"}`}>{b.verdict}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-ink-dim">Shadow&apos;s 2026 profit came from its shorts, in a falling year for meme coins, and without its best 10 trades it was about break-even. Small edge, not big money: this book is the real test.</p>
      </section>
      <p className="text-xs text-ink-faint">{d.updated_at ? `Updated ${at(d.updated_at)} Dubai. ` : ""}A simulation on Binance futures prices. No real wallet follows it. Not financial advice.</p>
    </div>
  );
}
