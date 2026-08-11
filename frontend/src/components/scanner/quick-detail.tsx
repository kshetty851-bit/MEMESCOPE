"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";

import { RowActions } from "@/components/scanner/row-actions";
import { EvidenceDots, RadarScore } from "@/components/scanner/radar-score";
import { Delta } from "@/components/ui/delta";
import { FreshnessLabel, NoMarketData } from "@/components/ui/freshness";
import { Num } from "@/components/ui/num";
import { RiskChip } from "@/components/ui/risk-chip";
import { Sheet } from "@/components/ui/sheet";
import { Sparkline } from "@/components/ui/sparkline";
import { Stat } from "@/components/ui/stat";
import { api } from "@/lib/api-client";
import { buySellPressure, type RankedEntry } from "@/lib/scanner";
import { baseRateSummary, compactAge, compactUsd, expiresIn } from "@/lib/radar-row";
import { formatMultiple } from "@/lib/radar";
import { cn } from "@/lib/utils";
import type { MarketHistoryPage, TokenMarket } from "@/types/api";

/**
 * QUICK INTELLIGENCE — the middle step between a row and the dossier.
 *
 * The card carried the why-now sentence, the base rate and the evidence inline,
 * which is exactly why it was 160px tall and why ten of them filled a screen.
 * None of that information is lost; it moved behind one click.
 *
 * What this panel is **not** is a copy of `/tokens/[mint]`. It answers one
 * question — "is this worth opening properly?" — and every path out of it leads
 * to the full page. Two things are fetched that the scanner list cannot carry:
 *
 *   - transaction counts, because `MarketStripOut` on the list response has no
 *     buy/sell fields (they live on the per-token market snapshot);
 *   - price history for the sparkline, because the list carries no series.
 *
 * Both are per-token by nature, which is why they are here and not columns.
 * The query keys match the token page's exactly, so opening the dossier next
 * reuses this cache rather than refetching, and the live-update invalidations
 * already target them.
 */

