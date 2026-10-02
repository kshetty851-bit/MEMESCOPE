/**
 * KARTHIK & RAFIQ, 50-50 (Karthik, 2026-09-28): what each of them has made on
 * the real wallet since 3 PM Dubai on 28 Sep, when they put in $50 each, and
 * each day's % of the balance it opened with — like Karthik's Lab.
 * Trading profit only; the server's `partners` block (`real_wallet/partners.py`).
 */

import { useEffect, useState } from "react";

export interface PartnersDay {
  n: number;
  from: string;
  to: string;
  running: boolean;
  trades: number;
  pnl_usd: string;
  pct: string;
  balance_usd: string;
}

export interface Partners {
  started_at: string;
  capital_usd: string;
  profit_usd: string;
  balance_usd: string;
  pct: string;
  trades: number;
  wins: number;
  open: number;
  sol_usd?: string | null;
  value_pct?: string | null;
  open_cost_usd?: string;
  total_put_in_sol?: string;
  total_value_usd?: string | null;
  total_value_profit_usd?: string | null;
  total_value_sol?: string | null;
  total_value_profit_sol?: string | null;
  partners: {
    name: string;
    share: string;
    put_in_usd: string;
    profit_usd: string;
    now_usd: string;
    put_in_sol?: string;
    value_usd?: string | null;
    value_profit_usd?: string | null;
    value_sol?: string | null;
    value_profit_sol?: string | null;
  }[];
  days: PartnersDay[];
}

const money = (value: string | number) => {
  const n = Number(value);
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toFixed(2)}`;
};
const signed = (value: string | number) => `${Number(value) >= 0 ? "+" : ""}${money(value)}`;
const sol = (value: string | null | undefined, sign = false) =>
  value == null ? null : `${sign && Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(4)} SOL`;
const tone = (value: string | number) =>
  Number(value) > 0 ? "text-up" : Number(value) < 0 ? "text-down" : "text-ink";

const DAY_MS = 86_400_000;
const HORIZON_DAYS = 30;

/** "4d 07h 12m 08s" since `from`. */
export function elapsed(from: number, now: number): string {
  const s = Math.max(0, Math.floor((now - from) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${Math.floor(s / 86400)}d ${pad(Math.floor(s / 3600) % 24)}h ${pad(
    Math.floor(s / 60) % 60)}m ${pad(s % 60)}s`;
}

/**
 * Day 30's value if the gain so far keeps its average daily pace (Karthik,
 * 2026-10-02). Straight-line, not compounded; null before a full day, when a
 * few hours would be stretched thirty-fold.
 */
