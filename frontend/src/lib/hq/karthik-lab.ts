import { api } from "@/lib/api-client";
import { SITE_TIME_ZONE } from "@/lib/site-time";

/**
 * Karthik's Lab, as HQ reads it: `GET /labs/graduation/karthik/summary`.
 *
 * Karthik's desk watches this book since 2026-09-26. It replaced `/karthik-ops`,
 * the operator for the retired Karthik Paper Wallet, whose last action was on
 * 2026-09-17 and whose status line had been describing a deleted Track Record.
 * The summary is the lab's own cached read (60s) — the same figures as the
 * Karthik's Lab page — so HQ adds no load and can never disagree with it.
 */
export interface KarthikLabSummary {
  started_at: string;
  /** Fixed before the first trade; the book is judged then, not before. */
  judge_at: string;
  capital_usd: string;
  ticket_usd: string;
  balance_usd: string;
  pnl_usd: string;
  pnl_pct: string;
  trades: number;
  wins: number;
  /** Trades that closed at a rug's loss (net -50% or worse). */
  rugs: number;
}

export function fetchKarthikLab(): Promise<KarthikLabSummary> {
  return api.get<KarthikLabSummary>("/labs/graduation/karthik/summary");
}

export function usd(value: string | number): string {
  const n = Number(value);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function signedPct(value: string | number): string {
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

/** "23 Oct", in Dubai time like every other date on the site. */
export function judgeDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: SITE_TIME_ZONE,
  });
}
