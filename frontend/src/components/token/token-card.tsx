"use client";

import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { TokenAvatar } from "@/components/brand/token-avatar";
import { Badge } from "@/components/ui/badge";
import { Meter } from "@/components/ui/metric";
import { StageRail } from "@/components/token/stage-rail";
import { Label } from "@/components/ui/panel";
import { AGENTS } from "@/lib/design/agents";
import { formatAge, formatUsd, shortenAddress } from "@/lib/format";
import { deriveIntelligence, type Signal } from "@/lib/intelligence";
import { lifecycleStage } from "@/lib/lifecycle";
import { cn } from "@/lib/utils";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";

/**
 * The token card.
 *
 * Twelve data points without becoming a spreadsheet. The hierarchy is strict:
 * identity → valuation → the division's four signals → the verdict. A user
 * scanning fast reads only the left edge and the verdict bar; a user
 * evaluating reads everything.
 *
 * Elite Gems are the only cards that get gold, a reticle and a lit border.
 * If more than a few percent of a feed looked like this, it would mean
 * nothing.
 */

function SignalPip({
  signal,
  invert = false,
  pending = false,
}: {
  signal: Signal;
  invert?: boolean;
  pending?: boolean;
}) {
  const spec = AGENTS[signal.agent];
  // Risk is the one signal where a high score is bad — it fills toward danger.
  const tone = invert && signal.score > 0.5 ? "var(--color-danger)" : spec.hue;

  return (
    <div
      className="flex min-w-0 flex-col gap-1.5"
      title={pending ? "Awaiting first market observation" : signal.readout}
    >
      <span className="flex items-center gap-1 text-label uppercase text-ink-faint">
        <AgentSigil agent={signal.agent} size={11} style={{ color: spec.hue }} />
        <span className="truncate">{signal.agent}</span>
      </span>
      {/* An unobserved token gets no verdict at all. Showing a half-full risk
          bar would tell the user "moderately dangerous" when the truth is
          "not yet measured" — the two must never look alike. */}
      {pending ? (
        <span className="h-3 rounded-[2px] border border-dashed border-line" />
      ) : (
        <Meter value={signal.score} segments={5} tone={tone} label={`${signal.agent} signal`} />
      )}
    </div>
  );
}

/**
 * Arrival card — a token discovered but not yet observed.
 *
 * Enrichment lags discovery by a minute or two, so a newest-first feed would
 * otherwise open on a screenful of empty fields. Rendering unobserved tokens as
 * a slim arrival that expands into a full card once the division reports is both
 * more honest than padding them with zeroes and a better read of the product
 * story: you are watching the division work.
 */
function ArrivalCard({
  token,
  className,
  style,
}: {
  token: DiscoveredToken;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <Link
      href={`/tokens/${token.mint_address}`}
      style={style}
      className={cn(
        "group relative flex items-center gap-3 overflow-hidden rounded-panel border border-line/70 bg-surface/40 px-4 py-3 backdrop-blur-xl",
        "transition-[transform,border-color] duration-200 ease-[var(--ease-instrument)] hover:-translate-y-0.5 hover:border-line-bright",
        className,
      )}
    >
      {/* Continuous sweep: the division is actively working this token. */}
      <span
        aria-hidden
        className="ambient pointer-events-none absolute inset-y-0 -left-full w-1/2 bg-gradient-to-r from-transparent via-plasma/8 to-transparent animate-[ticker_2.8s_linear_infinite]"
      />

      <TokenAvatar mint={token.mint_address} size={30} />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-ink">
            {token.name ?? "Unnamed token"}
          </p>
          {token.symbol && (
            <span className="shrink-0 rounded-chip bg-elevated px-1.5 py-0.5 text-[0.625rem] text-ink-dim">
              {token.symbol}
            </span>
          )}
        </div>
        <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-faint">
          <AgentSigil agent="scout" size={11} className="text-scout" />
          Discovered — division analysing
        </p>
      </div>

      <span data-numeric className="shrink-0 text-xs text-ink-faint">
        {formatAge(token.discovered_at)}
      </span>

      <StageRail stage="detected" className="w-28 shrink-0" />
    </Link>
  );
}

