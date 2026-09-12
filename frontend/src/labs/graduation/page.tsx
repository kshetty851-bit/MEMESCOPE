"use client";

import { Fragment, useEffect, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { shortenAddress } from "@/lib/format";

import {
  useGraduationReturns,
  useGraduationStatus,
  useGraduationTournament,
  useGraduationTrades,
} from "./hooks";
import type {
  ArmRow,
  Funnel,
  PaperBook,
  PaperPosition,
  RecentToken,
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

const STAGES: { key: keyof Funnel; label: string; note: string }[] = [
  { key: "seen", label: "Seen", note: "admitted from the launch feed" },
  { key: "crossed_70", label: "70%", note: "tracked from here" },
  { key: "crossed_80", label: "80%", note: "" },
  { key: "crossed_90", label: "90%", note: "" },
  { key: "crossed_95", label: "95%", note: "" },
  { key: "graduated", label: "Graduated", note: "curve filled" },
];

function pct(part: number, whole: number): string {
  if (!whole) return "—";
  return `${((part / whole) * 100).toFixed(1)}%`;
}

function progress(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value).toFixed(1)}%`;
}

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

function TokenRow({ token }: { token: RecentToken }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2 pr-3 font-medium">
        {token.symbol ?? <span className="text-ink-dim">unnamed</span>}
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-ink-dim">
        {shortenAddress(token.mint)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums">
        {progress(token.max_progress_pct)}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-ink-dim">
        {token.sample_count}
      </td>
      <td className="py-2 text-right">
        {token.migrated ? (
          <span className="rounded-full bg-up/15 px-2 py-0.5 text-[11px] text-up">
            graduated
          </span>
        ) : token.tracked ? (
          <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
            tracking
          </span>
        ) : (
          <span className="text-[11px] text-ink-dim">watching</span>
        )}
      </td>
    </tr>
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
            </td>
            <td
              className={`pt-2 pr-3 text-right font-medium tabular-nums ${
                total > 0 ? "text-up" : total < 0 ? "text-down" : ""
              }`}
            >
              {signedUsd(String(total))}
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
        <PanelTitle>The 50 rules</PanelTitle>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
        >
          {open ? "Hide" : "Show all 50"}
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
      </p>
      {open.length ? (
        <div className="flex flex-col gap-1">
          <h4 className="text-label uppercase tracking-[0.08em] text-ink-dim">
            Open — marked, nothing banked
          </h4>
          <TradeTable rows={open} closed={false} empty="none open" />
        </div>
      ) : null}
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
  const [openArm, setOpenArm] = useState<string | null>(null);
  if (!data?.running) return null;
  const band = data.control_band === null ? null : Number(data.control_band);
  const shown = showAll ? data.arms : data.arms.slice(0, 12);
  const lead = data.arms.find((a) => a.name === data.leader);
  const margin =
    lead && band !== null ? Number(lead.realised_usd) - band : null;

  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Strategy tournament — 50 arms</PanelTitle>
        <span className="flex items-center gap-3">
          <span className="text-micro text-ink-dim">
            running <Elapsed since={data?.started_at ?? null} />
          </span>
          <span
            className={`transition-opacity ${isFetching ? "opacity-50" : "opacity-100"}`}
          >
            <Freshness at={dataUpdatedAt} />
          </span>
        </span>
      </PanelHeader>
      <div className="flex flex-col gap-5 p-4">
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
              Leader
            </span>
            <span className="truncate font-mono text-heading font-semibold text-ink">
              {data.leader || "—"}
            </span>
            <span className="text-micro text-ink-dim">
              {lead ? (
                <>
                  <span
                    className={`grad-figure ${
                      Number(lead.realised_usd) >= 0 ? "text-up" : "text-down"
                    }`}
                  >
                    {signedUsd(lead.realised_usd)}
                  </span>{" "}
                  on {lead.trades} closed
                  {margin !== null ? (
                    <>
                      {" · "}
                      <span className={margin > 0 ? "text-up" : "text-down"}>
                        {margin > 0 ? "+" : ""}
                        {usd(String(margin))} vs random
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
            value={band === null ? "—" : signedUsd(String(band))}
            note={data.best_control || "best random arm"}
          />
          <Stat
            label="Closed trades"
            value={data.total_trades.toLocaleString()}
            note={`across all 50 arms · ${Number(data.hours_running).toFixed(1)}h in`}
          />
          <Stat
            label="Position size"
            value={usd(data.notional_usd)}
            note="identical on every arm"
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
          must beat the best random arm, and its profit factor must clear{" "}
          <b className="text-ink">
            {Number(data.required_profit_factor).toFixed(2)}
          </b>{" "}
          — the bar is not a round number but the 95th percentile of what the
          luckiest of 42 noise arms reaches at the leader&rsquo;s own trade
          count, so it falls as the sample grows. At 40 trades that is above
          20; at 250 it is about 2.3.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-10" />
              <col />
              <col className="w-32" />
              <col className="w-28" />
              <col className="w-20" />
              <col className="w-48" />
              <col className="w-20" />
              <col className="w-20" />
              <col className="w-16" />
              <col className="w-24" />
            </colgroup>
            <thead>
              <tr className="text-label uppercase tracking-[0.08em] text-ink-dim">
                <th className="pb-2 pl-1 text-left font-medium">#</th>
                <th className="pb-2 pr-3 text-left font-medium">Arm</th>
                <th className="pb-2 pr-3 text-right font-medium">Equity</th>
                <th className="pb-2 pr-3 text-right font-medium">Realised</th>
                <th className="pb-2 pr-3 text-right font-medium">Return</th>
                <th className="pb-2 pr-3 text-right font-medium">
                  30d projection
                </th>
                <th className="pb-2 pr-3 text-right font-medium">Wipeout</th>
                <th className="pb-2 pr-3 text-right font-medium">Trades</th>
                <th className="pb-2 pr-3 text-right font-medium">PF</th>
                <th className="pb-2 pr-1 text-right font-medium">Top token</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((a: ArmRow, i: number) => {
                const v = Number(a.realised_usd);
                const beats = band !== null && a.trades > 0 && v > band;
                const isLeader = a.name === data.leader;
                return (
                  <Fragment key={a.name}>
                  <tr
                    className={`grad-row border-t border-line align-top ${
                      isLeader ? "grad-leader" : ""
                    } ${a.is_control ? "text-ink-dim" : ""}`}
                    style={{ animationDelay: `${Math.min(i, 14) * 28}ms` }}
                  >
                    <td className="py-2.5 pl-1 text-label tabular-nums text-ink-dim">
                      {i + 1}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            setOpenArm((v) => (v === a.name ? null : a.name))
                          }
                          className={`truncate font-mono text-xs hover:text-accent ${
                            isLeader ? "font-semibold text-ink" : ""
                          }`}
                          title="show every trade this arm has made"
                        >
                          {openArm === a.name ? "▾ " : "▸ "}
                          {a.name}
                        </button>
                        {a.is_control ? (
                          <span className="shrink-0 rounded-full border border-down/40 px-1.5 py-px text-micro uppercase tracking-[0.08em] text-down">
                            random
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-0.5 block truncate text-micro text-ink-dim">
                        {a.note}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right">
                      <span
                        className={`grad-figure font-medium ${
                          Number(a.equity_usd) > Number(data.capital_usd)
                            ? "text-up"
                            : Number(a.equity_usd) < Number(data.capital_usd)
                              ? "text-down"
                              : ""
                        }`}
                      >
                        {usd(a.equity_usd)}
                      </span>
                      {Number(a.unrealised_usd) !== 0 ? (
                        <span className="block text-micro tabular-nums text-ink-dim">
                          incl. {signedUsd(a.unrealised_usd)} open
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2.5 pr-3 text-right">
                      <span className="inline-flex items-baseline justify-end gap-1.5">
                        <span
                          className={`grad-figure font-medium ${
                            v > 0 ? "text-up" : v < 0 ? "text-down" : "text-ink-dim"
                          }`}
                        >
                          {a.trades ? signedUsd(a.realised_usd) : "—"}
                        </span>
                        <span
                          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                            beats && !a.is_control ? "bg-up" : "bg-transparent"
                          }`}
                          title={
                            beats && !a.is_control
                              ? "ahead of every random arm"
                              : undefined
                          }
                        />
                      </span>
                    </td>
                    <td
                      className={`grad-figure py-2.5 pr-3 text-right ${
                        Number(a.return_pct) > 0
                          ? "text-up"
                          : Number(a.return_pct) < 0
                            ? "text-down"
                            : "text-ink-dim"
                      }`}
                    >
                      {a.trades
                        ? `${Number(a.return_pct) > 0 ? "+" : ""}${Number(
                            a.return_pct,
                          ).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-right">
                      {a.projected_30d_usd === null ? (
                        <span className="text-micro text-ink-dim">
                          too few trades
                        </span>
                      ) : (
                        <>
                          <span
                            className={`grad-figure font-medium ${
                              Number(a.projected_30d_usd) > 0
                                ? "text-up"
                                : "text-down"
                            }`}
                          >
                            {signedUsd(a.projected_30d_usd)}
                          </span>
                          <span className="block text-micro tabular-nums text-ink-dim">
                            {signedUsd(a.projected_30d_low)} to{" "}
                            {signedUsd(a.projected_30d_high)}
                          </span>
                        </>
                      )}
                    </td>
                    <td className="py-2.5 pr-3 text-right">
                      {a.ruin_pct === null ? (
                        <span className="text-micro text-ink-dim">—</span>
                      ) : (
                        <span
                          className={`grad-figure ${
                            Number(a.ruin_pct) >= 50
                              ? "text-down"
                              : Number(a.ruin_pct) >= 10
                                ? "text-warn"
                                : "text-ink-dim"
                          }`}
                        >
                          {Number(a.ruin_pct).toFixed(0)}%
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3 text-right">
                      <span className="grad-figure">{a.trades}</span>
                      {a.open_positions ? (
                        <span className="ml-1 text-micro text-ink-dim">
                          +{a.open_positions}
                        </span>
                      ) : null}
                    </td>
                    <td className="grad-figure py-2.5 pr-3 text-right">
                      {a.profit_factor ?? "—"}
                    </td>
                    <td className="grad-figure py-2.5 pr-1 text-right text-ink-dim">
                      {a.top_token_share
                        ? `${(Number(a.top_token_share) * 100).toFixed(0)}%`
                        : "—"}
                    </td>
                  </tr>
                  {openArm === a.name ? (
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
            <b className="text-ink">Read the 30-day band, not its middle.</b>{" "}
            It is thirty days of the same rule at the same trade rate (
            {data.arms.find((a) => a.projected_trades)?.projected_trades.toLocaleString() ??
              "—"}{" "}
            trades), resampled from what that arm has actually done — and after{" "}
            {Number(data.hours_running).toFixed(1)} hours the band spans
            outcomes that are mostly an accident of which tokens arrived.
            It is simulated as an <b className="text-ink">account</b>, not a
            running total: positions stay {usd(data.notional_usd)} whatever the
            equity, and an account that cannot pay for the next one stops — so
            the worst thirty days costs {usd(data.capital_usd)} and no more,
            and a path wiped out on day three never collects the other
            twenty-seven. <b className="text-ink">Wipeout</b> is the share of
            simulated months that ended that way, which is the number a running
            total cannot express. Return % is against each arm&rsquo;s{" "}
            {usd(data.capital_usd)}. A dot marks an arm ahead of every random
            one. Open positions are the
            small <span className="text-ink">+n</span> beside the trade count and
            are <b className="text-ink">not</b> in the realised column — an
            unrealised number is what every book in this platform&rsquo;s history
            was leading on shortly before it wasn&rsquo;t.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function ReturnsPanel() {
  const { data } = useGraduationReturns();
  if (!data?.running || !data.usable) return null;
  const top = data.tiers[0]?.reached || 1;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>How far they got</PanelTitle>
      </PanelHeader>
      <div className="flex flex-col gap-4 p-4">
        <p className="max-w-[65ch] text-xs text-ink-dim">
          The highest price each graduated token reached in the hour after its
          pool opened, as a multiple of the open. Tiers are cumulative — a
          token at 5x is counted in 1.5x, 2x and 3x too.
        </p>

        <div className="flex flex-col gap-1.5">
          {data.tiers.map((t) => {
            const share = data.usable ? (t.reached / data.usable) * 100 : 0;
            return (
              <div key={t.label} className="flex items-center gap-3 text-sm">
                <span className="w-12 shrink-0 text-right font-mono text-ink-dim">
                  {t.label}
                </span>
                <div className="h-4 flex-1 overflow-hidden rounded-sm bg-line/40">
                  <div
                    className="h-full bg-up/70"
                    style={{ width: `${Math.max(t.reached ? 1 : 0, (t.reached / top) * 100)}%` }}
                  />
                </div>
                <span className="w-28 shrink-0 tabular-nums">
                  {t.reached}
                  <span className="ml-1.5 text-ink-dim">
                    {share.toFixed(share < 1 ? 2 : 1)}%
                  </span>
                </span>
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-2 rounded-md border border-down/40 p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            …and where they ended
          </h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Stat
              label="Ended below their open"
              value={pct(data.ended_below_open, data.usable)}
              note={`${data.ended_below_open} of ${data.usable}`}
            />
            <Stat
              label="Ended down 90%+"
              value={pct(data.ended_down_90, data.usable)}
              note={`${data.ended_down_90} of ${data.usable}`}
            />
            <Stat
              label="Best seen"
              value={data.best_multiple ? `${data.best_multiple}x` : "—"}
              note="single token, at its peak"
            />
          </div>
        </div>

        <p className="max-w-[65ch] text-xs text-ink-dim">
          <b className="text-ink">The denominator matters more than the tiers.</b>{" "}
          {data.seen.toLocaleString()} tokens were admitted from the launch
          feed, {data.migrated.toLocaleString()} graduated,{" "}
          {data.priced.toLocaleString()} have a recorded price series, and{" "}
          {data.usable.toLocaleString()} of those came from a single pool and
          are counted here. {data.excluded_multi_pool} were excluded because
          their marks crossed pools, which produces a &ldquo;peak&rdquo; that
          is a change of denomination rather than a price — one such token
          appeared to do 162x in a minute. A percentage quoted against the{" "}
          {data.seen.toLocaleString()} rather than the{" "}
          {data.usable.toLocaleString()} is wrong by a factor of thirty.
        </p>
      </div>
    </Panel>
  );
}

function PaperPanel({ book }: { book: PaperBook }) {
  // The full history, fetched apart from the board. While it loads the panel
  // shows the handful `/status` already carried, so the table is never empty
  // just because a second request is in flight.
  const { data: history } = useGraduationTrades(book.book);
  const filtered = book.book === "filtered";
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "closed_at",
    desc: true,
  });
  const onSort = (key: SortKey) =>
    setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }));
  const allClosed = history?.closed_trades ?? book.closed_trades;
  const pnl = Number(book.pnl_usd);
  const tone = pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "";
  const side = (Number(book.cost_pct_per_side) * 100).toFixed(2);
  const round = (Number(book.cost_pct_per_side) * 200).toFixed(2);
  // Derived, not written down: a hardcoded "both closed losses" was wrong
  // within the hour, and a stale number in a paragraph about honesty is
  // worse than no number.
  const worst = allClosed.reduce(
    (w, p) => Math.min(w, Number(p.net_return ?? 0)),
    0,
  );
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          {filtered ? "Paper book B — filtered" : "Paper book A — control"}
        </PanelTitle>
      </PanelHeader>
      <div className="flex flex-col gap-4 p-4">
        {filtered ? (
          <p className="max-w-[65ch] rounded-md border border-accent/40 p-3 text-xs text-ink-dim">
            <b className="text-ink">Identical rules, one extra check at entry:</b>{" "}
            {book.filter_description}. Replaying 537 graduations, a never-seen
            symbol rugged inside five minutes 18% of the time against 3% for
            a reused one, and pools opening in the daytime-UTC hours rugged
            15% against 5%. Two days of data is not enough to trust the
            P&L, so it runs here beside the control on the same graduations
            and the two are compared after four weeks. Nothing about the
            control changed.
          </p>
        ) : null}
        <p className="max-w-[65ch] text-xs text-ink-dim">
          Buy the pool open, {usd(book.notional_usd)} a position,{" "}
          {book.max_slots} at once, sell at {book.max_hold_minutes} minutes.
          No stop, no target — both were replayed against 430 recorded
          graduations and each made every hold worse. The size is where
          execution is cheapest: the priority fee is flat in SOL, so it is
          2.06% a side on a $10 position and 0.21% on a $100 one. Five
          minutes is the longest hold that is positive at any cost; past ten
          the average is negative even at a zero fee.
        </p>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Stat
            label="Equity"
            value={usd(book.equity_usd)}
            note={`from ${usd(book.starting_usd)} start`}
          />
          <Stat
            label="Realised"
            value={signedUsd(book.realised_usd)}
            note={`${signedUsd(book.unrealised_usd)} open`}
          />
          <Stat
            label="Open"
            value={`${book.open_positions}/${book.max_slots}`}
            note={
              book.voided
                ? `${book.closed_positions} closed, ${book.voided} voided`
                : `${book.closed_positions} closed`
            }
          />
          <Stat
            label="Wins"
            value={
              book.closed_positions
                ? `${((book.wins / book.closed_positions) * 100).toFixed(0)}%`
                : "—"
            }
            note={`${book.wins} of ${book.closed_positions}`}
          />
        </div>
        <div className="flex flex-col gap-2 rounded-md border border-line p-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            The gate, written down {book.gate_started} before a single trade
          </h3>
          <p className="max-w-[65ch] text-xs text-ink-dim">
            {book.gate_weeks} weeks. Below any of these at the end, the book
            closes — not &ldquo;reconsider&rdquo;. This lab has produced nine
            no-edge results; a tenth is the expected outcome, and the gate is
            what makes that outcome cost nothing.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {[
              {
                label: "Profit factor",
                need: `>= ${Number(book.gate_min_pf).toFixed(2)}`,
                got: book.profit_factor,
                ok: book.profit_factor !== null
                  && Number(book.profit_factor) >= Number(book.gate_min_pf),
                fmt: (v: string) => Number(v).toFixed(2),
              },
              {
                label: "Closed trades",
                need: `>= ${book.gate_min_trades}`,
                got: String(book.closed_positions),
                ok: book.closed_positions >= book.gate_min_trades,
                fmt: (v: string) => v,
              },
              {
                label: "Biggest token's share of profit",
                need: `<= ${(Number(book.gate_max_token_share) * 100).toFixed(0)}%`,
                got: book.top_token_share,
                ok: book.top_token_share !== null
                  && Number(book.top_token_share) <= Number(book.gate_max_token_share),
                fmt: (v: string) => `${(Number(v) * 100).toFixed(1)}%`,
              },
            ].map((g) => (
              <div key={g.label} className="flex flex-col">
                <span className="text-[11px] text-ink-dim">{g.label}</span>
                <span className="text-sm tabular-nums">
                  <span className={g.got === null ? "text-ink-dim" : g.ok ? "text-up" : "text-down"}>
                    {g.got === null ? "—" : g.fmt(g.got)}
                  </span>
                  <span className="text-ink-dim"> / need {g.need}</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        <p className={`text-sm font-semibold tabular-nums ${tone}`}>
          {signedUsd(book.pnl_usd)} ({Number(book.return_pct) >= 0 ? "+" : ""}
          {(Number(book.return_pct) * 100).toFixed(2)}%) against the{" "}
          {usd(book.starting_usd)} book
        </p>

        <div className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            Open trades — marked to the last price, nothing banked
          </h3>
          <TradeTable
            rows={book.open_trades}
            closed={false}
            empty="No open positions. The book opens one per graduating token as pools appear."
          />
        </div>

        {book.voided ? (
          <p className="max-w-[65ch] rounded-md border border-down/40 p-3 text-xs text-ink-dim">
            <span className="font-semibold text-ink">
              {book.voided} closed{" "}
              {book.voided === 1 ? "trade is" : "trades are"} voided and count
              for nothing above.
            </span>{" "}
            DexScreener answers with every pool a token trades in, and the
            recorder took whichever was listed first — so for these tokens the
            price series crossed from one pool to another mid-position. ORE&apos;s
            marks moved from its SOL pair to a USD-quoted one and &ldquo;rose&rdquo;
            100x in a minute with no trade behind it. That is not a price
            change, it is a change of instrument, so these trades are shown and
            excluded. The sampler now pins the pool it first saw, so it cannot
            happen again — but the rows already written still say what they
            say.
          </p>
        ) : null}

        <div className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
            Closed trades — all {allClosed.length}, banked, sortable
          </h3>
          <TradeTable
            rows={allClosed}
            closed
            sort={sort}
            onSort={onSort}
            empty="Nothing closed yet. Until a position exits, this book has proved nothing."
          />
        </div>

        {/* The question this page will be asked is "would a real wallet have
            made this?", so it is answered here rather than left implied. */}
        <div className="max-w-[65ch] rounded-md border border-line p-3 text-xs text-ink-dim">
          <p className="mb-1 font-semibold text-ink">
            Would a real wallet have made this?
          </p>
          <p>
            Close, but not to the cent, and the difference cuts both ways.
            Every price above is a real trade printed on-chain and read from
            the same DexScreener feed the rest of this site uses — nothing is
            simulated — and each leg is charged {side}% ({round}% round trip)
            for the pump fee, assumed slippage and priority fee. What a live
            wallet would hit differently:
          </p>
          <ul className="mt-1 list-disc pl-4">
            <li>
              Slippage here is <em>assumed</em>, not measured. These pools run
              deep enough that a {usd(book.notional_usd)} order moves the price
              well under the assumption, so the charge is more likely too harsh
              than too kind.
            </li>
            <li>
              The stop is checked once a minute against a sampled price, so an
              exit fills at the next price seen, not at the stop level. A token
              that collapses between samples fills far below the stop
              {worst < -Number(book.trailing_pct) ? (
                <>
                  {" "}
                  — the worst exit here landed at {(worst * 100).toFixed(0)}%
                  against a{" "}
                  {(Number(book.trailing_pct) * 100).toFixed(0)}% stop
                </>
              ) : null}
              . A live stop order would not have waited for the next sample,
              but on a pool draining that fast it may not have filled either.
            </li>
            <li>
              Nothing here can fail, get sandwiched, or miss a block. A real
              buy at a pool open competes with bots for the same slot.
            </li>
            <li>
              Costs here are modelled, not measured per trade:{" "}
              {(Number(book.cost_pct_per_side) * 100).toFixed(2)}% a side is
              PumpSwap&apos;s 25bp fee, 25bp of assumed slippage, and the flat
              priority fee at this position size. Median pool depth at the
              open is about $98,000, where a {usd(book.notional_usd)} order
              moves the price roughly 0.10% — so the slippage term is
              deliberately set above what the median implies, because the
              error that matters is the one that flatters the book.
            </li>
          </ul>
          <p className="mt-1">
            So treat these as what the rules would have earned at the prices
            the market actually printed — honest, and not a promise.
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

  const { funnel, signals } = data;

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

      <Panel>
        <PanelHeader>
          <PanelTitle>Right now</PanelTitle>
        </PanelHeader>
        <div className="grid grid-cols-2 gap-6 p-4 sm:grid-cols-4">
          <Stat
            label="Watch set"
            value={`${data.watch_set}`}
            note={`of ${data.watch_set_max} max`}
          />
          <Stat
            label="RPC calls / min"
            value={`${data.rpc_calls_per_minute}`}
            note="derived from the watch set"
          />
          <Stat
            label="New tokens / hr"
            value={`${data.tokens_last_hour}`}
            note="admitted from the feed"
          />
          <Stat
            label="Curve samples / hr"
            value={`${data.samples_last_hour}`}
            note="written only when reserves move"
          />
          <Stat
            label="Last chain read"
            value={
              data.seconds_since_chain_read === null
                ? "never"
                : `${data.seconds_since_chain_read}s ago`
            }
            note={data.recorder_stalled ? "STALLED" : "polling normally"}
          />
        </div>
      </Panel>

      <Panel>
        <PanelHeader>
          <PanelTitle>How far they get</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          <div className="flex min-w-[520px] items-end gap-2">
            {STAGES.map((stage) => {
              const value = funnel[stage.key];
              const share = funnel.seen ? value / funnel.seen : 0;
              return (
                <div key={stage.key} className="flex flex-1 flex-col gap-2">
                  <div className="flex h-28 items-end">
                    <div
                      className="w-full rounded-t bg-accent/70"
                      style={{ height: `${Math.max(share * 100, 1.5)}%` }}
                    />
                  </div>
                  <div className="flex flex-col gap-0.5 border-t border-line pt-2">
                    <span className="text-sm font-semibold tabular-nums">
                      {value}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider text-ink-dim">
                      {stage.label}
                    </span>
                    <span className="text-[11px] tabular-nums text-ink-dim">
                      {pct(value, funnel.seen)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader>
            <PanelTitle>Graduation signals</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <p className="max-w-[60ch] text-xs text-ink-dim">
              Two independent sources report a graduation — the migration feed
              and the curve account&rsquo;s own <code>complete</code> flag —
              and either can arrive alone. Counting one would undercount.
            </p>
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Both agreed</dt>
                <dd className="tabular-nums">{signals.both}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Feed only</dt>
                <dd className="tabular-nums">{signals.feed_only}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Chain only</dt>
                <dd className="tabular-nums">{signals.chain_only}</dd>
              </div>
            </dl>
          </div>
        </Panel>

        <Panel>
          <PanelHeader>
            <PanelTitle>What has been recorded</PanelTitle>
          </PanelHeader>
          <div className="flex flex-col gap-3 p-4">
            <dl className="flex flex-col gap-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Curve samples</dt>
                <dd className="tabular-nums">{data.curve_samples}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Checkpoints</dt>
                <dd className="tabular-nums">{data.checkpoints}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">…of those, with reserves</dt>
                <dd className="tabular-nums">
                  {data.checkpoints_with_reserves}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Post-graduation samples</dt>
                <dd className="tabular-nums">{data.postgrad_samples}</dd>
              </div>
            </dl>
            {/* The lab's own shutter speed. It bounds every pre-graduation
                question, because a strategy can only trade what it can see. */}
            <div className="flex flex-col gap-2 border-t border-line pt-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-dim">
                Can the climb be seen? — last hour, poll every{" "}
                {data.poll_interval_s}s
              </h3>
              <dl className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-ink-dim">Graduates observed</dt>
                  <dd className="tabular-nums">{data.graduates_observed}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-dim">…ever seen climbing</dt>
                  <dd className="tabular-nums">
                    {pct(data.graduates_seen_climbing, data.graduates_observed)}
                    <span className="ml-2 text-ink-dim">
                      {data.graduates_seen_climbing}
                    </span>
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-ink-dim">…ever seen at 90%+</dt>
                  <dd className="tabular-nums">
                    {pct(data.graduates_seen_at_90, data.graduates_observed)}
                    <span className="ml-2 text-ink-dim">
                      {data.graduates_seen_at_90}
                    </span>
                  </dd>
                </div>
              </dl>
              <p className="max-w-[60ch] text-xs text-ink-dim">
                Half of all graduates complete their curve within a minute of
                first sighting, so the poll interval is the population filter,
                not a detail. Measured over all of history at a fifteen-second
                poll it was 34% / 16.6%; these are the last hour, so a change
                to the interval shows here within the hour. The second figure
                is the only set a pre-graduation strategy could actually trade.
              </p>
            </div>
            {!data.quote_side_trusted ? (
              <p className="max-w-[60ch] rounded border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
                The curve&rsquo;s SOL side is not modelled correctly yet, so
                reserve and market-cap figures should not be relied on. The
                token side is sound — progress and the checkpoints are
                unaffected, and they are what this lab records.
              </p>
            ) : null}
          </div>
        </Panel>
      </div>

      <LeaderboardPanel />

      <RulesPanel />

      <ReturnsPanel />

      {data.paper.running ? <PaperPanel book={data.paper} /> : null}
      {data.paper_filtered.running ? (
        <PaperPanel book={data.paper_filtered} />
      ) : null}

      <Panel>
        <PanelHeader>
          <PanelTitle>Furthest up the curve</PanelTitle>
        </PanelHeader>
        <div className="overflow-x-auto p-4">
          {data.recent.length === 0 ? (
            <EmptyState
              title="Nothing has moved yet"
              body="No watched token has recorded a progress reading."
            />
          ) : (
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
                  <th className="pb-2 pr-3 font-medium">Symbol</th>
                  <th className="pb-2 pr-3 font-medium">Mint</th>
                  <th className="pb-2 pr-3 text-right font-medium">Peak</th>
                  <th className="pb-2 pr-3 text-right font-medium">Samples</th>
                  <th className="pb-2 text-right font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((token) => (
                  <TokenRow key={token.mint} token={token} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>

      <p className="text-xs text-ink-dim">
        Polling {data.rpc_host} · recorder refreshes every{" "}
        {data.poll_interval_s}s · this page every 30s
      </p>
    </div>
  );
}
