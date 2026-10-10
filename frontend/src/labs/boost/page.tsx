"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Days, formatElapsed, Row } from "@/labs/karthik/page";
import type { KarthikDay, KarthikTrade } from "@/labs/karthik/types";
import { api } from "@/lib/api-client";

/**
 * BOOST LAB (Karthik, 2026-10-10). Does paying DexScreener pay? Every coin a
 * graduation book bought that already had a paid DexScreener profile, or
 * boosts, when it was bought — any pool size — sold four minutes later.
 * Paper only; every figure is the API's.
 */

type BoostTrade = KarthikTrade & { rugged: boolean; profile: boolean; boosts: number | null; live: boolean };
interface MinuteLine {
  minutes: number;
  current: boolean;
  trades: number;
  pnl_usd: string;
  wins?: number;
  rugs: number;
  lowest_usd: string;
}
export interface BoostLab {
  computing?: boolean;
  started_at: string;
  backtest_from: string;
  boosts_since?: string;
  samples_since?: string;
  first_trade_at?: string | null;
  hold_minutes?: number;
  ticket_usd?: number;
  capital_usd?: number;
  balance_usd?: string;
  coins_seen?: number;
  coins_picked?: number;
  boosted_coins?: number;
  days?: KarthikDay[];
  closed?: BoostTrade[];
  minutes?: MinuteLine[];
}

