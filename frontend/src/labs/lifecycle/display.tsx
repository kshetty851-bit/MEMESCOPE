import { Tooltip } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { formatAge } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { DataClass, Measured, SourceStatus } from "./types";

/**
 * DISPLAY PRIMITIVES FOR THE LIFECYCLE LAB
 *
 * The one rule this file exists to keep: **an unavailable figure never looks
 * like zero.** `Num` renders a bare dash, which in a column of returns is easy
 * to skim past as "nothing happened". Here the word is spelled out —
 * "unavailable" — with the reason one hover or focus away, because the
 * reason is the finding ("no_source" and "source_disabled" are different
 * facts about the world).
 *
 * Money and ratios arrive as strings and are converted with Number() only at
 * the moment of display. Money itself goes through lib/format (formatUsd,
 * formatPrice); nothing here re-implements it.
 */

export function humanize(code: string | null | undefined): string {
  if (!code) return "";
  return code.replace(/_/g, " ");
}

/** Explicit absence. Text, not a dash; reason on hover/focus and for screen readers. */
export function Unavailable({
  reason,
  className,
}: {
  reason?: string | null;
  className?: string;
}) {
  const why = reason ? humanize(reason) : "no reason given";
  return (
    <Tooltip content={`Unavailable: ${why}`} className={className}>
      <span
        tabIndex={0}
        data-unavailable
        className={cn(
          "cursor-help text-xs italic text-ink-3 underline decoration-dotted underline-offset-2",
        )}
      >
        unavailable
        <span className="sr-only"> — {why}</span>
      </span>
    </Tooltip>
  );
}

export function isPresent(value: string | null | undefined): value is string {
  if (value === null || value === undefined || value === "") return false;
  return Number.isFinite(Number(value));
}

/** A Measured through a formatter; null value is "unavailable", never formatted. */
export function MeasuredValue({
  measured,
  format,
  className,
}: {
  measured: Measured | null | undefined;
  format: (value: string) => string;
  className?: string;
}) {
  if (!measured || !isPresent(measured.value)) {
    return <Unavailable reason={measured?.unavailable_reason ?? "not reported"} />;
  }
  return (
    <span data-numeric className={cn("tabular-nums", className)}>
      {format(measured.value)}
    </span>
  );
}

/** A plain nullable string figure (money / ratio) with an optional reason for null. */
export function Figure({
  value,
  format,
  reason,
  className,
}: {
  value: string | null | undefined;
  format: (value: string) => string;
  reason?: string | null;
  className?: string;
}) {
  if (!isPresent(value)) return <Unavailable reason={reason ?? "not reported"} />;
  return (
    <span data-numeric className={cn("tabular-nums", className)}>
      {format(value)}
    </span>
  );
}

// ---- formatters (non-money) ------------------------------------------------

/**
 * Ratios are assumed to be fractions of one (0.05 = 5%), like the Graduation
 * Lab's `net_return`. This is the single place that assumption lives.
 */
export function formatRatioPct(value: string): string {
  const n = Number(value) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

export function formatSignedUsd(value: string): string {
  const n = Number(value);
  const body = Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${n < 0 ? "-" : n > 0 ? "+" : ""}$${body}`;
}

export function formatPlainUsd(value: string): string {
  const n = Number(value);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatMultiple(value: string): string {
  return `${Number(value).toFixed(2)}×`;
}

export function formatNumber(value: string): string {
  const n = Number(value);
  if (Number.isInteger(n)) return n.toLocaleString("en-US");
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** A fraction of one as a plain percentage ("0.977" -> "97.7%"), no sign. */
export function formatPlainPct(value: string): string {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

/** "21600" -> "every 6h". Collection cadence, shown verbatim from the server. */
export function formatInterval(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "unavailable";
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`;
  if (seconds % 60 === 0) return `every ${seconds / 60}m`;
  return `every ${seconds}s`;
}

export function formatConfidence(value: string): string {
  return `${Math.round(Number(value) * 100)}%`;
}

/** "10-03 14:00Z" — compact, always UTC (the platform stores timestamptz/UTC). */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const s = d.toISOString();
  return `${s.slice(0, 10)} ${s.slice(11, 16)}Z`;
}

/** Compact age from a duration in seconds, reusing lib/format's rounding. */
export function ageFromSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  return formatAge(new Date(Date.now() - seconds * 1000).toISOString());
}

export function agoFromIso(iso: string | null | undefined): string {
  if (!iso) return "never";
  return `${formatAge(iso)} ago`;
}

// ---- labels ----------------------------------------------------------------

export function DataClassLabel({
  dataClass,
  className,
}: {
  dataClass: DataClass | "authoritative" | "exploratory";
  className?: string;
}) {
  const exploratory = dataClass === "backfill" || dataClass === "exploratory";
  return (
    <Badge tone={exploratory ? "warn" : "plasma"} className={className}>
      {exploratory ? "EXPLORATORY (backfill)" : "AUTHORITATIVE (forward)"}
    </Badge>
  );
}

/** Always on screen. The lab never trades; this is not a footnote. */
export function PaperOnlyBanner() {
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line bg-sunken px-3 py-2"
    >
      <span className="text-label font-semibold uppercase tracking-wider text-warn">
        PAPER ONLY — no real trading
      </span>
      <span className="text-xs text-ink-3">
        Simulated paper entries and paper exits on a research ledger. Nothing here
        touches a wallet.
      </span>
    </div>
  );
}

/**
 * Every status gets its own words AND its own look, so the pill never relies on
 * colour alone: disabled/never_collected are dashed/dotted outlines (nothing was
 * attempted), unavailable/stale/partial are warm (something was attempted and
 * fell short, each differently), error is red. No pill renders a number.
 */
const STATUS_PILL: Record<
  SourceStatus,
  { text: string; tone: "safe" | "neutral" | "warn" | "danger" | "plasma"; cls?: string }
> = {
  available: { text: "collecting", tone: "safe" },
  disabled: { text: "disabled", tone: "neutral", cls: "border-dashed" },
  unavailable: { text: "unavailable", tone: "warn" },
  error: { text: "error", tone: "danger" },
  stale: { text: "stale", tone: "warn", cls: "border-dashed" },
  partial: { text: "partial", tone: "plasma" },
  never_collected: { text: "never collected", tone: "neutral", cls: "border-dotted italic" },
};

export function StatusPill({ status }: { status: SourceStatus | (string & {}) }) {
  const spec = STATUS_PILL[status as SourceStatus] ?? {
    text: humanize(status),
    tone: "neutral" as const,
  };
  return (
    <span data-status={status} className="inline-flex">
      <Badge tone={spec.tone} className={spec.cls}>
        {spec.text}
      </Badge>
    </span>
  );
}
