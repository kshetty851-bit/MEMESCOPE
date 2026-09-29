"use client";

import { useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useKarthikBook } from "./hooks";
import type { KarthikBook, KarthikDay, KarthikFlows, KarthikTrade, KarthikWhatIfLine } from "./types";

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
 * DOLLARS ONLY (Karthik, 2026-09-27): the rupee line under every figure was
 * removed at his request.
 */

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
  /** A second line under the value, when a figure has one. */
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
/**
 * Day 30, roughly (Karthik, 2026-09-27). The book trades a fixed $50 ticket,
 * so it grows by dollars a day rather than compounding: today's balance plus
 * the average finished day's profit for every day left to the judge date,
 * and the same at the worst finished day's pace. A guide, not a promise — it
 * rests on the few days there have been.
 */
export function day30(days: KarthikDay[], judgeAt: string, now = Date.now()) {
  const done = days.filter((d) => !d.running);
  if (done.length === 0 || days.length === 0) return null;
  const pnl = done.map((d) => Number(d.pnl_usd));
  const avg = pnl.reduce((a, b) => a + b, 0) / pnl.length;
  const worst = Math.min(...pnl);
  const balance = Number(days[0]!.balance_usd); // newest first, running day included
  const left = Math.max(0, (Date.parse(judgeAt) - now) / 86_400_000);
  return { expected: balance + avg * left, worstPace: balance + worst * left, avg, basedOn: done.length };
}

