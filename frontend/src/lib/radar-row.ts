import type { BaseRate, RadarEntry } from "@/types/radar";

/**
 * RADAR ROW PRESENTATION
 *
 * Formats and labels. **It never decides.** The same rule `lib/radar.ts`
 * carries: a threshold applied here would be a second, unversioned opinion
 * that could disagree with the engine about the same token.
 *
 * Every function returns an explicit dash for absent data. "We did not measure
 * this" and "this is zero" are different claims, and a row that renders the
 * first as the second is the estimate this platform refuses to make.
 */

function n(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Compact USD. Returns null so callers render their own dash. */
export function compactUsd(value: string | null | undefined): string | null {
  const amount = n(value);
  if (amount === null) return null;

  const abs = Math.abs(amount);
  if (abs >= 1_000_000_000) return `$${(amount / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(amount / 1_000).toFixed(1)}K`;
  if (abs >= 1) return `$${amount.toFixed(2)}`;
  return `$${amount.toFixed(4)}`;
}

/** A signed percentage. Null in, null out — never a flat 0%. */
export function signedPct(value: string | null | undefined): string | null {
  const amount = n(value);
  if (amount === null) return null;
  const sign = amount > 0 ? "+" : "";
  return `${sign}${amount.toFixed(amount >= 100 || amount <= -100 ? 0 : 1)}%`;
}

export function changeTone(
  value: string | null | undefined,
): "positive" | "negative" | "neutral" {
  const amount = n(value);
  if (amount === null || amount === 0) return "neutral";
  return amount > 0 ? "positive" : "negative";
}

/** Compact age from a duration in seconds: 45s, 12m, 3h, 5d. */
export function compactAge(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return null;
  }
  const value = Math.max(0, seconds);
  if (value < 60) return `${Math.floor(value)}s`;
  if (value < 3_600) return `${Math.floor(value / 60)}m`;
  if (value < 86_400) return `${Math.floor(value / 3_600)}h`;
  return `${Math.floor(value / 86_400)}d`;
}

/** How long a signal's claim has left. Same shape as `compactAge`. */
export function expiresIn(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null;
  if (seconds <= 0) return "expired";
  return compactAge(seconds);
}

/**
 * Risk, in words.
 *
 * The score is a dimension like every other, so **high is safe** — the exact
 * inversion a reader will assume wrong if the number is shown bare. Never
 * returns a band for an unmeasured risk.
 */
export function riskBand(
  value: string | null | undefined,
): { label: string; tone: "safe" | "warn" | "danger" } | null {
  const score = n(value);
  if (score === null) return null;
  if (score >= 70) return { label: "Low risk", tone: "safe" };
  if (score >= 40) return { label: "Elevated risk", tone: "warn" };
  return { label: "High risk", tone: "danger" };
}

/**
 * Evidence, in words. The share of the model that had data when this row was
 * scored — a 90 scored on a third of the model is not a 90.
 */
export function evidenceBand(
  value: string | null | undefined,
): { label: string; tone: "safe" | "warn" | "danger" } | null {
  const score = n(value);
  if (score === null) return null;
  if (score >= 80) return { label: "Full", tone: "safe" };
  if (score >= 50) return { label: "Partial", tone: "warn" };
  return { label: "Thin", tone: "danger" };
}

/**
 * The base rate as a sentence a reader cannot mistake for a prediction.
 *
 * Below the published minimum sample this returns the backend's own
 * `insufficient_reason` and no percentages at all. The counts are never turned
 * into a rate here — that decision belongs to the engine that published the
 * threshold.
 */
export function baseRateSummary(rate: BaseRate | null | undefined): {
  quotable: boolean;
  headline: string;
  lines: string[];
} | null {
  if (!rate) return null;

  if (!rate.sufficient) {
    return {
      quotable: false,
      headline: `${rate.sample} past ${rate.sample === 1 ? "detection" : "detections"}`,
      lines: [
        rate.insufficient_reason ??
          `Below the ${rate.minimum_sample} detections needed to quote a rate.`,
      ],
    };
  }

  const share = (count: number) => `${Math.round((count / rate.sample) * 100)}%`;
  return {
    quotable: true,
    headline: `${rate.sample} similar signals`,
    lines: [
      `${share(rate.reached_2x)} reached 2×`,
      `${share(rate.reached_5x)} reached 5×`,
      `${share(rate.reached_10x)} reached 10×`,
    ],
  };
}

/**
 * How a token is named on a row.
 *
 * Enrichment does not always return a name or a symbol, and a token we have not
 * identified is a real state. The mint is shown instead of the word "Unnamed" —
 * truncated, it is still the one identifier that always exists and the one a
 * reader can act on.
 *
 * The secondary line is dropped when it merely repeats the primary: "SAOF SAOF"
 * reads as two facts and is one.
 */
export function tokenNaming(entry: {
  mint_address: string;
  name: string | null;
  symbol: string | null;
}): { primary: string; secondary: string | null } {
  const symbol = entry.symbol?.trim() || null;
  const name = entry.name?.trim() || null;
  const primary =
    symbol ?? name ?? `${entry.mint_address.slice(0, 4)}…${entry.mint_address.slice(-4)}`;
  const secondary =
    name && name.toLowerCase() !== primary.toLowerCase() ? name : null;
  return { primary, secondary };
}

/**
 * The Radar's own order, applied client-side only as a tiebreak-free mirror of
 * what the backend already sorted. Present so a caller can re-rank a page it
 * already holds without refetching; it never changes which rows are on it.
 */
export type RadarSortKey = "score" | "peak" | "current" | "age";

export function sortRadarEntries(
  entries: RadarEntry[],
  key: RadarSortKey,
): RadarEntry[] {
  const sorted = [...entries];
  const by = (value: string | null): number => n(value) ?? -Infinity;

  switch (key) {
    case "peak":
      return sorted.sort((a, b) => by(b.peak_multiple) - by(a.peak_multiple));
    case "current":
      return sorted.sort((a, b) => by(b.current_multiple) - by(a.current_multiple));
    case "age":
      return sorted.sort(
        (a, b) => (a.age_seconds ?? Infinity) - (b.age_seconds ?? Infinity),
      );
    default:
      return sorted.sort(
        (a, b) => by(b.opportunity_score) - by(a.opportunity_score),
      );
  }
}
