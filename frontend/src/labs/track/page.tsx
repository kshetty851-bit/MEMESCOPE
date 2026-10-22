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


/** 2.98M / 45,988: a counter must fit its tile on any screen. */
const compact = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e5 ? `${(n / 1e3).toFixed(0)}k` : fmt(n);

function reduced(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** True once the element has scrolled into view (and stays true). */
function useInView<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (reduced() || typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e?.isIntersecting) { setSeen(true); io.disconnect(); } },
                                        { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return [ref, seen];
}

/** Counts up from 0 once `run` turns true. */
function CountUp({ value, run = true, format = fmt }: { value: number; run?: boolean; format?: (n: number) => string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (!run) return;
    if (reduced()) { setShown(value); return; }
    const start = performance.now(), span = 1600;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / span);
      setShown(value * (k === 1 ? 1 : 1 - Math.pow(2, -10 * k)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, run]);
  return <span className="tabular-nums">{format(Math.round(shown))}</span>;
}

/** A section that rises in when it scrolls into view; its children animate then too. */
function Reveal({ children, className = "", as: Tag = "section" }: { children: React.ReactNode; className?: string; as?: "section" | "div" }) {
  const [ref, seen] = useInView<HTMLElement>();
  return <Tag ref={ref as React.RefObject<never>} className={`tr-reveal ${seen ? "is-in" : ""} ${className}`}>{children}</Tag>;
}

function tier(x: number): string {
  return x >= 100 ? "tr-x--legend" : x >= 10 ? "tr-x--big" : x >= 2 ? "tr-x--good" : "tr-x--small";
}

function Stat({ label, value, hint, i, glyph }: { label: string; value: number; hint?: string; i: number; glyph: string }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} className={`tr-stat ${seen ? "is-in" : ""}`} style={{ ["--i" as string]: i }}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-dim">{label}</span>
        <span aria-hidden className="tr-stat-glyph">{glyph}</span>
      </div>
      <div className="tr-stat-num mt-2 font-brand font-semibold text-ink" title={fmt(value)}>
        <CountUp value={value} run={seen} format={compact} />
      </div>
      <div className="mt-1 truncate text-[11px] text-ink-dim">{hint ?? fmt(value)}</div>
    </div>
  );
}

