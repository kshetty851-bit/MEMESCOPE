"use client";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import {
  HEALTH_STATUS_LABEL,
  HEALTH_STATUS_TONE,
  type HealthDimension,
  collectedCount,
} from "@/lib/health";

/**
 * Project Health — six readouts, each able to explain itself.
 *
 * Deliberately not a gauge. A dial implies a measured quantity on a known
 * scale, and four of these six have no data source at all — rendering those as
 * an empty arc would read as "zero", which is a claim the platform cannot
 * make. A status word and a sentence can say "not collected" without lying.
 *
 * The header states how many readouts are actually populated, so a user never
 * has to count the greyed-out rows to work out how much of this is real.
 */
export function ProjectHealth({ dimensions }: { dimensions: HealthDimension[] }) {
  const collected = collectedCount(dimensions);

  return (
    <Panel density="comfortable" className="flex flex-col gap-4">
      <header className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium tracking-tight text-ink">Project health</h2>
        <span className="text-xs text-ink-faint">
          {collected} of {dimensions.length} signals available
        </span>
      </header>

      <ul className="flex flex-col divide-y divide-line/50">
        {dimensions.map((dimension) => (
          <li key={dimension.id} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-ink">{dimension.label}</span>
              <span
                className="text-xs font-medium tracking-tight"
                style={{ color: HEALTH_STATUS_TONE[dimension.status] }}
              >
                {HEALTH_STATUS_LABEL[dimension.status]}
              </span>
            </div>
            <p className="max-w-prose text-xs leading-relaxed text-ink-dim">
              {dimension.detail}
            </p>
            {dimension.evidence.length > 1 ? (
              <Why label="More">
                <ul className="flex flex-col gap-1">
                  {dimension.evidence.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </Why>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
