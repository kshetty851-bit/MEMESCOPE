"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { WhyNow } from "@/components/opportunity/why-now";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Meter } from "@/components/ui/metric";
import { Label } from "@/components/ui/panel";
import {
  PRIORITY_LABEL,
  PRIORITY_TONE,
  STAGE_LABEL,
  STAGE_TONE,
  formatAgo,
  formatExpiresIn,
  secondsSince,
  signalLabel,
} from "@/lib/opportunities";
import { num, ratio } from "@/lib/scores";
import { cn } from "@/lib/utils";
import type { Opportunity, OpportunitySignal } from "@/types/opportunity";

/**
 * The full reading on one opportunity.
 *
 * A drawer rather than a route: the board is the thing being scanned, and
 * sending the reader to a page and back loses their scroll position, their
 * filters and their place in a list that repolls every minute.
 *
 * Everything shown is already in the board response — the drawer issues no
 * request of its own. That is why it opens instantly and why it cannot
 * disagree with the card behind it.
 */
export function OpportunityDrawer({
  opportunity,
  onClose,
}: {
  opportunity: Opportunity | null;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const open = opportunity !== null;

  // Escape closes, and focus moves into the drawer on open so a keyboard user
  // is not left behind on the card they activated.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!opportunity) return null;

  const stageHue = STAGE_TONE[opportunity.stage];
  const priorityHue = PRIORITY_TONE[opportunity.priority_band];
  const identity =
    opportunity.symbol ??
    opportunity.name ??
    `${opportunity.mint_address.slice(0, 4)}…${opportunity.mint_address.slice(-4)}`;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* A mouse affordance, not a control. Hidden from assistive tech because
          the Close button and Escape already dismiss the drawer — exposing it
          would put two identically-named controls in the a11y tree. */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-abyss/70 backdrop-blur-sm"
      />

      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={`${identity} — ${STAGE_LABEL[opportunity.stage]}`}
        tabIndex={-1}
        className={cn(
          "relative flex h-full w-full max-w-lg flex-col overflow-y-auto",
          "border-l border-line/80 bg-surface/95 backdrop-blur-2xl",
          "focus:outline-none",
        )}
      >
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{
            background: `linear-gradient(90deg, transparent, ${stageHue}, transparent)`,
          }}
        />

        {/* --- Header ------------------------------------------------------- */}
        <header className="flex items-start justify-between gap-4 border-b border-line/60 p-6">
          <div className="min-w-0">
            <Label>Opportunity</Label>
            <h2 className="mt-1 truncate text-title font-semibold text-ink">{identity}</h2>
            {opportunity.name && opportunity.symbol && (
              <p className="mt-1 truncate text-sm text-ink-dim">{opportunity.name}</p>
            )}
            <p
              data-numeric
              className="mt-2 truncate font-mono text-xs text-ink-faint"
              title={opportunity.mint_address}
            >
              {opportunity.mint_address}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex flex-col gap-6 p-6">
          {/* --- State ----------------------------------------------------- */}
          <section className="flex flex-wrap items-center gap-2">
            <span
              className="rounded-chip border px-2 py-0.5 text-label font-medium uppercase"
              style={{
                color: stageHue,
                borderColor: `color-mix(in oklch, ${stageHue} 35%, transparent)`,
                background: `color-mix(in oklch, ${stageHue} 10%, transparent)`,
              }}
            >
              {STAGE_LABEL[opportunity.stage]}
            </span>
            <Badge tone="neutral">{opportunity.status.replace(/_/g, " ")}</Badge>
            {/* Generation is only meaningful past the first: it says this token
                has been called before, and that the earlier call is still on the
                record rather than having been overwritten. */}
            {opportunity.generation > 1 && (
              <Badge tone="warn">Generation {opportunity.generation}</Badge>
            )}
          </section>

          {/* --- Readings --------------------------------------------------- */}
          <section className="grid grid-cols-2 gap-4 rounded-card border border-line/60 bg-surface/40 p-4">
            <div>
              <Label>Confidence</Label>
              <p data-numeric className="mt-1 font-mono text-2xl text-ink">
                {Math.round(num(opportunity.confidence))}
              </p>
              <Meter
                value={ratio(opportunity.confidence)}
                segments={10}
                label={`Confidence ${Math.round(num(opportunity.confidence))} of 100`}
                className="mt-2"
              />
            </div>
            <div>
              <Label>Priority</Label>
              <p
                data-numeric
                className="mt-1 font-mono text-2xl"
                style={{ color: priorityHue }}
              >
                {Math.round(num(opportunity.priority))}
              </p>
              <p className="mt-2 text-xs" style={{ color: priorityHue }}>
                {PRIORITY_LABEL[opportunity.priority_band]} priority
              </p>
            </div>
          </section>

          {/* --- Timing ------------------------------------------------------ */}
          <section>
            <Label>Timing</Label>
            <dl className="mt-2 grid grid-cols-2 gap-3">
              <Row
                label="Detected"
                value={formatAgo(secondsSince(opportunity.detected_at))}
                hint={opportunity.detected_at}
              />
              <Row
                label="Last confirmed"
                value={formatAgo(opportunity.confirmed_age_seconds)}
                hint={opportunity.last_confirmed_at}
              />
            </dl>
            <p className="mt-3 text-xs leading-relaxed text-ink-faint">
              Detection time is written once and never revised — every claim this
              platform makes about how an opportunity performed is measured from it.
            </p>
          </section>

          {/* --- Signals ----------------------------------------------------- */}
          <section className="flex flex-col gap-4">
            <Label>
              {opportunity.signals.length}{" "}
              {opportunity.signals.length === 1 ? "live signal" : "live signals"}
            </Label>
            {opportunity.signals.map((signal) => (
              <SignalBlock key={`${signal.signal_type}:${signal.provider}`} signal={signal} />
            ))}
            {opportunity.signals.length === 0 && (
              <p className="text-sm text-ink-faint">
                Every signal on this opportunity has lapsed. It stays on the record;
                it is no longer being reported as live.
              </p>
            )}
          </section>

          <Link
            href={`/tokens/${opportunity.mint_address}`}
            className="text-sm text-plasma transition-colors hover:text-ink"
          >
            Open the full token dossier →
          </Link>
        </div>
      </div>
    </div>
  );
}

