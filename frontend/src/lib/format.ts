import type { DecimalString } from "@/types/api";

/**
 * Formatting for market values.
 *
 * Money arrives from the API as a decimal *string* so precision survives the
 * wire. Converting to a JS number is safe only at the moment of display, and
 * only for magnitudes a human reads — never for arithmetic that is stored.
 */

/** Compact USD: $1.2K, $3.4M, $5.6B. */
export function formatUsd(value: DecimalString | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";

  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  if (amount === 0) return "$0";

  const abs = Math.abs(amount);
  if (abs >= 1_000_000_000) return `$${(amount / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(amount / 1_000).toFixed(1)}K`;
  if (abs >= 1) return `$${amount.toFixed(2)}`;
  return `$${amount.toFixed(4)}`;
}

/** Token prices go far below cent precision, so they need their own rule. */
export function formatPrice(value: DecimalString | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";

  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  if (amount === 0) return "$0";

  const abs = Math.abs(amount);
  if (abs >= 1) return `$${amount.toFixed(4)}`;
  if (abs >= 0.0001) return `$${amount.toFixed(6)}`;
  // Below that, fixed notation is unreadable; exponential is honest.
  return `$${amount.toExponential(3)}`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat().format(value);
}

/** Compact age: 45s, 12m, 3h, 5d. */
export function formatAge(iso: string | null | undefined): string {
  if (!iso) return "—";

  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

export function shortenAddress(
  address: string | null | undefined,
  lead = 4,
  tail = 4,
): string {
  if (!address) return "—";
  if (address.length <= lead + tail + 1) return address;
  return `${address.slice(0, lead)}…${address.slice(-tail)}`;
}
