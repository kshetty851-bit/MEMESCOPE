"use client";

/**
 * Track record (Karthik, 2026-10-22: "build track record on the left bar, put
 * all this information and keep updating! mention which token did how many x
 * returns"). Everything is read from `/track-record`, refreshed every thirty
 * minutes on the server from what MEMESCOPE recorded; nothing is estimated.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";

interface Mover {
  mint: string;
  symbol: string | null;
  name: string | null;
  graduated_at: string;
  pool_usd: number;
  peak_x: number;
  peak_after_min: number;
  end_x: number;
}
interface BestPaper { mint: string; symbol: string | null; book: string; opened_at: string; x: number; pool_usd: number }
interface BestReal { mint: string; symbol: string | null; opened_at: string; strategy: string; stake_usd: number; pnl_usd: number; x: number }
interface Day { date: string; graduated: number; measured: number; x2: number; x10: number; best_x: number | null; best_symbol: string | null }
export interface TrackRecord {
  warming_up?: boolean;
  totals: {
    coins_seen: number; seen_since: string | null; curve_tracked: number; graduated: number;
    graduated_since: string | null; paper_coins: number; paper_trades: number; strategies: number;
    real_trades: number; real_coins: number; real_wins: number; real_pnl_usd: number;
    real_since: string | null; safety_checks: number; at: string;
  };
  best: { paper: BestPaper[]; real: BestReal[] };
  reached: Record<string, number>;
  measured: number;
  ended_down_80: number;
  hall_of_fame: Mover[];
  this_week: Mover[];
  days: Day[];
}

const DUBAI = { timeZone: "Asia/Dubai" } as const;
const fmt = (n: number) => n.toLocaleString("en-US");
const short = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : fmt(n);
const xs = (x: number) => (x >= 100 ? `${Math.round(x)}x` : x >= 10 ? `${x.toFixed(1)}x` : `${x.toFixed(2)}x`);
const usd = (v: number) => `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 0 : 2 })}`;
const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", ...DUBAI }) : "—";
const when = (min: number) => (min < 60 ? `${Math.round(min)} min` : `${(min / 60).toFixed(min < 600 ? 1 : 0)} h`);
const coin = (m: { symbol: string | null; name?: string | null; mint: string }) =>
  cleanName(m.symbol) ?? cleanName(m.name ?? null) ?? `${m.mint.slice(0, 4)}…${m.mint.slice(-4)}`;
const chart = (mint: string) => `https://dexscreener.com/solana/${mint}`;

function reduced(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Counts up from 0 the first time it is shown. */
function CountUp({ value, format = fmt }: { value: number; format?: (n: number) => string }) {
  const [shown, setShown] = useState(reduced() ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced()) { setShown(value); return; }
    const start = performance.now(), a = from.current, span = 1400;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / span), e = 1 - Math.pow(2, -10 * k);
      setShown(a + (value - a) * (k === 1 ? 1 : e));
      if (k < 1) raf = requestAnimationFrame(step); else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <span className="tabular-nums">{format(Math.round(shown))}</span>;
}

function tier(x: number): string {
  return x >= 100 ? "tr-x--legend" : x >= 10 ? "tr-x--big" : x >= 2 ? "tr-x--good" : "tr-x--small";
}

function Stat({ label, value, hint, i }: { label: string; value: number; hint?: string; i: number }) {
  return (
    <div className="tr-stat" style={{ ["--i" as string]: i }}>
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className="mt-2 font-brand text-3xl font-semibold text-ink sm:text-4xl"><CountUp value={value} /></div>
      {hint ? <div className="mt-1 text-xs text-ink-dim">{hint}</div> : null}
    </div>
  );
}

function Funnel({ t }: { t: TrackRecord["totals"] }) {
  const steps = [
    ["Coins seen launching", t.coins_seen, "every pump.fun launch our scanner saw"],
    ["Tracked on the launch curve", t.curve_tracked, "watched trade by trade before graduating"],
    ["Graduated", t.graduated, "finished the curve and opened a real pool"],
    ["Traded on paper", t.paper_coins, `${fmt(t.paper_trades)} trades by ${t.strategies} strategies`],
    ["Traded with real money", t.real_coins, `${fmt(t.real_trades)} trades`],
  ] as const;
  const top = Math.log10(t.coins_seen || 1);
  return (
    <ol className="space-y-3">
      {steps.map(([label, n, note], i) => (
        <li key={label} className="tr-funnel-row" style={{ ["--i" as string]: i }}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink">{label}</span>
            <span className="font-mono tabular-nums text-ink"><CountUp value={n} /></span>
          </div>
          <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-sunken">
            <span className="tr-funnel-bar" style={{ ["--w" as string]: `${Math.max(4, (100 * Math.log10(Math.max(1, n))) / top)}%`, ["--i" as string]: i }} />
          </div>
          <div className="mt-1 text-[11px] text-ink-dim">{note}</div>
        </li>
      ))}
    </ol>
  );
}

