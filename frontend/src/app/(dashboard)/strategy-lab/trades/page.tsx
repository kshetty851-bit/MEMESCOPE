"use client";

import { useMemo, useState } from "react";

import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useLabBoard, useLabTrades } from "@/hooks/use-lab";
import type { LabTrade } from "@/types/lab";

/**
 * V6 STRATEGY LAB — TRADES
 *
 * Every position the twenty wallets hold or have closed, with the **full**
 * contract address. The whole point of this page is that a reader can copy the
 * mint and check the token against the market themselves rather than taking the
 * Lab's word for it, so the address is never abbreviated in the copyable field
 * and each row links out to DexScreener and Solscan.
 *
 * Research simulation. These are virtual positions in a paper tournament; no
 * real order was ever placed for any of them.
 *
 * Every figure is served already computed — nothing here recomputes a P&L.
 */

/** Same $1,000 / $100 rescale the leaderboard offers; see BOOK_SIZES there. */
const BOOK_SIZES = [
  { usd: 1000, scale: 1, label: "$1,000" },
  { usd: 100, scale: 0.1, label: "$100" },
] as const;

function money(v: number | null | undefined, digits = 2, scale = 1): string {
  return v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `$${(v * scale).toFixed(digits)}`;
}

function signed(v: number | null | undefined, scale = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const x = v * scale;
  return `${x >= 0 ? "+" : "−"}$${Math.abs(x).toFixed(2)}`;
}

function mult(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(3)}×`;
}

function held(hours: number): string {
  if (!Number.isFinite(hours)) return "—";
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  return `${hours.toFixed(1)}h`;
}

function when(iso: string | null): string {
  return iso ? iso.slice(5, 16).replace("T", " ") : "—";
}

/** Copies the address itself, not a shortened display of it. */
function CopyMint({ mint }: { mint: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      <code className="select-all break-all font-mono text-[10px] text-ink">{mint}</code>
      <button
        onClick={() => {
          navigator.clipboard?.writeText(mint).then(
            () => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            },
            () => setCopied(false),
          );
        }}
        title="Copy contract address"
        className="shrink-0 rounded border border-line px-1 text-[10px] text-muted hover:text-ink"
      >
        {copied ? "copied" : "copy"}
      </button>
    </span>
  );
}

function Links({ mint }: { mint: string }) {
  const targets = [
    { label: "DexScreener", href: `https://dexscreener.com/solana/${mint}` },
    { label: "Solscan", href: `https://solscan.io/token/${mint}` },
    { label: "Jupiter", href: `https://jup.ag/swap/SOL-${mint}` },
  ];
  return (
    <span className="inline-flex gap-2">
      {targets.map((t) => (
        <a
          key={t.label}
          href={t.href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-muted underline decoration-dotted hover:text-ink"
        >
          {t.label}
        </a>
      ))}
    </span>
  );
}

function marks(t: LabTrade): string {
  const hit = [t.reached_125 && "1.25×", t.reached_150 && "1.5×", t.reached_200 && "2×"]
    .filter(Boolean)
    .join(" ");
  return hit || "—";
}

