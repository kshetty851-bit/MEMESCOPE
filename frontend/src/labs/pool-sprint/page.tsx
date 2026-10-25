"use client";

import { useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Figure, StartDates } from "@/labs/karthik/page";
import { WorldClocks } from "@/labs/karthik/world-clocks";

import { downloadPoolSprintCsv, usePoolSprintBook, usePoolSprintTrades } from "./hooks";
import type { SprintBook, SprintTrade } from "./types";

export const usd = (v: string | number) =>
  Number(v).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const signed = (v: string | number) => `${Number(v) >= 0 ? "+" : ""}${usd(v)}`;
const tone = (v: string | number) => (Number(v) >= 0 ? "text-up" : "text-down");
const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Dubai",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
const th = "px-2 py-1.5 text-right font-normal";
const td = "px-2 py-2 text-right";

export function SprintRules({ data }: { data: SprintBook }) {
  const rules = [
    [
      "What it buys",
      "Verified token/SOL pools only: the base mint must match the token and the quote mint must be wrapped SOL. The first recorded pool liquidity must be at least $10,000 and below $40,000. Non-SOL and unverified pools are excluded; no later pool is substituted. No name, crew, volume, quiet-pool or rugged-name filters.",
    ],
    [
      "Fresh + 65% buys",
      "The first recorded observation must be between 0 and 30 seconds after graduation. At that observation, buys must be at least 65% of buys plus sells in the last five minutes. These are transaction counts, not dollar volume. Missing graduation times, missing counts or zero transactions are refused. Later readings cannot qualify a refused token.",
    ],
    [
      "Trade size",
      `${usd(data.ticket_usd)} per token from ${usd(data.capital_usd)}. Several trades can overlap. Sale proceeds become available only when the simulated sale happens; an unaffordable entry is skipped.`,
    ],
    [
      "Sells",
      "Five minutes after entry, at the first positive same-pool DexScreener reading from minute 5 through minute 7. If none exists, use the first same-pool minute candle closing in that window. No target or stop-loss.",
    ],
    [
      "Pricing gaps",
      "An entry without a usable exit after seven minutes reserves its entire stake as a loss in the balance and daily boxes. It is labelled unpriced, not counted as an observed rug. A later backfill can revise it.",
    ],
    [
      "Profit basis",
      "Fixed USD, before fees and slippage. Entry prices are recorded quotes, not executable fills. Historical candle closes are estimates, not proof that a swap could fill at that price. Cost scenarios below replay their own cash limits.",
    ],
    [
      "Since day one",
      "Replayed from 1 October 2026, midnight Dubai. The strategy was chosen after these results were seen; historical profits are not an independent test.",
    ],
    [
      "Paper only",
      "This lab holds no wallet, submits no orders and changes no real-wallet settings.",
    ],
  ];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Rule book</PanelTitle>
      </PanelHeader>
      <ul className="space-y-1.5 text-[13px] leading-relaxed">
        {rules.map(([title, body]) => (
          <li key={title} className="flex gap-2">
            <span
              aria-hidden
              className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent"
            />
            <span>
              <b>{title}:</b> <span className="text-ink-dim">{body}</span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function SprintTradeRow({ trade: t }: { trade: SprintTrade }) {
  return (
    <tr className="border-t border-line/60">
      <td className="whitespace-nowrap py-1.5 pr-3">{when(t.opened_at)}</td>
      <td className="py-1.5 pr-3 font-medium">
        <a
          href={`https://dexscreener.com/solana/${t.pair ?? t.mint}`}
          target="_blank"
          rel="noreferrer"
          className="text-accent hover:underline"
          title={t.mint}
        >
          {t.symbol || `${t.mint.slice(0, 6)}…`} ↗
        </a>
        <span className="ml-1 text-[11px] text-ink-dim">/ SOL</span>
      </td>
      <td className={`${td} whitespace-nowrap text-[11px] text-ink-dim`}>
        {t.graduated_at && t.entry_buys != null && t.entry_sells != null ? (
          <>
            {Math.round((Date.parse(t.opened_at) - Date.parse(t.graduated_at)) / 1000)}s ·{" "}
            {t.entry_buys}/{t.entry_buys + t.entry_sells} buys
          </>
        ) : (
          "—"
        )}
      </td>
      <td className={td}>{usd(t.pool_usd)}</td>
      <td className={`${td} ${t.pct != null ? tone(t.pct) : "text-ink-dim"}`}>
        {t.pct == null
          ? "—"
          : `${Number(t.pct) >= 0 ? "+" : ""}${Number(t.pct).toFixed(2)}%`}
      </td>
      <td className={`${td} ${t.pnl_usd != null ? tone(t.pnl_usd) : "text-ink-dim"}`}>
        {t.pnl_usd == null ? "—" : usd(t.pnl_usd)}
      </td>
      <td className="py-1.5 pl-3 text-[11px] text-ink-dim">
        {t.status === "unpriced"
          ? "Unpriced · stake reserved"
          : t.status === "open"
            ? "Still open"
            : t.status === "cash_skipped"
              ? "Skipped · no free cash"
              : t.source === "geckoterminal_candle_close"
                ? "Minute candle close"
                : "DexScreener quote"}
        {t.rugged ? <span className="ml-1 text-down">· rug</span> : null}
      </td>
    </tr>
  );
}

function Trades({ day, onClear }: { day: string | null; onClear: () => void }) {
  const [status, setStatus] = useState("all");
  const [offset, setOffset] = useState(0);
  const [show, setShow] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(false);
  const q = usePoolSprintTrades(day, status, offset);
  const visible = Boolean(day) || show;
  return (
    <Panel>
      <PanelHeader>
        <div>
          <PanelTitle>{day ? `Trades settling ${day} · Dubai` : "Every trade"}</PanelTitle>
          <p className="mt-1 text-[12px] text-ink-dim">
            {q.data?.total.toLocaleString() ?? "…"} matching entries · 100 per page
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {day ? (
            <button
              className="text-xs text-accent"
              onClick={() => {
                onClear();
                setOffset(0);
              }}
            >
              All dates
            </button>
          ) : null}
          <button
            className="rounded-md border border-line px-2.5 py-1 text-xs"
            onClick={() => setShow(!show)}
            aria-expanded={visible}
          >
            {visible && !day ? "Hide ▴" : "Show ▾"}
          </button>
          <button
            className="rounded-md border border-line px-2.5 py-1 text-xs"
            disabled={downloading}
            onClick={() => {
              setDownloading(true);
              setDownloadError(false);
              void downloadPoolSprintCsv()
                .catch(() => setDownloadError(true))
                .finally(() => setDownloading(false));
            }}
          >
            {downloading ? "Downloading…" : "Download all CSV"}
          </button>
        </div>
      </PanelHeader>
      {downloadError ? (
        <p role="alert" className="mb-2 text-xs text-down">
          Download failed. Please try again.
        </p>
      ) : null}
      {visible ? (
        <>
          <label className="mb-3 flex items-center gap-2 text-xs text-ink-dim">
            Show
            <select
              aria-label="Trade status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
              className="rounded border border-line bg-canvas p-1 text-ink"
            >
              <option value="all">All entries</option>
              <option value="priced">Priced exits</option>
              <option value="rugs">Rugs</option>
              <option value="unpriced">Unpriced exits</option>
              <option value="open">Still open</option>
              <option value="cash_skipped">Cash skips</option>
            </select>
          </label>
          {q.isLoading ? (
            <p className="text-xs text-ink-dim">Loading trades…</p>
          ) : q.isError ? (
            <p role="alert" className="text-xs text-down">
              Could not load trades. <button onClick={() => void q.refetch()}>Retry</button>
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] text-[13px] tabular-nums">
                <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
                  <tr>
                    <th className="py-1 pr-3 text-left font-normal">Bought · Dubai</th>
                    <th className="py-1 pr-3 text-left font-normal">Coin</th>
                    <th className={th}>Entry check</th>
                    <th className={th}>Pool</th>
                    <th className={th}>Result</th>
                    <th className={th}>Money</th>
                    <th className="py-1 pl-3 text-left font-normal">Pricing</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data?.trades.map((t) => (
                    <SprintTradeRow key={t.mint} trade={t} />
                  ))}
                </tbody>
              </table>
              {q.data?.trades.length === 0 ? (
                <p className="py-3 text-xs text-ink-dim">No entries match this view.</p>
              ) : null}
            </div>
          )}
          <div className="mt-3 flex items-center justify-between text-xs text-ink-dim">
            <button
              className="rounded border border-line px-2 py-1 disabled:opacity-40"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 100))}
            >
              Previous
            </button>
            <span>
              {offset + 1}–{Math.min(offset + 100, q.data?.total ?? 0)} of{" "}
              {q.data?.total ?? 0}
            </span>
            <button
              className="rounded border border-line px-2 py-1 disabled:opacity-40"
              disabled={offset + 100 >= (q.data?.total ?? 0)}
              onClick={() => setOffset(offset + 100)}
            >
              Next
            </button>
          </div>
        </>
      ) : null}
    </Panel>
  );
}

