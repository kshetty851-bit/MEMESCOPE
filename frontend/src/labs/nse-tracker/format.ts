/**
 * Rendering only. Nothing here computes a result the server did not send.
 *
 * `null` is drawn as `—` throughout and never as `0`. The backend is careful
 * to send null for "not measurable yet" — an outcome whose 40-bar window is
 * still open, a relative return with no index for the window — and printing
 * those as zero would turn "we cannot know" into "it went nowhere" on screen.
 */

const DASH = "—";

function missing(value: number | null | undefined): boolean {
  return value === null || value === undefined || !Number.isFinite(value);
}

/** Rupees, in Indian digit grouping. */
export function inr(value: number | null | undefined, digits = 2): string {
  if (missing(value)) return DASH;
  return `₹${(value as number).toLocaleString("en-IN", {
    minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/**
 * Turnover in crore, because that is the unit this market is read in: a
 * ₹1,20,45,67,890 cell is unreadable and ₹120 Cr is the same fact.
 */
export function crore(value: number | null | undefined): string {
  if (missing(value)) return DASH;
  const cr = (value as number) / 1_00_00_000;
  if (cr >= 100) return `₹${cr.toFixed(0)} Cr`;
  if (cr >= 1) return `₹${cr.toFixed(1)} Cr`;
  return `₹${((value as number) / 1_00_000).toFixed(1)} L`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (missing(value)) return DASH;
  const v = value as number;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`;
}

export function plainPct(value: number | null | undefined, digits = 1): string {
  if (missing(value)) return DASH;
  return `${(value as number).toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
  if (missing(value)) return DASH;
  return (value as number).toLocaleString("en-IN");
}

export function mult(value: number | null | undefined): string {
  if (missing(value)) return DASH;
  return `${(value as number).toFixed(1)}×`;
}

/** `2026-09-10` → `10 Sep`. Bars are daily; the year is in the header. */
export function day(value: string | null | undefined): string {
  if (!value) return DASH;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return DASH;
  return parsed.toLocaleDateString("en-IN", {
    day: "numeric", month: "short", timeZone: "UTC" });
}

/** Direction, for the semantic colour tokens. Zero is neutral, not a gain. */
export function tone(value: number | null | undefined): "up" | "down" | "flat" {
  if (missing(value) || value === 0) return "flat";
  return (value as number) > 0 ? "up" : "down";
}

export const TONE_CLASS: Record<"up" | "down" | "flat", string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-ink-3",
};

/**
 * The board's order and the badge treatment. NEAR sorts first and is the only
 * state given a lit badge — it is the one a reader acts on, and everything
 * else on the list is context for it.
 *
 * The server already sorts. This exists so a filtered view can re-sort without
 * inventing a second opinion about which state matters.
 */
export const STATE_ORDER: Record<string, number> = {
  NEAR: 0,
  WATCH: 1,
  BREAKOUT: 2,
  FALSE_BREAKOUT: 3,
  FAILED: 4,
  EXPIRED: 5,
  NONE: 6,
};

export const STATE_CLASS: Record<string, string> = {
  NEAR: "border-up/40 bg-up/15 text-up",
  WATCH: "border-line bg-surface-2 text-ink-2",
  BREAKOUT: "border-accent/40 bg-accent/10 text-accent",
  FALSE_BREAKOUT: "border-down/30 bg-down/10 text-down",
  FAILED: "border-down/30 bg-down/10 text-down",
  EXPIRED: "border-line bg-surface-2 text-ink-4",
  NONE: "border-line bg-surface-2 text-ink-4",
};

export const STATE_LABEL: Record<string, string> = {
  NEAR: "NEAR",
  WATCH: "WATCH",
  BREAKOUT: "BROKE OUT",
  FALSE_BREAKOUT: "FALSE BREAK",
  FAILED: "FAILED",
  EXPIRED: "EXPIRED",
  NONE: "QUIET",
};

/** Server codes, rendered here, never composed. */
export const CLOSE_REASON_LABELS: Record<string, string> = {
  FALSE_BREAKOUT: "Closed back under",
  FAILED: "Failed",
  EXPIRED: "Expired",
  no_volume: "Through without volume",
  fell_away: "Fell away from the level",
  score_faded: "Score faded",
  window_complete: "Window complete",
};

/**
 * The five score components, heaviest weight first.
 *
 * The ORDER is the point. `Object.entries` on the payload gives whatever key
 * order the JSON happened to carry, which puts the 10%-weighted component
 * above the 30%-weighted one as often as not — so the reader's eye lands on
 * the least important bar first.
 */
export const COMPONENT_ORDER = [
  "proximity", "compression", "trend", "volume", "touches",
] as const;

export const COMPONENT_LABELS: Record<string, string> = {
  proximity: "Proximity",
  compression: "Compression",
  trend: "Trend",
  volume: "Volume",
  touches: "Touches",
};
