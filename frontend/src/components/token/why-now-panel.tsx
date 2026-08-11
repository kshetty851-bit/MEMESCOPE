"use client";

import { EvidenceDots, RadarScore } from "@/components/scanner/radar-score";
import { Num } from "@/components/ui/num";
import { InfoTip } from "@/components/ui/tooltip";
import { formatMultiple } from "@/lib/radar";
import { baseRateSummary, compactAge, expiresIn } from "@/lib/radar-row";
import { cn } from "@/lib/utils";
import type { RadarEntry } from "@/types/radar";

/**
 * WHY THIS TOKEN, WHY NOW.
 *
 * The one section on the page that is pure backend prose. `why_now.sentence`,
 * the signal label and the base-rate wording all arrive rendered from stored
 * codes; this component chooses the order and the typography and writes nothing
 * of its own about any token.
 *
 * That rule is why the base rate reads the way it does. Below the published
 * minimum sample the API sends `insufficient_reason` instead of percentages,
 * and this prints that verbatim — a rate from three detections is noise wearing
 * the costume of evidence, and the threshold that decides so lives in the
 * engine, not here.
 */
export function WhyNowPanel({
  radar,
  className,
}: {
  radar: RadarEntry | undefined;
  className?: string;
}) {
  if (!radar) {
    return (
      <section className={cn("flex flex-col gap-2", className)}>
        <h2 className="text-sm font-medium tracking-tight text-ink">Why now</h2>
        <p className="text-sm leading-relaxed text-ink-3">
          This token is not currently on the Radar, so there is no detection
          context for it. That is not a verdict — most discovered tokens are
          never ranked.
        </p>
      </section>
    );
  }

  const rate = baseRateSummary(radar.base_rate);

  return (
    <section className={cn("flex flex-col gap-3", className)} aria-labelledby="why-now">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="why-now" className="text-sm font-medium tracking-tight text-ink">
          Why now
        </h2>
        <div className="flex items-center gap-3">
          <span className="flex items-baseline gap-1.5 text-xs">
            <span className="text-ink-3">Age</span>
            <Num
              value={radar.age_seconds}
              display={compactAge(radar.age_seconds)}
              tone="flat"
            />
          </span>
          <span className="flex items-center gap-1.5 text-xs">
            <span className="text-ink-3">Evidence</span>
            <EvidenceDots evidence={radar.evidence} />
          </span>
          <RadarScore score={radar.opportunity_score} category={radar.category} />
        </div>
      </header>

      {/* Rendered by the backend. Displayed verbatim. */}
      {radar.why_now ? (
        <p className="text-sm leading-relaxed text-ink">{radar.why_now.sentence}</p>
      ) : null}

      {radar.signal ? (
        <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
          <span className="rounded-sm border border-accent/25 bg-accent/[0.08] px-1.5 py-0.5 text-accent">
            {radar.signal.label}
          </span>
          <span className="text-ink-3">
            Expires in {expiresIn(radar.signal.expires_in_seconds) ?? "—"}
          </span>
        </p>
      ) : null}

      {radar.detection_reason.length > 0 ? (
        <div>
          <p className="text-label font-medium uppercase text-ink-3">
            Conditions met at detection
          </p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {radar.detection_reason.map((reason) => (
              <li key={reason} className="text-xs leading-relaxed text-ink-2">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {rate ? (
        <div className="border-t border-line-subtle pt-3">
          <p className="flex items-center gap-1.5 text-label font-medium uppercase text-ink-3">
            Similar historical signals
            <InfoTip
              label="the base rate"
              content="What happened to past detections in this same category, measured over the permanent record with losers included. It is a property of the category and makes no claim about this token."
            />
          </p>

          {rate.quotable ? (
            <div className="mt-2 flex flex-col gap-1.5">
              <p className="text-sm text-ink">{rate.headline}</p>
              <p data-numeric className="flex flex-wrap gap-x-5 text-xs text-ink-2">
                {rate.lines.map((line) => (
                  <span key={line}>{line}</span>
                ))}
              </p>
              <p data-numeric className="flex flex-wrap gap-x-5 text-xs text-ink-3">
                <span>
                  Median peak {formatMultiple(radar.base_rate?.median_peak_multiple)}
                </span>
                <span>
                  Median now {formatMultiple(radar.base_rate?.median_current_multiple)}
                </span>
              </p>
            </div>
          ) : (
            <p className="mt-2 text-xs leading-relaxed text-ink-3">{rate.lines[0]}</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
