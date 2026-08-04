/**
 * HOW OLD IS THIS NUMBER?
 *
 * Sprint 28.1. The backend now refreshes displayed tokens every ~15 seconds
 * (Top 10 measured at 7s average), but a price is only as good as its
 * timestamp — and some tokens legitimately have no recent data because the
 * provider indexes no pool for them. Before this, a three-hour-old price and a
 * seven-second-old price rendered identically.
 *
 * Pure, and deliberately so: the band a price falls into is the product's claim
 * about its own data, and it must be the same claim on every surface. `now` is
 * a parameter so the bands are testable without freezing a clock.
 *
 * **Never returns "live".** The age is the honest figure; "live" is a promise
 * about the future that a timestamp cannot support.
 */

/** Bands are published, not tuned per surface. */
export type FreshnessBand = "fresh" | "normal" | "ageing" | "stale" | "unknown";

/** Seconds at which each band begins. Published because it is the claim. */
export const FRESHNESS_THRESHOLDS = {
  /** Under this reads as keeping up with the priority lane's own cadence. */
  fresh: 30,
  normal: 300,
  ageing: 1_800,
} as const;

export interface Freshness {
  band: FreshnessBand;
  /** Seconds since the reading. `null` when nothing was ever observed. */
  ageSeconds: number | null;
  /** "Updated 12 sec ago". Complete phrase — callers never append to it. */
  label: string;
  /** Screen-reader text, spelled out rather than abbreviated. */
  description: string;
}

/**
 * An elapsed duration, as a complete phrase.
 *
 * Returns a whole sentence fragment so a caller cannot produce "just now ago"
 * by decorating it — the mistake `formatAgo` was written to fix in `lib/radar`.
 */
export function ageLabel(seconds: number): string {
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)} sec ago`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3_600)} h ago`;
  return `${Math.floor(seconds / 86_400)} d ago`;
}

export function bandFor(seconds: number): FreshnessBand {
  if (seconds < FRESHNESS_THRESHOLDS.fresh) return "fresh";
  if (seconds < FRESHNESS_THRESHOLDS.normal) return "normal";
  if (seconds < FRESHNESS_THRESHOLDS.ageing) return "ageing";
  return "stale";
}

/**
 * How old a reading is, and what to say about it.
 *
 * `capturedAt` of `null` means the token has never been priced — a real state,
 * distinct from an old price, and it must not render as "stale" because there
 * is nothing to have gone stale.
 */
export function freshnessOf(
  capturedAt: string | null | undefined,
  now: number = Date.now(),
): Freshness {
  if (!capturedAt) {
    return {
      band: "unknown",
      ageSeconds: null,
      label: "No market data",
      description: "No market data has been observed for this token.",
    };
  }

  const observed = new Date(capturedAt).getTime();
  if (!Number.isFinite(observed)) {
    return {
      band: "unknown",
      ageSeconds: null,
      label: "No market data",
      description: "The reading carries no readable timestamp.",
    };
  }

  // A reading fractionally ahead of the browser clock is a clock disagreement,
  // not a price from the future.
  const seconds = Math.max(0, (now - observed) / 1000);
  const band = bandFor(seconds);
  return {
    band,
    ageSeconds: seconds,
    label: `Updated ${ageLabel(seconds)}`,
    description: `Market data last observed ${ageLabel(seconds)}.`,
  };
}

/**
 * The freshest reading across a set — what the live badge reports.
 *
 * Deliberately the *newest*, not the median: the badge answers "is the platform
 * still receiving data?", which one recent reading settles. Per-row staleness
 * is answered per row, and a badge that averaged the two questions would let a
 * healthy pipeline hide a stale row, or one stale row imply a dead pipeline.
 */
export function newestOf(
  timestamps: (string | null | undefined)[],
  now: number = Date.now(),
): Freshness {
  let newest: string | null = null;
  let best = Infinity;

  for (const stamp of timestamps) {
    if (!stamp) continue;
    const parsed = new Date(stamp).getTime();
    if (!Number.isFinite(parsed)) continue;
    const age = Math.max(0, (now - parsed) / 1000);
    if (age < best) {
      best = age;
      newest = stamp;
    }
  }

  return freshnessOf(newest, now);
}

/**
 * A mint, shortened so a symbol collision is resolvable.
 *
 * The audit found nine distinct mints named TNOS and five named SAOF, all
 * genuine pump.fun tokens. A symbol alone cannot identify a token here, and the
 * mint is the only identifier that always can.
 *
 * No numbering is invented — "TNOS #3" would imply an ordering the chain does
 * not have.
 */
export function shortMint(mint: string, lead = 4, tail = 4): string {
  if (mint.length <= lead + tail + 1) return mint;
  return `${mint.slice(0, lead)}…${mint.slice(-tail)}`;
}
