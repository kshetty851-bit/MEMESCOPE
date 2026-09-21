"use client";

import { Fragment, useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import {
  useFreshHeld,
  useFreshTrades,
  useGraduationStatus,
  useGraduationTournament,
  useGraduationTrades,
} from "./hooks";
import type {
  ArmRow,
  PaperPosition,
  SplitWallet,
} from "./types";

/**
 * GRADUATION LAB
 *
 * pump.fun tokens on their way up the bonding curve, and what happens in the
 * hour after they graduate. A STATUS BOARD, not a strategy: it reports what
 * the recorder has seen and ranks nothing.
 *
 * Every figure is computed on the backend. Nothing here applies a threshold —
 * a rule written in the page would be a second, unpublished rule competing
 * with the one the recorder followed.
 */

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-ink-dim">
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
    </div>
  );
}

function signed(value: string | null): string {
  if (value === null) return "—";
  const n = Number(value) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function usd(value: string | number | null): string {
  if (value === null) return "—";
  const n = Number(value);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function signedUsd(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value) >= 0 ? "+" : ""}${usd(value)}`;
}

/** A wallet figure as a return on the starting balance. */
function walletPct(value: string | number, start: string | number): string {
  const s = Number(start);
  if (!s) return "";
  const n = (Number(value) / s - 1) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}

const dexscreener = (mint: string) =>
  `https://dexscreener.com/solana/${mint}`;

/**
 * One trade. The mint is rendered in FULL and linked to the very feed the
 * marks come from, so every figure in the row can be checked against its
 * source rather than taken on trust.
 */
/** Minutes a closed position was held. */
function held(p: PaperPosition): number | null {
  if (!p.closed_at) return null;
  return Math.round(
    (new Date(p.closed_at).getTime() - new Date(p.opened_at).getTime()) / 60000,
  );
}

type SortKey = "closed_at" | "pnl_usd" | "net_return" | "held";

const SORTS: Record<SortKey, (p: PaperPosition) => number> = {
  closed_at: (p) => new Date(p.closed_at ?? p.opened_at).getTime(),
  pnl_usd: (p) => Number(p.pnl_usd ?? 0),
  net_return: (p) => Number(p.net_return ?? 0),
  held: (p) => held(p) ?? 0,
};

/** Why a trade was rebooked on 16 Sep, in the words the row's tooltip uses. */
const RESTATED: Record<string, string> = {
  fees: "Restated 16 Sep: same exit, re-charged at the pool's real fee tier plus Jupiter's 0.10%.",
  max_hold:
    "Restated 16 Sep: repriced on the first price recorded after the exit was due, instead of the newest one before it.",
  pool_collapsed:
    "Restated 16 Sep: the book had closed this on a price from before the pool was drained. Repriced on the first price after the exit was due, when the pool was already empty.",
  stale_exit:
    "Restated 16 Sep: no price was recorded after the exit was due, so the last one before it is used and flagged.",
};

/** Why a trade counts for nothing: the badge, and the sentence behind it. */
const EXCLUDED: Record<string, { label: string; title: string }> = {
  not_graduation_pool: {
    label: "not a graduation",
    title:
      "Bought as a graduation, but this token never graduated from pump.fun: its pool is not the one a pump.fun migration creates. Shown, counted nowhere.",
  },
  wallet_blocked: {
    label: "blocked — left out",
    title:
      "Your real wallet's safety checks would have refused this coin: the money behind it was on the block list, or behind a rug in the three hours before. So no book here counts it, as if it had never been bought.",
  },
  rugged: {
    label: "rugged — left out",
    title:
      "The pool was drained while this trade was open. Left out of every figure on request, as if the token had never been bought. No rule here could have avoided it in advance, so the figure shown is what it really lost.",
  },
};

/** Exit reasons a reader would otherwise have to decode. */
const EXIT_LABEL: Record<string, string> = {
  pool_collapsed: "pool drained",
  stale_exit: "no later price",
  drain_stop: "pool draining — sold",
  hard_stop: "stop",
};

/**
 * One trade. The mint is rendered in FULL and linked to the very feed the
 * marks come from, so every figure in the row can be checked against its
 * source rather than taken on trust.
 */
/** The wallet the reader picked on the board: one ticket, so many at a time. */
type WalletSize = { ticket: number; split: number };

/**
 * What this trade did for the chosen wallet.
 *
 * Blank rather than zero when the wallet never met the trade — older than the
 * week the walk covers, or left out of the board entirely — because a dash
 * says "not counted here" and $0.00 says "counted, made nothing".
 */
function SizeCell({ p }: { p: PaperPosition }) {
  if (p.size_funded === false) {
    return (
      <td className="py-2 pr-3 text-right text-ink-dim tabular-nums">
        <span title="Every slot was already in use when this trade appeared, so this wallet could not pay for it.">
          skipped
        </span>
      </td>
    );
  }
  if (p.size_pnl_usd === null || p.size_pnl_usd === undefined) {
    return <td className="py-2 pr-3 text-right text-ink-dim tabular-nums">—</td>;
  }
  const v = Number(p.size_pnl_usd);
  return (
    <td
      className={`py-2 pr-3 text-right font-medium tabular-nums ${
        v > 0 ? "text-up" : v < 0 ? "text-down" : ""
      }`}
    >
      {signedUsd(p.size_pnl_usd)}
    </td>
  );
}

function TradeRow({
  p,
  closed,
  size,
  since = null,
}: {
  p: PaperPosition;
  closed: boolean;
  size?: WalletSize | null;
  since?: string | null;
}) {
  const pnl = p.pnl_usd === null ? null : Number(p.pnl_usd);
  const tone = p.voided
    ? "text-ink-dim"
    : pnl === null
      ? ""
      : pnl > 0
        ? "text-up"
        : pnl < 0
          ? "text-down"
          : "";
  const minutes = held(p);
  return (
    <tr className={`border-t border-line align-top ${p.voided ? "opacity-60" : ""}`}>
      <td className="py-2 pr-3">
        <a
          href={dexscreener(p.mint)}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-accent"
        >
          <span className="font-medium">
            {p.name ?? p.symbol ?? "unnamed"}
            {p.name && p.symbol ? (
              <span className="ml-1 text-ink-dim">{p.symbol}</span>
            ) : null}
          </span>
          <span className="block break-all font-mono text-[10px] leading-tight text-ink-dim">
            {p.mint}
          </span>
        </a>
        {p.liq_open_usd ? (
          <span className="mt-0.5 block text-micro tabular-nums text-ink-dim">
            pool {usd(p.liq_open_usd)}
            {p.liq_close_usd && p.liq_close_usd !== p.liq_open_usd
              ? ` → ${usd(p.liq_close_usd)}`
              : ""}
            {p.impact_open
              ? ` · impact ${(Number(p.impact_open) * 100).toFixed(2)}%`
              : ""}
            {p.impact_close
              ? ` / ${(Number(p.impact_close) * 100).toFixed(2)}%`
              : ""}
          </span>
        ) : null}
      </td>
      {size ? <SizeCell p={p} /> : null}
      <td className="py-2 pr-3 text-right tabular-nums">
        {usd(p.notional_usd)}
      </td>
      <td className={`py-2 pr-3 text-right font-medium tabular-nums ${tone}`}>
        {p.voided ? (
          <span className="line-through">{signedUsd(p.pnl_usd)}</span>
        ) : (
          signedUsd(p.pnl_usd)
        )}
        {p.restated &&
        p.excluded !== "not_graduation_pool" &&
        p.was_pnl_usd !== p.pnl_usd ? (
          <span className="block text-micro font-normal text-ink-dim">
            was {signedUsd(p.was_pnl_usd)}
          </span>
        ) : null}
      </td>
      <td className={`py-2 pr-3 text-right tabular-nums ${tone}`}>
        {p.voided ? (
          <span className="line-through">{signed(p.net_return)}</span>
        ) : (
          signed(p.net_return)
        )}
        {p.restated &&
        p.excluded !== "not_graduation_pool" &&
        p.was_net_return !== p.net_return ? (
          <span className="block text-micro text-ink-dim">
            was {signed(p.was_net_return)}
          </span>
        ) : null}
      </td>
      <td className="py-2 text-right text-[11px] text-ink-dim">
        {p.voided ? (
          <span
            className="rounded-full bg-down/15 px-2 py-0.5 text-down"
            title={
              EXCLUDED[p.excluded ?? ""]?.title ??
              "The recorded price series for this token crossed pools, so this trade is not counted."
            }
          >
            {EXCLUDED[p.excluded ?? ""]?.label ?? "voided"}
          </span>
        ) : closed ? (
          <>
            {EXIT_LABEL[p.close_reason ?? ""] ?? p.close_reason}
            <span className="block">{minutes}m held</span>
            {p.closed_at ? (
              <span
                className="block tabular-nums"
                title={
                  since
                    ? `Closed ${new Date(p.closed_at).toLocaleString()} — ${runHour(
                        p.closed_at, since)} into this book's run`
                    : `Closed ${new Date(p.closed_at).toLocaleString()}`
                }
              >
                {new Date(p.closed_at).toLocaleTimeString("en-GB", {
                  hour: "2-digit", minute: "2-digit",
                })}
                {since ? ` · ${runHour(p.closed_at, since)}` : ""}
              </span>
            ) : null}
            {p.restated ? (
              <span
                className="mt-0.5 inline-block rounded-full bg-accent/15 px-2 py-0.5 text-accent"
                title={RESTATED[p.restated] ?? "Restated 16 Sep."}
              >
                restated
              </span>
            ) : null}
          </>
        ) : (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-accent">
            open
          </span>
        )}
      </td>
    </tr>
  );
}

/** A sortable column heading. Clicking the active one flips the direction. */
function SortHead({
  label,
  sortKey,
  sort,
  onSort,
  align = "right",
}: {
  label: string;
  sortKey?: SortKey;
  sort: { key: SortKey; desc: boolean } | null;
  onSort?: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort && sortKey && sort.key === sortKey;
  const base = `pb-2 pr-3 font-medium ${align === "right" ? "text-right" : "text-left"}`;
  if (!sortKey || !onSort) return <th className={base}>{label}</th>;
  return (
    <th
      className={base}
      aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`uppercase tracking-wider hover:text-ink ${
          active ? "text-ink" : ""
        }`}
      >
        {label}
        <span className="ml-1">{active ? (sort.desc ? "\u2193" : "\u2191") : ""}</span>
      </button>
    </th>
  );
}

function TradeTable({
  rows,
  closed,
  empty,
  sort = null,
  onSort,
  size = null,
  since = null,
}: {
  rows: PaperPosition[];
  closed: boolean;
  empty: string;
  sort?: { key: SortKey; desc: boolean } | null;
  onSort?: (key: SortKey) => void;
  size?: WalletSize | null;
  since?: string | null;
}) {
  if (!rows.length) return <p className="text-xs text-ink-dim">{empty}</p>;
  const ordered = sort
    ? [...rows].sort(
        (a, b) => (SORTS[sort.key](a) - SORTS[sort.key](b)) * (sort.desc ? -1 : 1),
      )
    : rows;
  // Voided trades are shown but never summed: their prices came from two
  // different pools, so the figure would be a number about nothing.
  const counted = ordered.filter((p) => !p.voided);
  const foreign = ordered.filter((p) => p.excluded === "not_graduation_pool").length;
  const rugged = ordered.filter((p) => p.excluded === "rugged").length;
  const blocked = ordered.filter((p) => p.excluded === "wallet_blocked").length;
  const voided = ordered.length - counted.length - foreign - rugged - blocked;
  const total = counted.reduce((a, p) => a + Number(p.pnl_usd ?? 0), 0);
  const deployed = counted.reduce((a, p) => a + Number(p.notional_usd), 0);
  // The wallet's own total, from the same walk that filled the rows: what it
  // funded, banked and skipped. Not a scaling of the $100 column — a wallet
  // that could not pay for a trade made nothing on it, not a tenth.
  const sized = rows.reduce((a, p) => a + Number(p.size_pnl_usd ?? 0), 0);
  const skipped = rows.filter((p) => p.size_funded === false).length;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
            <SortHead label="Token / mint" sort={sort} align="left" />
            {size ? (
              <SortHead label={`At $${size.ticket}×${size.split}`} sort={sort} />
            ) : null}
            <SortHead label="Size" sort={sort} />
            <SortHead
              label={closed ? "Realised P&L" : "Unrealised P&L"}
              sortKey="pnl_usd"
              sort={sort}
              onSort={onSort}
            />
            <SortHead
              label="Return"
              sortKey="net_return"
              sort={sort}
              onSort={onSort}
            />
            <SortHead
              label={closed ? "Exit" : "State"}
              sortKey={closed ? "closed_at" : undefined}
              sort={sort}
              onSort={onSort}
            />
          </tr>
        </thead>
        <tbody>
          {ordered.map((p: PaperPosition) => (
            <TradeRow key={p.mint} p={p} closed={closed} size={size} since={since} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-line text-[11px] text-ink-dim">
            <td className="pt-2 pr-3">
              {counted.length} counted
              {foreign ? `, ${foreign} not graduations` : ""}
              {rugged ? `, ${rugged} rugged left out` : ""}
              {blocked ? `, ${blocked} blocked by the wallet's checks` : ""}
              {voided ? `, ${voided} voided` : ""}
            </td>
            {size ? (
              <td
                className={`pt-2 pr-3 text-right font-medium tabular-nums ${
                  sized > 0 ? "text-up" : sized < 0 ? "text-down" : ""
                }`}
              >
                {signedUsd(String(sized))}
                <span className="block text-micro font-normal text-ink-dim">
                  {skipped ? `${skipped} unaffordable` : "every trade funded"}
                </span>
              </td>
            ) : null}
            <td className="pt-2 pr-3 text-right tabular-nums">
              {usd(String(deployed))}
              <span className="block text-micro text-ink-dim">
                deployed in total
              </span>
            </td>
            {/* This total is the BOOK: every trade a fresh $100, profits
                summed. It is not an account balance and must never be read as
                one — $210 here came from $8,600 of cumulative deployment
                across 86 separate bets, beside a wallet of $88.70. Both are
                right; they count different things. So the per-trade average
                sits under it, which is the only figure of the three that does
                not depend on how much money you had. */}
            <td
              className={`pt-2 pr-3 text-right font-medium tabular-nums ${
                total > 0 ? "text-up" : total < 0 ? "text-down" : ""
              }`}
            >
              {signedUsd(String(total))}
              <span className="block text-micro font-normal text-ink-dim">
                {counted.length
                  ? `${signed(String(total / (deployed || 1)))} a trade`
                  : "—"}
              </span>
            </td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/**
 * HOW FAR THEY GOT
 *
 * The peak multiple each graduated token reached from its pool open. Peaks,
 * not outcomes — reaching 5x is not earning 5x, it needs the top called to
 * the minute — so where they ENDED sits directly underneath, because that is
 * the number a reader will otherwise supply for themselves, wrongly.
 */

/**
 * How long ago the figures beside this were fetched.
 *
 * On the page rather than in a comment because "why is nothing moving" is a
 * question the reader cannot otherwise answer: React Query suspends polling
 * while a tab is hidden, so a page left open in the background is correct and
 * frozen at the same time, and there is no way to tell that from a page that
 * is broken. A clock that keeps counting says which one you are looking at.
 */
function Freshness({ at }: { at: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!at) return null;
  const secs = Math.max(0, Math.round((now - at) / 1000));
  const stale = secs > 90;
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-micro tabular-nums ${
        stale ? "text-warn" : "text-ink-dim"
      }`}
      title={new Date(at).toLocaleTimeString()}
    >
      <span
        className={`${stale ? "" : "grad-live-dot"} inline-block h-1.5 w-1.5 rounded-full ${
          stale ? "bg-warn" : "bg-up"
        }`}
      />
      {secs < 60 ? `updated ${secs}s ago` : `updated ${Math.round(secs / 60)}m ago`}
    </span>
  );
}


/**
 * THE FIFTY RULES
 *
 * Published in full because a leaderboard of opaque names is not evidence of
 * anything — a reader has to be able to check that the arm which won is a
 * strategy and not a coincidence, and that the ones which lost were given a
 * fair run. Both halves of every rule come from the `Arm` record itself, so
 * this cannot describe a strategy the tournament is not running.
 */
function RulesPanel() {
  const { data } = useGraduationTournament();
  const [open, setOpen] = useState(false);
  if (!data?.running || !data.arms.length) return null;
  // Strategies by name, then the baseline — the arm every other must beat.
  const byName = [...data.arms].sort(
    (a, b) => Number(a.is_control) - Number(b.is_control) || a.name.localeCompare(b.name),
  );
  const baselines = byName.filter((a) => a.is_control).length;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>The {data.arms.length} rules</PanelTitle>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
        >
          {open ? "Hide" : `Show all ${data.arms.length}`}
        </button>
      </PanelHeader>
      <div className="flex flex-col gap-4 p-4">
        <p className="max-w-[70ch] text-xs leading-relaxed text-ink-dim">
          Every arm buys at the pool open with{" "}
          {usd(data.notional_usd)}, up to ten at a time, and is refused
          entirely if the order would move the pool more than 10% — what a real
          wallet&rsquo;s slippage tolerance does. Fills are the exact
          constant-product price against the pool&rsquo;s recorded depth, on
          both legs. Arms differ in <b className="text-ink">two places only</b>:
          which graduations they accept, and when they leave.
        </p>

        {open ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] table-fixed text-sm">
              <colgroup>
                <col className="w-44" />
                <col />
                <col className="w-56" />
              </colgroup>
              <thead>
                <tr className="text-label uppercase tracking-[0.08em] text-ink-dim">
                  <th className="pb-2 pr-3 text-left font-medium">Arm</th>
                  <th className="pb-2 pr-3 text-left font-medium">Buys</th>
                  <th className="pb-2 text-left font-medium">Sells</th>
                </tr>
              </thead>
              <tbody>
                {byName.map((a: ArmRow) => (
                  <tr
                    key={a.name}
                    className={`border-t border-line align-top ${
                      a.is_control ? "text-ink-dim" : ""
                    }`}
                  >
                    <td className="py-2 pr-3 font-mono text-xs break-all">
                      {a.name}
                      {a.is_control ? (
                        <span className="ml-1 whitespace-nowrap font-sans text-micro uppercase tracking-[0.08em] text-down">
                          baseline
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 text-xs">{a.entry_rule}</td>
                    <td className="py-2 text-xs">{a.exit_rule}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex gap-6">
            <div className="flex flex-col">
              <span className="font-mono text-heading font-semibold text-ink">
                {byName.length - baselines}
              </span>
              <span className="text-micro text-ink-dim">strategies</span>
            </div>
            <div className="flex flex-col">
              <span className="font-mono text-heading font-semibold text-ink">
                {baselines}
              </span>
              <span className="text-micro text-ink-dim">baseline</span>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

/**
 * How long this run has been going.
 *
 * Separate from `Freshness`, which says how stale the figures are. This says
 * how much evidence exists behind them — the single thing that decides
 * whether any profit factor on the board means anything, and the thing a
 * reader cannot recover from the page otherwise because the tournament has
 * been reset when its rules changed.
 */
/** How far into a book's run a moment falls, in the timer's own terms. */
function runHour(at: string, since: string): string {
  const hours = (new Date(at).getTime() - new Date(since).getTime()) / 3_600_000;
  return hours < 1 ? `${Math.max(0, Math.round(hours * 60))}m in` : `h+${Math.floor(hours)}`;
}

function Elapsed({ since }: { since: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!since) return null;
  const secs = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    <span className="grad-figure font-mono" title={new Date(since).toLocaleString()}>
      {d ? `${d}d ` : ""}
      {pad(h)}:{pad(m)}:{pad(s)}
    </span>
  );
}

/**
 * The fresh $500 book's trades, open and closed. The closed ones carry what
 * the $500 wallet made on each, so they add up to the balance above them; a
 * trade it had no free money for says skipped.
 */
function FreshTrades({ book, size, since }:
  { book: string; size: WalletSize; since: string }) {
  const { data, isLoading } = useFreshTrades(book);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "closed_at",
    desc: true,
  });
  if (isLoading) {
    return <p className="text-xs text-ink-dim">Loading trades…</p>;
  }
  const closed = data?.closed_trades ?? [];
  const open = data?.open_trades ?? [];
  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h4 className="text-label uppercase tracking-[0.08em] text-ink-dim">
          Open — {open.length} · marked, nothing banked
        </h4>
        <TradeTable
          rows={open}
          closed={false}
          empty="Nothing open right now. Each trade is held for only a few minutes, so the book sits in cash between them."
        />
      </div>
      {/* Folded away by default: a book runs to hundreds of closed trades,
          and four of them on one page is a wall of rows between the reader
          and the next book's balance. The count stays visible either way. */}
      <details className="flex flex-col gap-1">
        <summary className="grad-row cursor-pointer list-none text-label uppercase tracking-[0.08em] text-ink-dim hover:text-ink">
          <span className="mr-1 inline-block transition-transform [[open]_&]:rotate-90">
            &#9656;
          </span>
          Closed — {closed.length} · click to {closed.length ? "open" : "check"}
        </summary>
        <div className="mt-1">
          <TradeTable
            rows={closed}
            closed
            size={size}
            since={since}
            sort={sort}
            onSort={(key) =>
              setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))
            }
            empty="nothing closed yet"
          />
        </div>
      </details>
    </div>
  );
}

/**
 * The fresh book's closed coins as if it had never sold: each one priced by
 * selling it into its pool NOW, read on-chain by the server. A drained pool
 * pays next to nothing, and its "pool now" column says why.
 */
export function FreshHeld({ book }: { book: string }) {
  const { data, isLoading, isError } = useFreshHeld(book);
  if (isLoading) {
    return <p className="text-xs text-ink-dim">Reading every coin&rsquo;s pool on-chain…</p>;
  }
  if (isError || !data || data.rows.length === 0) return null;
  const sold = Number(data.sold_usd);
  const heldNow = Number(data.held_usd);
  const diff = heldNow - sold;
  return (
    <div className="mt-3 flex flex-col gap-2">
      <h4 className="text-label uppercase tracking-[0.08em] text-ink-dim">
        If it had never sold — held until now
      </h4>
      <p className="max-w-[78ch] text-xs leading-relaxed text-ink-dim">
        Every closed coin, priced by selling it into its pool right now
        {data.read_at
          ? ` (read on-chain ${new Date(data.read_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} Dubai)`
          : ""}
        , after the pool&rsquo;s fee, the router&rsquo;s and the sale&rsquo;s own price move.{" "}
        <b className="text-ink">Sold: {usd(sold)}</b> ·{" "}
        <b className={diff >= 0 ? "text-up" : "text-down"}>
          Held: {usd(heldNow)} ({diff >= 0 ? "+" : ""}
          {usd(diff)})
        </b>
        . A {usd(data.capital_usd)} wallet that never sold could only have bought its first{" "}
        {data.wallet_trades} coins: {usd(data.wallet_held_usd)} now.
        {data.unreadable ? ` ${data.unreadable} pool(s) could not be read.` : ""}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-xs">
          <thead>
            <tr className="text-left text-ink-dim">
              <th className="pb-1 pr-3 font-medium">Coin</th>
              <th className="pb-1 pr-3 font-medium">Bought</th>
              <th className="pb-1 pr-3 text-right font-medium">Sold for</th>
              <th className="pb-1 pr-3 text-right font-medium">Held now</th>
              <th className="pb-1 pr-3 text-right font-medium">vs sold</th>
              <th className="pb-1 text-right font-medium">Pool now</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const s = r.sold_usd === null ? null : Number(r.sold_usd);
              const h = r.held_usd === null ? null : Number(r.held_usd);
              const d = s !== null && h !== null ? h - s : null;
              return (
                <tr key={r.mint} className="border-t border-line tabular-nums">
                  <td className="py-1 pr-3">
                    <a className="text-accent hover:underline" href={dexscreener(r.mint)}
                       target="_blank" rel="noreferrer">
                      {r.symbol ?? r.mint.slice(0, 6)}
                    </a>
                  </td>
                  <td className="py-1 pr-3 text-ink-dim">
                    {new Date(r.opened_at).toLocaleString("en-GB", {
                      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                    })}
                  </td>
                  <td className="py-1 pr-3 text-right">{usd(s)}</td>
                  <td className={`py-1 pr-3 text-right ${h === null ? "text-ink-dim" : ""}`}>
                    {h === null ? "unread" : usd(h)}
                  </td>
                  <td className={`py-1 pr-3 text-right ${d === null ? "" : d >= 0 ? "text-up" : "text-down"}`}>
                    {d === null ? "—" : `${d >= 0 ? "+" : ""}${usd(d)}`}
                  </td>
                  <td className="py-1 text-right text-ink-dim">
                    {r.depth_usd === null ? "—" : usd(r.depth_usd).replace(/\.00$/, "")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * One arm's own trades, fetched on expand.
 *
 * Its own component so the hook is called unconditionally — a hook inside the
 * leaderboard's map would change count as rows open and close. Mounting it is
 * what triggers the fetch, so a collapsed arm costs nothing.
 */
function ArmTrades({ name, size }: { name: string; size: WalletSize }) {
  const { data, isLoading } = useGraduationTrades(name, size);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "closed_at",
    desc: true,
  });
  if (isLoading) {
    return <p className="p-3 text-xs text-ink-dim">Loading trades…</p>;
  }
  const closed = data?.closed_trades ?? [];
  const open = data?.open_trades ?? [];
  return (
    <div className="flex flex-col gap-3 border-l-2 border-accent/40 bg-ink/[0.02] p-3">
      <p className="max-w-[70ch] text-micro text-ink-dim">
        Every trade this arm has made. The mint is in full and links to
        DexScreener — the same feed the marks came from — and each row carries
        the pool depth and the price impact its order caused, so a fill can be
        checked rather than taken on trust.
        <br />
        <span className="mt-1 block">
          <b className="text-ink">
            Two columns, two questions.
          </b>{" "}
          <b className="text-ink">
            At ${size.ticket}×{size.split}
          </b>{" "}
          is the wallet you picked above: ${size.ticket} a trade out of $
          {size.ticket * size.split}, so a trade it had no free money for says{" "}
          <i>skipped</i> and those dollars add up to the wallet figure on the
          row. <b className="text-ink">Size</b> and{" "}
          <b className="text-ink">P&amp;L</b> are the book itself, which always
          bets a fresh $100 — so a hundred-odd trades there can total more than
          any wallet ever held, because the money was deployed again and again.
          Both are correct; they count different things.
        </span>
      </p>
      {/* Rendered even when empty. An arm that holds for minutes is FLAT most
          of the time, and a section that disappears when the count is zero
          reads as a missing feature rather than an answer. */}
      <div className="flex flex-col gap-1">
        <h4 className="text-label uppercase tracking-[0.08em] text-ink-dim">
          Open — {open.length} · marked, nothing banked
        </h4>
        <TradeTable
          rows={open}
          closed={false}
          empty="Nothing open right now. This arm holds each position for only a few minutes, so it sits in cash between trades."
        />
      </div>
      <div className="flex flex-col gap-1">
        <h4 className="text-label uppercase tracking-[0.08em] text-ink-dim">
          Closed — {closed.length}
        </h4>
        <TradeTable
          rows={closed}
          closed
          size={size}
          sort={sort}
          onSort={(key) =>
            setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))
          }
          empty="nothing closed yet"
        />
      </div>
    </div>
  );
}

/**
 * THE LEADERBOARD
 *
 * Fifty arms, eight of which decide by hashing the mint and therefore cannot
 * have an edge. Their best result is the bar every real arm has to clear —
 * without it a leaderboard just reports who is on top, which fifty coin
 * flippers also produce.
 *
 * The leader is NOT given the big-number treatment the counts get: an arm name
 * is a dozen characters of monospace and rendering it at display size collides
 * with whatever sits beside it. Figures get the scale; names get the width.
 */
function LeaderboardPanel() {
  const { data, dataUpdatedAt, isFetching } = useGraduationTournament();
  const [showAll, setShowAll] = useState(false);
  // undefined = untouched, so the top arm shows its trades on arrival;
  // null = deliberately collapsed. Two states, because falling back to the
  // leader whenever the value is empty makes row one impossible to close.
  const [openArm, setOpenArm] = useState<string | null | undefined>(undefined);
  // Which wallet size is shown, as "<ticket>x<count>". $100 x 1 is the board
  // as judged; the rest split the $100 or trade a bigger wallet.
  const [size, setSize] = useState("100x1");
  if (!data?.running) return null;
  const band = data.control_band === null ? null : Number(data.control_band);
  const splits = data.arms.find((a) => a.splits?.length)?.splits ?? [];
  const keyOf = (s: SplitWallet) => `${Number(s.ticket_usd)}x${s.split}`;
  const official = size === "100x1";
  // Each arm's wallet at the chosen size, falling back to the $100 column
  // (the two are the same walk at $100 x 1).
  const at = (a: ArmRow) => a.splits?.find((x) => keyOf(x) === size);
  const walletOf = (a: ArmRow) => at(a)?.wallet_usd ?? a.wallet_funded_usd;
  const ranked =
    official
      ? data.arms
      : [...data.arms].sort(
          (x, y) =>
            Number(y.trades > 0) - Number(x.trades > 0) ||
            Number(walletOf(y)) - Number(walletOf(x)),
        );
  const top = official ? data.leader : (ranked[0]?.name ?? "");
  const chosen = splits.find((x) => keyOf(x) === size);
  const ticket = Number(chosen?.ticket_usd ?? data.wallet_demo_usd);
  const start = Number(chosen?.start_usd ?? data.wallet_demo_usd);
  const shown = showAll ? ranked : ranked.slice(0, 12);
  const expanded = openArm === undefined ? (ranked[0]?.name ?? null) : openArm;
  const lead = data.arms.find((a) => a.name === data.leader);
  const margin =
    lead && band !== null ? Number(lead.wallet_funded_usd) - band : null;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Strategy tournament — {data.arms.length} arms</PanelTitle>
        <span className="flex items-center gap-3">
          <span className="text-micro text-ink-dim">
            {/* Since the NEWEST arm started — the only window in which every
                arm has traded the same tokens, and so the only one in which
                comparing them means anything. */}
            all arms live <Elapsed since={data?.started_at ?? null} />
          </span>
          <span
            className={`transition-opacity ${isFetching ? "opacity-50" : "opacity-100"}`}
          >
            <Freshness at={dataUpdatedAt} />
          </span>
        </span>
      </PanelHeader>
      <div className="flex flex-col gap-5 p-4">
        {/* What these numbers are made of. Stated at the top rather than
            buried, because every figure below is a claim about money and a
            reader is owed the provenance before the result. Written to be
            exactly true: it says what IS real and names the one thing a real
            wallet must do that this book does not. */}
        <p className="max-w-[78ch] rounded-lg border border-line bg-ink/[0.02] p-3 text-xs leading-relaxed text-ink-dim">
          <b className="text-ink">Nothing here is invented.</b> Only pump.fun
          graduations count: a token bought on any pool but the one its
          pump.fun migration created is shown struck through and counted
          nowhere. Every entry is priced at the first price this platform
          recorded for the pool, and every exit at the{" "}
          <b className="text-ink">first price recorded after it was due</b> — a
          stop is due a few seconds after it fires, the time a wallet needs to
          act. A pool drained by then is priced by what is left in it, not by
          its quote. Every fill is charged what a real wallet pays: the exact
          constant-product move your own order makes against the pool&rsquo;s{" "}
          <b className="text-ink">recorded depth</b>, on both legs, plus
          PumpSwap&rsquo;s fee for that market cap (0.30% to 1.25%),
          Jupiter&rsquo;s 0.10% and the network fee — the{" "}
          <b className="text-ink">toll</b> column is that cost, taken out before
          any number you see. An order that would move a pool more than 10% is{" "}
          <b className="text-ink">refused, not filled</b>, because a real
          transaction past its slippage limit reverts.
          <br />
          <span className="mt-1 block">
            What a wallet must do that this book does not:{" "}
            <b className="text-ink">land the transaction, on time</b>. The book
            buys when a pool is first listed and sells the moment its exit is
            due; a real {usd(data.notional_usd)} wallet does both tens of
            seconds later, and on these tokens the price moves in that time.
          </span>
        </p>
        {/* The restatement, stated where the numbers are. Every figure below
            is AFTER it, and a reader who remembers yesterday's board is owed
            the reason it changed. */}
        {data.restated_trades > 0 ? (
          <p className="max-w-[78ch] rounded-lg border border-accent/40 bg-accent/[0.05] p-3 text-xs leading-relaxed text-ink-dim">
            <b className="text-ink">Restated 16 Sep.</b>{" "}
            {data.restated_trades} closed trades on this board were rebooked
            under the rules above, and every one shows what it said before.{" "}
            {data.restated_excluded} were never graduations and count for
            nothing. {data.restated_repriced} exits moved to the first price
            recorded after they were due.
            {data.restated_collapsed ? (
              <span className="mt-1 block">
                <b className="text-ink">
                  {data.restated_collapsed} trades on tokens whose pool was
                  drained while the trade was open are left out
                </b>
                , as if those tokens had never been bought. That is a what-if:
                nothing in these rules could have avoided them in advance, and
                they really lost{" "}
                {usd(Math.abs(Number(data.restated_rugged_usd)))}, which a real
                wallet would have lost too. Drains after 16 Sep are counted
                like any other trade.
              </span>
            ) : null}
          </p>
        ) : null}
        {data.restated_rule.startsWith("onchain") ? (
          <p className="max-w-[78ch] rounded-lg border border-accent/40 bg-accent/[0.05] p-3 text-xs leading-relaxed text-ink-dim">
            <b className="text-ink">Re-priced 18 Sep.</b> BASE_75k_5m had
            been buying at DexScreener&apos;s first report on each new pool,
            which can come before the pool&apos;s first big buy. Its closed
            trades are rebooked at the pool&apos;s own prices &mdash; the buy
            at its reserves when taken, the sale when it was due &mdash; and
            new trades are priced that way. Bluey (17 Sep) had been booked at
            +1,044%; its pool says +4%.
          </p>
        ) : null}
        {data.blocked_trades > 0 ? (
          <p className="max-w-[78ch] rounded-lg border border-accent/40 bg-accent/[0.05] p-3 text-xs leading-relaxed text-ink-dim">
            <b className="text-ink">Your wallet&apos;s checks, applied here.</b>{" "}
            No book trades a coin your real wallet would refuse: money on its
            block list, or behind a rug in the three hours before. Since those
            checks went live on 18 Sep,{" "}
            <b className="text-ink">
              {data.blocked_trades} closed trades they would have turned away
              are left out of every figure
            </b>
            ; together those trades made {usd(data.blocked_pnl_usd)}.
          </p>
        ) : null}
        {/* Karthik's fresh books: an arm restarted with its own money and the
            wallet's checks on every trade. The arm's own trades, so its row on
            the board below stays whole for comparison. */}
        {(data.fresh_books ?? []).map((fresh) => {
          const tickets = Math.round(
            Number(fresh.capital_usd) / Number(fresh.ticket_usd),
          );
          const up = Number(fresh.pnl_usd) >= 0;
          return (
            <div
              key={fresh.book}
              className="grad-row max-w-[78ch] rounded-lg border border-line bg-ink/[0.02] p-4"
            >
              <div className="text-[11px] uppercase tracking-wider text-ink-dim">
                Fresh book &middot; {fresh.book} &middot; sells at{" "}
                {fresh.hold_minutes}m &middot; from{" "}
                {new Date(fresh.started_at).toLocaleString("en-GB", {
                  day: "numeric", month: "short", hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                Dubai &middot; running <Elapsed since={fresh.started_at} />
              </div>
              <div className="mt-1 text-2xl font-semibold text-ink">
                {usd(fresh.balance_usd)}{" "}
                <span className={`text-base ${up ? "text-up" : "text-down"}`}>
                  {up ? "+" : ""}
                  {usd(fresh.pnl_usd)} ({up ? "+" : ""}
                  {fresh.return_pct}%)
                </span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-ink-dim">
                Rule: {fresh.rule}. Started with {usd(fresh.capital_usd)},{" "}
                {usd(fresh.ticket_usd)} a
                trade: up to {tickets} at once, fewer after losses, exactly as
                your real wallet funds them, with its safety checks on every
                trade the lab records an operator for.{" "}
                {fresh.trades} trades, {fresh.wins} wins, {fresh.rugs} rugs;{" "}
                {fresh.skipped} skipped for lack of free money. Lowest balance{" "}
                {usd(fresh.lowest_usd)}.
              </p>
              <FreshTrades
                book={fresh.book}
                since={fresh.started_at}
                size={{ ticket: Number(fresh.ticket_usd), split: tickets }}
              />
              <FreshHeld book={fresh.book} />
            </div>
          );
        })}
        {/* Verdict. The headline is the finding; the terms are underneath. */}
        <div
          className={`grad-row rounded-lg border p-4 ${
            data.called
              ? "border-up/50 bg-up/[0.04]"
              : "border-line bg-ink/[0.02]"
          }`}
        >
          <span className="inline-flex items-center gap-2 text-label uppercase tracking-[0.08em] text-ink-dim">
            <span
              className={`grad-live-dot inline-block h-1.5 w-1.5 rounded-full ${
                data.called ? "bg-up" : "bg-accent"
              }`}
            />
            {data.called ? "Winner called" : "Running — no winner yet"}
          </span>
          <p
            className="mt-2 max-w-[64ch] text-heading leading-snug text-ink"
            style={{ fontFamily: "var(--font-brand)" }}
          >
            {data.verdict}
          </p>
        </div>

        {/* Leader gets width, counts get scale. */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))]">
          <div className="grad-row flex flex-col gap-1 rounded-lg border border-line p-3">
            <span className="text-label uppercase tracking-[0.08em] text-ink-dim">
              Balance now
            </span>
            {/* THE BALANCE FIRST. What the account is worth right now is what a
                reader came for, so it takes the scale and the left-hand slot;
                the arm that earned it is the caption underneath. */}
            <span
              className={`grad-figure text-2xl font-semibold tabular-nums ${
                !lead
                  ? "text-ink"
                  : Number(lead.wallet_funded_usd) >= Number(data.wallet_demo_usd)
                    ? "text-up"
                    : "text-down"
              }`}
            >
              {lead ? usd(lead.wallet_funded_usd) : usd(data.wallet_demo_usd)}
            </span>
            <span className="truncate font-mono text-micro text-ink">
              {data.leader || "—"}
            </span>
            <span className="text-micro text-ink-dim">
              {lead ? (
                <>
                  <span
                    className={`grad-figure ${
                      Number(lead.wallet_funded_usd) >=
                      Number(data.wallet_demo_usd)
                        ? "text-up"
                        : "text-down"
                    }`}
                  >
                    {signedUsd(
                      String(
                        Number(lead.wallet_funded_usd) -
                          Number(data.wallet_demo_usd),
                      ),
                    )}{" "}
                    ({walletPct(lead.wallet_funded_usd, data.wallet_demo_usd)})
                  </span>{" "}
                  · {lead.trades_funded} of {lead.trades} funded
                  {margin !== null ? (
                    <>
                      {" · "}
                      <span className={margin > 0 ? "text-up" : "text-down"}>
                        {margin > 0 ? "+" : ""}
                        {usd(String(margin))} vs baseline
                      </span>
                    </>
                  ) : null}
                </>
              ) : (
                "nothing closed yet"
              )}
            </span>
          </div>
          <Stat
            label="Bar to clear"
            value={band === null ? "—" : usd(String(band))}
            note={`${data.best_control || "baseline"} · $100 wallet`}
          />
          <Stat
            label="Closed trades"
            value={data.total_trades.toLocaleString()}
            note={`across all ${data.arms.length} arms · ${Number(data.hours_running).toFixed(1)}h in`}
          />
          {/* TWO clocks, and they say different things — which is exactly why
              one of them was impossible to find in micro type under an arm
              name. This is the LEADER's own age, from its first trade. The
              header's "all arms live" runs from the NEWEST arm instead, so it
              reset to hours the moment the baseline was added yesterday while
              the leader had been running two days. A reader looking for "how
              long has this been going" was being shown the wrong one. */}
          <div className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-ink-dim">
              Leader running
            </span>
            <span className="text-2xl font-semibold tabular-nums">
              {lead?.first_trade_at ? (
                <Elapsed since={lead.first_trade_at} />
              ) : (
                "—"
              )}
            </span>
            <span className="text-xs text-ink-dim">
              {lead
                ? `since its first trade · all arms comparable for ${Number(
                    data.hours_running,
                  ).toFixed(1)}h`
                : "no trades yet"}
            </span>
          </div>
        </div>

        <p className="max-w-[68ch] text-xs leading-relaxed text-ink-dim">
          Every arm sees the same graduations, pays the same costs and uses the
          same clock; they differ only in which tokens they accept and when they
          leave.{" "}
          {data.arms.some((a) => a.is_control) ? (
            <>
              <b className="text-ink">
                {data.arms
                  .filter((a) => a.is_control)
                  .map((a) => a.name)
                  .join(", ")}{" "}
                is the baseline
              </b>{" "}
              (tagged below): it buys every graduation above its pool floor with
              no other rule, so it is the bar a real arm must clear.{" "}
            </>
          ) : null}
          To be called, an arm needs {data.min_trades}+ closed trades, no
          single token above{" "}
          {(Number(data.max_token_share) * 100).toFixed(0)}% of its profit, it
          must beat the baseline, and its profit factor must clear{" "}
          <b className="text-ink">
            {Number(data.required_profit_factor).toFixed(2)}
          </b>{" "}
          — the bar is not a round number but the 95th percentile of what the
          luckiest of 42 noise arms reaches at the leader&rsquo;s own trade
          count, so it falls as the sample grows. At 40 trades that is above
          20; at 250 it is about 2.3.
        </p>

        {splits.length > 1 ? (
          <div className="flex flex-col gap-2">
            <div
              className="flex flex-wrap items-center gap-1.5 text-xs"
              role="group"
              aria-label="Wallet size"
            >
              <span className="mr-1 text-ink-dim">Wallet size:</span>
              {splits.map((s) => (
                <button
                  key={keyOf(s)}
                  type="button"
                  onClick={() => setSize(keyOf(s))}
                  aria-pressed={size === keyOf(s)}
                  className={`rounded border px-2 py-1 tabular-nums transition-colors ${
                    size === keyOf(s)
                      ? "border-accent bg-accent/[0.08] text-accent"
                      : "border-line text-ink-dim hover:text-ink"
                  }`}
                >
                  ${Number(s.ticket_usd)}×{s.split}
                </button>
              ))}
            </div>
            <p className="max-w-[78ch] text-xs leading-relaxed text-ink-dim">
              {official ? (
                <>
                  Every trade uses the whole $100, so one drained pool can take
                  the lot. Pick a split to see the same trades made with a
                  smaller part of the wallet each time, or a bigger wallet to
                  see what the same trades do at a larger size.
                </>
              ) : start > Number(data.wallet_demo_usd) ? (
                <>
                  <b className="text-ink">
                    A ${start} wallet, trading ${ticket} at a time.
                  </b>{" "}
                  A bigger order moves the pool further, so every trade pays
                  more price impact on the way in and out; the network fee is a
                  smaller share of it. A drained pool still takes the whole
                  trade. Gains are measured against the ${start} it started
                  with. <b className="text-ink">Lowest</b> is the least the
                  wallet held at any sell. The verdict above is judged on $100
                  trades, and the projections apply only to them.
                </>
              ) : (
                <>
                  <b className="text-ink">
                    Each trade uses ${ticket} of the $100.
                  </b>{" "}
                  A drained pool costs ${ticket} instead of $100, and every win is
                  smaller too; the network fee takes a bigger share of a smaller
                  trade, and the trade moves the pool less. Ranked by balance at
                  this size. <b className="text-ink">Lowest</b> is the least the
                  wallet held at any sell. The verdict above is judged on $100
                  trades, and the projections apply only to them.
                </>
              )}
            </p>
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-10" />
              <col className="w-48" />
              <col className="w-36" />
              <col className="w-16" />
              <col className="w-20" />
              <col className="w-24" />
              <col className="w-24" />
              <col className="w-24" />
              <col className="w-24" />
            </colgroup>
            <thead>
              <tr className="text-label uppercase tracking-[0.08em] text-ink-dim">
                <th className="pb-2 pl-1 text-left font-medium">#</th>
                <th className="pb-2 pr-3 text-left font-medium">Strategy</th>
                <th
                  className="pb-2 pr-3 text-right font-medium"
                  title="What a real $100 account would hold, taking only the trades it could actually pay for. Holding one $100 position leaves nothing for a second, so overlapping signals are skipped — the count is under each figure."
                >
                  Balance <span className="text-ink-dim">your $100</span>
                </th>
                <th className="pb-2 pr-3 text-right font-medium">Open</th>
                <th className="pb-2 pr-3 text-right font-medium">Closed</th>
                {/* Four horizons side by side rather than one collapsed cell.
                    They are PREFIXES of the same simulated path, so they cannot
                    contradict each other — a wallet dead at 1d is dead at 30d —
                    and seeing them together is the only way to read the shape
                    of the forecast instead of one number from it. A blank means
                    the history does not reach a tenth of the way to that
                    horizon, which is a refusal, not a zero. */}
                {(["1d", "1w", "15d", "30d"] as const).map((h) => (
                  <th
                    key={h}
                    className="pb-2 pr-1 text-right font-medium"
                    title="Where your $100 lands if the arm keeps doing what it has done — projected from the trades the wallet could actually fund. Blank means too little history to say."
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((a: ArmRow, i: number) => {
                const isLeader = a.name === top;
                const wallet = walletOf(a);
                const here = at(a);
                const opening = Number(here?.start_usd ?? data.wallet_demo_usd);
                // Wiped, and kept on the board on purpose: these rows are the
                // evidence that one slot means one token can end the wallet.
                const dead = a.trades > 0 && Number(wallet) === 0;
                return (
                  <Fragment key={a.name}>
                  <tr
                    className={`grad-row border-t border-line align-top ${
                      isLeader ? "grad-leader" : ""
} ${dead ? "grad-dead" : ""} ${
                      a.is_control ? "text-ink-dim" : ""
                    }`}
                    style={{ animationDelay: `${Math.min(i, 14) * 28}ms` }}
                  >
                    <td className="py-2.5 pl-1 text-label tabular-nums text-ink-dim">
                      {/* The arm's TRUE rank, not its position in this list.
                          A pinned row appended after the top twelve would
                          otherwise read as 13th when it is fortieth. */}
                      {ranked.findIndex((x) => x.name === a.name) + 1}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <button
                          type="button"
                          onClick={() =>
                            setOpenArm(expanded === a.name ? null : a.name)
                          }
                          className={`break-all text-left font-mono text-xs hover:text-accent ${
                            isLeader ? "font-semibold text-ink" : ""
                          }`}
                          title="show every trade this arm has made"
                          aria-expanded={expanded === a.name}
                        >
                          {expanded === a.name ? "▾ " : "▸ "}
                          {a.name}
                        </button>
                        {a.is_control ? (
                          <span className="shrink-0 rounded-full border border-down/40 px-1.5 py-px text-micro uppercase tracking-[0.08em] text-down">
                            baseline
                          </span>
                        ) : null}
                        {dead ? (
                          <span className="shrink-0 rounded-full border border-down bg-down/15 px-1.5 py-px text-micro uppercase tracking-[0.08em] text-down">
                            dead
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-0.5 block truncate text-micro text-ink-dim">
                        {a.note}
                      </span>
                      {/* This arm's OWN clock. The board's header clock runs
                          from the NEWEST arm, so every arm is compared over a
                          window they all traded in — which is right for the
                          comparison and says nothing about how much evidence
                          any single row has behind it. */}
                      {/* A LIVE clock, not a figure. `arm_hours` is computed
                          server-side and therefore frozen between polls — it
                          jumped every thirty seconds and sat still in between.
                          `Elapsed` ticks each second off the first trade's own
                          timestamp, which is the same component the board
                          header uses, so the two cannot drift apart. */}
                      <span className="mt-0.5 block text-micro tabular-nums text-ink-dim">
                        {a.first_trade_at ? (
                          <>
                            <span className="rounded bg-ink/[0.06] px-1.5 py-px text-ink">
                              <Elapsed since={a.first_trade_at} />
                            </span>{" "}
                            since first trade
                          </>
                        ) : (
                          "no trades yet"
                        )}
                      </span>
                    </td>
                    {/* P&L: what the $100 wallet made or lost. The balance
                        sits under it, because "+$27" and "$127" are different
                        questions and both get asked. */}
                    {/* The ONLY money column now. The column beside this one counts
                        every trade the arm made, which is right for ranking
                        arms and wrong for "what would my $100 have done" — an
                        account already holding a $100 position cannot fund a
                        second, so overlapping signals are skipped. The skipped
                        count sits underneath because it is the whole reason
                        the two figures differ. */}
                    {/* BALANCE at the top, gain underneath — the same order as
                        the summary card, so a reader is not asked to switch
                        between "what is it worth" and "what did it make" going
                        down the page. The gain keeps the colour, because that
                        is the part with a sign. */}
                    <td className="py-2.5 pr-3 text-right">
                      <span
                        className={`grad-figure font-semibold tabular-nums ${
                          a.trades === 0 || Number(wallet) === 0
                            ? "text-ink-dim"
                            : "text-ink"
                        }`}
                      >
                        {a.trades === 0
                          ? "—"
                          : Number(wallet) === 0
                            ? "WIPED"
                            : usd(wallet)}
                      </span>
                      {a.trades === 0 || Number(wallet) === 0 ? null : (
                        <>
                          <span
                            className={`block text-micro tabular-nums ${
                              Number(wallet) > opening
                                ? "text-up"
                                : Number(wallet) === opening
                                  ? "text-ink-dim"
                                  : "text-down"
                            }`}
                          >
                            {signedUsd(
                              String(Number(wallet) - opening),
                            )}{" "}
                            ({walletPct(wallet, opening)})
                          </span>
                          <span className="block text-micro tabular-nums text-ink-dim">
                            {here?.trades_funded ?? a.trades_funded} funded
                            {(here?.trades_skipped ?? a.trades_skipped)
                              ? `, ${here?.trades_skipped ?? a.trades_skipped} unaffordable`
                              : ""}
                          </span>
                          {here ? (
                            <span
                              className="block text-micro tabular-nums text-ink-dim"
                              title="The least the wallet held at any sell, open trades at cost."
                            >
                              lowest {usd(here.low_usd)}
                            </span>
                          ) : null}
                        </>
                      )}
                    </td>
                    <td className="grad-figure py-2.5 pr-3 text-right tabular-nums">
                      {a.open_positions || "—"}
                    </td>
                    <td className="grad-figure py-2.5 pr-3 text-right tabular-nums">
                      {a.trades.toLocaleString()}
                    </td>
                    {/* The 30-day figure when the arm has enough history to
                        reach for it, otherwise the longest horizon it CAN
                        support, labelled. An empty column is less use than a
                        shorter honest one. */}
                    {(
                      [
                        a.projected_1d_usd,
                        a.projected_1w_usd,
                        a.projected_15d_usd,
                        a.projected_30d_usd,
                      ] as const
                    ).map((v, i) => (
                      <td
                        key={i}
                        className="py-2.5 pr-1 text-right align-top"
                      >
                        {v === null || !official ? (
                          <span
                            className="text-micro text-ink-dim"
                            title={
                              !official
                                ? "Projections are for $100 trades only."
                                : "Not enough history to reach a tenth of the way to this horizon."
                            }
                          >
                            &mdash;
                          </span>
                        ) : (
                          <span
                            className={`grad-figure font-medium tabular-nums ${
                              Number(v) >= Number(data.wallet_demo_usd)
                                ? "text-up"
                                : "text-down"
                            }`}
                          >
                            {usd(v)}
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                  {expanded === a.name ? (
                    <tr>
                      <td colSpan={9} className="p-0">
                        <ArmTrades
                          name={a.name}
                          size={{ ticket, split: chosen?.split ?? 1 }}
                        />
                      </td>
                    </tr>
                  ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          {data.arms.length > 12 ? (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
            >
              {showAll
                ? "Show the top 12"
                : `Show all ${data.arms.length} arms, controls included`}
            </button>
          ) : null}
          <p className="max-w-[64ch] text-micro leading-relaxed text-ink-dim">
            <b className="text-ink">How to read this.</b>{" "}
            <b className="text-ink">Balance</b> is what a real{" "}
            {usd(data.wallet_demo_usd)} account would hold now — every price recorded
            from the live feed at the minute it happened, every fill charged the
            exact move your own order makes against the pool&rsquo;s recorded
            depth plus swap and priority fees, and any order that would move a
            pool more than 10% refused rather than filled. It counts{" "}
            <b className="text-ink">only the trades that account could pay for</b>:
            holding one {usd(data.wallet_demo_usd)} position leaves nothing for a
            second, so overlapping signals are skipped and the line underneath
            says how many. Which ones get skipped is timing rather than skill, so
            an arm that happened to be busy through its own worst trades is
            flattered here — the skipped count is how you spot it.{" "}
            <b className="text-ink">Open</b> and <b className="text-ink">Closed</b>{" "}
            are position counts; open positions are not in the P&amp;L, because
            an unrealised number is what every book in this platform&rsquo;s
            history was leading on shortly before it wasn&rsquo;t.{" "}
            <b className="text-ink">Click any strategy name</b> to see every
            trade behind its figures, open and closed — the leader is already
            open below.
            <br />
            <span className="mt-1 block">
              <b className="text-ink">1d / 1w / 15d / 30d</b> is where{" "}
              <b className="text-ink">your {usd(data.wallet_demo_usd)}</b> lands
              if the arm keeps doing exactly what it has done — projected from
              the trades that wallet could actually FUND, at the rate it funds
              them, not from every trade the arm made. The four are prefixes of
              one simulated path, so they cannot disagree: a wallet dead at a day
              is dead at a month. A dash means the arm has not run a tenth of the
              way to that horizon, and a blank is a refusal rather than a zero.
              It is an <b className="text-ink">estimate, not a promise</b> — run forward a
              thousand times from the trades so far, and the middle one shown. An
              arm only gets a 30-day figure once its own history reaches a tenth
              of the way there; otherwise the longest horizon it can honestly
              support is shown and labelled. <b className="text-ink">WIPED</b>{" "}
              means the wallet fell below the size at which a trade is worth
              placing. Those rows stay on the board because deleting losers is
              how a leaderboard starts flattering itself.
            </span>
            </p>
        </div>
      </div>
    </Panel>
  );
}

export function GraduationLabPage() {
  const { data, isLoading, isError, refetch } = useGraduationStatus();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <ErrorState
          title="Could not load the Graduation Lab"
          body="The status endpoint did not answer."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!data.running) {
    return (
      <div className="p-6">
        <EmptyState
          title="The Graduation Lab is not running"
          body="LAB_GRADUATION_ENABLED is off, so the recorder is not connected. This is not the same as the lab running and finding nothing — no tokens are being watched at all."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Graduation Lab</h1>
        <p className="max-w-[65ch] text-sm text-ink-dim">
          pump.fun tokens climbing the bonding curve, recorded from the free
          launch feed and a {data.poll_interval_s}s chain poll. The recorder
          ranks nothing; the paper book below trades every graduation it sees
          on rules fixed in advance, and holds no real funds.
        </p>
      </header>

      {data.recorder_stalled ? (
        <div className="rounded border border-danger/50 bg-danger/10 p-4">
          <p className="text-sm font-semibold text-danger">
            The recorder is not reading the chain
          </p>
          <p className="mt-1 max-w-[65ch] text-xs text-danger">
            {data.watch_set} tokens are being watched but nothing has been read
            for{" "}
            {data.seconds_since_chain_read === null
              ? "any recorded time"
              : `${data.seconds_since_chain_read}s`}
            , against a {data.stall_threshold_s}s threshold. The counts below
            are what was already stored — they will look normal while nothing
            new arrives. Usual causes: a revoked or wrong RPC key, an
            unreachable node, or a stopped recorder.
          </p>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">

      </div>

      <LeaderboardPanel />

      <RulesPanel />

      <p className="text-xs text-ink-dim">
        Polling {data.rpc_host} · recorder refreshes every{" "}
        {data.poll_interval_s}s · this page every 30s
      </p>
    </div>
  );
}