function SignalBlock({ signal }: { signal: OpportunitySignal }) {
  const expiringSoon = signal.expires_in_seconds < 3600;

  return (
    <article className="rounded-card border border-line/60 bg-surface/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-ink">{signal.explanation.headline}</p>
        <Badge tone={signal.severity === "critical" ? "apex" : "plasma"}>
          {signalLabel(signal.signal_type)}
        </Badge>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* Strength is the provider's claim about the transition; confidence is
            what the engine derived from it. Showing both is what stops a
            confident-looking card hiding a single unconfirmed observation. */}
        <Row label="Strength" value={String(Math.round(num(signal.strength)))} />
        <Row label="Confidence" value={String(Math.round(num(signal.confidence)))} />
        <Row label="Confirmations" value={String(signal.confirmations)} />
        <Row
          label="Expires in"
          value={formatExpiresIn(signal.expires_in_seconds)}
          tone={expiringSoon ? "var(--color-warn)" : undefined}
        />
      </dl>

      <WhyNow explanation={signal.explanation} className="mt-4" />

      <p className="mt-3 text-xs text-ink-faint">
        Reported by <span className="text-ink-dim">{signal.provider}</span> over{" "}
        <span data-numeric className="font-mono">
          {signal.observations}
        </span>{" "}
        observations.
      </p>
    </article>
  );
}

function Row({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div>
      <dt>
        <Label>{label}</Label>
      </dt>
      <dd
        data-numeric
        className="mt-0.5 font-mono text-sm text-ink"
        style={tone ? { color: tone } : undefined}
        title={hint}
      >
        {value}
      </dd>
    </div>
  );
}
