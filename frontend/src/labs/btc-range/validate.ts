import type { FieldBounds } from "./types";

/**
 * Client-side check against the server's own bounds. It exists to save a round
 * trip and to point at the field; the server still validates, and its answer
 * wins. Compared as numbers — these are limits on an input, not stored money.
 */
export function validateField(
  bounds: FieldBounds,
  raw: string | boolean | undefined,
): string | null {
  if (bounds.kind === "bool") return null;

  const text = typeof raw === "string" ? raw.trim() : "";
  if (text === "") return "Enter a value.";

  const value = Number(text);
  if (!Number.isFinite(value)) return "Enter a number.";
  if (bounds.kind === "int" && !Number.isInteger(value)) return "Enter a whole number.";

  const min = Number(bounds.min);
  const max = Number(bounds.max);
  if (Number.isFinite(min) && value < min) return `Must be at least ${bounds.min}.`;
  if (Number.isFinite(max) && value > max) return `Must be at most ${bounds.max}.`;
  return null;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Both are `YYYY-MM-DD`, UTC days. Empty means "use the server default". */
export function validateWindow(
  start: string,
  end: string,
  firstAt: string | null,
  lastAt: string | null,
): { start: string | null; end: string | null } {
  const errors: { start: string | null; end: string | null } = { start: null, end: null };
  const first = firstAt?.slice(0, 10) ?? null;
  const last = lastAt?.slice(0, 10) ?? null;

  if (start && !DAY.test(start)) errors.start = "Enter a date.";
  if (end && !DAY.test(end)) errors.end = "Enter a date.";
  if (errors.start || errors.end) return errors;

  if (start && first && start < first) errors.start = `Stored candles begin on ${first}.`;
  if (start && last && start > last) errors.start = `Stored candles end on ${last}.`;
  if (end && first && end < first) errors.end = `Stored candles begin on ${first}.`;
  if (end && last && end > last) errors.end = `Stored candles end on ${last}.`;
  if (!errors.start && !errors.end && start && end && start > end) {
    errors.end = "End must be on or after the start.";
  }
  return errors;
}

/** Default window: the last 30 days of stored candles, or less if there are fewer. */
export function defaultWindow(
  firstAt: string | null,
  lastAt: string | null,
): { start: string; end: string } {
  if (!lastAt) return { start: "", end: "" };
  const end = lastAt.slice(0, 10);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  let start = new Date(endMs - 30 * 86_400_000).toISOString().slice(0, 10);
  const first = firstAt?.slice(0, 10);
  if (first && start < first) start = first;
  return { start, end };
}

/** ISO bounds for the POST: start of the start day, end of the end day, clamped to the data. */
export function windowToIso(
  start: string,
  end: string,
  firstAt: string | null,
  lastAt: string | null,
): { start?: string; end?: string } {
  const out: { start?: string; end?: string } = {};
  if (start) {
    let iso = `${start}T00:00:00Z`;
    if (firstAt && Date.parse(iso) < Date.parse(firstAt)) iso = firstAt;
    out.start = iso;
  }
  if (end) {
    let iso = `${end}T23:59:59Z`;
    if (lastAt && Date.parse(iso) > Date.parse(lastAt)) iso = lastAt;
    out.end = iso;
  }
  return out;
}
