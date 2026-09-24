"use client";

import { useEffect, useState } from "react";

import { inr } from "@/labs/nse-tracker/format";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useKarthikBook } from "./hooks";
import type { KarthikDay, KarthikTrade } from "./types";

/**
 * KARTHIK'S LAB — ONE BOOK, PAPER ONLY.
 *
 * $500 on one rule, started when he asked for it and judged thirty days later.
 * It holds no wallet and has never placed an order; the real wallet is its own
 * page and its own switch.
 *
 * THREE FIGURES SIT BESIDE THE BALANCE, because the balance alone has misled
 * every reading of this lab so far:
 *
 *  - WITHOUT ITS BEST TRADE. The arm this copies made +$1,060, of which two
 *    coins were +429% and +527%; the other 177 trades made about $100 between
 *    them. A balance that is one coin is not a strategy, and the only way to
 *    see that on a page is to print the number with the coin removed.
 *  - LOWEST. A book that reached its balance by way of half its money is one
 *    nobody would still have been holding.
 *  - RUGS. On the copied arm all four landed on a single day. They cluster,
 *    and an average hides that.
 *
 * The JUDGE DATE is fixed in the backend and printed here rather than computed
 * from today, so it cannot quietly move to whenever the number looks best.
 *
 * RUPEES sit beside every dollar, because that is the currency Karthik reads
 * money in. The rate is a fixed constant rather than a live feed: it is there
 * to give the numbers a familiar size, and a book judged on whether it beat
 * its own starting balance cannot be changed by the rate used to print it.
 */

/**
 * Dollars to rupees. Checked against three sources on 23 Sep 2026, which
 * agreed within 0.1% (95.65 / 95.74 / 95.76).
 *
 * ponytail: a constant, not a live feed. A drifting rate would move every
 * number on the page for reasons that have nothing to do with the strategy;
 * swap in a fetched rate only if rupees ever become the currency a decision
 * is made in.
 */
const RUPEES_PER_DOLLAR = 95.7;

function rupees(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return inr(n * RUPEES_PER_DOLLAR, 0);
}

/**
 * How long the book has been running, ticking every second.
 *
 * It counts UP from the start rather than down to the judge date, because the
 * question this page answers is "how much has it seen so far" — thirty days is
 * the promise, but a balance is only worth reading against the time that made
 * it.
 */
