"use client";

import { Num } from "@/components/ui/num";
import { Stat, StatRow } from "@/components/ui/stat";
import { buySellPressure } from "@/lib/scanner";
import { compactUsd } from "@/lib/radar-row";
import { formatCount, shortenAddress } from "@/lib/format";
import { cn, formatDate } from "@/lib/utils";
import type { DiscoveredToken, MarketSnapshot, TokenMarket } from "@/types/api";

/**
 * MARKET AND PROVENANCE.
 *
 * Two things a dossier has to answer that the verdict band deliberately does
 * not: what the flow looks like across three windows, and where any of this
 * came from.
 *
 * The transaction split reuses `buySellPressure` from the scanner rather than
 * dividing inline — which is what keeps the 0/0 guard, the missing-count guard
 * and the "transactions, not wallets" wording identical on both screens.
 */

function TxSplit({ snapshot }: { snapshot: MarketSnapshot }) {
  const pressure = buySellPressure(snapshot.buy_count_24h, snapshot.sell_count_24h);

  if (!pressure) {
    return (
      <p className="text-xs text-ink-3">
        No transaction counts recorded in the last 24 hours.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        className="flex h-1.5 overflow-hidden rounded-full bg-line"
        role="img"
        aria-label={`${pressure.buys} buy and ${pressure.sells} sell transactions in 24 hours, ${pressure.buyPct.toFixed(0)} percent buys`}
      >
        <span className="bg-up" style={{ width: `${pressure.buyPct}%` }} />
        <span className="bg-down" style={{ width: `${100 - pressure.buyPct}%` }} />
      </div>
      <p data-numeric className="flex flex-wrap items-baseline gap-x-4 text-xs">
        <span className="text-up">{formatCount(pressure.buys)} buys</span>
        <span className="text-down">{formatCount(pressure.sells)} sells</span>
        <span className="text-ink-3">{pressure.buyPct.toFixed(0)}% buy</span>
      </p>
      {/* Stated every time this renders, on every surface. */}
      <p className="text-xs leading-relaxed text-ink-3">
        Transaction counts, not unique wallets. One wallet can produce many, and
        MEMESCOPE has no holder data for this token.
      </p>
    </div>
  );
}

export function MarketPanel({
  market,
  token,
  className,
}: {
  market: TokenMarket | undefined;
  token: DiscoveredToken | undefined;
  className?: string;
}) {
  const snapshot = market?.market ?? null;

  const provenance: { label: string; value: string | null }[] = [
    { label: "Pair", value: snapshot?.trading_pair ?? null },
    { label: "DEX", value: snapshot?.dex_name ?? null },
    {
      label: "Pool",
      value: snapshot?.pool_address ? shortenAddress(snapshot.pool_address, 6, 6) : null,
    },
    {
      label: "Creator",
      value: token?.creator_address ? shortenAddress(token.creator_address, 6, 6) : null,
    },
    {
      label: "Discovered",
      value: token?.discovered_at ? formatDate(token.discovered_at) : null,
    },
    {
      label: "On chain",
      value: token?.block_time ? formatDate(token.block_time) : null,
    },
    { label: "Observations", value: market ? String(market.snapshot_count) : null },
    { label: "Refresh tier", value: market?.tier ?? null },
    { label: "Provider", value: snapshot?.provider ?? null },
  ];

  return (
    <div className={cn("flex flex-col gap-5", className)}>
      <section className="flex flex-col gap-2.5">
        <h2 className="text-sm font-medium tracking-tight text-ink">Flow</h2>
        {snapshot ? (
          <>
            <StatRow className="grid-cols-3">
              <Stat
                label="Volume 5m"
                value={snapshot.volume_5m}
                display={compactUsd(snapshot.volume_5m)}
                size="sm"
              />
              <Stat
                label="Volume 1h"
                value={snapshot.volume_1h}
                display={compactUsd(snapshot.volume_1h)}
                size="sm"
              />
              <Stat
                label="Volume 24h"
                value={snapshot.volume_24h}
                display={compactUsd(snapshot.volume_24h)}
                size="sm"
              />
            </StatRow>
            <TxSplit snapshot={snapshot} />
          </>
        ) : (
          <p className="text-xs text-ink-3">
            No pool has been indexed for this token yet, so there is no flow to
            report. It is still being polled.
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2.5">
        <h2 className="text-sm font-medium tracking-tight text-ink">Valuation</h2>
        <StatRow className="grid-cols-2">
          <Stat
            label="Fully diluted"
            value={snapshot?.fully_diluted_valuation}
            display={compactUsd(snapshot?.fully_diluted_valuation)}
            size="sm"
          />
          <Stat
            label="Price (native)"
            value={snapshot?.price_native}
            display={
              snapshot?.price_native
                ? `${Number(snapshot.price_native).toPrecision(4)} SOL`
                : null
            }
            size="sm"
          />
        </StatRow>
      </section>

      <section className="flex flex-col gap-2.5">
        <h2 className="text-sm font-medium tracking-tight text-ink">Provenance</h2>
        <dl className="flex flex-col divide-y divide-line-subtle">
          {provenance.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-4 py-1.5">
              <dt className="text-xs text-ink-3">{row.label}</dt>
              <dd className="min-w-0 truncate text-right">
                {row.value === null ? (
                  <Num value={null} absentLabel={`${row.label} not recorded`} />
                ) : (
                  <span data-numeric className="text-xs text-ink-2">
                    {row.value}
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