function Days({ days, judgeAt }: { days: KarthikDay[]; judgeAt: string }) {
  if (days.length === 0) return null;
  const guess = day30(days, judgeAt);
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {guess ? (
        <div
          className="min-w-[132px] shrink-0 rounded-lg border border-dashed border-accent/60 bg-accent/[0.06] p-2"
          data-testid="day-30"
          title={`If every day left is like the average finished day so far (${usd(String(guess.avg))} a day, from ${guess.basedOn} days). At the worst finished day's pace it would be ${usd(String(guess.worstPace))}.`}
        >
          <div className="text-[10px] uppercase tracking-wider text-accent">Day 30 · expected</div>
          <div className="mt-0.5 text-base font-semibold tabular-nums text-ink">
            ≈ {usd(String(Math.round(guess.expected)))}
          </div>
          <div className="text-[11px] tabular-nums text-ink-dim">
            worst-day pace {usd(String(Math.round(guess.worstPace)))}
          </div>
        </div>
      ) : null}
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
      <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums">
        {new Date(trade.opened_at).toLocaleString("en-GB", {
          timeZone: "Asia/Dubai",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}
      </td>
      <td className="py-1.5 pr-3 font-medium">
        {trade.mint ? (
          // DexScreener's page for the token: its chart shows the price at the
          // minute the book bought and sold, so every row can be checked.
          <a
            href={`https://dexscreener.com/solana/${trade.mint}`}
            target="_blank"
            rel="noreferrer"
            className="text-accent underline-offset-2 hover:underline"
            title={`Verify ${trade.symbol || trade.mint} on DexScreener`}
          >
            {trade.symbol || `${trade.mint.slice(0, 6)}…`} <span aria-hidden>↗</span>
          </a>
        ) : (
          trade.symbol || "—"
        )}
      </td>
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
      </td>
    </tr>
  );
}

function bandLabel(lo: number, hi: number | null): string {
  const k = (n: number) => `$${Math.round(n / 1000)}k`;
  return hi == null ? `${k(lo)}+` : `${k(lo)}–${k(hi)}`;
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
 * IF EACH TRADE HAD BEEN (Karthik, 2026-09-27): every trade size down, every
 * pool floor across, one table in place of the side checks. Each cell is its
 * own book from the same start at that size, one trade at a time, on the
 * pools at or above that floor — the book's own walk, so skips, pool impact
 * at that size and the cash limit are the real book's.
 */
function SizeGrid({ data }: { data: KarthikBook }) {
  const w = data.whatif;
  // Hidden, not broken, while an older API (no `cells`) is still serving.
  if (!w?.floors?.length || !w.sizes?.every((row) => Array.isArray(row.cells))) return null;
  const k = (n: number) => `$${Math.round(n / 1000)}k+`;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>If each trade had been</PanelTitle>
      </PanelHeader>
      <div className="overflow-x-auto p-3">
        <table className="w-full min-w-[56rem] text-[12px] tabular-nums">
          <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="py-1 pr-3 text-left font-normal">size</th>
              {w.floors.map((f) => (
                <th
                  key={f.floor_usd}
                  className={`py-1 px-2 text-right font-normal ${f.book ? "rounded-t-md bg-accent/10 text-accent" : ""}`}
                >
                  {k(f.floor_usd)}
                  {f.replayed_below ? "*" : ""}
                  {f.book ? <div className="text-[10px] normal-case tracking-normal">this book</div> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {w.sizes.map((s) => (
              <tr key={s.ticket_usd} className={`border-t border-line/60 ${s.current ? "font-semibold" : ""}`}>
                <td className="whitespace-nowrap py-1.5 pr-3">
                  {usd(s.ticket_usd).replace(".00", "")}
                  <span className="font-normal text-ink-dim"> on {usd(s.capital_usd).replace(".00", "")}</span>
                  {s.current ? <span className="ml-1 text-[10px] font-normal text-accent">now</span> : null}
                </td>
                {s.cells.map((c, i) => (
                  <td
                    key={w.floors[i]!.floor_usd}
                    className={`whitespace-nowrap py-1.5 px-2 text-right ${w.floors[i]!.book ? "bg-accent/10" : ""}`}
                    title={`${c.trades} trades · ${c.rugs} rugs · lowest ${usd(c.lowest_usd)}`}
                  >
                    <Signed line={c} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] leading-relaxed text-ink-dim">
          Each cell is its own book from {day(data.started_at)} at that size, one trade at a
          time, buying only pools at or above that floor. Hover a cell for its trades, rugs
          and lowest balance. A look back, not a test.
        </p>
      </div>
    </Panel>
  );
}

/**
 * THE RULE BOOK (Karthik, 2026-09-27): the book's rules in plain words, for
 * anyone reading the page. Every number comes from the API, so the words
 * cannot drift from what the book actually does.
 */
export function RuleBook({ data }: { data: KarthikBook }) {
  const pool = data.pools_usd?.[0];
  const top = data.pools_usd?.[1];
  const ageMin = data.max_entry_age_s ? data.max_entry_age_s / 60 : null;
  const rugEvery = data.rugs > 0 ? Math.round(data.trades / data.rugs) : null;
  const rules: [string, string][] = [
    ["What it buys", "New pump.fun coins right after they “graduate” — finish their launch and open a real trading pool. About 1,000 do that every day."],
    ...(pool ? [["Only big pools", top ? `The pool must hold between ${usd(pool).replace(".00", "")} and ${usd(top).replace(".00", "")}.` : `The pool must hold ${usd(pool).replace(".00", "")} or more.`] as [string, string]] : []),
    ...(data.quiet_max_txs ? [["Only quiet pools", `Fewer than ${data.quiet_max_txs} trades in the pool so far when it buys. A busy start is skipped.`] as [string, string]] : []),
    ...(ageMin ? [["Only fresh coins", `It buys within ${ageMin} minutes of the coin graduating, or not at all. A late buy sits in the danger zone when creators sell.`] as [string, string]] : []),
    ["One at a time", "While it holds a coin, the next one is skipped. It can never be caught in two bad coins at once."],
    ["Trade size", `${usd(data.ticket_usd)} per trade, from a ${usd(data.capital_usd)} balance.`],
    ["Always sells", `Exactly ${data.hold_minutes} minutes after buying. No price targets, no stop-loss — the clock decides.`],
    ["The risk", `If a coin's creator drains the pool (a “rug”), that trade loses almost all of it.${rugEvery ? ` So far about 1 in ${rugEvery} trades.` : ""}`],
    ["Paper money", "A simulation on real market prices. The real wallet follows the same rules on its own."],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Rule book</PanelTitle>
      </PanelHeader>
      <ul className="space-y-1.5 p-3 text-[13px] leading-relaxed">
        {rules.map(([title, body]) => (
          <li key={title} className="flex gap-2">
            <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent" />
            <span>
              <b className="text-ink">{title}:</b> <span className="text-ink-dim">{body}</span>
            </span>
          </li>
        ))}
      </ul>
      {data.max_entry_age_since ? (
        <p className="px-3 pb-3 text-[11px] text-ink-dim">
          The fresh-coin rule was added on {day(data.max_entry_age_since)} and replayed from the
          first day, like every other rule here.
        </p>
      ) : null}
    </Panel>
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

/** Top right: every graduation seen since the book opened, bought or not
    (Karthik, 2026-09-27). Refreshes with the book, once a minute. */
export function GraduationsSeen({ count, rugs }: {
  count: number | undefined;
  rugs?: KarthikBook["graduations_rugged"];
}) {
  if (count === undefined) return null;
  return (
    <div className="text-right" data-testid="graduations-seen">
      <div className="text-lg font-semibold tabular-nums text-accent">
        {count.toLocaleString("en-US")}
      </div>
      <div className="text-[11px] uppercase tracking-wider text-ink-dim">
        graduations seen &middot; taken or not
      </div>
      {rugs && rugs.measured > 0 ? (
        <div className="mt-0.5 text-[11px] text-ink-dim" data-testid="graduations-rugged">
          <span className="font-semibold tabular-nums text-down">
            {rugs.rugged.toLocaleString("en-US")}
          </span>{" "}
          rugged ({Math.round((100 * rugs.rugged) / rugs.measured)}%) &middot; fell 80%+ in
          their first hour, of {rugs.measured.toLocaleString("en-US")} checked
        </div>
      ) : null}
    </div>
  );
}

function money(value: string): string {
  return `$${Math.round(Number(value)).toLocaleString("en-US")}`;
}

/** Under the pool box: who put money into the coins the book bought, from
    graduation to the book's sell, read on-chain (Karthik, 2026-09-27). */
export function MoneyIn({ flows }: { flows: KarthikFlows | undefined }) {
  if (!flows || flows.measured === 0) return null;
  const rows: [string, string, string, string][] = [
    ["Owners & related wallets", flows.insider_buy_usd, flows.insider_sell_usd, "text-warn"],
    ["Other traders", flows.other_buy_usd, flows.other_sell_usd, "text-ink"],
  ];
  return (
    <div
      className="ml-auto mt-2 w-fit max-w-[19rem] rounded-md border border-line bg-canvas/85 px-3 py-2 text-[11px] backdrop-blur-sm"
      data-testid="money-in"
    >
      <div className="uppercase tracking-wider text-ink-dim">Money in our coins</div>
      <table className="mt-1 tabular-nums">
        <thead>
          <tr className="text-ink-dim">
            <th />
            <th className="px-2 text-right font-normal">bought</th>
            <th className="text-right font-normal">sold</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([who, bought, sold, tone]) => (
            <tr key={who}>
              <td className={`pr-2 ${tone}`}>{who}</td>
              <td className="px-2 text-right font-medium text-ink">{money(bought)}</td>
              <td className="text-right text-ink-2">{money(sold)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1 leading-snug text-ink-dim">
        {flows.other_buyers.toLocaleString("en-US")} other buyers.
        {flows.insider_bought_trades !== undefined
          ? ` Owners bought in ${flows.insider_bought_trades} and sold in ${flows.insider_sold_trades} of ${flows.measured} trades — mostly one big buy at graduation that makes the pool deep.`
          : ` Owners sold in ${flows.insider_sold_trades} of ${flows.measured} trades.`}{" "}
        Graduation to our sell, on-chain{flows.measured < flows.trades ? ` · ${flows.measured} of ${flows.trades} trades read so far` : ""}.
      </div>
    </div>
  );
}

/** Pool floors, as the grid below uses them: each counts every trade at or above it. */
const POOL_FLOORS = [75_000, 100_000, 150_000, 200_000];

/** Under the count: how many of the book's trades each pool floor took, and
    what they made (Karthik, 2026-09-27: "75k+, 100k+ like this", not bands).
    From the trade list, so it moves with it. */
export function PoolTrades({ trades }: { trades: KarthikTrade[] }) {
  const rows = POOL_FLOORS.map((floor) => {
    const above = trades.filter((t) => t.pool_usd !== null && Number(t.pool_usd) >= floor);
    return {
      label: `$${floor / 1000}k+`,
      trades: above.length,
      pnl: above.reduce((sum, t) => sum + Number(t.pnl_usd), 0),
    };
  }).filter((r) => r.trades > 0);
  if (!rows.length) return null;
  return (
    <div
      className="ml-auto mt-2 w-fit rounded-md border border-line bg-canvas/85 px-3 py-2 text-[11px] backdrop-blur-sm"
      data-testid="pool-trades"
    >
      <div className="uppercase tracking-wider text-ink-dim">Trades by pool size</div>
      <table className="mt-1 tabular-nums">
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="pr-4 text-ink-2">{r.label}</td>
              <td className="pr-3 text-right font-medium text-ink">{r.trades}</td>
              <td className={`text-right ${r.pnl < 0 ? "text-down" : "text-up"}`}>
                {r.pnl < 0 ? "-" : "+"}${Math.abs(r.pnl).toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
    <div className="min-w-0 space-y-4">
      {/* Two columns from 1150px: the counts and their boxes on the right, and
          the header grows to fit them rather than lying over the rule book. */}
      <div className="grid gap-x-8 gap-y-2 min-[1150px]:grid-cols-[minmax(0,1fr)_auto]">
        <h1 className="text-xl font-semibold min-[1150px]:col-start-1 min-[1150px]:row-start-1">
          Karthik&apos;s Lab
        </h1>
        <div className="min-[1150px]:col-start-2 min-[1150px]:row-span-2 min-[1150px]:row-start-1">
          <div className="flex items-baseline justify-end gap-6">
            <GraduationsSeen count={data.graduations_seen} rugs={data.graduations_rugged} />
            <div className="text-right">
              <div className="text-lg font-semibold tabular-nums">{elapsed}</div>
              <div className="text-[11px] uppercase tracking-wider text-ink-dim">
                running &middot; {days} days to judgement
              </div>
            </div>
          </div>
          <PoolTrades trades={data.trades_list} />
          <MoneyIn flows={data.flows} />
        </div>
        <div className="min-[1150px]:col-start-1 min-[1150px]:row-start-2">
        <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-ink-dim">
          {usd(data.capital_usd)} at {usd(data.ticket_usd)} a trade on one
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
            chosen on {day(data.pools_since)} and replayed from day 1, so every figure
            here is a look back until then. The table below shows every other floor.
          </p>
        ) : null}
        {data.one_at_a_time_since ? (
          <p className="mt-1 max-w-[78ch] text-[12px] leading-relaxed text-ink-dim">
            <b className="text-ink-2">One trade at a time:</b> it buys only when nothing is
            held, and lets a signal go while a trade is open. Chosen on{" "}
            {day(data.one_at_a_time_since)} and replayed from day 1, so every figure here
            and in the table below follows this rule; only trades from{" "}
            {day(data.one_at_a_time_since)} on test it.
          </p>
        ) : null}
        </div>
      </div>

      <RuleBook data={data} />

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">
          Every 24 hours · percent of the balance that day started with
        </div>
        <Days days={data.days} judgeAt={data.judge_at} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Figure
          label="Balance"
          value={`${usd(data.balance_usd)}  ${pctOfCapital(data.pnl_usd, data.capital_usd)}`}
          tone={up ? "up" : "down"}
          hint={`${up ? "+" : ""}${usd(data.pnl_usd)} on ${usd(data.capital_usd)}`}
        />
        <Figure
          label="Lowest it has been"
          value={`${usd(data.lowest_usd)}  ${pctOfCapital(
            Number(data.lowest_usd) - Number(data.capital_usd), data.capital_usd)}`}
          hint="what holding it actually felt like"
        />
        <Figure
          label="Rugs"
          value={String(data.rugs)}
          hint={`of ${data.trades} trades · ${data.wins} wins`}
        />
      </div>


      <SizeGrid data={data} />

      <TradeList data={data} />
    </div>
  );
}
