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

/** `1725900000` → `2d 14h 03m`, ticking. For elapsed time, not durations. */
export function elapsed(fromIso: string, now: number): string {
  const start = Date.parse(fromIso);
  if (!Number.isFinite(start)) return "—";
  const secs = Math.max(0, Math.floor((now - start) / 1000));
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return d > 0 ? `${d}d ${pad(h)}h ${pad(m)}m` : `${pad(h)}h ${pad(m)}m ${pad(s)}s`;
}

/**
 * Where to go to check a mint against the market.
 *
 * DexScreener rather than an explorer: the question a reader has about one of
 * these rows is "did that price really happen", and DexScreener answers it
 * with the pool's own chart. An explorer answers a different question.
 */
export const dexscreener = (mint: string) => `https://dexscreener.com/solana/${mint}`;
