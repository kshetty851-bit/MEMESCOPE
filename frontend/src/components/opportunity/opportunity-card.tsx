"use client";

import { WhyNow } from "@/components/opportunity/why-now";
import { Badge } from "@/components/ui/badge";
import { Meter } from "@/components/ui/metric";
import { Label, Panel } from "@/components/ui/panel";
import {
  PRIORITY_LABEL,
  PRIORITY_TONE,
  STAGE_LABEL,
  STAGE_TONE,
  formatAgo,
  formatExpiresIn,
  leadSignal,
  signalLabel,
} from "@/lib/opportunities";
import { num, ratio } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { Opportunity } from "@/types/opportunity";

/**
 * One opportunity, as the engine reports it.
 *
 * The card leads with **what changed and when** — not with size, and not with a
 * score. That ordering is the product argument: this board exists to answer
 * "what became interesting just now", so the newest fact has to be the first
 * thing read.
 *
 * One card per token, always. Several concurrent signals render as several
 * badges on one card rather than several entries, which is what the engine's
 * `(mint, generation)` uniqueness guarantees at the other end.
 *
 * `confirmed_age_seconds` is shown rather than hidden: `priority` is as of the
 * last evaluation, and a reader is entitled to see that a ranking is nine
 * minutes old instead of being handed a silently re-sorted board.
 */
export function OpportunityCard({
  opportunity,
  onOpen,
}: {
  opportunity: Opportunity;
  onOpen: (opportunity: Opportunity) => void;
}) {
  const lead = leadSignal(opportunity);
  const stageHue = STAGE_TONE[opportunity.stage];
  const priorityHue = PRIORITY_TONE[opportunity.priority_band];
  const identity =
    opportunity.symbol ??
    opportunity.name ??
    `${opportunity.mint_address.slice(0, 4)}…${opportunity.mint_address.slice(-4)}`;

  return (
    <Panel accent={stageHue} interactive density="compact" className="group">
      <button
        type="button"
        onClick={() => onOpen(opportunity)}
        aria-haspopup="dialog"
        aria-label={`Open ${identity} — ${STAGE_LABEL[opportunity.stage]}`}
        className="flex w-full flex-col gap-3 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-plasma"
      >
        {/* --- Identity + stage -------------------------------------------- */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">{identity}</p>
            {opportunity.name && opportunity.symbol && (
              <p className="mt-0.5 truncate text-xs text-ink-faint">{opportunity.name}</p>
            )}
          </div>
          <span
            className="shrink-0 rounded-chip border px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.1em]"
            style={{
              color: stageHue,
              borderColor: `color-mix(in oklch, ${stageHue} 35%, transparent)`,
              background: `color-mix(in oklch, ${stageHue} 10%, transparent)`,
            }}
          >
            {STAGE_LABEL[opportunity.stage]}
          </span>
        </div>

        {/* --- Active signals ---------------------------------------------- */}
        <div className="flex flex-wrap gap-1.5" aria-label="Active signals">
          {opportunity.signals.map((signal) => (
            <Badge
              key={`${signal.signal_type}:${signal.provider}`}
              tone={signal.severity === "critical" ? "apex" : "plasma"}
            >
              {signalLabel(signal.signal_type)}
            </Badge>
          ))}
          {opportunity.signals.length === 0 && (
            <span className="text-xs text-ink-faint">No live signals</span>
          )}
        </div>

        {/* --- Confidence + priority --------------------------------------- */}
        <div className="grid grid-cols-2 items-end gap-3 rounded-card border border-line/60 bg-surface/40 p-2.5">
          <div>
            <Label>Confidence</Label>
            <p data-numeric className="mt-0.5 font-mono text-lg text-ink">
              {Math.round(num(opportunity.confidence))}
            </p>
            <Meter
              value={ratio(opportunity.confidence)}
              segments={8}
              label={`Confidence ${Math.round(num(opportunity.confidence))} of 100`}
              className="mt-1.5"
            />
          </div>
          <div>
            <Label>Priority</Label>
            <p
              data-numeric
              className="mt-0.5 font-mono text-lg"
              style={{ color: priorityHue }}
            >
              {Math.round(num(opportunity.priority))}
            </p>
            <p className="mt-1.5 text-xs" style={{ color: priorityHue }}>
              {PRIORITY_LABEL[opportunity.priority_band]}
            </p>
          </div>
        </div>

        {/* --- Timing ------------------------------------------------------- */}
        <dl className="grid grid-cols-3 gap-2">
          <Timing label="Detected" value={formatAgo(secondsSinceIso(opportunity.detected_at))} />
          <Timing
            label="Confirmed"
            value={formatAgo(opportunity.confirmed_age_seconds)}
          />
          <Timing
            label="Expires in"
            value={lead ? formatExpiresIn(lead.expires_in_seconds) : "—"}
            tone={lead && lead.expires_in_seconds < 3600 ? "var(--color-warn)" : undefined}
          />
        </dl>

        {/* --- Why now ------------------------------------------------------ */}
        {lead && (
          <WhyNow
            explanation={lead.explanation}
            compact
            className="border-t border-line/60 pt-3"
          />
        )}
      </button>
    </Panel>
  );
}

function Timing({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <dt>
        <Label>{label}</Label>
      </dt>
      <dd
        data-numeric
        className={cn("mt-0.5 font-mono text-xs text-ink-dim")}
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Rendered from the timestamp rather than a server-supplied age.
 *
 * The board reports `confirmed_age_seconds` but not a detection age, and
 * deriving it here keeps the card correct while a page sits open between polls.
 */
function secondsSinceIso(iso: string): number {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return 0;
  return Math.max(0, Math.round((Date.now() - parsed) / 1000));
}