export default function StrategyLabTradesPage() {
  const [strategy, setStrategy] = useState<string>("");
  const [status, setStatus] = useState<"" | "open" | "closed">("");
  const [sortKey, setSortKey] = useState<string>("opened_at");
  const [asc, setAsc] = useState(false);
  const [scale, setScale] = useState<number>(1);

  const board = useLabBoard();
  const { data, isLoading, error } = useLabTrades(
    strategy || undefined,
    status || undefined,
  );

  const rows = useMemo(() => {
    if (!data) return [];
    const copy = [...data.trades];
    copy.sort((a, b) => {
      const x = a[sortKey as keyof LabTrade];
      const y = b[sortKey as keyof LabTrade];
      if (typeof x === "number" && typeof y === "number") return asc ? x - y : y - x;
      return asc
        ? String(x ?? "").localeCompare(String(y ?? ""))
        : String(y ?? "").localeCompare(String(x ?? ""));
    });
    return copy;
  }, [data, sortKey, asc]);

  if (error) return <ErrorState body="The Strategy Lab trades feed is unavailable." />;
  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const strategies = board.data?.strategies ?? [];
  const th = (key: string, label: string, numeric = false) => (
    <th
      key={key}
      onClick={() => {
        if (sortKey === key) setAsc(!asc);
        else {
          setSortKey(key);
          setAsc(false);
        }
      }}
      className={`cursor-pointer whitespace-nowrap py-1 pr-3 font-normal hover:text-ink ${
        numeric ? "text-right" : ""
      }`}
    >
      {label}
      {sortKey === key ? (asc ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div className="space-y-4">
      <Panel density="compact">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <Label>V6 STRATEGY LAB — TRADES</Label>
            <h1 className="mt-1 text-lg font-medium text-ink">
              Every open and closed position, with its contract address
            </h1>
            <p className="mt-1 text-xs font-medium tracking-wide text-warning">
              PAPER / RESEARCH ONLY — no real order was placed for any of these
            </p>
          </div>
          <dl className="grid grid-cols-3 gap-x-6 text-xs">
            <div>
              <dt className="text-muted">Shown</dt>
              <dd className="font-mono text-ink">{data.total}</dd>
            </div>
            <div>
              <dt className="text-muted">Open</dt>
              <dd className="font-mono text-ink">{data.open}</dd>
            </div>
            <div>
              <dt className="text-muted">Closed</dt>
              <dd className="font-mono text-ink">{data.closed}</dd>
            </div>
          </dl>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="rounded border border-line bg-transparent px-2 py-1 text-xs text-ink"
          >
            <option value="">All 20 strategies</option>
            {strategies
              .slice()
              .sort((a, b) => a.strategy_id.localeCompare(b.strategy_id))
              .map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.strategy_id} {s.name}
                </option>
              ))}
          </select>
          {(["", "open", "closed"] as const).map((v) => (
            <button
              key={v || "all"}
              onClick={() => setStatus(v)}
              className={`rounded border px-2 py-1 text-xs ${
                status === v
                  ? "border-accent text-ink"
                  : "border-line text-muted hover:text-ink"
              }`}
            >
              {v === "" ? "all" : v}
            </button>
          ))}
          <span className="ml-3 text-[10px] text-muted">READ AS</span>
          {BOOK_SIZES.map((b) => (
            <button
              key={b.usd}
              onClick={() => setScale(b.scale)}
              className={`rounded border px-2 py-1 text-xs ${
                b.scale === scale
                  ? "border-accent text-accent"
                  : "border-line text-muted hover:text-ink"
              }`}
            >
              {b.label}
            </button>
          ))}
          <p className="ml-auto text-[10px] text-muted">
            addresses are shown in full — click <span className="text-ink">copy</span>, or
            open DexScreener / Solscan / Jupiter to check the token yourself
          </p>
        </div>
      </Panel>

      <Panel density="compact">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="text-muted">
              <tr>
                {th("strategy_id", "Strategy")}
                {th("symbol", "Token")}
                <th className="py-1 pr-3 font-normal">Contract address (CA)</th>
                <th className="py-1 pr-3 font-normal">Verify</th>
                {th("status", "Status")}
                {th("opened_at", "Opened")}
                {th("closed_at", "Closed")}
                {th("held_hours", "Held", true)}
                {th("size_usd", "Size", true)}
                {th("current_value_usd", "Value", true)}
                {th("realised_pnl", "P&L", true)}
                {th("exec_multiple", "Exec ×", true)}
                {th("peak_exec_multiple", "Peak ×", true)}
                <th className="py-1 pr-3 font-normal">Marks</th>
                {th("exit_reason", "Exit")}
                {th("route_state", "Route")}
              </tr>
            </thead>
            <tbody className="text-ink">
              {rows.map((t) => {
                const pnl = t.status === "closed" ? t.realised_pnl : t.unrealised_pnl;
                return (
                  <tr
                    key={`${t.strategy_id}-${t.mint}`}
                    className="border-t border-line align-top hover:bg-surface-2"
                  >
                    <td className="whitespace-nowrap py-1 pr-3 font-mono">
                      {t.strategy_id}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3">
                      {t.symbol ?? t.token_name ?? "—"}
                    </td>
                    <td className="py-1 pr-3">
                      <CopyMint mint={t.mint} />
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3">
                      <Links mint={t.mint} />
                    </td>
                    <td
                      className={`whitespace-nowrap py-1 pr-3 font-mono ${
                        t.status === "open" ? "text-accent" : "text-muted"
                      }`}
                    >
                      {t.status}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono">
                      {when(t.opened_at)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono">
                      {when(t.closed_at)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 text-right font-mono">
                      {held(t.held_hours)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 text-right font-mono">
                      {money(t.size_usd, 2, scale)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 text-right font-mono">
                      {money(t.current_value_usd, 2, scale)}
                    </td>
                    <td
                      className={`whitespace-nowrap py-1 pr-3 text-right font-mono ${
                        (pnl ?? 0) > 0
                          ? "text-success"
                          : (pnl ?? 0) < 0
                            ? "text-danger"
                            : ""
                      }`}
                    >
                      {signed(pnl, scale)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 text-right font-mono">
                      {mult(t.exec_multiple)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 text-right font-mono">
                      {mult(t.peak_exec_multiple)}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono">{marks(t)}</td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono">
                      {t.exit_reason ?? "—"}
                      {t.partial_done ? " (partial taken)" : ""}
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3 font-mono text-muted">
                      {t.route_state ?? "—"}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={16} className="py-3 text-muted">
                    No trades match this filter yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <p className="mt-2 border-t border-line pt-2 text-[10px] leading-relaxed text-muted">
          <span className="text-ink">Value</span> for an open position is what it could be
          SOLD for right now, not what it cost — which is why a position can show a loss
          the moment it opens. <span className="text-ink">Exec ×</span> is that value over
          cost; <span className="text-ink">Peak ×</span> is the best it ever reached.{" "}
          <span className="text-ink">Marks</span> record whether an executable 1.25× / 1.5×
          / 2× was actually available, never a chart price. A position closed{" "}
          <span className="text-ink">dead_zero</span> settled at $0.00 because the provider
          reported the pool inactive.
        </p>
      </Panel>
    </div>
  );
}