export function dayThirty(capital: number, value: number, days: number): number | null {
  if (!(days >= 1)) return null;
  // A wallet cannot be worth less than nothing.
  return Math.max(0, capital + ((value - capital) / days) * HORIZON_DAYS);
}

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export function PartnersCard({ data }: { data: Partners | undefined }) {
  const now = useNow();
  if (!data) return null;
  const started = new Date(data.started_at).getTime();
  const capital = Number(data.capital_usd);
  const worth = Number(data.total_value_usd ?? data.balance_usd);
  const expected = dayThirty(capital, worth, (now - started) / DAY_MS);
  const since = new Date(data.started_at)
    .toLocaleString("en-GB", {
      timeZone: "Asia/Dubai", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
      hour12: true,
    })
    .replace("Sept", "Sep")
    .replace(/\s?(am|pm)$/i, (m) => ` ${m.trim().toUpperCase()}`);
  return (
    <section className="mt-6 rounded-lg border border-accent/40 bg-accent/[0.04] p-4" data-testid="partners">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-accent">Karthik &amp; Rafiq · 50-50</p>
        <p className="text-xs text-ink-3">
          {money(data.capital_usd)} in since {since} (Dubai) · {data.trades} trades · {data.wins} won
          {data.open ? ` · ${data.open} open` : ""}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs text-ink-3">Running for</p>
          <p className="text-xl font-semibold tabular-nums text-ink" data-testid="partners-timer">
            {elapsed(started, now)}
          </p>
        </div>
        {expected != null ? (
          <div className="text-right">
            <p className="text-xs text-ink-3">Day {HORIZON_DAYS} expected total</p>
            <p className={`text-xl font-semibold tabular-nums ${tone(expected - capital)}`}
               data-testid="partners-day30">
              {money(expected)}
            </p>
            <p className="text-[11px] text-ink-3">if the pace so far holds · not a promise</p>
          </div>
        ) : null}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {data.partners.map((p) => {
          const now = p.value_profit_usd != null;
          const headline = now ? p.value_profit_usd! : p.profit_usd;
          return (
            <div key={p.name} className="rounded-md border border-line bg-canvas/40 p-3">
              <p className="text-sm font-medium text-ink">{p.name}</p>
              <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone(headline)}`}>
                {signed(headline)}
              </p>
              {now && p.value_profit_sol != null ? (
                <p className={`text-sm tabular-nums ${tone(p.value_profit_sol)}`}>
                  {sol(p.value_profit_sol, true)}
                </p>
              ) : null}
              <p className="text-xs text-ink-3">
                put in {money(p.put_in_usd)}
                {p.put_in_sol ? ` (${sol(p.put_in_sol)})` : ""} · now{" "}
                {now ? `${money(p.value_usd!)} (${sol(p.value_sol)})` : money(p.now_usd)}
              </p>
              {now ? (
                <p className="text-xs text-ink-3">from trades {signed(p.profit_usd)}</p>
              ) : null}
            </div>
          );
        })}
        <div className="rounded-md border border-line bg-canvas/40 p-3">
          <p className="text-sm font-medium text-ink">Together</p>
          {data.total_value_profit_usd != null ? (
            <>
              <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone(data.total_value_profit_usd)}`}>
                {signed(data.total_value_profit_usd)}
              </p>
              {data.total_value_profit_sol != null ? (
                <p className={`text-sm tabular-nums ${tone(data.total_value_profit_sol)}`}>
                  {sol(data.total_value_profit_sol, true)}
                </p>
              ) : null}
              <p className="text-xs text-ink-3">
                {money(data.capital_usd)} → {money(data.total_value_usd!)} ({sol(data.total_value_sol)}) ·{" "}
                <span className={tone(data.value_pct ?? 0)}>
                  {Number(data.value_pct) >= 0 ? "+" : ""}
                  {Number(data.value_pct).toFixed(2)}%
                </span>
              </p>
              <p className="text-xs text-ink-3">from trades {signed(data.profit_usd)}</p>
            </>
          ) : (
            <>
              <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone(data.profit_usd)}`}>
                {signed(data.profit_usd)}
              </p>
              <p className="text-xs text-ink-3">
                {money(data.capital_usd)} → {money(data.balance_usd)} ·{" "}
                <span className={tone(data.pct)}>
                  {Number(data.pct) >= 0 ? "+" : ""}
                  {Number(data.pct).toFixed(2)}%
                </span>
              </p>
            </>
          )}
        </div>
      </div>

      {data.days.length ? (
        <div className="-mx-1 mt-3 flex gap-2 overflow-x-auto px-1 pb-1">
          {data.days.map((d) => (
            <div
              key={d.n}
              className={`min-w-[112px] shrink-0 rounded-lg border p-2 ${
                d.running ? "border-dashed border-line" : "border-line"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wider text-ink-3">
                {d.running ? `Day ${d.n} · so far` : `Day ${d.n}`}
              </div>
              {/* Dollars only (Karthik, 2026-09-30), as in Karthik's Lab. */}
              <div className={`mt-0.5 text-base font-semibold tabular-nums ${tone(d.pnl_usd)}`}>
                {signed(d.pnl_usd)}
              </div>
              <div className="text-[11px] tabular-nums text-ink-3">{d.trades} trades</div>
            </div>
          ))}
        </div>
      ) : null}
      <p className="mt-2 text-[11px] text-ink-3">
        Profit is what the wallet is worth now at today&apos;s SOL price
        {data.sol_usd ? ` (${money(data.sol_usd)} per SOL)` : ""} minus the $100, split half and
        half, so it moves with SOL. A trade that is open counts at what it would sell for now.
        &quot;From trades&quot; is the trading profit alone, and the days below are trading profit.
        Each day runs 3 PM to 3 PM Dubai. Day {HORIZON_DAYS} expected: the gain so far at its
        average daily pace, carried to day {HORIZON_DAYS} — one bad rug or SOL&apos;s price moves it.
      </p>
    </section>
  );
}
