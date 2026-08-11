"use client";

import { Delta } from "@/components/ui/delta";
import { FreshnessLabel, NoMarketData } from "@/components/ui/freshness";
import { Num } from "@/components/ui/num";
import { RiskChip } from "@/components/ui/risk-chip";
import { ScoreBadge } from "@/components/ui/score-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat } from "@/components/ui/stat";
import { InfoTip } from "@/components/ui/tooltip";
import { num } from "@/lib/design/bands";
import { formatMultiple } from "@/lib/radar";
import { compactUsd } from "@/lib/radar-row";
import { STATUS_MESSAGE } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { MarketSnapshot } from "@/types/api";
import type { RadarEntry } from "@/types/radar";
import type { ScoreStatus, TokenScore } from "@/types/score";

/**
 * THE VERDICT BAND — everything a decision needs, above the fold.
 *
 * The page this replaces had no prominent score anywhere. The number the whole
 * product is built on appeared only as a line inside a narrative panel two
 * scrolls down, while the top of the page was given to a market table. On the
 * one screen where MEMESCOPE has a real `ScoreGrade` from the backend, the
 * score was the least visible thing on it.
 *
 * Three blocks, left to right in decision order: **what MEMESCOPE thinks**
 * (score, grade, elite), **what could go wrong** (risk band, veto), and **what
 * it is worth** (price and size). Everything else on the page explains one of
 * these three.
 *
 * Unlike the scanner, this screen *can* use `ScoreBadge` properly: `/scores/
 * {mint}` returns the engine's own `ScoreGrade`, so the band is read rather
 * than derived. No threshold is applied here.
 */
export function VerdictBand({
  score,
  scoreStatus,
  isScorePending,
  radar,
  snapshot,
  capturedAt,
}: {
  score: TokenScore | null;
  scoreStatus: ScoreStatus | undefined;
  isScorePending: boolean;
  radar: RadarEntry | undefined;
  snapshot: MarketSnapshot | null;
  capturedAt: string | null | undefined;
}) {
  const evidence = score?.evidence;

  return (
    <section
      aria-label="Verdict"
      className="grid gap-px overflow-hidden rounded-lg border border-line bg-line lg:grid-cols-[auto_minmax(0,1fr)]"
    >
      {/* --- Conviction ------------------------------------------------- */}
      <div className="flex items-center gap-5 bg-surface px-5 py-4">
        {isScorePending ? (
          <Skeleton className="size-[104px] rounded-full" />
        ) : (
          <ScoreBadge
            score={score?.score}
            grade={score?.grade}
            isElite={score?.is_elite ?? false}
            variant="dial"
          />
        )}

        <div className="flex min-w-0 flex-col gap-2">
          {/* An unscored token is a backend state, not an error, and each state
              has its own sentence. */}
          {!isScorePending && !score ? (
            <p className="max-w-[16rem] text-xs leading-relaxed text-ink-3">
              {(scoreStatus && STATUS_MESSAGE[scoreStatus]) ??
                "No score has been published for this token."}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <RiskChip band={radar?.risk_band} reasons={radar?.risk_reasons} />
            {score?.risk.has_veto ? (
              <span className="rounded-sm border border-down/35 bg-down/10 px-1.5 py-0.5 text-label font-medium uppercase text-down">
                Risk gate engaged
                <span className="sr-only">
                  — the score was capped regardless of every other signal
                </span>
              </span>
            ) : null}
          </div>

          {evidence ? (
            <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              <div className="flex items-baseline gap-1.5">
                <dt className="text-ink-3">Evidence</dt>
                <dd>
                  <Num
                    value={evidence.evidence}
                    format={(v) => `${Math.round(Number(v))}%`}
                    tone="flat"
                  />
                </dd>
              </div>
              <div className="flex items-baseline gap-1.5">
                <dt className="text-ink-3">Coverage</dt>
                <dd>
                  <Num
                    value={evidence.coverage}
                    format={(v) => `${Math.round(Number(v))}%`}
                    tone="flat"
                  />
                </dd>
              </div>
              <div className="flex items-baseline gap-1.5">
                <dt className="text-ink-3">Observations</dt>
                <dd>
                  <Num value={evidence.observations} tone="flat" />
                </dd>
              </div>
              <InfoTip
                label="evidence and coverage"
                content="Coverage is the share of the model's weight that could be applied to this token. Evidence discounts that by how deeply it was observed. Both describe MEMESCOPE's data, not the project."
              />
            </dl>
          ) : null}
        </div>
      </div>

      {/* --- Market ------------------------------------------------------ */}
      <div className="flex flex-col justify-center gap-3 bg-surface px-5 py-4">
        <div className="grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-3 xl:grid-cols-5">
          <Stat
            label="Price"
            value={snapshot?.price_usd}
            display={compactUsd(snapshot?.price_usd)}
            size="md"
          />
          <Stat
            label="Market cap"
            value={snapshot?.market_cap}
            display={compactUsd(snapshot?.market_cap)}
            size="md"
          />
          <Stat
            label="Liquidity"
            value={snapshot?.liquidity_usd}
            display={compactUsd(snapshot?.liquidity_usd)}
            size="md"
          />
          <Stat
            label="Volume 24h"
            value={snapshot?.volume_24h}
            display={compactUsd(snapshot?.volume_24h)}
            size="md"
          />
          <Stat label="Change 24h" size="md">
            <Delta value={radar?.market?.change_24h_pct} size="md" />
          </Stat>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line-subtle pt-3">
          {/* Peak and current, never one without the other. */}
          <span className="flex items-baseline gap-2">
            <span className="text-label uppercase text-ink-3">Now</span>
            <Num
              value={radar?.current_multiple}
              display={formatMultiple(radar?.current_multiple)}
              signed
              pivot={1}
              className="text-sm font-medium"
            />
          </span>
          <span className="flex items-baseline gap-2">
            <span className="text-label uppercase text-ink-3">Peak</span>
            <Num
              value={radar?.peak_multiple}
              display={formatMultiple(radar?.peak_multiple)}
              tone="muted"
              className="text-sm font-medium"
            />
          </span>
          {radar ? <Retention radar={radar} /> : null}

          <span className="ml-auto">
            {capturedAt ? (
              <FreshnessLabel capturedAt={capturedAt} withDot />
            ) : (
              <NoMarketData />
            )}
          </span>
        </div>
      </div>
    </section>
  );
}

/**
 * How much of the peak is still held.
 *
 * Arithmetic on two published figures, not a judgement — and the single most
 * decision-relevant thing on the band: a token grinding upward and one that
 * round-tripped show the same `Now ×`.
 */
function Retention({ radar }: { radar: RadarEntry }) {
  const peak = num(radar.peak_multiple);
  const current = num(radar.current_multiple);
  if (peak === null || current === null || peak <= 0) return null;

  const givenBack = Math.round((1 - current / peak) * 100);
  if (givenBack <= 0) return null;

  return (
    <span
      className={cn(
        "flex items-baseline gap-2",
        givenBack >= 50 ? "text-down" : "text-ink-2",
      )}
    >
      <span className="text-label uppercase text-ink-3">Off peak</span>
      <span data-numeric className="text-sm font-medium">
        −{givenBack}%
      </span>
    </span>
  );
}
