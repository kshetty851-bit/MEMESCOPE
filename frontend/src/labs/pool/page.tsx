"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Days, formatElapsed, Row } from "@/labs/karthik/page";
import type { KarthikDay, KarthikTrade } from "@/labs/karthik/types";
import { api } from "@/lib/api-client";

/** The thirty, working for the $10k book; loaded after the page so HQ's
 *  drawings stay out of its bundle. */
const CheckpointPool10k = dynamic(
  () => import("@/components/hq/checkpoint").then((m) => m.CheckpointPool10k),
  { ssr: false },
);

/**
 * POOL LAB (Karthik, 2026-10-05: "build Pool LAB - lets start 10k pool WITH
 * this 10x splits. and another table build 50k pool - 50$ on 500$ each with 10
 * user wallets backtest, keep the trade price real way, start the timer too").
 * Every figure is the API's (`/labs/graduation/pool-lab`); the page only lays
 * them out. Paper only.
 */

interface SizeLine {
  ticket_usd: number;
  capital_usd: number;
  balance_usd: string;
  pnl_usd: string;
  pnl_pct: string;
  trades: number;
  rugs: number;
  wins?: number;
  lowest_usd: string;
}
interface WalletRow {
  name: string;
  balance_usd: number;
  pnl_usd: number;
  trades: number;
  rugs: number;
  lowest_usd: number;
}
interface WalletBook {
  wallets: WalletRow[];
  total_usd: number;
  pnl_usd: number;
  trades: number;
  uncapped_total_usd: number;
  uncapped_pnl_usd: number;
  coins: number;
}
interface OpenTrade {
  symbol: string | null;
  mint: string;
  opened_at: string;
  pool_usd: string | null;
  /** After costs, at the last mark; null before the first one. */
  pct_now: string | null;
}
/** The $10k book at $50 on $500, laid out like Karthik's Lab. */
interface TenKRules {
  floor_usd: number;
  skip_pool_usd: [number, number];
  quiet_max_txs: number;
  max_entry_age_s: number;
  hold_minutes: number;
}
interface TenKBook {
  ticket_usd: number;
  capital_usd: number;
  rules?: TenKRules;
  balance_usd: string;
  days: KarthikDay[];
  closed: (KarthikTrade & { rugged: boolean })[];
  open: OpenTrade[];
}
export interface PoolLab {
  computing?: boolean;
  started_at: string;
  backtest_from: string;
  computed_at?: string;
  ten_k?: { live: SizeLine[]; live_coins: number; book?: TenKBook };
  fifty_k?: { backtest: WalletBook; live: WalletBook; ticket_usd: number; start_usd: number;
              coin_cap_usd: number };
}