function usd(value: string | number | null | undefined, signed = false): string {
  if (value == null) return "—";
  const n = Number(value);
  const body = `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return n < 0 ? `-${body}` : signed && n > 0 ? `+${body}` : body;
}
const tone = (v: string | number) => (Number(v) > 0 ? "text-up" : Number(v) < 0 ? "text-down" : "text-ink-3");
const dubai = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Dubai", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function BoostRuleBook({ d }: { d: BoostLab }) {
  const rules: [string, string][] = [
    ["What it buys", "Every new pump.fun coin our graduation books bought, at any pool size, that ALREADY had a paid DexScreener profile (logo, links) or active boosts at that moment."],
    ["Always sells", `${d.hold_minutes ?? 4} minutes after buying. No stop-loss, no price targets.`],
    ["Why 4 minutes", "On the first 28 such coins (8–10 Oct), 4 minutes made the most; past 5 minutes they fell apart, with a quarter rugged by 8–10 minutes. The table below re-prices the same coins at other sell times."],
    ["Money", `${usd(d.ticket_usd)} per trade from ${usd(d.capital_usd)}, several at once while the cash allows.`],
    ["How it knows", `It checks DexScreener for a paid profile or boosts before each buy. From ${d.samples_since ? dubai(d.samples_since) : "10 Oct"} Dubai it reads every coin as it graduates; before that it only saw about one coin in five, and boost counts only from ${d.boosts_since ? dubai(d.boosts_since) : "10 Oct"}.`],
    ["The catch", "It was chosen after looking at those 28 coins, and three of them carried the profit. This book is the test, not the proof."],
    ["Paper money", "The books' own buys, re-priced with the same fees and price impact. No real wallet follows it."],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Rule book · Boost Lab</PanelTitle>
      </PanelHeader>
      <ul className="space-y-1.5 p-3 text-[13px] leading-relaxed" data-testid="boost-rule-book">
        {rules.map(([title, body]) => (
          <li key={title} className="flex gap-2">
            <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent" />
            <span>
              <b className="text-ink">{title}:</b> <span className="text-ink-dim">{body}</span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function BoostBook({ d }: { d: BoostLab }) {
  const closed = d.closed ?? [];
  const pnl = Number(d.balance_usd ?? 0) - Number(d.capital_usd ?? 0);
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          Book · {usd(d.ticket_usd)} on {usd(d.capital_usd)} · balance{" "}
          <span className="tabular-nums">{usd(d.balance_usd)}</span>
        </PanelTitle>
      </PanelHeader>
      <div className="space-y-4 p-3" data-testid="boost-book">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Fig label="Profit" value={`${usd(pnl, true)}`} cls={tone(pnl)}
               hint={d.capital_usd ? `${pnl >= 0 ? "+" : ""}${((100 * pnl) / Number(d.capital_usd)).toFixed(0)}% on ${usd(d.capital_usd)}` : ""} />
          <Fig label="Trades" value={String(closed.length)} hint={`${closed.filter((c) => c.rugged).length} rugs`} />
          <Fig label="Coins picked" value={String(d.coins_picked ?? 0)} hint={`of ${d.coins_seen ?? 0} the books bought`} />
          <Fig label="Boosted coins" value={String(d.boosted_coins ?? 0)} hint="with boosts on record" />
        </div>
        {d.days?.length ? <Days days={d.days} trades={closed} real={false} /> : null}
        <details className="overflow-x-auto">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Closed · {closed.length} · {closed.filter((c) => c.rugged).length} rugs
          </summary>
          <table className="mt-1 w-full text-[13px]" data-testid="boost-closed">
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
              {closed.map((c) => <Row key={`${c.mint}-${c.opened_at}`} trade={c} real={false} />)}
            </tbody>
          </table>
        </details>
      </div>
    </Panel>
  );
}

function Fig({ label, value, hint, cls = "text-ink" }: { label: string; value: string; hint?: string; cls?: string }) {
  return (
    <div className="rounded-lg border border-line p-2">
      <div className="text-[10px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div className={`mt-0.5 text-base font-semibold tabular-nums ${cls}`}>{value}</div>
      {hint ? <div className="text-[11px] tabular-nums text-ink-dim">{hint}</div> : null}
    </div>
  );
}

export function MinuteTable({ lines, capital }: { lines: MinuteLine[]; capital?: number }) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>If it sold at another minute · same coins · {usd(capital)} each</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[28rem] text-[13px] tabular-nums" data-testid="boost-minutes">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">sell after</th>
              <th className="px-2 text-right font-normal">trades</th>
              <th className="px-2 text-right font-normal">rugs</th>
              <th className="px-2 text-right font-normal">profit</th>
              <th className="px-2 text-right font-normal">lowest</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.minutes} className={`border-t border-line/60 ${l.current ? "font-semibold" : ""}`}>
                <td className="py-1.5 pr-3">{l.minutes} min{l.current ? " · the book" : ""}</td>
                <td className="px-2 text-right">{l.trades}</td>
                <td className={`px-2 text-right ${l.rugs ? "text-down" : ""}`}>{l.rugs}</td>
                <td className={`px-2 text-right ${tone(l.pnl_usd)}`}>{usd(l.pnl_usd, true)}</td>
                <td className="px-2 text-right">{usd(l.lowest_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function BoostLabPage() {
  const q = useQuery({
    queryKey: ["boost-lab"],
    queryFn: () => api.get<BoostLab>("/labs/graduation/boost-lab"),
    // The worker rebuilds every five minutes.
    refetchInterval: (query) => (query.state.data?.computing ? 15_000 : 60_000),
  });
  const now = useNow();
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) {
    return <ErrorState title="Could not load the Boost Lab" body="The page could not reach the API." onRetry={() => void q.refetch()} />;
  }
  const d = q.data;
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Boost Lab</h1>
          <p className="text-sm text-ink-3">
            Paper only. Does paying DexScreener pay? Coins with a paid profile or boosts, sold at 4 minutes.
          </p>
        </div>
        <div className="text-right" data-testid="boost-timer">
          <div className="text-lg font-semibold tabular-nums">
            {now >= Date.parse(d.started_at) ? formatElapsed(now - Date.parse(d.started_at)) : "starts soon"}
          </div>
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">
            live since {dubai(d.started_at)} · looked back to {d.first_trade_at ? dubai(d.first_trade_at) : dubai(d.backtest_from)}
          </div>
        </div>
      </div>
      {d.computing ? (
        <p className="text-sm text-ink-3">Working it out — about five minutes after a restart.</p>
      ) : (
        <>
          <BoostRuleBook d={d} />
          <BoostBook d={d} />
          {d.minutes ? <MinuteTable lines={d.minutes} capital={d.capital_usd} /> : null}
        </>
      )}
    </div>
  );
}
