"use client";

import { useMemo } from "react";

import { Num } from "@/components/ui/num";
import { RiskChip } from "@/components/ui/risk-chip";
import { InfoTip } from "@/components/ui/tooltip";
import { tokenNarrative, type Statement } from "@/lib/sentinel";
import { STATUS_MESSAGE } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";
import type { ScoreStatus, TokenScore } from "@/types/score";

/**
 * THE RISK READ.
 *
 * Was `SentinelRead` — the same statements, staged as a named character with a
 * coloured sigil, a breathing dot animation and a hue of its own. The
 * statements were always the backend's; the costume was ours. This keeps the
 * former and drops the latter.
 *
 * The detail view is the only place the engine's `reasons` exist — the ranking
 * endpoint omits them because a list is scanned rather than read — so this is
 * the only surface that can name a specific finding. It orders and presents
 * them. It does not write them.
 *
 * Where a token has no score, it says which of the engine's states applies
 * rather than filling the space with something reassuring.
 */

const TONE: Record<Statement["tone"], string> = {
  neutral: "bg-ink-3",
  positive: "bg-up",
  caution: "bg-warn",
  critical: "bg-down",
};

export function RiskRead({
  score,
  status,
  radar,
  isPending = false,
  className,
}: {
  score: TokenScore | null;
  status: ScoreStatus | undefined;
  radar: RadarEntry | undefined;
  /** The score query is still in flight — distinct from having no score. */
  isPending?: boolean;
  className?: string;
}) {
  const statements = useMemo(() => (score ? tokenNarrative(score) : []), [score]);

  return (
    <section className={cn("flex flex-col gap-3", className)} aria-labelledby="risk-read">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h2
          id="risk-read"
          className="flex items-center gap-1.5 text-sm font-medium tracking-tight text-ink"
        >
          Risk
          <InfoTip
            label="the risk read"
            content="An interpretation of the scoring engine's own output, not independent analysis. Every sentence below was rendered by the backend from a stored reason code."
          />
        </h2>

        <div className="flex items-center gap-3">
          <RiskChip band={radar?.risk_band} reasons={radar?.risk_reasons} />
          {score ? (
            <span className="flex items-baseline gap-1.5 text-xs">
              <span className="text-ink-3">Market risk</span>
              <Num
                value={score.risk.market_risk}
                format={(v) => `${Math.round(Number(v))}`}
                tone="flat"
              />
              <span className="text-ink-4">/ 100</span>
            </span>
          ) : null}
        </div>
      </header>

      {score?.risk.has_veto ? (
        <p className="rounded-md border border-down/30 bg-down/[0.07] px-3 py-2 text-xs leading-relaxed text-down">
          The risk gate capped this score outright, regardless of every other
          signal.
        </p>
      ) : null}

      <div aria-live="polite">
        {isPending ? (
          // "Still fetching" and "there is nothing to say" are different claims.
          <p className="text-sm text-ink-3">Reading the engine output…</p>
        ) : statements.length === 0 ? (
          <p className="text-sm text-ink-3">
            {(status && STATUS_MESSAGE[status]) ??
              "No readout available for this token yet."}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {statements.map((statement) => (
              <li
                key={statement.id}
                className="flex gap-2.5 text-sm leading-relaxed text-ink-2"
              >
                <span
                  aria-hidden
                  className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", TONE[statement.tone])}
                />
                <span className="min-w-0">{statement.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {radar?.risk_reasons.length ? (
        <div className="border-t border-line-subtle pt-3">
          <p className="text-label font-medium uppercase text-ink-3">Radar risk notes</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {radar.risk_reasons.map((reason) => (
              <li key={reason} className="text-xs leading-relaxed text-ink-2">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