function Ticker({ movers }: { movers: Mover[] }) {
  const items = movers.slice(0, 20);
  if (!items.length) return null;
  const row = (hidden: boolean) => (
    <ul className="tr-ticker-row" aria-hidden={hidden || undefined}>
      {items.map((m) => (
        <li key={m.mint}>
          <span className="text-ink">{coin(m)}</span>
          <span className={`font-brand font-semibold ${tier(m.peak_x)}`}>{xs(m.peak_x)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="tr-ticker" aria-label="Biggest multiples after graduation">
      <div className="tr-ticker-track">{row(false)}{row(true)}</div>
    </div>
  );
}

function Funnel({ t }: { t: TrackRecord["totals"] }) {
  const [ref, seen] = useInView<HTMLOListElement>();
  const steps = [
    ["Coins seen launching", t.coins_seen, "every pump.fun launch our scanner saw"],
    ["Tracked on the launch curve", t.curve_tracked, "watched trade by trade"],
    ["Graduated", t.graduated, "opened a real trading pool"],
    ["Traded on paper", t.paper_coins, `${fmt(t.paper_trades)} trades · ${t.strategies} strategies`],
    ["Traded with real money", t.real_coins, `${fmt(t.real_trades)} trades`],
  ] as const;
  const top = Math.log10(t.coins_seen || 1);
  return (
    <ol ref={ref} className={`tr-funnel ${seen ? "is-in" : ""}`}>
      {steps.map(([label, n, note], i) => (
        <li key={label} style={{ ["--i" as string]: i, ["--w" as string]: `${Math.max(18, (100 * Math.log10(Math.max(1, n))) / top)}%` }}>
          <div className="tr-funnel-bar">
            <span className="tr-funnel-sheen" aria-hidden />
            <span className="relative font-brand text-lg font-semibold text-ink sm:text-xl"><CountUp value={n} run={seen} format={compact} /></span>
          </div>
          <div className="mt-1 text-center text-xs text-ink"><b className="font-medium">{label}</b> <span className="text-ink-dim">· {note}</span></div>
        </li>
      ))}
    </ol>
  );
}

function Multiples({ d }: { d: TrackRecord }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  const order = ["1.1", "1.5", "2", "5", "10", "50", "100"];
  return (
    <div ref={ref} className={`space-y-2.5 ${seen ? "is-in" : ""} tr-tiers`}>
      {order.map((k, i) => {
        const n = d.reached[k] ?? 0, pct = d.measured ? (100 * n) / d.measured : 0;
        return (
          <div key={k} className="grid grid-cols-[3.5rem_1fr_minmax(5.5rem,auto)] items-center gap-3">
            <span className={`font-brand text-lg font-semibold ${tier(Number(k))}`}>{k}x</span>
            <div className="h-3 overflow-hidden rounded-full bg-sunken">
              <span className="tr-tier-bar" style={{ ["--w" as string]: `${Math.max(0.8, pct)}%`, ["--i" as string]: i }} data-x={k} />
            </div>
            <span className="text-right font-mono text-xs tabular-nums text-ink-dim">
              <CountUp value={n} run={seen} /> <span className="text-ink-faint">· {pct < 1 ? pct.toFixed(2) : pct.toFixed(0)}%</span>
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

const MEDAL = ["gold", "silver", "bronze"] as const;

function Podium({ top }: { top: Mover[] }) {
  // Second, first, third: the winner stands in the middle.
  const order = [top[1], top[0], top[2]].filter(Boolean) as Mover[];
  return (
    <div className="tr-podium">
      {order.map((m) => {
        const rank = top.indexOf(m) + 1;
        return (
          <a key={m.mint} href={chart(m.mint)} target="_blank" rel="noreferrer"
             className={`tr-medal tr-medal--${MEDAL[rank - 1]} ${rank === 1 ? "is-first" : ""}`}
             aria-label={`${coin(m)} reached ${xs(m.peak_x)} — open chart`}>
            <span className="tr-medal-ring" aria-hidden />
            <span className="tr-medal-inner">
              <span className="tr-medal-rank">#{rank}</span>
              <span className={`tr-medal-x font-brand font-bold ${tier(m.peak_x)}`}>{xs(m.peak_x)}</span>
              <span className="mt-2 truncate text-base font-semibold text-ink">{coin(m)}</span>
              <span className="mt-1 text-[11px] text-ink-dim">
                {day(m.graduated_at)} · peaked {when(m.peak_after_min)} in · ${short(m.pool_usd)} pool
              </span>
              <span className="mt-2 text-[11px] text-ink-faint">last reading <b className={m.end_x >= 1 ? "text-up" : "text-down"}>{xs(m.end_x)}</b> · chart ↗</span>
            </span>
          </a>
        );
      })}
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
      <div className="mt-0.5 text-[11px] text-ink-dim">peaked {when(m.peak_after_min)} in · ${short(m.pool_usd)} pool</div>
      <div className="mt-2 text-[11px] text-ink-faint">
        last reading: <span className={m.end_x >= 1 ? "text-up" : "text-down"}>{xs(m.end_x)}</span>
        <span className="float-right text-accent opacity-0 transition-opacity group-hover:opacity-100">chart ↗</span>
      </div>
    </a>
  );
}

function Panel({ title, kicker, children, className = "" }: { title: string; kicker?: string; children: React.ReactNode; className?: string }) {
  return (
    <Reveal className={`tr-panel ${className}`}>
      <header className="mb-4">
        {kicker ? <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">{kicker}</div> : null}
        <h2 className="mt-1 font-brand text-xl font-semibold text-ink sm:text-2xl">{title}</h2>
      </header>
      {children}
    </Reveal>
  );
}

function Days({ days }: { days: Day[] }) {
  const recent = days.slice(-30);
  const top = Math.max(1, ...recent.map((d) => d.graduated));
  return (
    <div className="tr-days">
      <div className="flex h-56 items-end gap-[3px] lg:h-72">
        {recent.map((d, i) => (
          <div key={d.date} className="group relative flex h-full flex-1 flex-col justify-end"
               title={`${day(d.date)}: ${fmt(d.graduated)} graduated · ${d.x2} reached 2x · ${d.x10} reached 10x${d.best_x ? ` · best ${cleanName(d.best_symbol) ?? "unnamed"} ${xs(d.best_x)}` : ""}`}>
            <span className="tr-day-bar" style={{ ["--h" as string]: `${(100 * d.graduated) / top}%`, ["--i" as string]: i }}>
              <span className="tr-day-hot" style={{ ["--h" as string]: `${d.graduated ? (100 * d.x2) / d.graduated : 0}%` }} />
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap justify-between gap-2 text-[11px] text-ink-faint">
        <span>{day(recent[0]?.date ?? null)}</span>
        <span><i className="mr-1 inline-block size-2 rounded-sm bg-raised align-middle" />graduated <i className="ml-3 mr-1 inline-block size-2 rounded-sm bg-up align-middle" />of them reached 2x</span>
        <span>{day(recent.at(-1)?.date ?? null)}</span>
      </div>
    </div>
  );
}

function Row({ i, href, name, meta, x }: { i: number; href: string; name: string; meta: React.ReactNode; x: number }) {
  return (
    <li className="tr-row flex items-center gap-3 py-2.5" style={{ ["--i" as string]: i }}>
      <span className="w-5 font-mono text-[11px] text-ink-faint">{i + 1}</span>
      <a href={href} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-sm font-medium text-ink hover:text-accent">{name}</a>
      <span className="hidden text-[11px] text-ink-dim sm:inline">{meta}</span>
      <span className={`w-20 text-right font-brand text-lg font-semibold ${tier(x)}`}>{xs(x)}</span>
    </li>
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
        <div aria-hidden className="tr-aurora"><i /><i /><i /></div>
        <div aria-hidden className="tr-grid" />
        <div className="relative">
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent">MEMESCOPE · since {day(t.seen_since)}</div>
          <h1 className="tr-title mt-2 font-brand font-bold">Track record</h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-dim">
            Every coin we have watched, measured and traded — counted on chain, not estimated, refreshed every thirty
            minutes. <span className="text-ink">Updated {new Date(t.at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...DUBAI })} Dubai.</span>
          </p>
        </div>
        <div className="relative mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-6">
          <Stat i={0} glyph="◎" label="Coins seen" value={t.coins_seen} hint={`since ${day(t.seen_since)}`} />
          <Stat i={1} glyph="∿" label="Curve tracked" value={t.curve_tracked} />
          <Stat i={2} glyph="↗" label="Graduated" value={t.graduated} hint={`since ${day(t.graduated_since)}`} />
          <Stat i={3} glyph="⚗" label="Strategies" value={t.strategies} hint="tested on paper" />
          <Stat i={4} glyph="▤" label="Paper trades" value={t.paper_trades} hint={`${fmt(t.paper_coins)} coins`} />
          <Stat i={5} glyph="◆" label="Real trades" value={t.real_trades} hint={`${winRate}% won · ${usd(t.real_pnl_usd)}`} />
        </div>
        <div className="relative mt-6"><Ticker movers={data.hall_of_fame} /></div>
      </header>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel kicker="The funnel" title="From millions of launches to a few real trades"><Funnel t={t} /></Panel>
        <Panel kicker="After graduating" title={`How high ${fmt(data.measured)} graduations went`}><Multiples d={data} /></Panel>
      </div>

      <Panel kicker="Hall of fame" title="The biggest multiples after graduation">
        <Podium top={data.hall_of_fame.slice(0, 3)} />
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
          {data.hall_of_fame.slice(3, 18).map((m, i) => <MoverCard key={m.mint} m={m} rank={i + 4} />)}
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_1fr]">
        <Panel kicker="Last 7 days" title="This week's biggest movers">
          <ol className="divide-y divide-line-subtle">
            {data.this_week.slice(0, 10).map((m, i) => (
              <Row key={m.mint} i={i} href={chart(m.mint)} name={coin(m)} x={m.peak_x}
                   meta={<>{day(m.graduated_at)} · ${short(m.pool_usd)}</>} />
            ))}
          </ol>
        </Panel>
        <Panel kicker="Day by day" title="Graduations, and how many doubled"><Days days={data.days} /></Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel kicker="Karthik's Lab · paper" title="Our best trades">
          <ol className="divide-y divide-line-subtle">
            {data.best.paper.slice(0, 8).map((b, i) => (
              <Row key={b.mint} i={i} href={chart(b.mint)} name={coin(b)} x={b.x} meta={<>{day(b.opened_at)} · ${short(b.pool_usd)} pool</>} />
            ))}
          </ol>
        </Panel>
        <Panel kicker={`Real money · ${winRate}% of ${fmt(t.real_trades)} trades won`} title="The real wallet's best trades">
          <ol className="divide-y divide-line-subtle">
            {data.best.real.slice(0, 8).map((b, i) => (
              <Row key={`${b.mint}-${b.opened_at}`} i={i} href={chart(b.mint)} name={coin(b)} x={b.x}
                   meta={<>{day(b.opened_at)} · {usd(b.stake_usd)} in · <span className="text-up">+{usd(b.pnl_usd)}</span></>} />
            ))}
          </ol>
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
