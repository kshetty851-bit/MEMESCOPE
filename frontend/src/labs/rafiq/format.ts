/**
 * Rendering only. Nothing here computes a result the server did not send.
 *
 * `Number()` appears in this file and nowhere else in the lab, and only ever
 * on the way to a screen. A decimal string is the source of truth; a float is
 * a way of drawing it.
 */

export function usd(value: string | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(digits)}` : "—";
}

export function signedUsd(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : "−"}$${Math.abs(n).toFixed(2)}`;
}

export function pct(value: string | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(digits)}%` : "—";
}

export function plainPct(value: string | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "—";
}

export function price(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  // Sub-cent tokens are the norm here, so significant digits beat fixed ones.
  return n >= 0.01 ? `$${n.toFixed(4)}` : `$${n.toPrecision(4)}`;
}

/** `65200` → `18h 6m`. Ages are read at a glance, not to the second. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "—";
  }
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Direction, for the semantic colour tokens. Zero is neutral, not a gain. */
export function tone(value: string | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined) return "flat";
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export const TONE_CLASS: Record<"up" | "down" | "flat", string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-ink-3",
};
