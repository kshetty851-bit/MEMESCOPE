"use client";

import Link from "next/link";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { TokenAvatar } from "@/components/brand/token-avatar";
import { Badge } from "@/components/ui/badge";
import { Meter } from "@/components/ui/metric";
import { StageRail } from "@/components/token/stage-rail";
import { Label } from "@/components/ui/panel";
import { AGENTS, type AgentId } from "@/lib/design/agents";
import { formatAge, formatUsd, shortenAddress } from "@/lib/format";
import { lifecycleStage } from "@/lib/lifecycle";
import { GRADE_LABEL, GRADE_TONE, freshnessLabel, num, ratio } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";
import type { TokenScore } from "@/types/score";

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

/**
 * One backend-reported figure as a labelled meter.
 *
 * Every value here is served by the scoring API. Nothing is derived on the
 * client, so what the card shows and what `/scores/{mint}` would return cannot
 * drift apart.
 */
function ScorePip({
  label,
  agent,
  value,
  tone,
  title,
}: {
  label: string;
  agent: AgentId;
  /** 0–1. */
  value: number;
  tone?: string;
  title: string;
}) {
  const spec = AGENTS[agent];

  return (
    <div className="flex min-w-0 flex-col gap-1.5" title={title}>
      <span className="flex items-center gap-1 text-label uppercase text-ink-faint">
        <AgentSigil agent={agent} size={11} style={{ color: spec.hue }} />
        <span className="truncate">{label}</span>
      </span>
      <Meter value={value} segments={5} tone={tone ?? spec.hue} label={`${label} signal`} />
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
  score,
  className,
  style,
}: {
  token: DiscoveredToken;
  market: MarketSnapshot | null;
  /** From the scoring API. Null until the engine has evaluated this token. */
  score: TokenScore | null;
  className?: string;
  style?: React.CSSProperties;
}) {
  const stage = lifecycleStage(token, market, score);

  // No score means the division has not reported yet. An arrival card says so
  // rather than rendering meters at zero, which would read as "measured and
  // bad" when the truth is "not yet measured".
  if (!score) {
    return <ArrivalCard token={token} className={className} style={style} />;
  }

  const elite = score.is_elite;
  const scorePct = Math.round(num(score.score));
  const confidencePct = Math.round(num(score.evidence.confidence));
  const freshness = num(score.evidence.freshness);

  return (
    <Link
      href={`/tokens/${token.mint_address}`}
      style={style}
      className={cn(
        "group relative block overflow-hidden rounded-panel border bg-surface/70 backdrop-blur-xl",
        "transition-[transform,border-color,box-shadow] duration-250 ease-[var(--ease-instrument)]",
        "hover:-translate-y-1 focus-visible:-translate-y-1",
        elite
          ? "reticle border-apex/45 text-apex shadow-[0_0_0_1px_color-mix(in_oklch,var(--color-apex)_20%,transparent),0_20px_60px_-24px_color-mix(in_oklch,var(--color-apex)_60%,transparent)]"
          : score.risk.has_veto
            ? "border-danger/40 hover:border-danger/60"
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
            {elite ? (
              <Badge tone="apex">
                <AgentSigil agent="apex" size={11} />
                Elite Gem
              </Badge>
            ) : score.risk.has_veto ? (
              // The risk gate capped this score outright. It outranks the
              // trading state: a tradeable rug is still a rug.
              <Badge tone="danger">
                <AgentSigil agent="sentinel" size={11} />
                Vetoed
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

        {/* Division readouts — every value served by the scoring API.
            Three columns, not four: the overall score is the headline in the
            verdict bar directly below, and repeating it here only squeezed the
            labels until they truncated. */}
        <div className="mt-5 grid grid-cols-3 gap-3 border-t border-line pt-4">
          <ScorePip
            label="Confidence"
            agent="oracle"
            value={ratio(score.evidence.confidence)}
            title={`Evidence ${Math.round(num(score.evidence.evidence))}% discounted by freshness`}
          />
          <ScorePip
            label="Evidence"
            agent="scout"
            value={ratio(score.evidence.evidence)}
            title={`${score.evidence.observations} observations, ${Math.round(
              num(score.evidence.coverage),
            )}% model coverage`}
          />
          <ScorePip
            label="Risk"
            agent="sentinel"
            value={ratio(score.risk.market_risk)}
            tone={
              num(score.risk.market_risk) > 50 ? "var(--color-danger)" : AGENTS.sentinel.hue
            }
            title={
              score.risk.has_veto
                ? "Risk gate vetoed this token — score capped"
                : `Market risk ${Math.round(num(score.risk.market_risk))} of 100`
            }
          />
        </div>

        {/* Verdict */}
        <div className="mt-4 flex items-center justify-between gap-4 rounded-card bg-abyss/60 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <AgentSigil agent="oracle" size={14} className="text-oracle" />
            <Label>Grade</Label>
            <span
              className="text-sm font-medium"
              style={{ color: GRADE_TONE[score.grade] }}
            >
              {GRADE_LABEL[score.grade]}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Label>Score</Label>
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
              {scorePct}
            </span>
          </div>
        </div>

        {/* Provenance: which model, how fresh, and when it last ran. */}
        <p className="mt-3 flex items-center gap-2 text-[0.6875rem] text-ink-faint">
          <span>{freshnessLabel(freshness)}</span>
          <span aria-hidden>·</span>
          <span data-numeric>{formatAge(score.evaluated_at)} ago</span>
          <span aria-hidden>·</span>
          <span>{score.model_version}</span>
        </p>
      </div>
    </Link>
  );
}
