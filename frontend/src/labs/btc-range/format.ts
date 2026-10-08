import { SITE_TIME_ZONE } from "@/lib/site-time";

import type { Call, ExitReason } from "./types";

/**
 * DISPLAY FORMATTING. Every figure arrives as a decimal string and stays one
 * until here; `Number()` is applied at the moment of display and nowhere else.
 */

const DASH = "—";

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** `$67,123.45`; signed adds `+` for gains. */
export function usd(
  value: string | number | null | undefined,
  options: { signed?: boolean; digits?: number } = {},
): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  const digits = options.digits ?? 2;
  const body = `$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
  if (n < 0) return `-${body}`;
  return options.signed && n > 0 ? `+${body}` : body;
}

/** A percentage the server has already scaled (`"12.5"` is 12.5%). */
export function pct(
  value: string | number | null | undefined,
  options: { signed?: boolean; digits?: number } = {},
): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  const body = `${Math.abs(n).toFixed(options.digits ?? 2)}%`;
  if (n < 0) return `-${body}`;
  return options.signed && n > 0 ? `+${body}` : body;
}

/** A plain decimal, e.g. a profit factor or an R multiple. */
export function dec(value: string | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  return n === null ? DASH : n.toFixed(digits);
}

export function signedDec(value: string | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${Math.abs(n).toFixed(digits)}`;
}

/** Dubai wall-clock, like every other clock on the site. */
export function when(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleString("en-GB", {
    timeZone: SITE_TIME_ZONE,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function whenDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleDateString("en-GB", {
    timeZone: SITE_TIME_ZONE,
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Sign → tone for `Num`. Zero and unknown are flat, never green or red. */
export function signTone(
  value: string | number | null | undefined,
): "up" | "down" | "flat" {
  const n = toNumber(value);
  if (n === null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export const EXIT_LABEL: Record<ExitReason, string> = {
  take_profit: "Take profit",
  stop_loss: "Stop loss",
  time_stop: "Time stop",
  end_of_data: "End of data",
};

export const CALL_LABEL: Record<Call, string> = {
  long: "LONG",
  short: "SHORT",
  wait: "WAIT",
};

export { toNumber };