export function TokenCard({
  token,
  market,
  className,
  style,
}: {
  token: DiscoveredToken;
  market: MarketSnapshot | null;
  className?: string;
  style?: React.CSSProperties;
}) {
  const intel = deriveIntelligence(token, market);
  const stage = lifecycleStage(token, market, intel);

  if (intel.provisional) {
    return <ArrivalCard token={token} className={className} style={style} />;
  }

  const confidencePct = Math.round(intel.confidence * 100);
  const gemPct = Math.round(intel.gemProbability * 100);

  return (
    <Link
      href={`/tokens/${token.mint_address}`}
      style={style}
      className={cn(
        "group relative block overflow-hidden rounded-panel border bg-surface/70 backdrop-blur-xl",
        "transition-[transform,border-color,box-shadow] duration-250 ease-[var(--ease-instrument)]",
        "hover:-translate-y-1 focus-visible:-translate-y-1",
        intel.elite
          ? "reticle border-apex/45 text-apex shadow-[0_0_0_1px_color-mix(in_oklch,var(--color-apex)_20%,transparent),0_20px_60px_-24px_color-mix(in_oklch,var(--color-apex)_60%,transparent)]"
          : "border-line hover:border-line-bright",
        className,
      )}
    >
      {/* Scan sweep on hover — the instrument re-reading the row. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-16 -translate-y-full bg-gradient-to-b from-plasma/12 to-transparent transition-transform duration-700 ease-[var(--ease-instrument)] group-hover:translate-y-[400%]"
      />

      <div className="relative p-5">
        {/* Identity */}
        <div className="flex items-start gap-3">
          <TokenAvatar mint={token.mint_address} size={42} />

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate font-medium text-ink">
                {token.name ?? "Unnamed token"}
              </p>
              {token.symbol && (
                <span className="shrink-0 rounded-chip bg-elevated px-1.5 py-0.5 text-[0.6875rem] font-medium text-ink-dim">
                  {token.symbol}
                </span>
              )}
            </div>
            <p data-numeric className="mt-0.5 truncate text-xs text-ink-faint">
              {shortenAddress(token.mint_address, 6, 6)}
            </p>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <span data-numeric className="text-xs text-ink-faint">
              {formatAge(token.discovered_at)}
            </span>
            {intel.elite ? (
              <Badge tone="apex">
                <AgentSigil agent="apex" size={11} />
                Elite Gem
              </Badge>
            ) : market?.trading_status === "trading" ? (
              <Badge tone="safe">Trading</Badge>
            ) : (
              <Badge tone="neutral">Pending</Badge>
            )}
          </div>
        </div>

        <StageRail stage={stage} className="mt-4" />

        {/* Valuation */}
        <div className="mt-4 grid grid-cols-3 gap-3">
          {[
            { label: "Market Cap", value: formatUsd(market?.market_cap) },
            { label: "Liquidity", value: formatUsd(market?.liquidity_usd) },
            { label: "Volume 24h", value: formatUsd(market?.volume_24h) },
          ].map((item) => (
            <div key={item.label} className="min-w-0">
              <Label>{item.label}</Label>
              <p data-numeric className="mt-1 truncate text-sm font-medium text-ink">
                {item.value}
              </p>
            </div>
          ))}
        </div>

        {/* Squad signals */}
        <div className="mt-5 grid grid-cols-4 gap-3 border-t border-line pt-4">
          <SignalPip signal={intel.momentum} pending={intel.provisional} />
          <SignalPip signal={intel.whale} pending={intel.provisional} />
          <SignalPip signal={intel.community} pending={intel.provisional} />
          <SignalPip signal={intel.risk} invert pending={intel.provisional} />
        </div>

        {/* Verdict */}
        <div className="mt-4 flex items-center justify-between gap-4 rounded-card bg-abyss/60 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <AgentSigil agent="oracle" size={14} className="text-oracle" />
            <Label>Confidence</Label>
            <span
              data-numeric
              className={cn(
                "text-sm font-medium",
                confidencePct >= 70
                  ? "text-safe"
                  : confidencePct >= 40
                    ? "text-ink"
                    : "text-ink-faint",
              )}
            >
              {intel.provisional ? "—" : `${confidencePct}%`}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Label>Gem</Label>
            <span
              data-numeric
              className={cn(
                "text-sm font-medium",
                intel.elite ? "text-apex" : "text-ink-dim",
              )}
            >
              {intel.provisional ? "—" : `${gemPct}%`}
            </span>
          </div>
        </div>

        {intel.provisional && (
          <p className="mt-3 text-[0.6875rem] text-ink-faint">
            Awaiting first market observation.
          </p>
        )}
      </div>
    </Link>
  );
}