function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-t border-line-subtle pt-3", className)}>
      <h3 className="text-label font-medium uppercase text-ink-3">{title}</h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function QuickDetail({
  entry,
  onClose,
}: {
  entry: RankedEntry | null;
  onClose: () => void;
}) {
  const mint = entry?.mint_address;

  const market = useQuery({
    queryKey: ["tokens", mint, "market"],
    queryFn: () => api.get<TokenMarket>(`/tokens/${mint}/market`),
    enabled: Boolean(mint),
  });

  const history = useQuery({
    queryKey: ["tokens", mint, "history", 1],
    queryFn: () =>
      api.get<MarketHistoryPage>(`/tokens/${mint}/history?page=1&page_size=25`),
    enabled: Boolean(mint),
  });

  // The API returns newest first; a trace reads oldest to newest.
  const trace = useMemo(() => {
    const items = history.data?.items ?? [];
    return items
      .map((row) => Number(row.price_usd ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0)
      .reverse();
  }, [history.data]);

  const snapshot = market.data?.market ?? null;
  const pressure = buySellPressure(snapshot?.buy_count_24h, snapshot?.sell_count_24h);
  const rate = entry ? baseRateSummary(entry.base_rate) : null;

  if (!entry) return null;

  return (
    <Sheet
      open
      onClose={onClose}
      eyebrow={`Rank ${entry.rank} · quick intelligence`}
      title={entry.symbol?.trim() || entry.name?.trim() || "Token"}
      header={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <RadarScore score={entry.opportunity_score} category={entry.category} />
            <RiskChip band={entry.risk_band} reasons={entry.risk_reasons} />
            <EvidenceDots evidence={entry.evidence} />
          </div>
          <RowActions mint={entry.mint_address} symbol={entry.symbol} />
        </div>
      }
      footer={
        <Link
          href={`/tokens/${entry.mint_address}`}
          className={cn(
            "flex h-9 w-full items-center justify-center rounded-md",
            "border border-accent/40 bg-accent/10 text-sm font-medium text-accent",
            "transition-colors duration-[var(--duration-instant)]",
            "hover:border-accent/70 hover:bg-accent/16",
          )}
        >
          Open full token intelligence
        </Link>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Why now — rendered by the backend, displayed verbatim. Nothing on
            this screen composes prose about a token. */}
        {entry.why_now ? (
          <p className="text-sm leading-relaxed text-ink">{entry.why_now.sentence}</p>
        ) : null}

        {entry.signal ? (
          <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className="rounded-sm border border-accent/25 bg-accent/[0.08] px-1.5 py-0.5 text-accent">
              {entry.signal.label}
            </span>
            <span className="text-ink-3">
              Expires in {expiresIn(entry.signal.expires_in_seconds) ?? "—"}
            </span>
          </p>
        ) : null}

        <div className="grid grid-cols-2 gap-x-4 gap-y-3">
          <Stat
            label="Price"
            display={compactUsd(entry.market?.price_usd)}
            value={entry.market?.price_usd}
            size="sm"
          />
          <Stat
            label="Market cap"
            display={compactUsd(entry.market?.market_cap)}
            value={entry.market?.market_cap}
            size="sm"
          />
          <Stat
            label="Liquidity"
            display={compactUsd(entry.market?.liquidity_usd)}
            value={entry.market?.liquidity_usd}
            size="sm"
          />
          <Stat
            label="Volume 24h"
            display={compactUsd(entry.market?.volume_24h)}
            value={entry.market?.volume_24h}
            size="sm"
          />
          <Stat label="Age" display={compactAge(entry.age_seconds)} value={entry.age_seconds} size="sm" />
          <Stat label="Change 24h" size="sm">
            <Delta value={entry.market?.change_24h_pct} size="md" />
          </Stat>
        </div>

        {/* Peak and current, always together. A call that reached 18x and gave
            it back is not an 18x call. */}
        <Section title="Since detection">
          <div className="flex items-baseline gap-6">
            <span className="flex flex-col gap-0.5">
              <span className="text-label uppercase text-ink-3">Current</span>
              <Num
                value={entry.current_multiple}
                display={formatMultiple(entry.current_multiple)}
                signed
                pivot={1}
                className="text-sm font-medium"
              />
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-label uppercase text-ink-3">Peak</span>
              <Num
                value={entry.peak_multiple}
                display={formatMultiple(entry.peak_multiple)}
                signed
                pivot={1}
                className="text-sm font-medium"
              />
            </span>
          </div>
        </Section>

        {trace.length > 1 ? (
          <Section title="Recent price">
            <Sparkline points={trace} width={300} height={44} />
            <p className="mt-1.5 text-xs text-ink-3">
              Last {trace.length} stored observations. Not a chart of the market —
              it is what MEMESCOPE recorded.
            </p>
          </Section>
        ) : null}

        <Section title="Transactions 24h">
          {pressure ? (
            <>
              <div
                className="flex h-1.5 overflow-hidden rounded-full bg-line"
                role="img"
                aria-label={`${pressure.buys} buy and ${pressure.sells} sell transactions in 24 hours, ${pressure.buyPct.toFixed(0)} percent buys`}
              >
                <span className="bg-up" style={{ width: `${pressure.buyPct}%` }} />
                <span className="bg-down" style={{ width: `${100 - pressure.buyPct}%` }} />
              </div>
              <p data-numeric className="mt-2 flex items-baseline gap-3 text-xs">
                <span className="text-up">{pressure.buys.toLocaleString()} buys</span>
                <span className="text-down">{pressure.sells.toLocaleString()} sells</span>
                <span className="text-ink-3">
                  {pressure.buyPct.toFixed(0)}% buy
                </span>
              </p>
              {/* Said explicitly, every time. One wallet can produce a hundred
                  of these and the API cannot tell us that. */}
              <p className="mt-1.5 text-xs text-ink-3">
                Transaction counts, not unique wallets. MEMESCOPE has no holder
                data for this token.
              </p>
            </>
          ) : market.isPending ? (
            <p className="text-xs text-ink-3">Loading…</p>
          ) : (
            <p className="text-xs text-ink-3">
              No transaction counts recorded for this token.
            </p>
          )}
        </Section>

        {entry.risk_reasons.length > 0 ? (
          <Section title="Risk notes">
            <ul className="flex flex-col gap-1">
              {entry.risk_reasons.map((reason) => (
                <li key={reason} className="text-xs leading-relaxed text-ink-2">
                  {reason}
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {rate ? (
          <Section title="Similar historical signals">
            {rate.quotable ? (
              <div className="flex flex-col gap-1">
                <p className="text-sm text-ink">{rate.headline}</p>
                <p data-numeric className="flex flex-wrap gap-x-4 text-xs text-ink-2">
                  {rate.lines.map((line) => (
                    <span key={line}>{line}</span>
                  ))}
                </p>
                <p data-numeric className="flex flex-wrap gap-x-4 text-xs text-ink-3">
                  <span>Median peak {formatMultiple(entry.base_rate?.median_peak_multiple)}</span>
                  <span>Median now {formatMultiple(entry.base_rate?.median_current_multiple)}</span>
                </p>
              </div>
            ) : (
              <p className="text-xs leading-relaxed text-ink-3">{rate.lines[0]}</p>
            )}
            <p className="mt-2 text-xs leading-relaxed text-ink-3">
              Measured over past detections in this category, losers included. It
              makes no claim about this token.
            </p>
          </Section>
        ) : null}

        <Section title="Data">
          {entry.market?.captured_at ? (
            <FreshnessLabel capturedAt={entry.market.captured_at} withDot />
          ) : (
            <NoMarketData />
          )}
          {entry.market?.dex_name ? (
            <p className="mt-1.5 text-xs text-ink-3">Pool on {entry.market.dex_name}</p>
          ) : null}
        </Section>
      </div>
    </Sheet>
  );
}
