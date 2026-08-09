"use client";

import { Fragment, useState } from "react";

import { TokenIdentity } from "@/components/brand/token-identity";
import { FreshnessLabel, NoMarketData } from "@/components/ui/freshness";
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
}: {
  value: string | null;
  tone?: "positive" | "negative" | "neutral";
  className?: string;
}) {
  return (
    <td
      className={cn(
        "py-2.5 text-right tabular-nums",
        value === null && "text-ink-faint",
        tone === "positive" && "text-safe",
        tone === "negative" && "text-danger",
        (!tone || tone === "neutral") && value !== null && "text-ink-dim",
        className,
      )}
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
    return <p className="text-sm text-ink-faint">{emptyLabel}</p>;
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
      <table className="w-full min-w-[1040px] text-sm">
        <thead>
          <tr className="border-b border-line text-label uppercase tracking-wide text-ink-faint">
            <th className="py-2 text-left font-medium">Token</th>
            <th className="py-2 text-right font-medium">Entry</th>
            <th className="py-2 text-right font-medium">Trailing stop</th>
            <th className="py-2 text-right font-medium">
              {positions[0]?.status === "closed" ? "Exit" : "Current"}
            </th>
            <th className="py-2 text-right font-medium">Result</th>
            <th className="py-2 text-right font-medium">Peak</th>
            <th className="py-2 text-right font-medium">P/L</th>
            <th className="py-2 text-right font-medium">Execution</th>
            <th className="py-2 text-right font-medium">Status</th>
            <th className="py-2 text-right font-medium">Quote</th>
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
                <tr
                  className="border-b border-line/50 transition-colors hover:bg-elevated/40"
                >
                  <td className="py-2.5 pr-4">
                    <TokenIdentity
                      mint={position.mint_address}
                      name={position.name}
                      symbol={position.symbol}
                      imageUrl={position.image_url}
                      size="xs"
                      showMint={false}
                    />
                    <span className="ml-2 text-xs text-ink-faint">
                      #{position.entry_rank} at entry
                    </span>
                  </td>
                  <Cell value={formatPrice(position.entry_price)} />
                  <Cell value={formatPrice(position.trailing_stop_price)} />
                  <Cell value={formatPrice(position.current_price)} />
                  <Cell
                    value={pct(position.current_pct)}
                    tone={signTone(position.current_pct)}
                  />
                  <Cell value={pct(position.peak_pct)} tone="neutral" />
                  <Cell value={usd(position.pnl_usd)} tone={signTone(position.pnl_usd)} />
                  <td
                    className="py-2.5 text-right text-xs text-ink-faint"
                    title={
                      position.exit_execution_fallback_reason ??
                      position.entry_execution_fallback_reason ??
                      position.exit_execution_route ??
                      position.entry_execution_route ??
                      undefined
                    }
                  >
                    {modelLabel(
                      closed
                        ? position.exit_execution_model_version
                        : position.entry_execution_model_version,
                    )}
                  </td>
                  <td className="py-2.5 text-right">
                    <span
                      className={cn(
                        "rounded-chip border px-1.5 py-0.5 text-label uppercase tracking-wide",
                        closed
                          ? "border-line bg-elevated text-ink-faint"
                          : "border-plasma/25 bg-plasma/[0.07] text-plasma",
                      )}
                    >
                      {closed ? (exitLabel(position.exit_reason) ?? "Closed") : "Open"}
                    </span>
                  </td>
                  {/* An open position is marked to a stored reading, not to a
                      live quote. Saying when it was observed is the difference
                      between a mark and a claim. A closed trade settled at its
                      exit and shows nothing here — a finished result cannot go
                      stale. */}
                  <td className="py-2.5 text-right">
                    {closed ? (
                      <span className="text-xs text-ink-faint">settled</span>
                    ) : position.current_price_at ? (
                      <FreshnessLabel capturedAt={position.current_price_at} />
                    ) : (
                      <NoMarketData />
                    )}
                  </td>
                  {onPreviewManualSell ? (
                    <td className="py-2.5 text-right">
                      {closed ? null : (
                        <button
                          type="button"
                          onClick={() => void loadPreview(position.mint_address)}
                          disabled={previewing === position.mint_address}
                          className="rounded-chip border border-line px-2 py-1 text-xs text-ink-dim transition-colors hover:border-line-bright hover:text-ink disabled:cursor-wait disabled:opacity-60"
                        >
                          {previewing === position.mint_address ? "Loading" : "Sell"}
                        </button>
                      )}
                    </td>
                  ) : null}
                </tr>
                {selected ? (
                  <tr className="border-b border-line bg-elevated/40">
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
      {error && preview === null ? (
        <p className="mt-2 text-sm text-danger">{error}</p>
      ) : null}
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
          <p className="mt-0.5 text-xs text-ink-faint">
            Uses the latest observed market snapshot. No real order will be placed.
          </p>
        </div>
        <FreshnessLabel capturedAt={preview.quote_observed_at} />
      </div>
      {preview.warning ? (
        <p className="mt-2 rounded-md border border-danger/30 bg-danger/[0.06] px-2 py-1 text-xs text-danger">
          {preview.warning}
        </p>
      ) : null}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-label uppercase tracking-wide text-ink-faint">{label}</dt>
            <dd className="mt-0.5 text-sm tabular-nums text-ink">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {preview.cost_unavailable_reason ? (
        <p className="mt-2 text-xs text-ink-faint">{preview.cost_unavailable_reason}</p>
      ) : null}
      {preview.execution_fallback_reason ? (
        <p className="mt-2 text-xs text-ink-faint">
          Fallback: {preview.execution_fallback_reason}
        </p>
      ) : null}
      {error ? <p className="mt-2 text-sm text-danger">{error}</p> : null}
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-chip border border-line px-2.5 py-1 text-xs text-ink-dim transition-colors hover:border-line-bright hover:text-ink"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isSelling}
          className="rounded-chip border border-danger/35 bg-danger/[0.08] px-2.5 py-1 text-xs text-danger transition-colors hover:border-danger disabled:cursor-wait disabled:opacity-60"
        >
          {isSelling ? "Selling" : "Confirm sell"}
        </button>
      </div>
    </div>
  );
}