export function PoolSprintContent({ data: d }: { data: SprintBook }) {
  const [day, setDay] = useState<string | null>(null);
  return (
    <div className="min-w-0 space-y-4">
      <div className="min-w-0 [&_.wclock_svg]:h-20 [&_.wclock_svg]:w-20 [&_.wclock_.text-2xl]:text-xl sm:[&_.wclock_svg]:h-28 sm:[&_.wclock_svg]:w-28 sm:[&_.wclock_.text-2xl]:text-2xl">
        <WorldClocks />
      </div>
      <div className="grid gap-3 min-[1150px]:grid-cols-[minmax(0,1fr)_auto]">
        <div>
          <h1 className="text-xl font-semibold">Pool Sprint Lab</h1>
          <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-ink-dim">
            {usd(d.capital_usd)} at {usd(d.ticket_usd)} a trade · verified SOL pairs ·
            $10k–$40k pools · first seen within 30 seconds · at least 65% buy transactions ·
            sell after 5 minutes. Replayed from{" "}
            <b className="text-ink">1 October 2026, midnight Dubai</b>. Paper only.
          </p>
          <p className="mt-2 text-[12px] text-ink-dim">
            SOL-only replay: {(d.excluded_non_sol ?? 0).toLocaleString()} non-SOL or
            mismatched pools excluded; {(d.unverified_pools ?? 0).toLocaleString()} pools
            awaiting identity verification. All boxes and tables use the corrected rule.{" "}
            {(d.excluded_entry_rule ?? 0).toLocaleString()} verified SOL pools did not pass
            the Fresh + 65% entry rule.
          </p>
          <p className="mt-2 rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-[13px] text-ink-2">
            Recorded-price paper replay, not executed profit. This rule was selected after
            comparing historical results. Its delayed-entry research test lost money; fees,
            slippage and stale quotes can erase the apparent profit.
          </p>
          {Number(d.free_cash_usd) < Number(d.ticket_usd) && d.open === 0 ? (
            <p className="mt-2 rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-[13px] text-ink">
              The account cannot fund another {usd(d.ticket_usd)} entry: only{" "}
              {usd(d.free_cash_usd)} remains. Later days can show zero profit because trades
              were skipped for insufficient cash, not because their prices were flat.
            </p>
          ) : null}
          <p className="mt-2 max-w-[78ch] rounded-lg border border-accent/40 bg-accent/[0.06] px-3 py-2 text-[13px] leading-relaxed text-ink-2">
            <b>Before costs, in fixed dollars.</b> Every balance, daily box and table uses
            its own funded replay. Unpriced exits reserve the full stake:{" "}
            {usd(d.pricing_reserve_usd)} across {d.unpriced} entries. Priced-trade profit is{" "}
            {signed(d.priced_pnl_usd)}; profit after that reserve is {signed(d.pnl_usd)}.
          </p>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold tabular-nums text-accent">
            {d.signals.toLocaleString()}
          </div>
          <div className="text-[11px] uppercase tracking-wider text-ink-dim">
            Eligible tokens seen
          </div>
          <div className="mt-2 text-xs text-ink-dim">
            {d.dex_exits.toLocaleString()} quote exits · {d.candle_exits.toLocaleString()}{" "}
            candle exits
          </div>
          <div className="mt-1 text-xs text-ink-dim">
            Readings through {when(d.as_of)} Dubai
          </div>
          <div className="mt-1 text-xs text-ink-dim">
            {d.refresh_error
              ? "Refresh failed · showing last successful reading"
              : d.refreshing
                ? "Checking recorded readings…"
                : "Refreshes every 30 seconds"}
          </div>
          {!d.live_read_as_of ? (
            <div className="mt-1 text-xs text-warn">
              Historical snapshot · waiting for live refresh
            </div>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Figure
          label="Balance · after pricing reserve"
          value={usd(d.balance_usd)}
          tone={Number(d.pnl_usd) >= 0 ? "up" : "down"}
          hint={`${signed(d.pnl_usd)} on ${usd(d.capital_usd)} · before costs`}
        />
        <Figure
          label="Lowest settled balance"
          value={usd(d.lowest_usd)}
          hint="Open trades held at cost; unpriced overdue trades at zero"
        />
        <Figure
          label="Rugs · priced exits"
          value={d.rugs.toLocaleString()}
          hint={`of ${d.closed.toLocaleString()} priced exits · ${d.wins.toLocaleString()} wins`}
        />
        <Figure
          label="Free cash now"
          value={usd(d.free_cash_usd)}
          hint={`${usd(d.open_stake_usd)} committed to ${d.open} open entries`}
        />
        <Figure
          label="Lowest free cash"
          value={usd(d.lowest_cash_usd)}
          hint={`${d.max_concurrent} maximum overlapping entries`}
        />
        <Figure
          label="Skipped · insufficient cash"
          value={d.skipped.toLocaleString()}
          hint={`${d.trades.toLocaleString()} funded entries · ${d.unpriced} unpriced exits`}
        />
      </div>

      <SprintRules data={d} />

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-dim">
          Every Dubai day · profit after pricing reserves · click to see entries
        </div>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2">
          {d.days.map((row) => (
            <button
              key={row.date}
              aria-pressed={day === row.date}
              onClick={() => setDay(day === row.date ? null : row.date)}
              className={`rounded-lg border bg-ink/[0.02] p-2 text-left hover:border-accent/60 ${day === row.date ? "border-accent ring-1 ring-accent" : row.running ? "border-dashed border-line" : "border-line"}`}
            >
              <div className="text-[10px] uppercase tracking-wider text-ink-dim">
                Day {row.n}
                {row.running ? " · so far" : ""}
              </div>
              <div
                className={`mt-0.5 text-base font-semibold tabular-nums ${tone(row.pnl_usd)}`}
              >
                {signed(row.pnl_usd)}
              </div>
              <div className="text-[11px] text-ink-dim">
                {row.priced} exits ·{" "}
                <span className={row.rugs ? "text-down" : ""}>{row.rugs} rugs</span>
              </div>
              {row.unpriced ? (
                <div className="text-[10px] text-warn">
                  {row.unpriced} unpriced reserves
                </div>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <Trades key={day ?? "all-dates"} day={day} onClear={() => setDay(null)} />

      <Panel>
        <PanelHeader>
          <PanelTitle>Day by day · the funded {usd(d.capital_usd)} book</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-[13px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className="py-1 text-left font-normal">Dubai date</th>
                {[
                  "Bought",
                  "Priced exits",
                  "Unpriced",
                  "Rugs",
                  "Cash skips",
                  "Profit",
                  "Balance",
                ].map((h) => (
                  <th className={th} key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.days.map((r) => (
                <tr key={r.date} className="border-t border-line/60">
                  <td className="py-2">
                    <button
                      className="text-accent hover:underline"
                      onClick={() => setDay(r.date)}
                    >
                      {r.date}
                      {r.running ? " · so far" : ""}
                    </button>
                  </td>
                  <td className={td}>{r.opened}</td>
                  <td className={td}>{r.priced}</td>
                  <td className={td}>{r.unpriced}</td>
                  <td className={`${td} text-down`}>{r.rugs}</td>
                  <td className={td}>{r.skipped}</td>
                  <td className={`${td} ${tone(r.pnl_usd)}`}>{signed(r.pnl_usd)}</td>
                  <td className={td}>{usd(r.balance_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <StartDates
        book="Pool Sprint"
        lines={d.start_dates}
        capital={Number(d.capital_usd)}
        ticket={Number(d.ticket_usd)}
      />

      <Panel>
        <PanelHeader>
          <PanelTitle>
            Trading costs · each scenario starts with {usd(d.capital_usd)} at{" "}
            {usd(d.ticket_usd)} per trade
          </PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[38rem] text-[13px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                {[
                  "Cost per round trip",
                  "Balance",
                  "Profit",
                  "Funded",
                  "Cash skips",
                  "Rugs",
                  "Lowest",
                ].map((h) => (
                  <th className={th} key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.costs.map((r) => (
                <tr key={r.cost_usd} className="border-t border-line/60">
                  <td className={td}>{usd(r.cost_usd)}</td>
                  <td className={td}>{usd(r.balance_usd)}</td>
                  <td className={`${td} ${tone(r.pnl_usd)}`}>{signed(r.pnl_usd)}</td>
                  <td className={td}>{r.trades.toLocaleString()}</td>
                  <td className={td}>{r.skipped.toLocaleString()}</td>
                  <td className={td}>{r.rugs}</td>
                  <td className={td}>{usd(r.lowest_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-ink-dim">
          Illustrative total costs, charged once at entry. Each row reinvests its own
          proceeds and skips unaffordable trades; results are not simply costs subtracted
          from an unlimited account.
        </p>
      </Panel>

      <Panel>
        <PanelHeader>
          <PanelTitle>
            If each trade had been · same {usd(d.capital_usd)} starting money
          </PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-[13px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                <th className={th}>Stake</th>
                {["$10k–$40k · this book", "$20k–$40k", "$30k–$40k"].map((h) => (
                  <th className={th} key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.sizes.map((r) => (
                <tr
                  key={r.ticket_usd}
                  className={`border-t border-line/60 ${Number(r.ticket_usd) === 50 ? "bg-accent/10 font-semibold" : ""}`}
                >
                  <td className={td}>{usd(r.ticket_usd)}</td>
                  {r.cells.map((c, i) => (
                    <td key={i} className={td}>
                      <div>{usd(c.balance_usd)}</div>
                      <div className={`text-xs ${tone(c.pnl_usd)}`}>
                        {signed(c.pnl_usd)}
                      </div>
                      <div className="text-[10px] font-normal text-ink-dim">
                        {c.trades} trades · {c.skipped} cash skips · {c.rugs} rugs
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-ink-dim">
          Independent funded replays, before costs. Unpriced stakes are reserved. Quote
          returns scale with the stake; price impact is not modelled. These historical
          comparisons are not tested entry rules.
        </p>
      </Panel>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Our funded trades · by entry pool size</PanelTitle>
          </PanelHeader>
          <table className="w-full text-[13px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                {["Pool", "Trades", "Rugs", "Profit / reserve"].map((h) => (
                  <th className={th} key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.bands.map((b) => (
                <tr key={b.low} className="border-t border-line/60">
                  <td className={td}>
                    ${b.low / 1000}k–${b.high / 1000}k
                  </td>
                  <td className={td}>{b.trades}</td>
                  <td className={td}>{b.rugs}</td>
                  <td className={`${td} ${tone(b.pnl_usd)}`}>{signed(b.pnl_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel>
          <PanelHeader>
            <PanelTitle>1–10 independent paper accounts</PanelTitle>
          </PanelHeader>
          <table className="w-full text-[13px] tabular-nums">
            <thead className="text-[11px] uppercase tracking-wider text-ink-dim">
              <tr>
                {["Accounts", "Starting money", "Combined balance", "Combined P/L"].map(
                  (h) => (
                    <th className={th} key={h}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                <tr key={n} className="border-t border-line/60">
                  <td className={td}>{n}</td>
                  <td className={td}>{usd(n * Number(d.capital_usd))}</td>
                  <td className={td}>{usd(n * Number(d.balance_usd))}</td>
                  <td className={`${td} ${tone(d.pnl_usd)}`}>
                    {signed(n * Number(d.pnl_usd))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-ink-dim">
            Copies of the same paper replay, not real wallets. Assumes identical quotes and
            no extra market impact. Each account keeps its own {usd(d.capital_usd)} cash
            limit.
          </p>
        </Panel>
      </div>
      <p className="text-[11px] leading-relaxed text-ink-dim">
        Historical estimates, not executed returns. Before fees and slippage; unpriced
        reserves may change after backfills. This is not financial advice.
      </p>
    </div>
  );
}

export function PoolSprintPage() {
  const q = usePoolSprintBook();
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data)
    return (
      <ErrorState
        title="Could not load Pool Sprint Lab"
        body="The paper replay could not reach the API. No real wallet is connected to this lab."
        onRetry={() => void q.refetch()}
      />
    );
  return <PoolSprintContent data={q.data} />;
}
