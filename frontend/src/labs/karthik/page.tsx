"use client";

import { useEffect, useState } from "react";

import { inr } from "@/labs/nse-tracker/format";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useKarthikBook } from "./hooks";
import type { KarthikBook, KarthikDay, KarthikTrade, KarthikWhatIfLine } from "./types";

/**
 * KARTHIK'S LAB — ONE BOOK, PAPER ONLY.
 *
 * His own money on one rule, started when he asked for it and judged thirty
 * days later. Resized on 24 Sep from $500 at $100 to $600 at $200, and on
 * 25 Sep to $400 at $200.
 * It holds no wallet and has never placed an order; the real wallet is its own
 * page and its own switch.
 *
 * TWO FIGURES SIT BESIDE THE BALANCE, because the balance alone has misled
 * every reading of this lab so far. (A third, the balance WITHOUT ITS BEST
 * TRADE, was removed on 2026-09-24 at Karthik's request.)
 *
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

function bandLabel(lo: number, hi: number | null): string {
  const k = (n: number) => `$${Math.round(n / 1000)}k`;
  return hi == null ? `${k(lo)}+` : `${k(lo)}–${k(hi)}`;
}

function replayedCount(bands: { book: boolean; replayed?: number }[]): number {
  return bands.filter((b) => !b.book).reduce((sum, b) => sum + (b.replayed ?? 0), 0);
}

function Signed({ line }: { line: KarthikWhatIfLine }) {
  const n = Number(line.pnl_usd);
  return (
    <span className={n >= 0 ? "text-up" : "text-down"}>
      {n >= 0 ? "+" : ""}
      {usd(line.pnl_usd)}{" "}
      <span className="text-[11px] opacity-80">
        ({Number(line.pnl_pct) >= 0 ? "+" : ""}
        {Number(line.pnl_pct).toFixed(1)}%)
      </span>
    </span>
  );
}

/**
 * THE SIDE PANEL: the same book on other terms, to check, never to trade.
 *
 * "Pools $150k+ only" was asked for after EVO (24 Sep): on the quiet rule's
 * record the $75k-$150k pools died 3 times in 41 trades, those above 2 in 223.
 * The trade-size table answers "what if I had used $10, $20...". Every line is
 * the book's own walk on the same capital and start, so skips, pool impact at
 * that size and the cash limit are the real book's.
 */
