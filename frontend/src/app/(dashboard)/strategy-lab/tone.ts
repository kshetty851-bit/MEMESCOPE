/**
 * How the Strategy Lab table decides what to colour and what to call itself.
 *
 * A separate module ONLY because it must be: a Next.js App Router `page.tsx`
 * may export nothing but `default` and a fixed set of route fields, so an
 * exported helper there fails `next build` with "not a valid Page export
 * field" — after `tsc --noEmit` has already passed. That is exactly how two
 * deploys were lost: the type-check was clean, the build was not, and
 * production silently stayed on the previous commit.
 */

import type { LabStrategyRow } from "@/types/lab";

/**
 * Green for gain, red for loss — and NOTHING for zero or unmeasured.
 *
 * The third case is the one that matters. A strategy with no closed trades has
 * a null P&L, and `—` painted green would read as a flat result rather than as
 * an absent one. Exactly zero stays neutral too: it is a real reading, not a
 * win. `text-up` / `text-down` are the platform's own tokens; inventing a
 * colour here would compile to nothing and fail silently.
 */
export function toneOf(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return "";
  return v > 0 ? "text-up" : "text-down";
}

/**
 * The columns that are a profit or a loss, and are therefore coloured.
 *
 * Deliberately not every numeric column. Max drawdown is always a loss and
 * would be permanently red, win rate is not P&L, and a table where most cells
 * are coloured is one where the colour stops carrying information.
 *
 * `equity` is the exception that needs its own comparison: it is always a
 * positive number, so its sign says nothing — what makes it a gain or a loss
 * is where it sits against the money the strategy started with.
 */
const PNL_COLUMNS = new Set([
  "net_pnl",
  "return_pct",
  "open_return_pct",
  "deployed_return_pct",
  "expectancy",
  "equity",
]);

export function cellTone(row: LabStrategyRow, key: string): string {
  if (!PNL_COLUMNS.has(key)) return "";
  if (key === "equity") return toneOf(row.equity - row.starting_equity);
  return toneOf(row[key as keyof LabStrategyRow] as number | null | undefined);
}

/**
 * Which generation of the tournament this is — "V7" — read from the ids the
 * API served rather than written here.
 *
 * This page read "V6 FORWARD STRATEGY LAB · 20 STRATEGIES" for the whole of
 * V7, which has 21. A generation written into a heading is wrong from the
 * moment the next tournament starts and nobody re-reads a heading, so it is
 * derived once and every caption follows it.
 *
 * Null when the ids do not agree on one prefix: a mixed board should say
 * nothing rather than name the wrong generation confidently.
 */
export function generationOf(ids: string[]): string | null {
  const prefixes = new Set(ids.map((id) => id.split("-")[0]).filter(Boolean));
  return prefixes.size === 1 ? [...prefixes][0]! : null;
}

/**
 * The do-nothing benchmark, identified by what it IS rather than by its id.
 *
 * This was pinned to the literal "V6-01" and so had silently highlighted
 * nothing since V7 began. A control stakes no money and holds no positions,
 * which is true of it in any generation.
 */
export function isCashControl(row: LabStrategyRow): boolean {
  return row.size_usd === 0 && row.max_concurrent === 0;
}
