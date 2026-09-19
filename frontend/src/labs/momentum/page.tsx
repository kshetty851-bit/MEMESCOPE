"use client";

import { Fragment, useState } from "react";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import {
  useMomentumBoard,
  useMomentumSignals,
  useMomentumStatus,
  useMomentumTrades,
} from "./hooks";
import type { ArmRow, MomentumStatus, SplitRow, TradeRow } from "./types";

/**
 * MOMENTUM LAB
 *
 * Fifty paper strategies that buy the momentum candle on Solana tokens older
 * than seven days, each from a $1,000 wallet. Every number is computed on the
 * backend; nothing here applies a rule of its own.
 */

const FAMILIES: [string, string][] = [
  ["control", "Controls — random rules that cannot have an edge"],
  ["entry", "5-minute candle — the base rule, one entry condition changed each"],
  ["universe", "5-minute candle — the universe sliced by pool size and token age"],
  ["exit", "5-minute candle — the base entry, one exit changed each"],
  ["m15", "15-minute candles"],
  ["m1h", "1-hour candles"],
  ["catch", "Caught mid-candle — bought while the move is happening"],
  ["dip", "The opposite bet — buy the red candle"],
];

function pct(v: number | null, digits = 2): string {
  if (v === null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function usd(v: number | null): string {
  if (v === null) return "—";
  return `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function price(v: number | null): string {
  if (v === null) return "—";
  if (v >= 1) return v.toFixed(4);
  return v.toPrecision(4);
}

function tone(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "text-up" : "text-down";
}

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${(s / 3600).toFixed(1)}h ago`;
  return `${(s / 86400).toFixed(1)}d ago`;
}

function time(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const dex = (pair: string) => `https://dexscreener.com/solana/${pair}`;

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-ink-dim">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
    </div>
  );
}

function Health({ s }: { s: MomentumStatus }) {
  const stale = s.seconds_since_sample !== null && s.seconds_since_sample > 180;
  return (
    <Panel>
      <div className="grid grid-cols-2 gap-5 p-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat
          label="Tokens watched"
          value={String(s.pools_active)}
          note={`older than ${s.min_age_days} days`}
        />
        <Stat
          label="Last price"
          value={ago(s.last_sample_at)}
          note={`${s.pools_sampled_5m} pools in 5 min`}
        />
        <Stat label="Momentum candles" value={String(s.signals_24h)} note="last 24 hours" />
        <Stat label="Open positions" value={String(s.open_positions)} note="all strategies" />
        <Stat label="Closed trades" value={s.closed_trades.toLocaleString()} note="all strategies" />
        <Stat label="Running since" value={s.started_at ? ago(s.started_at) : "—"} note="first fill" />
      </div>
      {stale ? (
        <p className="border-t border-line px-4 py-2 text-xs text-danger">
          No fresh price for {s.seconds_since_sample}s. The figures below are what
          was already recorded; nothing new is arriving.
        </p>
      ) : null}
    </Panel>
  );
}

function SplitTable({ splits, start }: { splits: SplitRow[]; start: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] text-xs">
        <thead>
          <tr className="text-left text-ink-dim">
            <th className="pb-1 pr-3 font-medium">Split</th>
            <th className="pb-1 pr-3 text-right font-medium">Wallet</th>
            <th className="pb-1 pr-3 text-right font-medium">Lowest</th>
            <th className="pb-1 pr-3 text-right font-medium">Taken</th>
            <th className="pb-1 text-right font-medium">Skipped (no free ticket)</th>
          </tr>
        </thead>
        <tbody>
          {splits.map((w) => (
            <tr key={w.split} className="border-t border-line tabular-nums">
              <td className="py-1 pr-3">
                {w.split} × {usd(w.ticket).replace(".00", "")}
              </td>
              <td className={`py-1 pr-3 text-right ${tone(w.end - start)}`}>
                {usd(w.end)} <span className="text-ink-dim">{pct((w.end / start - 1) * 100, 1)}</span>
              </td>
              <td className="py-1 pr-3 text-right">{usd(w.low)}</td>
              <td className="py-1 pr-3 text-right">{w.funded}</td>
              <td className="py-1 text-right">{w.skipped}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Trades({ arm }: { arm: string }) {
  const { data, isLoading } = useMomentumTrades(arm);
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  const rows = data?.trades ?? [];
  if (!rows.length) {
    return <p className="text-xs text-ink-dim">No trades yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-xs">
        <thead>
          <tr className="text-left text-ink-dim">
            <th className="pb-1 pr-3 font-medium">Token</th>
            <th className="pb-1 pr-3 font-medium">Candle</th>
            <th className="pb-1 pr-3 text-right font-medium">Bought</th>
            <th className="pb-1 pr-3 text-right font-medium">Sold</th>
            <th className="pb-1 pr-3 font-medium">Why</th>
            <th className="pb-1 text-right font-medium">Return</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t: TradeRow) => {
            const f = t.features ?? {};
            const ret = typeof f.ret === "number" ? f.ret * 100 : null;
            const live =
              t.open_price && t.last_price ? (t.last_price / t.open_price - 1) * 100 : null;
            // Decided under a rule that has since changed: shown, counted nowhere.
            const voided = t.status === "void";
            return (
              <tr
                key={`${t.pair_address}-${t.decided_at}`}
                className={`border-t border-line align-top tabular-nums ${voided ? "text-ink-dim line-through" : ""}`}
              >
                <td className="py-1.5 pr-3">
                  <a className="text-accent hover:underline" href={dex(t.pair_address)} target="_blank" rel="noreferrer">
                    {t.symbol ?? t.mint.slice(0, 6)}
                  </a>
                  <span className="ml-1 text-ink-dim">{t.dex_id}</span>
                </td>
                <td className="py-1.5 pr-3 text-ink-dim">
                  {t.signal_tf} {time(t.signal_start)}
                  {ret !== null ? <span className="ml-1 text-ink">{pct(ret, 1)}</span> : null}
                  {typeof f.vol_x === "number" ? ` · ${f.vol_x}x vol` : ""}
                  {typeof f.change_m5 === "number" ? ` · ${pct(f.change_m5, 1)} in 5m` : ""}
                </td>
                <td className="py-1.5 pr-3 text-right">
                  {t.open_price === null ? (
                    <span className="text-ink-dim">{t.status}</span>
                  ) : (
                    <>
                      {price(t.open_price)}
                      <span className="block text-ink-dim">{time(t.opened_at)}</span>
                    </>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right">
                  {t.close_price === null ? (
                    <span className="text-ink-dim">
                      {t.status === "open" || t.status === "closing" ? `now ${price(t.last_price)}` : "—"}
                    </span>
                  ) : (
                    <>
                      {price(t.close_price)}
                      <span className="block text-ink-dim">{time(t.closed_at)}</span>
                    </>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-ink-dim">
                  {voided ? "not counted: before the 20-trade rule" : (t.exit_reason ?? (t.status === "open" ? "holding" : t.status))}
                </td>
                <td className={`py-1.5 text-right ${tone(t.net_return_pct ?? live)}`}>
                  {t.net_return_pct !== null ? pct(t.net_return_pct) : live !== null ? `${pct(live)} open` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Board({ start }: { start: number }) {
  const { data, isLoading, isError } = useMomentumBoard();
  const [split, setSplit] = useState(10);
  const [open, setOpen] = useState<string | null>(null);
  if (isLoading) return <Skeleton className="h-96 w-full" />;
  if (isError || !data?.running) return null;
  const walletOf = (a: ArmRow) => a.splits.find((s) => s.split === split) ?? a.wallet;
  const splits = data.arms[0]?.splits ?? [];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>The {data.arms.length} strategies</PanelTitle>
        <span className="flex flex-wrap items-center gap-1 text-xs">
          <span className="mr-1 text-ink-dim">each $1,000 wallet split</span>
          {splits.map((s) => (
            <button
              key={s.split}
              type="button"
              onClick={() => setSplit(s.split)}
              className={`rounded border px-2 py-0.5 tabular-nums ${
                s.split === split ? "border-accent text-accent" : "border-line text-ink-dim hover:text-ink"
              }`}
            >
              {s.split} × {usd(s.ticket).replace(".00", "")}
            </button>
          ))}
        </span>
      </PanelHeader>
      <div className="flex flex-col gap-4 p-4">
        <p className="max-w-[80ch] rounded-lg border border-line bg-ink/[0.02] p-3 text-xs leading-relaxed text-ink-dim">
          <b className="text-ink">Paper only, priced like a real wallet.</b> A buy is decided when
          a candle closes and filled at the <b className="text-ink">next price recorded after
          the decision</b>, never the price it was decided on. Every fill pays the pool&rsquo;s fee
          (0.30%, or pump.fun&rsquo;s market-cap tier), the router&rsquo;s cut and the price move
          its own order makes — the <b className="text-ink">toll</b> column. Each trade is measured
          at $100; the wallet column re-walks them in order, skipping any signal that arrives while
          every ticket is in use. A strategy has shown something only when it beats its yardstick by
          three standard errors (measured between hours) — with fifty strategies, one or two will beat
          it at two by luck alone.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
            <colgroup>
              <col className="w-56" />
              <col className="w-32" />
              <col className="w-20" />
              <col className="w-16" />
              <col className="w-24" />
              <col className="w-20" />
              <col className="w-24" />
              <col className="w-52" />
            </colgroup>
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-ink-dim">
                <th className="pb-2 pr-3 font-medium">Strategy</th>
                <th className="pb-2 pr-3 text-right font-medium">Wallet</th>
                <th className="pb-2 pr-3 text-right font-medium">Trades</th>
                <th className="pb-2 pr-3 text-right font-medium">Win</th>
                <th className="pb-2 pr-3 text-right font-medium">Avg trade</th>
                <th className="pb-2 pr-3 text-right font-medium">Toll</th>
                <th className="pb-2 pr-3 text-right font-medium">vs yardstick</th>
                <th className="pb-2 font-medium">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {FAMILIES.map(([family, title]) => {
                const arms = data.arms.filter((a) => a.family === family);
                if (!arms.length) return null;
                return (
                  <Fragment key={family}>
                    <tr>
                      <td colSpan={8} className="pb-1 pt-4 text-xs font-semibold text-ink">
                        {title}
                      </td>
                    </tr>
                    {arms.map((a) => {
                      const w = walletOf(a);
                      const toll =
                        a.gross_pct !== null && a.mean_pct !== null ? a.gross_pct - a.mean_pct : null;
                      const shown = open === a.name;
                      return (
                        <Fragment key={a.name}>
                          <tr className={`border-t border-line align-top ${a.is_control ? "text-ink-dim" : ""}`}>
                            <td className="py-2 pr-3">
                              <button
                                type="button"
                                onClick={() => setOpen(shown ? null : a.name)}
                                aria-expanded={shown}
                                className="text-left font-mono text-xs hover:text-accent"
                              >
                                {shown ? "▾ " : "▸ "}
                                {a.name}
                              </button>
                              <span className="block text-xs text-ink-dim">{a.note}</span>
                            </td>
                            <td className={`py-2 pr-3 text-right tabular-nums ${tone(w.end - start)}`}>
                              {usd(w.end)}
                              <span className="block text-xs text-ink-dim">
                                {pct((w.end / start - 1) * 100, 1)}
                                {a.unrealised_usd ? ` · open ${usd(a.unrealised_usd)}` : ""}
                              </span>
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums">
                              {a.trades}
                              <span className="block text-xs text-ink-dim">{a.open} open</span>
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums">
                              {a.trades ? `${Math.round((a.wins / a.trades) * 100)}%` : "—"}
                            </td>
                            <td className={`py-2 pr-3 text-right tabular-nums ${tone(a.mean_pct)}`}>
                              {pct(a.mean_pct)}
                              {a.se_pct !== null ? (
                                <span className="block text-xs text-ink-dim">± {a.se_pct.toFixed(2)}</span>
                              ) : null}
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums text-ink-dim">
                              {toll === null ? "—" : `${toll.toFixed(2)}%`}
                            </td>
                            <td className={`py-2 pr-3 text-right tabular-nums ${a.z_vs !== null && Math.abs(a.z_vs) >= 3 ? tone(a.z_vs) : ""}`}>
                              {a.z_vs === null ? "—" : `${a.z_vs >= 0 ? "+" : ""}${a.z_vs.toFixed(1)}σ`}
                              {a.vs ? <span className="block text-xs text-ink-dim">{a.vs}</span> : null}
                            </td>
                            <td className="py-2 text-xs">{a.verdict}</td>
                          </tr>
                          {shown ? (
                            <tr>
                              <td colSpan={8} className="pb-4">
                                <div className="flex flex-col gap-3 rounded-lg border border-line bg-ink/[0.02] p-3">
                                  <p className="text-xs">
                                    <b>Buy:</b> {a.entry}
                                    <br />
                                    <b>Sell:</b> {a.exit}
                                  </p>
                                  <SplitTable splits={a.splits} start={start} />
                                  <Trades arm={a.name} />
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}

function Radar() {
  const { data } = useMomentumSignals();
  const rows = data?.signals ?? [];
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Momentum candles, newest first</PanelTitle>
        <span className="text-xs text-ink-dim">every candle a rule accepted, bought or not</span>
      </PanelHeader>
      <div className="p-4">
        {!rows.length ? (
          <p className="text-xs text-ink-dim">
            None yet. A token needs about two hours of its own candles before any rule may judge it.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead>
                <tr className="text-left text-ink-dim">
                  <th className="pb-1 pr-3 font-medium">Token</th>
                  <th className="pb-1 pr-3 font-medium">Candle</th>
                  <th className="pb-1 pr-3 text-right font-medium">Move</th>
                  <th className="pb-1 pr-3 text-right font-medium">Volume</th>
                  <th className="pb-1 pr-3 text-right font-medium">Body</th>
                  <th className="pb-1 pr-3 text-right font-medium">Buys / sell</th>
                  <th className="pb-1 text-right font-medium">Strategies</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const f = s.features;
                  const move = typeof f.ret === "number" ? f.ret * 100 : (f.change_m5 ?? null);
                  return (
                    <tr key={`${s.pair_address}-${s.tf}-${s.start}`} className="border-t border-line tabular-nums">
                      <td className="py-1 pr-3">
                        <a className="text-accent hover:underline" href={dex(s.pair_address)} target="_blank" rel="noreferrer">
                          {s.symbol ?? s.mint.slice(0, 6)}
                        </a>
                      </td>
                      <td className="py-1 pr-3 text-ink-dim">
                        {s.tf === "tick" ? "live 5m" : s.tf} · {ago(s.at)}
                      </td>
                      <td className={`py-1 pr-3 text-right ${tone(move)}`}>{pct(move, 1)}</td>
                      <td className="py-1 pr-3 text-right">{f.vol_x != null ? `${f.vol_x}x` : "—"}</td>
                      <td className="py-1 pr-3 text-right">{f.body_x != null ? `${f.body_x}x` : "—"}</td>
                      <td className="py-1 pr-3 text-right">{f.buy_ratio ?? "—"}</td>
                      <td className="py-1 text-right" title={s.arms.join(", ")}>{s.arms.length}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Panel>
  );
}

export function MomentumLabPage() {
  const { data, isLoading, isError, refetch } = useMomentumStatus();

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
          title="Could not load the Momentum Lab"
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
          title="The Momentum Lab is not running"
          body="LAB_MOMENTUM_ENABLED is off, so no prices are being recorded and no strategy is trading."
        />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Momentum Lab</h1>
        <p className="max-w-[70ch] text-sm text-ink-dim">
          Solana tokens whose market is more than {data.min_age_days} days old, with at least $
          {Math.round(data.min_liquidity_usd / 1000)}k of liquidity, priced every 30 seconds. When
          a <b className="text-ink">momentum candle</b> closes — a big green candle for that token,
          on heavy volume, closing near its high, with at least {data.min_trades_5m} trades in
          five minutes — {data.arms} paper strategies decide whether to buy. Each starts with {usd(data.start_usd).replace(".00", "")}. No real funds.
        </p>
      </header>
      <Health s={data} />
      <Board start={data.start_usd} />
      <Radar />
    </div>
  );
}
