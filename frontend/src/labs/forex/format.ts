import { toNumber } from "@/labs/btc-range/format";

import type { Coded, Note } from "./types";

/**
 * DISPLAY FORMATTING. Money arrives as a decimal string and stays one until
 * here. The shared helpers are the BTC lab's (`usd`, `pct`, `dec`, ...); this
 * file adds only what a forex page needs that they lack: UTC clocks (candles
 * are UTC, and a Dubai clock on a London-open breakout would mislead), prices
 * at the instrument's quote precision, and note rendering.
 */
export { dec, pct, signedDec, signTone, toNumber, usd } from "@/labs/btc-range/format";

export const DASH = "—";

/** `3 Mar 2026, 07:15` in UTC. */
export function utc(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return `${date.toLocaleString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })} UTC`;
}

export function utcDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** A quote price at the instrument's precision (EUR/USD 5, USD/JPY 3). */
export function price(value: number | string | null | undefined, decimals = 5): string {
  const n = toNumber(value);
  return n === null ? DASH : n.toFixed(decimals);
}

export function count(value: number | string | null | undefined): string {
  const n = toNumber(value);
  return n === null ? DASH : n.toLocaleString("en-US");
}

/** `135` -> `2h 15m`. Unit conversion only. */
export function minutes(value: number | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return DASH;
  if (n < 60) return `${Math.round(n)}m`;
  const h = Math.floor(n / 60);
  const m = Math.round(n - h * 60);
  if (h < 24) return m ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d ${h - d * 24}h`;
}

/** The text of a note: already `{code,text}`, or a bare string, or nothing. */
export function noteText(note: Note | undefined): string | null {
  if (!note) return null;
  if (typeof note === "string") return note;
  return note.text || null;
}

export function isCoded(value: unknown): value is Coded {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Coded).text === "string" &&
    "code" in value
  );
}

/** `train_days` -> `Train days`; `params.rsi_period` -> `Rsi period`. */
export function humanize(key: string): string {
  const spaced = key.replace(/[._]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** `2026-03` -> `Mar 2026`. */
const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  const idx = Number(m) - 1;
  return MONTHS[idx] && y ? `${MONTHS[idx]} ${y}` : ym;
}
