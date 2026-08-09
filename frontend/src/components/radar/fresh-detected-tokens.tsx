"use client";

import { TokenIdentity } from "@/components/brand/token-identity";
import { FreshnessLabel } from "@/components/ui/freshness";
import { Skeleton } from "@/components/ui/skeleton";
import { useFreshDetectedTokens } from "@/hooks/use-radar";
import { CATEGORY_LABEL } from "@/lib/radar";
import { formatAge, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FreshDetectedToken, RadarCategory } from "@/types/radar";

function statusFor(token: FreshDetectedToken): string {
  if (token.radar_status === "radar") return "Radar";
  if (token.radar_score !== null) return "Scored";
  if (token.current_market_cap !== null || token.current_liquidity !== null) {
    return "Enriching";
  }
  if (token.metadata_status === "pending") return "Detected";
  return "Detected";
}

function categoryLabel(value: string | null): string | null {
  if (!value) return null;
  return CATEGORY_LABEL[value as RadarCategory] ?? value.replaceAll("_", " ");
}

function FreshTokenRow({ token }: { token: FreshDetectedToken }) {
  const status = statusFor(token);
  const exact = new Date(token.discovered_at).toLocaleString();
  return (
    <li className="rounded-card border border-line/60 bg-surface/35 p-3 transition-colors hover:border-line-bright">
      <div className="flex items-start justify-between gap-3">
        <TokenIdentity
          mint={token.mint_address}
          name={token.name}
          symbol={token.symbol}
          imageUrl={token.image_url}
          size="sm"
          className="min-w-0"
        />
        <span
          className={cn(
            "shrink-0 rounded-chip border px-2 py-0.5 text-[0.625rem] uppercase tracking-wide",
            status === "Radar"
              ? "border-plasma/25 bg-plasma/[0.07] text-plasma"
              : "border-line bg-elevated text-ink-faint",
          )}
        >
          {status}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-faint">
        <span title={exact}>Detected {formatAge(token.discovered_at)} ago</span>
        {token.current_market_cap ? (
          <span>{formatUsd(token.current_market_cap)} MCAP</span>
        ) : null}
        {token.current_liquidity ? (
          <span>{formatUsd(token.current_liquidity)} liquidity</span>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="text-ink-dim">
          {token.radar_score !== null
            ? `Radar ${Number(token.radar_score).toFixed(1)}`
            : "Radar pending"}
          {categoryLabel(token.radar_category)
            ? ` · ${categoryLabel(token.radar_category)}`
            : ""}
        </span>
        {token.market_observed_at ? (
          <FreshnessLabel capturedAt={token.market_observed_at} />
        ) : (
          <span className="text-ink-faint">No market quote yet</span>
        )}
      </div>
    </li>
  );
}

export function FreshDetectedTokens() {
  const query = useFreshDetectedTokens(30);

  return (
    <section className="rounded-card border border-line bg-surface/30 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-label uppercase tracking-wide text-plasma">
            Fresh detected tokens
          </p>
          <h2 className="mt-1 text-lg font-semibold text-ink">
            Newest discoveries, before the crowd catches up
          </h2>
          <p className="mt-1 text-xs text-ink-faint">
            Ordered by MEMESCOPE discovery time. Scoring and market enrichment appear
            only when those rows exist.
          </p>
        </div>
        {query.data?.length ? (
          <span className="text-xs text-ink-faint">{query.data.length} latest</span>
        ) : null}
      </div>

      {query.isPending ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-28 rounded-card" />
          ))}
        </div>
      ) : query.isError ? (
        <p className="mt-4 text-sm text-ink-faint">
          Fresh detections are not responding. The main Radar remains independent.
        </p>
      ) : query.data.length === 0 ? (
        <p className="mt-4 text-sm text-ink-faint">
          No discoveries recorded yet. New scanner detections will appear here
          automatically.
        </p>
      ) : (
        <ol className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {query.data.map((token) => (
            <FreshTokenRow key={token.mint_address} token={token} />
          ))}
        </ol>
      )}
    </section>
  );
}