export function formatElapsed(ms: number): string {
  if (ms < 0) return "not started yet";
  const s = Math.floor(ms / 1000);
  const days = Math.floor(s / 86_400);
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(Math.floor((s % 86_400) / 3600))}:${pad(
    Math.floor((s % 3600) / 60),
  )}:${pad(s % 60)}`;
  return days > 0 ? `${days}d ${clock}` : clock;
}

function useElapsed(startIso: string | undefined): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!startIso) return "—";
  return formatElapsed(now - new Date(startIso).getTime());
}

function usd(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** A figure as a percentage of the money the book started with. */
export function pctOfCapital(value: string | number | null | undefined,
                      capital: string | number): string {
  // Number(null) is 0, so a missing figure would otherwise print "+0.00%" --
  // "the book is exactly flat" -- which is a claim, not an absence.
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  const c = Number(capital);
  if (!Number.isFinite(n) || !Number.isFinite(c) || c === 0) return "—";
  return `${n >= 0 ? "+" : ""}${((100 * n) / c).toFixed(2)}%`;
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function Figure({
  label,
  value,
  sub,
  hint,
  tone,
}: {
  label: string;
  value: string;
  /** The same money in rupees, under the dollars rather than instead of them. */
  sub?: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="rounded-lg border border-line bg-ink/[0.02] p-3">
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</div>
      <div
        className={`mt-1 text-lg font-semibold tabular-nums ${
          tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""
        }`}
      >
        {value}
      </div>
      {sub ? (
        <div className="text-[13px] tabular-nums text-ink-dim">{sub}</div>
      ) : null}
      {hint ? <div className="mt-1 text-[12px] text-ink-dim">{hint}</div> : null}
    </div>
  );
}

/**
 * What each 24 hours made, as a strip across the top so it is the second thing
 * read after the balance and needs no scrolling on a phone.
 *
 * Newest on the left. The day in progress is marked, because a part-day's
 * percentage sitting unlabelled beside whole ones invites reading a quiet
 * morning as a bad day.
 */
function Days({ days }: { days: KarthikDay[] }) {
  if (days.length === 0) return null;
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {days.map((d) => {
        const pct = Number(d.pct);
        return (
          <div
            key={d.n}
            className={`min-w-[104px] shrink-0 rounded-lg border p-2 ${
              d.running ? "border-dashed border-line" : "border-line"
            } bg-ink/[0.02]`}
          >
            <div className="text-[10px] uppercase tracking-wider text-ink-dim">
              {d.running ? `Day ${d.n} · so far` : `Day ${d.n}`}
            </div>
            <div
              className={`mt-0.5 text-base font-semibold tabular-nums ${
                pct >= 0 ? "text-up" : "text-down"
              }`}
            >
              {pct >= 0 ? "+" : ""}
              {pct.toFixed(2)}%
            </div>
            <div className="text-[11px] tabular-nums text-ink-dim">
              {usd(d.pnl_usd)} · {d.trades} trades
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Row({ trade }: { trade: KarthikTrade }) {
  const pct = Number(trade.pct);
  return (
    <tr className="border-t border-line/60">
      <td className="py-1.5 pr-3 tabular-nums">
        {new Date(trade.opened_at).toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </td>
      <td className="py-1.5 pr-3 font-medium">{trade.symbol || "—"}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-ink-dim">
        {trade.pool_usd ? usd(trade.pool_usd) : "—"}
      </td>
      <td
        className={`py-1.5 pr-3 text-right tabular-nums ${
          pct >= 0 ? "text-up" : "text-down"
        }`}
      >
        {pct >= 0 ? "+" : ""}
        {pct.toFixed(2)}%
      </td>
      <td
        className={`py-1.5 text-right tabular-nums ${
          Number(trade.pnl_usd) >= 0 ? "text-up" : "text-down"
        }`}
      >
        {usd(trade.pnl_usd)}
        <div className="text-[11px] text-ink-dim">{rupees(trade.pnl_usd)}</div>
      </td>
    </tr>
  );
}

export function KarthikLabPage() {
  const { data, isLoading, isError, refetch } = useKarthikBook();
  // Before the early returns: a hook may not sit behind a condition, and the
  // loading and error branches below are exactly that.
  const elapsed = useElapsed(data?.started_at);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load Karthik's book"
        body="The book is a walk over the arm's own closed trades, so this failing means the page could not reach the API — not that the arm has stopped trading."
        onRetry={() => void refetch()}
      />
    );
  }

  const up = Number(data.pnl_usd) >= 0;
  const withoutBest = Number(data.without_best_usd);
  const days = Math.max(
    0,
    Math.ceil(
      (new Date(data.judge_at).getTime() - Date.now()) / 86_400_000,
    ),
  );

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-xl font-semibold">Karthik&apos;s Lab</h1>
          <div className="text-right">
            <div className="text-lg font-semibold tabular-nums">{elapsed}</div>
            <div className="text-[11px] uppercase tracking-wider text-ink-dim">
              running &middot; {days} days to judgement
            </div>
          </div>
        </div>
        <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-ink-dim">
          {usd(data.capital_usd)} ({rupees(data.capital_usd)}) at{" "}
          {usd(data.ticket_usd)} ({rupees(data.ticket_usd)}) a trade on one
          rule: <b>{data.rule}</b>. Started {day(data.started_at)},{" "}
          <b>judged {day(data.judge_at)}</b>. Paper only: this book holds no
          wallet and has never placed an order.
        </p>
      </div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">
          Every 24 hours · percent of the balance that day started with
        </div>
        <Days days={data.days} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Figure
          label="Balance"
          value={`${usd(data.balance_usd)}  ${pctOfCapital(data.pnl_usd, data.capital_usd)}`}
          tone={up ? "up" : "down"}
          sub={rupees(data.balance_usd)}
          hint={`${up ? "+" : ""}${usd(data.pnl_usd)} on ${usd(data.capital_usd)}`}
        />
        <Figure
          label="Without its best trade"
          value={`${usd(withoutBest)}  ${pctOfCapital(withoutBest, data.capital_usd)}`}
          tone={withoutBest >= 0 ? "up" : "down"}
          sub={rupees(withoutBest)}
          hint="the same book minus one coin"
        />
        <Figure
          label="Lowest it has been"
          value={`${usd(data.lowest_usd)}  ${pctOfCapital(
            Number(data.lowest_usd) - Number(data.capital_usd), data.capital_usd)}`}
          sub={rupees(data.lowest_usd)}
          hint="what holding it actually felt like"
        />
        <Figure
          label="Rugs"
          value={String(data.rugs)}
          hint={`of ${data.trades} trades · ${data.wins} wins`}
        />
      </div>

      <Panel>
        <PanelHeader>
          <PanelTitle>
            Every trade{" "}
            <span className="font-normal text-ink-dim">
              &middot; sells at {data.hold_minutes} minutes
              {data.skipped ? ` · ${data.skipped} skipped for want of cash` : ""}
            </span>
          </PanelTitle>
        </PanelHeader>
        {data.trades_list.length === 0 ? (
          <EmptyState
            title="No trades yet"
            body="The rule buys a graduation over $75k whose pool is still quiet. On the arm it copies that is about sixty a day, so the first one usually arrives within the hour."
          />
        ) : (
          <div className="overflow-x-auto p-3">
            <table className="w-full text-[13px]">
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
                {data.trades_list.map((trade) => (
                  <Row key={`${trade.symbol}-${trade.opened_at}`} trade={trade} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
        Read the second figure before the first. The arm this copies made
        +$1,060 over 179 trades — and two coins, up 429% and 527%, are almost
        all of it; the other 177 made about $100 between them, while four rugs
        all landed on one day. A balance that is one coin is a lottery ticket,
        not a strategy, and thirty days is long enough for that to show.
      </p>
    </div>
  );
}
