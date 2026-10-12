"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Days, formatElapsed, McapHeads, Row } from "@/labs/karthik/page";
import type { KarthikDay, KarthikTrade } from "@/labs/karthik/types";
import { api } from "@/lib/api-client";

/**
 * BUSY POOL LAB (Karthik, 2026-10-12: "set up the busy pool as a separate lab
 * starting today with 200$ and 20$ per trade"). The pools the $10k book
 * refuses as busy, bought on paper by the same rules. Every figure is the API's.
 */

type BusyTrade = KarthikTrade & { rugged: boolean };
export interface BusyLab {
  computing?: boolean;
  started_at: string;
  first_trade_at?: string | null;
  ticket_usd?: number;
  capital_usd?: number;
  hold_minutes?: number;
  stop_pct?: number;
  busy_min_txs?: number;
  balance_usd?: string;
  days?: KarthikDay[];
  closed?: BusyTrade[];
  open?: { symbol: string | null; mint: string; opened_at: string; pool_usd: string | null }[];
}

function usd(value: string | number | null | undefined, signed = false): string {
  if (value == null) return "—";
  const n = Number(value);
  const body = `$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return n < 0 ? `-${body}` : signed && n > 0 ? `+${body}` : body;
}
const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-3");
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

export function BusyRuleBook({ d }: { d: BusyLab }) {
  const rules: [string, string][] = [
    ["What it buys", `Only the new pump.fun coins the $10k book refuses as busy: their pool already had ${d.busy_min_txs ?? 100} or more trades when it would buy.`],
    ["Everything else the same", "Pool of $10k or more, no $25k–$50k pools, bought within 2 minutes of graduating."],
    ["Sells", `${d.hold_minutes ?? 3} minutes after buying, or ${d.stop_pct ?? 10}% below the price paid, whichever comes first.`],
    ["Money", `${usd(d.ticket_usd)} per trade from ${usd(d.capital_usd)}, several at once while the cash allows.`],
    ["Why", "The $10k book skipped 4,788 busy coins from 5 to 12 Oct with no record of how they did. This is that record."],
    ["Paper money", "Real pool prices with each trade's price impact and fees. No real wallet follows it."],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Rule book · Busy Pool Lab</PanelTitle>
      </PanelHeader>
      <ul className="space-y-1.5 p-3 text-[13px] leading-relaxed" data-testid="busy-rule-book">
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

export function BusyBook({ d, now }: { d: BusyLab; now: number }) {
  const closed = d.closed ?? [];
  const pnl = Number(d.balance_usd ?? 0) - Number(d.capital_usd ?? 0);
  const open = d.open ?? [];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          Book · {usd(d.ticket_usd)} on {usd(d.capital_usd)} · balance{" "}
          <span className="tabular-nums">{usd(d.balance_usd)}</span>
        </PanelTitle>
      </PanelHeader>
      <div className="space-y-4 p-3" data-testid="busy-book">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Fig label="Profit" value={usd(pnl, true)} cls={tone(pnl)}
               hint={d.capital_usd ? `${pnl >= 0 ? "+" : ""}${((100 * pnl) / Number(d.capital_usd)).toFixed(1)}% on ${usd(d.capital_usd)}` : ""} />
          <Fig label="Trades" value={String(closed.length)} hint={`${closed.filter((c) => c.rugged).length} rugs`} />
          <Fig label="Open now" value={String(open.length)} hint="each sells within 3 minutes" />
        </div>
        {d.days?.length ? <Days days={d.days} trades={closed} real={false} /> : (
          <p className="text-[13px] text-ink-dim">No trades yet. The first busy-pool coin shows here within a minute of being sold.</p>
        )}
        {open.length ? (
          <table className="w-full text-[13px]" data-testid="busy-open">
            <tbody>
              {open.map((o) => (
                <tr key={o.mint} className="border-t border-line/60">
                  <td className="py-1.5 pr-3 tabular-nums">{formatElapsed(now - new Date(o.opened_at).getTime())} ago</td>
                  <td className="py-1.5 pr-3 font-medium">{o.symbol || `${o.mint.slice(0, 6)}…`}</td>
                  <td className="py-1.5 text-right tabular-nums text-ink-dim">{usd(o.pool_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        <details className="overflow-x-auto">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Closed · {closed.length} · {closed.filter((c) => c.rugged).length} rugs
          </summary>
          <table className="mt-1 w-full text-[13px]" data-testid="busy-closed">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className="py-1 pr-3 text-left font-normal">bought</th>
                <th className="py-1 pr-3 text-left font-normal">coin</th>
                <th className="py-1 pr-3 text-right font-normal">pool</th>
                <McapHeads />
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

export function BusyLabPage() {
  const q = useQuery({
    queryKey: ["busy-lab"],
    queryFn: () => api.get<BusyLab>("/labs/graduation/busy-lab"),
    refetchInterval: (query) => (query.state.data?.computing ? 15_000 : 60_000),
  });
  const now = useNow();
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) {
    return <ErrorState title="Could not load the Busy Pool Lab" body="The page could not reach the API." onRetry={() => void q.refetch()} />;
  }
  const d = q.data;
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Busy Pool Lab</h1>
          <p className="text-sm text-ink-3">Paper only. The busy pools the $10k book refuses, bought by the same rules.</p>
        </div>
        <div className="text-right" data-testid="busy-timer">
          <div className="text-lg font-semibold tabular-nums">
            {now >= Date.parse(d.started_at) ? formatElapsed(now - Date.parse(d.started_at)) : "starts soon"}
          </div>
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">live since {dubai(d.started_at)} Dubai</div>
        </div>
      </div>
      {d.computing ? (
        <p className="text-sm text-ink-3">Working it out — about a minute after a restart.</p>
      ) : (
        <>
          <BusyRuleBook d={d} />
          <BusyBook d={d} now={now} />
        </>
      )}
    </div>
  );
}
