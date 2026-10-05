"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { formatElapsed } from "@/labs/karthik/page";
import { api } from "@/lib/api-client";

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
export interface PoolLab {
  computing?: boolean;
  started_at: string;
  backtest_from: string;
  computed_at?: string;
  ten_k?: { backtest: SizeLine[]; live: SizeLine[]; backtest_coins: number; live_coins: number };
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

/** $10k+ pools: each size on ten times its balance, backtest and live. */
export function TenKTable({ data }: { data: NonNullable<PoolLab["ten_k"]> }) {
  const live = new Map(data.live.map((l) => [l.ticket_usd, l]));
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>$10k+ pools · quiet rule · each size on 10× its balance</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto p-3" data-testid="pool-ten-k">
        <table className="w-full min-w-[40rem] text-[12px] tabular-nums">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">size</th>
              <th className="px-2 text-right font-normal">backtest · balance</th>
              <th className="px-2 text-right font-normal">profit</th>
              <th className="px-2 text-right font-normal">trades / rugs</th>
              <th className="px-2 text-right font-normal">lowest</th>
              <th className="px-2 text-right font-normal">live · balance</th>
              <th className="pl-2 text-right font-normal">profit</th>
            </tr>
          </thead>
          <tbody>
            {data.backtest.map((b) => {
              const l = live.get(b.ticket_usd);
              return (
                <tr key={b.ticket_usd} className="border-t border-line/60">
                  <td className="whitespace-nowrap py-1.5 pr-3">
                    {usd(b.ticket_usd).replace(".00", "")}
                    <span className="text-ink-dim"> on {usd(b.capital_usd).replace(".00", "")}</span>
                  </td>
                  <td className="px-2 text-right font-semibold text-ink">{usd(b.balance_usd)}</td>
                  <td className={`px-2 text-right ${tone(b.pnl_usd)}`}>{usd(b.pnl_usd, true)}</td>
                  <td className="px-2 text-right text-ink-3">{b.trades} / <span className={b.rugs ? "text-down" : ""}>{b.rugs}</span></td>
                  <td className="px-2 text-right text-ink-3">{usd(b.lowest_usd)}</td>
                  <td className="px-2 text-right font-semibold text-ink">{l ? usd(l.balance_usd) : "—"}</td>
                  <td className={`pl-2 text-right ${l ? tone(l.pnl_usd) : "text-ink-3"}`}>
                    {l ? usd(l.pnl_usd, true) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
          Backtest: {data.backtest_coins} coins since 1 Oct, rebuilt from the saved price readings
          (no $10k arm existed before), with every exit price confirmed by the next reading so a
          single bad print cannot count, and the real wallet&apos;s rug and repeat-creator blocks
          applied. Live: {data.live_coins} real-time paper trades since the timer started. Bigger
          sizes pay more pool impact, which is why profit does not grow in step with size.
        </p>
      </div>
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
        paper trades on $50k+ pools, without the coins the real wallets refuse.
      </p>
    </Panel>
  );
}

export function PoolLabPage() {
  const q = useQuery({
    queryKey: ["pool-lab"],
    queryFn: () => api.get<PoolLab>("/labs/graduation/pool-lab"),
    refetchInterval: (query) => (query.state.data?.computing ? 10_000 : 60_000),
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
      {d.computing || !d.ten_k || !d.fifty_k ? (
        <p className="text-sm text-ink-3">Working out the backtest — about a minute after a restart.</p>
      ) : (
        <>
          <TenKTable data={d.ten_k} />
          <FiftyKTables data={d.fifty_k} />
        </>
      )}
    </div>
  );
}