function WhatIf({ data }: { data: KarthikBook }) {
  const w = data.whatif;
  if (!w) return null;
  const deepUp = Number(w.deep.pnl_usd) >= 0;
  const old = data.every_trade;
  return (
    <aside className="space-y-4 lg:sticky lg:top-4">
      {old ? (
        <Panel>
          <PanelHeader>
            <PanelTitle>Check: every trade (the old rule)</PanelTitle>
          </PanelHeader>
          <div className="space-y-3 p-3">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-ink-dim">Balance</div>
              <div className={`text-xl font-semibold tabular-nums ${Number(old.pnl_usd) >= 0 ? "text-up" : "text-down"}`}>
                {usd(old.balance_usd)} {pctOfCapital(old.pnl_usd, data.capital_usd)}
              </div>
              <div className="text-[12px] tabular-nums text-ink-dim">{rupees(old.balance_usd)}</div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-[12px] tabular-nums">
              <div><div className="text-ink-dim">trades</div>{old.trades}</div>
              <div><div className="text-ink-dim">rugs</div>{old.rugs}</div>
              <div><div className="text-ink-dim">lowest</div>{usd(old.lowest_usd)}</div>
            </div>
            <p className="text-[12px] leading-relaxed text-ink-dim">
              The same start, buying every signal the cash allowed, as the book did
              before {day(data.one_at_a_time_since)}. Kept here so the change of rule
              stays visible.
            </p>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader>
          <PanelTitle>
            Check: pools {usd(w.floor_usd).replace(".00", "")}+ only
          </PanelTitle>
        </PanelHeader>
        <div className="space-y-3 p-3">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-ink-dim">Balance</div>
            <div className={`text-xl font-semibold tabular-nums ${deepUp ? "text-up" : "text-down"}`}>
              {usd(w.deep.balance_usd)} {pctOfCapital(w.deep.pnl_usd, data.capital_usd)}
            </div>
            <div className="text-[12px] tabular-nums text-ink-dim">{rupees(w.deep.balance_usd)}</div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[12px] tabular-nums">
            <div><div className="text-ink-dim">trades</div>{w.deep.trades}</div>
            <div><div className="text-ink-dim">rugs</div>{w.deep.rugs}</div>
            <div><div className="text-ink-dim">lowest</div>{usd(w.deep.lowest_usd)}</div>
          </div>
          <p className="text-[12px] leading-relaxed text-ink-dim">
            The same {usd(data.capital_usd)}, {usd(data.ticket_usd)} a trade and start
            date, buying only pools of {usd(w.floor_usd).replace(".00", "")} and up. A
            what-if to watch: the book on the left stays on its own rule. The floor was
            chosen after seeing EVO die at $146k, so only the days from now on test it.
          </p>
        </div>
      </Panel>

      {w.bands?.length ? (
        <Panel>
          <PanelHeader>
            <PanelTitle>Check: every pool size</PanelTitle>
          </PanelHeader>
          <div className="overflow-x-auto p-3">
            <table className="w-full text-[12px] tabular-nums">
              <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                <tr>
                  <th className="py-1 pr-2 text-left font-normal">pools</th>
                  <th className="py-1 pr-2 text-right font-normal">profit / loss</th>
                  <th className="py-1 pr-2 text-right font-normal">trades</th>
                  <th className="py-1 text-right font-normal">rugs</th>
                </tr>
              </thead>
              <tbody>
                {w.bands.map((b) => (
                  <tr key={b.lo_usd} className="border-t border-line/60">
                    <td className="py-1.5 pr-2">
                      {bandLabel(b.lo_usd, b.hi_usd)}
                      {b.book ? null : <span className="ml-1 text-[10px] text-ink-dim">*</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-right"><Signed line={b} /></td>
                    <td className="py-1.5 pr-2 text-right">{b.trades}</td>
                    <td className="py-1.5 text-right">{b.rugs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
              Each size is its own {usd(data.capital_usd)} book at {usd(data.ticket_usd)} a
              trade, one trade at a time, from the same start. $75k and up are this
              book&apos;s own trades cut by pool size. * The same rule on the pools this
              book skips: {replayedCount(w.bands)} of those trades were rebuilt from price
              snapshots (they read about a point a trade too kind), the rest were taken
              live. A look back, not a test.
            </p>
          </div>
        </Panel>
      ) : null}

      {w.floors ? (
        <Panel>
          <PanelHeader>
            <PanelTitle>Check: deeper pools</PanelTitle>
          </PanelHeader>
          <div className="overflow-x-auto p-3">
            <table className="w-full text-[12px] tabular-nums">
              <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                <tr>
                  <th className="py-1 pr-2 text-left font-normal">pools</th>
                  <th className="py-1 pr-2 text-right font-normal">balance</th>
                  <th className="py-1 pr-2 text-right font-normal">trades</th>
                  <th className="py-1 text-right font-normal">rugs</th>
                </tr>
              </thead>
              <tbody>
                {w.floors.map((f) => (
                  <tr key={f.floor_usd} className="border-t border-line/60">
                    <td className="py-1.5 pr-2">{usd(f.floor_usd).replace(".00", "")}+</td>
                    <td className="py-1.5 pr-2 text-right">
                      {usd(f.balance_usd)}{" "}
                      <span className={Number(f.pnl_usd) >= 0 ? "text-up" : "text-down"}>
                        {pctOfCapital(f.pnl_usd, data.capital_usd)}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right">{f.trades}</td>
                    <td className="py-1.5 text-right">{f.rugs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
              The same {usd(data.capital_usd)} at {usd(data.ticket_usd)} a trade, buying
              only pools at or above each line. Deeper pools rug less but move less, so
              wins shrink as the line rises. A look back, not a test.
            </p>
          </div>
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader>
          <PanelTitle>If each trade had been</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-3">
          <table className="w-full text-[12px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className="py-1 pr-2 text-left font-normal">size</th>
                <th className="py-1 pr-2 text-right font-normal">this book</th>
                <th className="py-1 text-right font-normal">
                  $75k+ pools
                </th>
              </tr>
            </thead>
            <tbody>
              {w.sizes.map((s) => (
                <tr key={s.ticket_usd} className={`border-t border-line/60 ${s.current ? "font-semibold" : ""}`}>
                  <td className="py-1.5 pr-2">
                    {usd(s.ticket_usd).replace(".00", "")}
                    <span className="font-normal text-ink-dim">
                      {" "}on {usd(s.capital_usd).replace(".00", "")}
                    </span>
                    {s.current ? <span className="ml-1 text-[10px] font-normal text-ink-dim">now</span> : null}
                  </td>
                  <td className="py-1.5 pr-2 text-right"><Signed line={s.all} /></td>
                  <td className="py-1.5 text-right"><Signed line={s.wide} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
            Each size runs on its own balance from the same start, and its % is of
            that balance. A rug costs the whole trade at any size.
          </p>
        </div>
      </Panel>
    </aside>
  );
}

const TRADES_OPEN_KEY = "memescope.karthikTradesOpen";

/**
 * Every trade the book took, folded away by default (Karthik, 2026-09-25):
 * the list is long and grows all day, and the figures above answer most
 * visits. The header keeps the count, and the choice to keep it open is
 * remembered in this browser.
 */
export function TradeList({ data }: { data: KarthikBook }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try {
      setOpen(window.localStorage.getItem(TRADES_OPEN_KEY) === "open");
    } catch {
      // Folded by default.
    }
  }, []);
  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      window.localStorage.setItem(TRADES_OPEN_KEY, next ? "open" : "closed");
    } catch {
      // Kept for this visit only.
    }
  }

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          Every trade{" "}
          <span className="font-normal text-ink-dim">
            &middot; {data.trades_list.length} closed &middot; sells at {data.hold_minutes} minutes
            {data.busy_skipped ? ` · ${data.busy_skipped} let go while holding one` : ""}
            {data.skipped ? ` · ${data.skipped} skipped for want of cash` : ""}
          </span>
        </PanelTitle>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls="karthik-trade-list"
          className="ml-auto rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
        >
          {open ? "Hide ▴" : "Show ▾"}
        </button>
      </PanelHeader>
      {open ? (
        <div id="karthik-trade-list">
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
        </div>
      ) : null}
    </Panel>
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
  const days = Math.max(
    0,
    Math.ceil(
      (new Date(data.judge_at).getTime() - Date.now()) / 86_400_000,
    ),
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_21rem] lg:items-start">
    <div className="min-w-0 space-y-4">
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
        <p className="mt-1 max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
          Resized on {day(data.resized_at)} from {usd(data.previous_capital_usd)} at{" "}
          {usd(data.previous_ticket_usd)} a trade, after its first day had been
          seen, and replayed from the same start at the new size. That makes the
          first day a look back rather than a test: only what happens from{" "}
          {day(data.resized_at)} on is a fair measure of this size.
        </p>
        {data.pools_usd && data.pools_since ? (
          <p className="mt-1 max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
            <b className="text-ink-2">
              Pools {bandLabel(data.pools_usd[0], data.pools_usd[1])} only:
            </b>{" "}
            chosen on {day(data.pools_since)} from the pool-size splits of this
            book&apos;s own trades (no rugs, and never below its start) and replayed from
            day 1, so every figure here is a look back until then. The checks beside it
            still show every size.
          </p>
        ) : null}
        {data.one_at_a_time_since ? (
          <p className="mt-1 max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
            <b className="text-ink-2">One trade at a time:</b> it buys only when nothing is
            held, and lets a signal go while a trade is open. Chosen on{" "}
            {day(data.one_at_a_time_since)} and replayed from day 1, so every figure here
            and in the checks beside it follows this rule; only trades from{" "}
            {day(data.one_at_a_time_since)} on test it.
          </p>
        ) : null}
      </div>

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">
          Every 24 hours · percent of the balance that day started with
        </div>
        <Days days={data.days} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Figure
          label="Balance"
          value={`${usd(data.balance_usd)}  ${pctOfCapital(data.pnl_usd, data.capital_usd)}`}
          tone={up ? "up" : "down"}
          sub={rupees(data.balance_usd)}
          hint={`${up ? "+" : ""}${usd(data.pnl_usd)} on ${usd(data.capital_usd)}`}
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


      <TradeList data={data} />

    </div>
    <WhatIf data={data} />
    </div>
  );
}
