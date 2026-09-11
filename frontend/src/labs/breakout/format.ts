/**
 * Rendering only. Nothing here computes a result the server did not send.
 *
 * The backend serialises every figure as a JSON number, so unlike the Rafiq
 * lab there are no decimal strings to parse — these functions only decide how
 * a number is drawn, and what to draw when it is null.
 */

export function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `$${value.toFixed(digits)}`;
}

export function compactUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(0)}k`;
  return `$${value.toFixed(0)}`;
}

export function signedUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : "−"}$${Math.abs(value).toFixed(2)}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}%`;
}

export function plainPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

/** A rate served as 0..1, drawn as a percentage. */
export function rate(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  // Sub-cent tokens are the norm here, so significant digits beat fixed ones.
  return value >= 0.01 ? `$${value.toFixed(4)}` : `$${value.toPrecision(4)}`;
}

/** `31.4` → `1d 7h`. Ages are read at a glance, not to the minute. */
export function hours(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const d = Math.floor(value / 24);
  const h = Math.round(value % 24);
  return d > 0 ? `${d}d ${h}h` : `${h}h`;
}

/** Direction, for the semantic colour tokens. Zero is neutral, not a gain. */
export function tone(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) {
    return "flat";
  }
  return value > 0 ? "up" : "down";
}

export const TONE_CLASS: Record<"up" | "down" | "flat", string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-ink-3",
};

/**
 * The watchlist's order, and the badge treatment. PRE_BREAKOUT sorts first
 * and is the only state given a lit badge — it is the one the trader acts on,
 * and everything else on the list is context for it.
 *
 * This mirrors `data.STATE_ORDER` on the backend. The server already sorts;
 * this exists so the client can re-sort a filtered view without inventing a
 * second opinion about which state matters.
 */
export const STATE_ORDER: Record<string, number> = {
  PRE_BREAKOUT: 0,
  WATCHING: 1,
  BROKE_OUT: 2,
  FAILED: 3,
  NONE: 4,
};

export const STATE_CLASS: Record<string, string> = {
  PRE_BREAKOUT: "border-up/40 bg-up/15 text-up",
  WATCHING: "border-line bg-surface-2 text-ink-2",
  BROKE_OUT: "border-line bg-surface-2 text-ink-3",
  FAILED: "border-down/30 bg-down/10 text-down",
  NONE: "border-line bg-surface-2 text-ink-4",
};

export const STATE_LABEL: Record<string, string> = {
  PRE_BREAKOUT: "PRE-BREAKOUT",
  WATCHING: "WATCHING",
  BROKE_OUT: "BROKE OUT",
  FAILED: "FAILED",
  NONE: "QUIET",
};