function Multiples({ d }: { d: TrackRecord }) {
  const order = ["1.1", "1.5", "2", "5", "10", "50", "100"];
  return (
    <div className="space-y-2.5">
      {order.map((k, i) => {
        const n = d.reached[k] ?? 0, pct = d.measured ? (100 * n) / d.measured : 0;
        return (
          <div key={k} className="grid grid-cols-[3.5rem_1fr_6.5rem] items-center gap-3">
            <span className={`font-brand text-lg font-semibold ${tier(Number(k))}`}>{k}x</span>
            <div className="h-3 overflow-hidden rounded-full bg-sunken">
              <span className="tr-tier-bar" style={{ ["--w" as string]: `${Math.max(0.6, pct)}%`, ["--i" as string]: i }} data-x={k} />
            </div>
            <span className="text-right font-mono text-xs tabular-nums text-ink-dim">
              {fmt(n)} <span className="text-ink-faint">· {pct < 1 ? pct.toFixed(2) : pct.toFixed(0)}%</span>
            </span>
          </div>
        );
      })}
      <div className="mt-3 rounded-lg border border-down/30 bg-down/10 px-3 py-2 text-xs text-ink-dim">
        <b className="text-down">The other side:</b> {fmt(d.ended_down_80)} of the same {fmt(d.measured)} coins ({d.measured ? Math.round((100 * d.ended_down_80) / d.measured) : 0}%) ended their first day down 80% or more.
      </div>
    </div>
  );
}

function MoverCard({ m, rank }: { m: Mover; rank: number }) {
  return (
    <a href={chart(m.mint)} target="_blank" rel="noreferrer" className="tr-card group" style={{ ["--i" as string]: rank }}
       aria-label={`${coin(m)} reached ${xs(m.peak_x)} — open chart`}>
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-[11px] text-ink-faint">#{rank}</span>
        <span className="text-[11px] text-ink-dim">{day(m.graduated_at)}</span>
      </div>
      <div className={`tr-x mt-1 font-brand font-bold leading-none ${tier(m.peak_x)}`}>{xs(m.peak_x)}</div>
      <div className="mt-2 truncate text-sm font-medium text-ink">{coin(m)}</div>
      <div className="mt-0.5 text-[11px] text-ink-dim">
        peaked {when(m.peak_after_min)} after graduating · ${short(m.pool_usd)} pool
      </div>
      <div className="mt-2 text-[11px] text-ink-faint">
        a day later: <span className={m.end_x >= 1 ? "text-up" : "text-down"}>{xs(m.end_x)}</span>
        <span className="float-right text-accent opacity-0 transition-opacity group-hover:opacity-100">chart ↗</span>
      </div>
    </a>
  );
}

function Panel({ title, kicker, children, className = "" }: { title: string; kicker?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`tr-panel ${className}`}>
      <header className="mb-4">
        {kicker ? <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">{kicker}</div> : null}
        <h2 className="mt-1 font-brand text-xl font-semibold text-ink">{title}</h2>
      </header>
      {children}
    </section>
  );
}

