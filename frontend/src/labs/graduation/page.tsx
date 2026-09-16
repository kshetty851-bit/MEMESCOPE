"use client";

import { Fragment, useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import {
  useGraduationStatus,
  useGraduationTournament,
  useGraduationTrades,
} from "./hooks";
import type {
  ArmRow,
  PaperPosition,
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

/** Hours since an arm's first trade, in the shortest form that stays exact. */
function elapsed(hours: string | number): string {
  const h = Number(hours);
  if (!h) return "new";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${(h / 24).toFixed(1)}d`;
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

/**
 * One trade. The mint is rendered in FULL and linked to the very feed the
 * marks come from, so every figure in the row can be checked against its
 * source rather than taken on trust.
 */
function TradeRow({ p, closed }: { p: PaperPosition; closed: boolean }) {
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
      <td className="py-2 pr-3 text-right tabular-nums">
        {usd(p.notional_usd)}
      </td>
      <td className={`py-2 pr-3 text-right font-medium tabular-nums ${tone}`}>
        {p.voided ? (
          <span className="line-through">{signedUsd(p.pnl_usd)}</span>
        ) : (
          signedUsd(p.pnl_usd)
        )}
      </td>
      <td className={`py-2 pr-3 text-right tabular-nums ${tone}`}>
        {p.voided ? (
          <span className="line-through">{signed(p.net_return)}</span>
        ) : (
          signed(p.net_return)
        )}
      </td>
      <td className="py-2 text-right text-[11px] text-ink-dim">
        {p.voided ? (
          <span
            className="rounded-full bg-down/15 px-2 py-0.5 text-down"
            title="The recorded price series for this token crossed pools, so this trade is not counted."
          >
            voided
          </span>
        ) : closed ? (
          <>
            {p.close_reason}
            <span className="block">{minutes}m held</span>
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
}: {
  rows: PaperPosition[];
  closed: boolean;
  empty: string;
  sort?: { key: SortKey; desc: boolean } | null;
  onSort?: (key: SortKey) => void;
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
  const total = counted.reduce((a, p) => a + Number(p.pnl_usd ?? 0), 0);
  const deployed = counted.reduce((a, p) => a + Number(p.notional_usd), 0);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
            <SortHead label="Token / mint" sort={sort} align="left" />
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
            <TradeRow key={p.mint} p={p} closed={closed} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-line text-[11px] text-ink-dim">
            <td className="pt-2 pr-3">
              {counted.length} counted
              {counted.length < ordered.length
                ? `, ${ordered.length - counted.length} voided`
                : ""}
            </td>
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

const ARM_FAMILIES: { prefix: string; title: string; blurb: string }[] = [
  {
    prefix: "E",
    title: "Exit only",
    blurb:
      "Every graduation, nothing filtered. These isolate the one variable that " +
      "earlier replay work found mattered — how long you hold.",
  },
  {
    prefix: "X",
    title: "Exit rules",
    blurb:
      "Targets and trailing stops layered on the 15- and 60-minute holds, to " +
      "see whether capping the upside pays for the drawdown it avoids.",
  },
  {
    prefix: "F",
    title: "One entry filter each",
    blurb:
      "A single condition at the pool open, all exiting at five minutes so the " +
      "filter is the only difference. Each filter's inverse is here too — a " +
      "signal that works must beat its own opposite.",
  },
  {
    prefix: "C",
    title: "Combinations",
    blurb:
      "Filters stacked, and the same filters at other hold lengths.",
  },
  {
    prefix: "R",
    title: "Controls — these cannot have an edge",
    blurb:
      "They decide by hashing the token address. Same graduations, same costs, " +
      "same exits; the rule is provably meaningless. Any arm that cannot beat " +
      "them has shown nothing.",
  },
];

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
  const byName = [...data.arms].sort((a, b) => a.name.localeCompare(b.name));
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

        {open
          ? ARM_FAMILIES.map((fam) => {
              const arms = byName.filter((a) => a.name.startsWith(fam.prefix));
              if (!arms.length) return null;
              return (
                <div key={fam.prefix} className="flex flex-col gap-2">
                  <h3 className="text-label uppercase tracking-[0.08em] text-ink-dim">
                    {fam.title} · {arms.length}
                  </h3>
                  <p className="max-w-[70ch] text-xs text-ink-dim">{fam.blurb}</p>
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
                        {arms.map((a: ArmRow) => (
                          <tr
                            key={a.name}
                            className={`border-t border-line align-top ${
                              a.is_control ? "text-ink-dim" : ""
                            }`}
                          >
                            <td className="py-2 pr-3 font-mono text-xs">
                              {a.name}
                            </td>
                            <td className="py-2 pr-3 text-xs">{a.entry_rule}</td>
                            <td className="py-2 text-xs">{a.exit_rule}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })
          : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {ARM_FAMILIES.map((fam) => (
                <div key={fam.prefix} className="flex flex-col">
                  <span className="font-mono text-heading font-semibold text-ink">
                    {byName.filter((a) => a.name.startsWith(fam.prefix)).length}
                  </span>
                  <span className="text-micro text-ink-dim">{fam.title}</span>
                </div>
              ))}
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
 * One arm's own trades, fetched on expand.
 *
 * Its own component so the hook is called unconditionally — a hook inside the
 * leaderboard's map would change count as rows open and close. Mounting it is
 * what triggers the fetch, so a collapsed arm costs nothing.
 */
function ArmTrades({ name }: { name: string }) {
  const { data, isLoading } = useGraduationTrades(name);
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
          <b className="text-ink">These are $100 fills, not a $100 account.</b>{" "}
          The totals below sum every trade as a fresh $100 bet — so a
          hundred-odd trades can total more than any wallet ever held, because
          the money was deployed again and again. The wallet figure on the row
          above is one $100 account taking these same trades one at a time,
          which is what you would actually do with $100. Both are correct. They
          count different things, and only the per-trade average is free of
          either.
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
  if (!data?.running) return null;
  const band = data.control_band === null ? null : Number(data.control_band);
  const shown = showAll ? data.arms : data.arms.slice(0, 12);
  const expanded = openArm === undefined ? (data.arms[0]?.name ?? null) : openArm;
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
          <b className="text-ink">Nothing here is invented.</b> Every entry and
          exit is priced at a price this platform actually recorded from the
          live feed, at the minute it happened. Every fill is charged the real
          cost of trading: the exact constant-product move your own order makes
          against the pool&rsquo;s <b className="text-ink">recorded depth</b>,
          on both legs, plus the swap fee and the priority fee — the{" "}
          <b className="text-ink">toll</b> column is that cost, taken out before
          any number you see. An order that would move a pool more than 10% is{" "}
          <b className="text-ink">refused, not filled</b>, because a real
          transaction past its slippage limit reverts. So a wallet trading these
          rules, at those moments, with {usd(data.notional_usd)} a position,
          would have paid these prices.
          <br />
          <span className="mt-1 block">
            The one thing it must do that this book does not:{" "}
            <b className="text-ink">land the transaction</b>. These fills assume
            your buy confirms at the price on screen. That is the honest gap,
            and it is the only one.
          </span>
        </p>
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
          <Stat
            label="Wallet simulated"
            value={usd(data.wallet_demo_usd)}
            note={`${data.wallet_demo_slots} positions, compounding`}
          />
        </div>

        <p className="max-w-[68ch] text-xs leading-relaxed text-ink-dim">
          Every arm sees the same graduations, pays the same costs and uses the
          same clock; they differ only in which tokens they accept and when they
          leave.{" "}
          <b className="text-ink">
            Eight of them (R1–R8) decide by hashing the token address
          </b>{" "}
          and cannot have an edge — run fifty strategies and one leads whether or
          not any is good, so their best result is the bar a real arm must
          clear. To be called, an arm needs {data.min_trades}+ closed trades,
          no single token above{" "}
          {(Number(data.max_token_share) * 100).toFixed(0)}% of its profit, it
          must beat the baseline — buying every graduation above the floor with no
          selection — and its profit factor must clear{" "}
          <b className="text-ink">
            {Number(data.required_profit_factor).toFixed(2)}
          </b>{" "}
          — the bar is not a round number but the 95th percentile of what the
          luckiest of 42 noise arms reaches at the leader&rsquo;s own trade
          count, so it falls as the sample grows. At 40 trades that is above
          20; at 250 it is about 2.3.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-10" />
              <col />
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
                  P&amp;L <span className="text-ink-dim">your $100</span>
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
                const isLeader = a.name === data.leader;
                // Wiped, and kept on the board on purpose: these rows are the
                // evidence that one slot means one token can end the wallet.
                const dead = a.trades > 0 && Number(a.wallet_funded_usd) === 0;
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
                      {data.arms.findIndex((x) => x.name === a.name) + 1}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setOpenArm(expanded === a.name ? null : a.name)
                          }
                          className={`truncate font-mono text-xs hover:text-accent ${
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
                      <span className="mt-0.5 block text-micro tabular-nums text-ink-dim">
                        trading {elapsed(a.arm_hours)}
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
                    <td className="py-2.5 pr-3 text-right">
                      <span
                        className={`grad-figure font-semibold tabular-nums ${
                          Number(a.wallet_funded_usd) > Number(data.wallet_demo_usd)
                            ? "text-up"
                            : Number(a.wallet_funded_usd) === Number(data.wallet_demo_usd)
                              ? "text-ink-dim"
                              : "text-down"
                        }`}
                      >
                        {a.trades === 0
                          ? "—"
                          : Number(a.wallet_funded_usd) === 0
                            ? "WIPED"
                            : signedUsd(
                                String(
                                  Number(a.wallet_funded_usd) -
                                    Number(data.wallet_demo_usd),
                                ),
                              )}
                      </span>
                      {a.trades === 0 ? null : (
                        <>
                          <span className="block text-micro tabular-nums text-ink-dim">
                            {Number(a.wallet_funded_usd) === 0
                              ? "—"
                              : `${walletPct(a.wallet_funded_usd, data.wallet_demo_usd)} · ${usd(a.wallet_funded_usd)}`}
                          </span>
                          <span className="block text-micro tabular-nums text-ink-dim">
                            {a.trades_funded} funded
                            {a.trades_skipped
                              ? `, ${a.trades_skipped} unaffordable`
                              : ""}
                          </span>
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
                        {v === null ? (
                          <span
                            className="text-micro text-ink-dim"
                            title="Not enough history to reach a tenth of the way to this horizon."
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
                        <ArmTrades name={a.name} />
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
            <b className="text-ink">P&amp;L</b> is what a real{" "}
            {usd(data.wallet_demo_usd)} account would hold — every price recorded
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
