"use client";

import { Fragment, useState } from "react";

import { TokenIdentity } from "@/components/brand/token-identity";
import { FreshnessLabel, NoMarketData } from "@/components/ui/freshness";

import { useSharedClock } from "@/hooks/use-shared-clock";
import { Skeleton } from "@/components/ui/skeleton";
import { exitLabel, pct, usd } from "@/lib/paper";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ManualSellPreview, ManualSellResult, PaperPosition } from "@/types/paper";

/**
 * EVERY SIMULATED TRADE
 *
 * Open and closed in one shape, because they are the same object at different
 * points in its life. Losers are never filtered out and never sorted below
 * winners — the default order is the order things happened.
 *
 * Two columns carry the honesty of the whole table:
 *
 *  - **Trailing stop** is where the only exit rule currently sits: the running
 *    high, less the fraction fixed at entry. Showing it beside the current
 *    price is what lets a reader check the exit against the rule rather than
 *    taking the result on trust. It is blank for a closed trade — the level
 *    that mattered is the exit price, which is its own column.
 *  - **Peak** stops at the exit for a closed trade. A high the token printed
 *    after the position closed belongs to the token, not to the trade, and
 *    crediting it would be the most flattering error available here.
 */

function Cell({
  value,
  tone,
  className,
  hint,
}: {
  value: string | null;
  tone?: "positive" | "negative" | "neutral";
  className?: string;
  hint?: string | null;
}) {
  return (
    <td
      className={cn(
        "py-2.5 text-right tabular-nums",
        value === null && "text-ink-3",
        tone === "positive" && "text-up",
        tone === "negative" && "text-down",
        (!tone || tone === "neutral") && value !== null && "text-ink-2",
        className,
      )}
      title={hint ?? undefined}
    >
      {value ?? "—"}
    </td>
  );
}

function signTone(value: string | null): "positive" | "negative" | "neutral" {
  if (value === null) return "neutral";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "neutral";
  return parsed > 0 ? "positive" : "negative";
}

function modelLabel(value: string | null): string {
  if (value === "jupiter_quote_v2") return "Jupiter";
  if (value === "legacy_constant_product_v1" || value === null) return "Legacy";
  return value;
}

function formatEntered(dateStr: string): string {
  const d = new Date(dateStr);
  if (!Number.isFinite(d.getTime())) return "—";
  const day = d.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  return `${day} · ${time}`;
}

