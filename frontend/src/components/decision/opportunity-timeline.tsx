"use client";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import { clock, entryDelaySeconds, exitLabel, formatDelay, stamp } from "@/lib/paper";
import type { PaperPosition } from "@/types/paper";
import type { RadarEntry } from "@/types/radar";

/**
 * Opportunity timeline — the token's journey as a story rather than a row of
 * isolated numbers.
 *
 * A user looking at "1.03×" cannot tell whether that is a token grinding
 * upward, or one that reached 4× and gave almost all of it back. Those are
 * opposite situations with the same current figure, and the second is where
 * users actually lose money: measured across the live Radar, entries retain
 * only ~60% of their peak on average.
 *
 * So the peak sits on the timeline as its own event, between detection and now.
 * The drawdown from it is arithmetic on two backend figures, not a judgement —
 * and it is the single most decision-relevant thing this page can show.
 *
 * Every milestone is drawn from `radar_tokens`, whose first-detection block is
 * written once and never updated. That immutability is what makes this a record
 * rather than a story the platform can retell in its own favour.
 *
 * The clock at the top is the one exception, and comes from the discovery
 * record rather than the Radar row: `discovered_at` is when MEMESCOPE first saw
 * the mint, which is minutes to hours before the Radar admitted it. Showing the
 * admission time as the detection time would quietly shorten every entry delay
 * measured against it. A mint with no stored discovery record says so.
 */
export function OpportunityTimeline({
  entry,
  position,
}: {
  entry: RadarEntry;
  position?: PaperPosition;
}) {
  const first = Number(entry.first_price ?? 0);
  const peak = Number(entry.peak_multiple ?? 1);
  const current = Number(entry.current_multiple ?? 1);

  const pastPeak = peak > current;
  const retained = peak > 0 ? current / peak : 1;
  const givenBack = Math.round((1 - retained) * 100);

  const detectedAt = clock(entry.discovered_at);
  const delay = position
    ? entryDelaySeconds(entry.discovered_at, position.opened_at)
    : null;

  const events: { key: string; title: string; detail: string; tone: string }[] = [
    {
      key: "detected",
      title: detectedAt ? `Detected ${detectedAt}` : "Detected by MEMESCOPE",
      detail:
        (detectedAt
          ? `First seen by MEMESCOPE at ${stamp(entry.discovered_at)}. `
          : "The detection time is not available for this mint — no discovery " +
            "record survives for it, and none is estimated. ") +
        `First observed at ${formatUsd(first)}. Every return below is measured ` +
        `from this moment — never from the token's launch, which MEMESCOPE did ` +
        `not call.`,
      tone: "var(--color-accent)",
    },
  ];

  if (position) {
    events.push({
      key: "entry",
      title: `Paper entry ${clock(position.opened_at) ?? ""}`.trim(),
      detail:
        (delay === null
          ? "The delay from detection cannot be measured without a stored detection time. "
          : `${formatDelay(delay)} after detection. `) +
        `Entered at rank #${position.entry_rank} on the strategy's own rule — ` +
        `there is no manual entry in this wallet.`,
      tone: "var(--color-ink-3)",
    });

    if (position.closed_at) {
      events.push({
        key: "exit",
        title: `Paper exit ${clock(position.closed_at) ?? ""}`.trim(),
        detail:
          `${exitLabel(position.exit_reason) ?? "Closed"} at ` +
          `${stamp(position.closed_at)}.`,
        tone: "var(--color-ink-3)",
      });
    }
  }

  if (entry.detection_reason.length > 0) {
    events.push({
      key: "why",
      title: "Why it qualified",
      detail: `${entry.detection_reason.length} conditions were met at detection.`,
      tone: "var(--color-ink-3)",
    });
  }

  if (peak > 1) {
    events.push({
      key: "peak",
      title: `Peak ${peak.toFixed(2)}×`,
      detail:
        `The highest point observed since detection. The peak only ever rises: ` +
        `a later fall cannot erase a high that happened.`,
      tone: "var(--color-up)",
    });
  }

  events.push({
    key: "current",
    title: `Currently ${current.toFixed(2)}×`,
    detail: pastPeak
      ? `Down ${givenBack}% from its peak. A token grinding upward and one that ` +
        `round-tripped can show the same figure here, which is why the peak is ` +
        `on this timeline.`
      : "At or above its highest observed point since detection.",
    tone: pastPeak ? "var(--color-down)" : "var(--color-up)",
  });

  return (
    <Panel density="comfortable" className="flex flex-col gap-4">
      <header className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium tracking-tight text-ink">Opportunity timeline</h2>
        <Why>
          Built from the Radar&rsquo;s permanent record. The first-detection block
          is written once and never updated, so the denominator of every return
          here cannot be quietly improved after the fact.
        </Why>
      </header>

      <ol className="flex flex-col">
        {events.map((event, index) => (
          <li key={event.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                aria-hidden
                className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                style={{ background: event.tone }}
              />
              {index < events.length - 1 ? (
                <span aria-hidden className="my-1 w-px flex-1 bg-line" />
              ) : null}
            </div>
            <div className="flex flex-col gap-1 pb-5 last:pb-0">
              <p className="text-sm font-medium text-ink">{event.title}</p>
              <p className="max-w-prose text-xs leading-relaxed text-ink-2">
                {event.detail}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "an unrecorded price";
  if (value < 0.01) return `$${value.toPrecision(3)}`;
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}