function Days({ days }: { days: Day[] }) {
  const recent = days.slice(-30);
  const top = Math.max(1, ...recent.map((d) => d.graduated));
  return (
    <div>
      <div className="flex h-56 items-end gap-[3px] lg:h-80">
        {recent.map((d, i) => (
          <div key={d.date} className="group relative flex h-full flex-1 flex-col justify-end"
               title={`${day(d.date)}: ${fmt(d.graduated)} graduated · ${d.x2} reached 2x · ${d.x10} reached 10x${d.best_x ? ` · best ${cleanName(d.best_symbol) ?? "unnamed"} ${xs(d.best_x)}` : ""}`}>
            <span className="tr-day-bar" style={{ ["--h" as string]: `${(100 * d.graduated) / top}%`, ["--i" as string]: i }}>
              <span className="tr-day-hot" style={{ ["--h" as string]: `${d.graduated ? (100 * d.x2) / d.graduated : 0}%` }} />
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-ink-faint">
        <span>{day(recent[0]?.date ?? null)}</span>
        <span><i className="mr-1 inline-block size-2 rounded-sm bg-raised align-middle" />graduated <i className="ml-3 mr-1 inline-block size-2 rounded-sm bg-up align-middle" />of them reached 2x</span>
        <span>{day(recent.at(-1)?.date ?? null)}</span>
      </div>
    </div>
  );
}

export function TrackRecordPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["track-record"],
    queryFn: () => api.get<TrackRecord>("/track-record"),
    refetchInterval: 120_000,
  });
  if (isLoading) return <p className="p-6 text-sm text-ink-dim">Loading the record…</p>;
  if (error || !data) return <p className="p-6 text-sm text-down">The track record could not be read.</p>;
  if (data.warming_up) return <p className="p-6 text-sm text-ink-dim">Building the record for the first time — about three minutes.</p>;
  const t = data.totals;
  const winRate = t.real_trades ? Math.round((100 * t.real_wins) / t.real_trades) : 0;

  return (
    <div className="tr-page space-y-6 pb-16">
      <header className="tr-hero">
        <div aria-hidden className="tr-hero-glow" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">MEMESCOPE · since {day(t.seen_since)}</div>
          <h1 className="tr-title mt-2 font-brand font-bold text-ink">Track record</h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-dim">
            Every coin we have watched, measured and traded — counted on chain, not estimated, and refreshed every
            thirty minutes. Updated {new Date(t.at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...DUBAI })} Dubai.
          </p>
        </div>
        <div className="relative mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Stat i={0} label="Coins seen" value={t.coins_seen} hint={`since ${day(t.seen_since)}`} />
          <Stat i={1} label="Curve tracked" value={t.curve_tracked} />
          <Stat i={2} label="Graduated" value={t.graduated} hint={`since ${day(t.graduated_since)}`} />
          <Stat i={3} label="Strategies tested" value={t.strategies} />
          <Stat i={4} label="Paper trades" value={t.paper_trades} hint={`${fmt(t.paper_coins)} coins`} />
          <Stat i={5} label="Real trades" value={t.real_trades} hint={`${winRate}% won · ${usd(t.real_pnl_usd)}`} />
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel kicker="The funnel" title="From millions of launches to a few real trades"><Funnel t={t} /></Panel>
        <Panel kicker="After graduating" title={`How high ${fmt(data.measured)} graduations went`}>
          <Multiples d={data} />
        </Panel>
      </div>

      <Panel kicker="Hall of fame" title="The biggest multiples after graduation">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {data.hall_of_fame.slice(0, 18).map((m, i) => <MoverCard key={m.mint} m={m} rank={i + 1} />)}
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Panel kicker="Last 7 days" title="This week's biggest movers">
          <ol className="divide-y divide-line-subtle">
            {data.this_week.slice(0, 10).map((m, i) => (
              <li key={m.mint} className="tr-row flex items-center gap-3 py-2" style={{ ["--i" as string]: i }}>
                <span className="w-5 font-mono text-[11px] text-ink-faint">{i + 1}</span>
                <a href={chart(m.mint)} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-sm text-ink hover:text-accent">{coin(m)}</a>
                <span className="hidden text-[11px] text-ink-dim sm:inline">{day(m.graduated_at)} · ${short(m.pool_usd)}</span>
                <span className={`w-20 text-right font-brand text-lg font-semibold ${tier(m.peak_x)}`}>{xs(m.peak_x)}</span>
              </li>
            ))}
          </ol>
        </Panel>
        <Panel kicker="Day by day" title="Graduations, and how many doubled"><Days days={data.days} /></Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel kicker="Karthik's Lab · paper" title="Our best trades">
          <ul className="divide-y divide-line-subtle">
            {data.best.paper.slice(0, 8).map((b, i) => (
              <li key={b.mint} className="tr-row flex items-center gap-3 py-2" style={{ ["--i" as string]: i }}>
                <a href={chart(b.mint)} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-sm text-ink hover:text-accent">{coin(b)}</a>
                <span className="text-[11px] text-ink-dim">{day(b.opened_at)} · ${short(b.pool_usd)} pool</span>
                <span className={`w-16 text-right font-brand text-lg font-semibold ${tier(b.x)}`}>{xs(b.x)}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel kicker={`Real money · ${winRate}% of ${fmt(t.real_trades)} trades won`} title="The real wallet's best trades">
          <ul className="divide-y divide-line-subtle">
            {data.best.real.slice(0, 8).map((b, i) => (
              <li key={`${b.mint}-${b.opened_at}`} className="tr-row flex items-center gap-3 py-2" style={{ ["--i" as string]: i }}>
                <a href={chart(b.mint)} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-sm text-ink hover:text-accent">{coin(b)}</a>
                <span className="text-[11px] text-ink-dim">{day(b.opened_at)} · {usd(b.stake_usd)} in · <span className="text-up">+{usd(b.pnl_usd)}</span></span>
                <span className={`w-16 text-right font-brand text-lg font-semibold ${tier(b.x)}`}>{xs(b.x)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-ink-faint">
        A multiple is the highest price a coin held for two readings in a row (about 20–30 seconds), against its first
        price after graduating, within 24 hours. Nobody can sell exactly at a peak, and most of these coins fell back.
        Pools under $5,000 at their first price, and readings where the price feed jumped to another pool, are left out.
        Not financial advice.
      </p>
    </div>
  );
}