function durationLabel(opened: string, closed: string | null, now: number): string {
  const o = new Date(opened).getTime();
  if (!Number.isFinite(o)) return "—";
  const end = closed ? new Date(closed).getTime() : now;
  if (!Number.isFinite(end)) return "—";
  
  const seconds = Math.max(0, (end - o) / 1000);
  const m = Math.floor(seconds / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  
  if (d > 0) return `${d}d ${h % 24}h`;
  if (h > 0) return `${h}h ${m % 60}m`;
  return `${m}m`;
}

export function PositionsTable({
  positions,
  isPending,
  emptyLabel,
  onPreviewManualSell,
  onManualSell,
}: {
  positions: PaperPosition[];
  isPending: boolean;
  emptyLabel: string;
  onPreviewManualSell?: (mint: string) => Promise<ManualSellPreview>;
  onManualSell?: (mint: string) => Promise<ManualSellResult>;
}) {
  const [preview, setPreview] = useState<ManualSellPreview | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [selling, setSelling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const showingClosedTrades = positions[0]?.status === "closed";

  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-10" />
        ))}
      </div>
    );
  }

  if (positions.length === 0) {
    return <p className="text-sm text-ink-3">{emptyLabel}</p>;
  }

  const loadPreview = async (mint: string) => {
    if (!onPreviewManualSell) return;
    setError(null);
    setPreviewing(mint);
    try {
      setPreview(await onPreviewManualSell(mint));
    } catch (caught) {
      setPreview(null);
      setError(caught instanceof Error ? caught.message : "Manual sell preview failed.");
    } finally {
      setPreviewing(null);
    }
  };

  const confirmSell = async (mint: string) => {
    if (!onManualSell) return;
    setError(null);
    setSelling(mint);
    try {
      await onManualSell(mint);
      setPreview(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Manual sell failed.");
    } finally {
      setSelling(null);
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1280px] text-sm">
        <thead>
          <tr className="border-b border-line text-label uppercase tracking-wide text-ink-3">
            <th className="py-2 text-left font-medium">Token</th>
            <th className="py-2 text-right font-medium">Entry MCAP</th>
            <th className="py-2 text-right font-medium">Current MCAP</th>
            <th className="py-2 text-right font-medium">
              {showingClosedTrades ? "Gross P/L" : "P/L"}
            </th>
            <th className="py-2 text-right font-medium">Entered</th>
            <th className="py-2 text-right font-medium">Held</th>
            {showingClosedTrades ? (
              <>
                <th className="py-2 text-right font-medium">Fees</th>
                <th className="py-2 text-right font-medium">Slippage</th>
                <th className="py-2 text-right font-medium">Net P/L</th>
              </>
            ) : null}
            <th className="py-2 text-right font-medium">Status / Market</th>
            <th className="py-2 text-right font-medium">Exit rule / Info</th>
            {onPreviewManualSell ? (
              <th className="py-2 text-right font-medium">Action</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => {
            const closed = position.status === "closed";
            const selected = preview?.mint_address === position.mint_address;
            return (
              <Fragment key={position.mint_address}>
                <tr className="border-b border-line/50 transition-colors hover:bg-raised/40">
                  <td className="py-2.5 pr-4">
                    <TokenIdentity
                      mint={position.mint_address}
                      name={position.name}
                      symbol={position.symbol}
                      imageUrl={position.image_url}
                      size="xs"
                      showMint={false}
                    />
                    <span className="ml-2 text-xs text-ink-3">
                      #{position.entry_rank} at entry
                    </span>
                    {/* Whose rules this row trades under. The open book is
                        pooled across the capital lineage, so a Gen 2 position
                        with no time limit sits beside a Gen 9 one with a
                        six-hour cutoff — unlabelled, the older rows read as
                        the current strategy ignoring its own rules. */}
                    {position.generation != null ? (
                      <span className="ml-2 rounded-sm border border-line px-1 py-0.5 text-[10px] text-ink-3">
                        Gen {position.generation}
                      </span>
                    ) : null}
                  </td>
                  <Cell value={usd(position.entry_market_cap)} />
                  <Cell value={usd(position.current_market_cap)} />
                  <Cell
                    value={usd(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                    hint={position.current_pct ? pct(position.current_pct) : undefined}
                    tone={signTone(
                      closed
                        ? (position.gross_pnl_usd ?? position.pnl_usd)
                        : position.pnl_usd,
                    )}
                  />
                  <td className="py-2.5 text-right text-xs text-ink-3 tabular-nums">
                    {formatEntered(position.opened_at)}
                  </td>
                  <td className="py-2.5 text-right text-xs text-ink-3 tabular-nums">
                    <DurationLabel opened={position.opened_at} closed={position.closed_at} />
                  </td>
                  {showingClosedTrades ? (
                    <>
                      <Cell
                        value={usd(position.fee_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.slippage_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                      <Cell
                        value={usd(position.net_pnl_usd)}
                        tone={signTone(position.net_pnl_usd)}
                        hint={position.cost_unavailable_reason}
                      />
                    </>
                  ) : null}
                  <td className="py-2.5 text-right">
                    <div className="flex flex-col items-end gap-1">
                      <span
                        className={cn(
                          "rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          closed
                            ? "border-line bg-raised text-ink-3"
                            : "border-accent/25 bg-accent/[0.07] text-accent",
                        )}
                      >
                        {closed ? (exitLabel(position.exit_reason) ?? "Closed") : "Open"}
                      </span>
                      {closed ? (
                        <span className="text-[10px] text-ink-3">settled</span>
                      ) : position.current_price_at ? (
                        <FreshnessLabel capturedAt={position.current_price_at} />
                      ) : (
                        <NoMarketData />
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 text-right text-xs">
                    <div className="flex flex-col items-end text-ink-3"
                        title={
                          position.exit_execution_fallback_reason ??
                          position.entry_execution_fallback_reason ??
                          position.exit_execution_route ??
                          position.entry_execution_route ??
                          undefined
                        }>
                      <span className="tabular-nums">
                      {
                        position.target_price && position.stop_price
                          ? `TP ${formatPrice(position.target_price)} / SL ${formatPrice(position.stop_price)}`
                          : position.trailing_activated_at
                            ? formatPrice(position.trailing_stop_price)
                            : position.trailing_activation_multiple
                              ? `Pending ${position.trailing_activation_multiple}x`
                              : position.trailing_stop_price
                                ? `Trail ${formatPrice(position.trailing_stop_price)}`
                                : "—"
                      }
                      </span>
                      {/* The holding rule, stated per row rather than assumed
                          from the live strategy: only positions opened under
                          HOLD-6H carry a cutoff, and the older ones must say
                          so instead of looking like the rule is being
                          ignored. */}
                      {!closed ? (
                        <span className="text-[10px]">
                          {position.expires_at
                            ? `Max hold until ${new Date(position.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                            : `No max hold (Gen ${position.generation ?? "?"} rules)`}
                        </span>
                      ) : null}
                      <span className="text-[10px]">
                      {modelLabel(
                        closed
                          ? position.exit_execution_model_version
                          : position.entry_execution_model_version,
                      )}
                      </span>
                    </div>
                  </td>
                  {onPreviewManualSell ? (
                    <td className="py-2.5 text-right">
                      {closed ? null : (
                        <button
                          type="button"
                          onClick={() => void loadPreview(position.mint_address)}
                          disabled={previewing === position.mint_address}
                          className="rounded-sm border border-line px-2 py-1 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:cursor-wait disabled:opacity-60"
                        >
                          {previewing === position.mint_address ? "Loading" : "Sell"}
                        </button>
                      )}
                    </td>
                  ) : null}
                </tr>
                {selected ? (
                  <tr className="border-b border-line bg-raised/40">
                    <td colSpan={onPreviewManualSell ? 11 : 10} className="py-3">
                      <ManualSellPreviewPanel
                        preview={preview}
                        error={error}
                        isSelling={selling === position.mint_address}
                        onCancel={() => {
                          setPreview(null);
                          setError(null);
                        }}
                        onConfirm={() => void confirmSell(position.mint_address)}
                      />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {error && preview === null ? <p className="mt-2 text-sm text-down">{error}</p> : null}
    </div>
  );
}

function ManualSellPreviewPanel({
  preview,
  error,
  isSelling,
  onCancel,
  onConfirm,
}: {
  preview: ManualSellPreview;
  error: string | null;
  isSelling: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const fields = [
    ["Token", preview.symbol ?? preview.name ?? preview.short_mint],
    ["Mint", preview.short_mint],
    ["Entry", formatPrice(preview.entry_price)],
    ["Observed entry", formatPrice(preview.entry_observed_price)],
    ["Latest", formatPrice(preview.latest_price)],
    ["Entry cap", usd(preview.entry_market_cap)],
    ["Current cap", usd(preview.current_market_cap)],
    ["Liquidity", usd(preview.liquidity_usd)],
    ["Gross P/L", usd(preview.gross_return_usd)],
    ["Fees", usd(preview.fee_usd)],
    ["Slippage", usd(preview.slippage_usd)],
    ["Net P/L", usd(preview.net_return_usd)],
    ["Execution", modelLabel(preview.execution_model_version)],
    ["Price impact", pct(preview.exit_execution_price_impact_pct)],
    ["Route", preview.exit_execution_route],
  ];

  return (
    <div className="rounded-md border border-line bg-canvas p-3 text-left">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-ink">Confirm paper sell</p>
          <p className="mt-0.5 text-xs text-ink-3">
            Uses the latest observed market snapshot. No real order will be placed.
          </p>
        </div>
        <FreshnessLabel capturedAt={preview.quote_observed_at} />
      </div>
      {preview.warning ? (
        <p className="mt-2 rounded-md border border-down/30 bg-down/[0.06] px-2 py-1 text-xs text-down">
          {preview.warning}
        </p>
      ) : null}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-label uppercase tracking-wide text-ink-3">{label}</dt>
            <dd className="mt-0.5 text-sm tabular-nums text-ink">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {preview.cost_unavailable_reason ? (
        <p className="mt-2 text-xs text-ink-3">{preview.cost_unavailable_reason}</p>
      ) : null}
      {preview.execution_fallback_reason ? (
        <p className="mt-2 text-xs text-ink-3">
          Fallback: {preview.execution_fallback_reason}
        </p>
      ) : null}
      {error ? <p className="mt-2 text-sm text-down">{error}</p> : null}
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-sm border border-line px-2.5 py-1 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isSelling}
          className="rounded-sm border border-down/35 bg-down/[0.08] px-2.5 py-1 text-xs text-down transition-colors hover:border-down disabled:cursor-wait disabled:opacity-60"
        >
          {isSelling ? "Selling" : "Confirm sell"}
        </button>
      </div>
    </div>
  );
}



function DurationLabel({ opened, closed }: { opened: string; closed: string | null }) {
  const now = useSharedClock(60000); // 1-minute shared clock
  return <>{durationLabel(opened, closed, now)}</>;
}