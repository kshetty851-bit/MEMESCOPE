import { api } from "@/lib/api-client";
import type {
  KarthikPositions,
  KarthikSkippedList,
  KarthikWallet,
} from "@/types/karthik";

/**
 * KARTHIK WALLET CLIENT
 *
 * Fetches and formats. **It never decides.** Every figure — the target, the
 * multiple, the capture rate, the exit reason — arrives already computed. A
 * threshold applied here would be a second, unpublished rule competing with the
 * one the wallet actually followed, and the two would disagree the first time
 * either changed.
 *
 * There is no write here at all. Karthik has no manual entry, no manual exit,
 * and no activation endpoint: it is started once by an operator command and
 * trades only on its own scheduled review.
 */

export function fetchKarthikWallet(): Promise<KarthikWallet> {
  return api.get<KarthikWallet>("/karthik");
}

export function fetchKarthikPositions(): Promise<KarthikPositions> {
  return api.get<KarthikPositions>("/karthik/positions");
}

/** The opportunities Karthik did not take. A capture rate needs its denominator. */
export function fetchKarthikSkipped(): Promise<KarthikSkippedList> {
  return api.get<KarthikSkippedList>("/karthik/skipped");
}

// --- Presentation ------------------------------------------------------------

/** `target_1_25x` → `Target 1.25x`. Server codes, rendered here, never composed. */
const EXIT_LABELS: Record<string, string> = {
  target_1_25x: "Target 1.25x",
  dead_zero: "Dead / zero",
};

const SKIP_LABELS: Record<string, string> = {
  skipped_insufficient_cash: "Insufficient cash",
  skipped_no_market: "No executable market",
};

export function exitLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return EXIT_LABELS[reason] ?? reason;
}

export function skipLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return SKIP_LABELS[reason] ?? reason;
}

/**
 * A multiple, to two places, with its `x`.
 *
 * Null in, dash out — the caller renders the dash. A position with no fresh
 * quote has no multiple, and showing `1.00x` for it would claim the token is
 * flat when the truth is that nobody has priced it.
 */
export function multiple(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return `${parsed.toFixed(2)}x`;
}

/** A price, at whatever precision it needs. Memecoins span many orders of magnitude. */
export function price(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  if (parsed === 0) return "$0";
  if (parsed < 0.000001) return `$${parsed.toExponential(3)}`;
  return `$${parsed.toPrecision(4)}`;
}

/** `2h 14m`. For a duration that is already known, unlike a delay, to be positive. */
export function duration(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  const total = Math.max(0, Math.round(seconds));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600) % 24;
  const d = Math.floor(total / 86400);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}