function usd(value: string | number | null | undefined, signed = false): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const body = `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `${n < 0 ? "-" : signed ? "+" : ""}${body}`;
}

const tone = (v: string | number) => (Number(v) >= 0 ? "text-up" : "text-down");

function day(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Dubai", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

/** $10k+ pools: each size on ten times its balance, live since the timer. */
export function TenKTable({ data }: { data: NonNullable<PoolLab["ten_k"]> }) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>$10k+ pools · quiet rule · each size on 10× its balance · live</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto p-3" data-testid="pool-ten-k">
        <table className="w-full min-w-[34rem] text-[12px] tabular-nums">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">size</th>
              <th className="px-2 text-right font-normal">balance</th>
              <th className="px-2 text-right font-normal">profit</th>
              <th className="px-2 text-right font-normal">trades</th>
              <th className="px-2 text-right font-normal">rugs</th>
              <th className="pl-2 text-right font-normal">lowest</th>
            </tr>
          </thead>
          <tbody>
            {data.live.map((l) => (
              <tr key={l.ticket_usd} className="border-t border-line/60">
                <td className="whitespace-nowrap py-1.5 pr-3">
                  {usd(l.ticket_usd).replace(".00", "")}
                  <span className="text-ink-dim"> on {usd(l.capital_usd).replace(".00", "")}</span>
                </td>
                <td className="px-2 text-right font-semibold text-ink">{usd(l.balance_usd)}</td>
                <td className={`px-2 text-right ${tone(l.pnl_usd)}`}>{usd(l.pnl_usd, true)}</td>
                <td className="px-2 text-right text-ink-3">{l.trades}</td>
                <td className={`px-2 text-right ${l.rugs ? "text-down" : "text-ink-3"}`}>{l.rugs}</td>
                <td className="pl-2 text-right text-ink-3">{usd(l.lowest_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
          {data.live_coins} real-time paper trades since the timer started, from the $10k paper
          book. Bigger sizes pay more pool impact, so profit does not grow in step with size.
        </p>
      </div>
    </Panel>
  );
}

/** Karthik, 2026-10-05: "10k pool should show open and closed trades too and
 *  daily profits and rugs same like karthik lab". */
export function TenKBookPanel({ book, now }: { book: TenKBook; now: number }) {
  const t = usd(book.ticket_usd).replace(".00", "");
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          $10k+ book · {t} on {usd(book.capital_usd).replace(".00", "")} · balance{" "}
          <span className="tabular-nums">{usd(book.balance_usd)}</span>
        </PanelTitle>
      </PanelHeader>
      <div className="space-y-4 p-3" data-testid="pool-ten-k-book">
        {book.days.length ? <Days days={book.days} /> : null}
        <div className="overflow-x-auto">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Open now · {book.open.length}
          </div>
          {book.open.length === 0 ? (
            <p className="text-[12px] text-ink-dim">Nothing held right now. Each trade sells after three minutes.</p>
          ) : (
            <table className="w-full text-[13px]" data-testid="pool-open">
              <tbody>
                {book.open.map((o) => (
                  <tr key={o.mint} className="border-t border-line/60">
                    <td className="py-1.5 pr-3 tabular-nums">{formatElapsed(now - new Date(o.opened_at).getTime())} ago</td>
                    <td className="py-1.5 pr-3 font-medium">
                      <a href={`https://dexscreener.com/solana/${o.mint}`} target="_blank" rel="noreferrer"
                         className="text-accent underline-offset-2 hover:underline">
                        {o.symbol || `${o.mint.slice(0, 6)}…`} <span aria-hidden>↗</span>
                      </a>
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums text-ink-dim">{usd(o.pool_usd)}</td>
                    <td className={`py-1.5 text-right tabular-nums ${o.pct_now == null ? "text-ink-dim" : tone(o.pct_now)}`}>
                      {o.pct_now == null ? "—" : `${Number(o.pct_now) >= 0 ? "+" : ""}${Number(o.pct_now).toFixed(2)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <details className="overflow-x-auto">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Closed · {book.closed.length} · {book.closed.filter((c) => c.rugged).length} rugs
          </summary>
          <table className="mt-1 w-full text-[13px]" data-testid="pool-closed">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className="py-1 pr-3 text-left font-normal">bought</th>
                <th className="py-1 pr-3 text-left font-normal">coin</th>
                <th className="py-1 pr-3 text-right font-normal">pool</th>
                <th className="py-1 pr-3 text-right font-normal">result</th>
                <th className="py-1 text-right font-normal">money</th>
              </tr>
            </thead>
            <tbody>
              {book.closed.map((c) => <Row key={`${c.mint}-${c.opened_at}`} trade={c} real={false} />)}
            </tbody>
          </table>
        </details>
      </div>
    </Panel>
  );
}

const k = (n: number) => `$${Math.round(n / 1000)}k`;

/** The $10k book's rules in plain words (Karthik, 2026-10-06: "write rule book
 *  in 10k lab"). Every number is the API's, so the words follow the book. */
export function TenKRuleBook({ book }: { book: TenKBook }) {
  const r = book.rules;
  if (!r) return null;
  const trades = book.closed.length;
  const rugs = book.closed.filter((c) => c.rugged).length;
  const [lo, hi] = r.skip_pool_usd;
  const rules: [string, string][] = [
    ["What it buys", "New pump.fun coins right after they “graduate” — finish their launch and open a real trading pool."],
    ["Small pools too", `The pool must hold ${k(r.floor_usd)} or more.`],
    ["Skips the middle", `No pools between ${k(lo)} and ${k(hi)}: they lost money in both halves of this book's first day, and Karthik's Lab's ${k(lo)}–${k(hi)} book lost almost all its money.`],
    ["Only quiet pools", `Fewer than ${r.quiet_max_txs} trades in the pool so far when it buys. A busy start is skipped.`],
    ["Only fresh coins", `It buys within ${r.max_entry_age_s / 60} minutes of the coin graduating, or not at all.`],
    ["No repeat creators", "Coins whose creator has launched a coin before are left out: on this book they lost money. (The $50k books buy them again.)"],
    ["Several at once", `${usd(book.ticket_usd)} per trade from a ${usd(book.capital_usd)} balance. It buys every coin that passes while a whole ${usd(book.ticket_usd)} is free.`],
    ["Always sells", `Exactly ${r.hold_minutes} minutes after buying. No price targets, no stop-loss — the clock decides.`],
    ["The risk", `Tiny pools rug often: a rug loses almost the whole trade.${rugs ? ` So far ${rugs} in ${trades} trades.` : ""}`],
    ["Paper money", "A simulation on real pool prices, with the price impact and fees of each trade. No real wallet follows it."],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Rule book · $10k book</PanelTitle>
      </PanelHeader>
      <ul className="space-y-1.5 p-3 text-[13px] leading-relaxed" data-testid="pool-rule-book">
        {rules.map(([title, body]) => (
          <li key={title} className="flex gap-2">
            <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent" />
            <span>
              <b className="text-ink">{title}:</b> <span className="text-ink-dim">{body}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="px-3 pb-3 text-[11px] text-ink-dim">
        The timer starts at the book&apos;s first trade. The {r.hold_minutes}-minute sell and the{" "}
        {k(lo)}–{k(hi)} skip came later (5–6 Oct) and are applied from the first trade, like
        every rule here.
      </p>
    </Panel>
  );
}

function WalletTable({ book, testId }: { book: WalletBook; testId: string }) {
  return (
    <table className="w-full min-w-[34rem] text-[12px] tabular-nums" data-testid={testId}>
      <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
        <tr>
          <th className="py-1 pr-3 text-left font-normal">wallet</th>
          <th className="px-2 text-right font-normal">balance</th>
          <th className="px-2 text-right font-normal">profit</th>
          <th className="px-2 text-right font-normal">trades</th>
          <th className="px-2 text-right font-normal">rugs</th>
          <th className="pl-2 text-right font-normal">lowest</th>
        </tr>
      </thead>
      <tbody>
        {book.wallets.map((w) => (
          <tr key={w.name} className="border-t border-line/60">
            <td className="py-1.5 pr-3 font-medium text-ink-2">{w.name}</td>
            <td className="px-2 text-right font-semibold text-ink">{usd(w.balance_usd)}</td>
            <td className={`px-2 text-right ${tone(w.pnl_usd)}`}>{usd(w.pnl_usd, true)}</td>
            <td className="px-2 text-right text-ink-3">{w.trades}</td>
            <td className={`px-2 text-right ${w.rugs ? "text-down" : "text-ink-3"}`}>{w.rugs}</td>
            <td className="pl-2 text-right text-ink-3">{usd(w.lowest_usd)}</td>
          </tr>
        ))}
        <tr className="border-t-2 border-line font-semibold">
          <td className="py-1.5 pr-3 text-ink">Total</td>
          <td className="px-2 text-right text-ink">{usd(book.total_usd)}</td>
          <td className={`px-2 text-right ${tone(book.pnl_usd)}`}>{usd(book.pnl_usd, true)}</td>
          <td className="px-2 text-right text-ink-3">{book.trades}</td>
          <td colSpan={2} />
        </tr>
      </tbody>
    </table>
  );
}

/** $50k+ pools: ten user wallets at $50 on $500, backtest and live. */
export function FiftyKTables({ data }: { data: NonNullable<PoolLab["fifty_k"]> }) {
  const perCoin = Math.floor(data.coin_cap_usd / data.ticket_usd);
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          $50k+ pools · 10 user wallets · {usd(data.ticket_usd).replace(".00", "")} on{" "}
          {usd(data.start_usd).replace(".00", "")} each
        </PanelTitle>
      </PanelHeader>
      <div className="grid gap-4 p-3 lg:grid-cols-2">
        {([["Backtest since 1 Oct", data.backtest, "pool-fifty-back"],
           ["Live since the timer", data.live, "pool-fifty-live"]] as const).map(([title, book, id]) => (
          <div key={id} className="overflow-x-auto">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">{title}</span>
              <span className="text-[11px] text-ink-3">{book.coins} coins</span>
            </div>
            <WalletTable book={book} testId={id} />
            <p className="mt-1 text-[11px] text-ink-dim">
              Without the per-coin cap (all ten in every coin):{" "}
              <b className={tone(book.uncapped_pnl_usd)}>{usd(book.uncapped_pnl_usd, true)}</b>
              {" "}on {usd(book.uncapped_total_usd)}.
            </p>
          </div>
        ))}
      </div>
      <p className="px-3 pb-3 text-[11px] leading-relaxed text-ink-dim">
        The real way: wallets that buy the same coin buy one after another, so each pays the price
        the ones before it pushed up, and they sell the same way. The real wallets cap user wallets
        at {usd(data.coin_cap_usd).replace(".00", "")} a coin, so {perCoin} wallets share each coin
        and the longest-waiting go first. Coins and results are Karthik&apos;s Lab&apos;s real-time
        paper trades on $50k+ pools.
      </p>
    </Panel>
  );
}

/** What Layla reads out in the Pool Lab: the $10k book at $50 on $500. */
function layla(d: PoolLab) {
  const line = d.ten_k?.live.find((l) => l.ticket_usd === 50);
  if (!line) return {};
  return { lab: { started_at: d.started_at, capital_usd: String(line.capital_usd), pnl_usd: line.pnl_usd,
                  trades: line.trades, wins: line.wins ?? 0, rugs: line.rugs,
                  name: "The $10k paper book", since: "the timer" } };
}

export function PoolLabPage() {
  const q = useQuery({
    queryKey: ["pool-lab"],
    queryFn: () => api.get<PoolLab>("/labs/graduation/pool-lab"),
    // The worker rebuilds every minute; open trades last five.
    refetchInterval: (query) => (query.state.data?.computing ? 10_000 : 30_000),
  });
  const now = useNow();
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) {
    return <ErrorState title="Could not load the Pool Lab" body="The page could not reach the API." onRetry={() => void q.refetch()} />;
  }
  const d = q.data;
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Pool Lab</h1>
          <p className="text-sm text-ink-3">
            Paper only. Small pools at every size, and ten user wallets sharing the same coins.
          </p>
        </div>
        <div className="text-right" data-testid="pool-timer">
          <div className="text-lg font-semibold tabular-nums">
            {formatElapsed(now - new Date(d.started_at).getTime())}
          </div>
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">
            live since {day(d.started_at)} · backtest from {day(d.backtest_from)}
          </div>
        </div>
      </div>
      <CheckpointPool10k money={layla(d)} />
      {d.computing || !d.ten_k || !d.fifty_k ? (
        <p className="text-sm text-ink-3">Working out the backtest — about a minute after a restart.</p>
      ) : (
        <>
          {d.ten_k.book ? <TenKRuleBook book={d.ten_k.book} /> : null}
          {d.ten_k.book ? <TenKBookPanel book={d.ten_k.book} now={now} /> : null}
          <TenKTable data={d.ten_k} />
          <FiftyKTables data={d.fifty_k} />
        </>
      )}
    </div>
  );
}
