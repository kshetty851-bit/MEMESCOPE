import { num } from "@/lib/design/bands";
import { RISK_BANDS, riskBandFrom } from "@/lib/design/bands";
import type { RadarEntry } from "@/types/radar";

/**
 * SCANNER LOGIC — pure, and therefore testable.
 *
 * Nothing here decides anything the engine already decided. It selects,
 * compares and filters over values the backend published. The two rules the
 * rest of the product runs on hold here too:
 *
 *  - An absent value is `null`, never 0. It sorts to the bottom in **both**
 *    directions and filters out of *every* band rather than defaulting into
 *    the worst one.
 *  - No threshold is invented. The risk band and the score are read as sent.
 *    The one derived figure in this file — buy/sell share — is arithmetic over
 *    two counts the backend published, and it is labelled as transactions
 *    rather than as people.
 */

/* --------------------------------------------------------------------------
   What the backend can sort
   -------------------------------------------------------------------------- */

/**
 * `/radar` accepts exactly these four. Anything else the user picks is applied
 * client-side over the page already held — which is a real distinction, not a
 * pedantic one: a client sort reorders 50 rows, a server sort reorders the
 * whole set and can change *which* 50 you have.
 */
export const SERVER_SORTS = ["score", "detected", "peak", "current"] as const;
export type ServerSort = (typeof SERVER_SORTS)[number];

export function isServerSort(key: string): key is ServerSort {
  return (SERVER_SORTS as readonly string[]).includes(key);
}

/* --------------------------------------------------------------------------
   Sorting
   -------------------------------------------------------------------------- */

export type ScannerSortKey =
  | "rank"
  | "age"
  | "price"
  | "marketCap"
  | "liquidity"
  | "volume"
  | "change"
  | "current"
  | "peak"
  | "score"
  | "risk"
  | "evidence";

/**
 * The comparable value behind a column.
 *
 * `rank` is the backend's own ordering, carried on the row rather than
 * recomputed — see `RankedEntry`. Returning `null` anywhere means "not
 * measured", and `useTableSort` puts those at the bottom whichever way the
 * column points.
 */
export function scannerSortValue(
  entry: RankedEntry,
  key: string,
): number | string | null {
  switch (key) {
    case "rank":
      return entry.rank;
    case "age":
      return entry.age_seconds ?? null;
    case "price":
      return num(entry.market?.price_usd);
    case "marketCap":
      return num(entry.market?.market_cap);
    case "liquidity":
      return num(entry.market?.liquidity_usd);
    case "volume":
      return num(entry.market?.volume_24h);
    case "change":
      return num(entry.market?.change_24h_pct);
    case "current":
      return num(entry.current_multiple);
    case "peak":
      return num(entry.peak_multiple);
    case "score":
      return num(entry.opportunity_score);
    case "evidence":
      return num(entry.evidence);
    case "risk": {
      // Sorted by band rank, not by the underlying score: the bands are what
      // the product claims, and the raw risk score runs the opposite way (a
      // LOW number is the dangerous end), which would silently invert this.
      const band = riskBandFrom(entry.risk_band);
      return band ? band.rank : null;
    }
    default:
      return null;
  }
}

/* --------------------------------------------------------------------------
   Rank
   -------------------------------------------------------------------------- */

export interface RankedEntry extends RadarEntry {
  /**
   * Position in the backend's ranking, 1-based, fixed at fetch time.
   *
   * This is the whole reason it lives on the row. The Radar's ordering is the
   * product's opinion; if the reader sorts by liquidity, the numbers must keep
   * pointing at the engine's ranking rather than renumbering 1..n to describe
   * the sort the reader just chose. Renumbering would turn a claim into a
   * label for scroll position.
   */
  rank: number;
}

/** Stamps the server's order onto the rows before any client sort can move them. */
export function withRank(entries: RadarEntry[]): RankedEntry[] {
  return entries.map((entry, index) => ({ ...entry, rank: index + 1 }));
}

/* --------------------------------------------------------------------------
   Filters
   -------------------------------------------------------------------------- */

export type RiskFilter = "all" | "low" | "medium" | "high" | "extreme";
export type FreshnessFilter = "all" | "priced" | "unpriced";
export type AgeFilter = "all" | "1h" | "24h" | "7d";

export interface ScannerFilters {
  risk: RiskFilter;
  freshness: FreshnessFilter;
  age: AgeFilter;
  /** Minimum liquidity in USD. 0 means no floor. */
  minLiquidity: number;
  /** Matches symbol, name or mint. Case-insensitive. */
  query: string;
}

export const DEFAULT_FILTERS: ScannerFilters = {
  risk: "all",
  freshness: "all",
  age: "all",
  minLiquidity: 0,
  query: "",
};

const AGE_LIMIT: Record<Exclude<AgeFilter, "all">, number> = {
  "1h": 3_600,
  "24h": 86_400,
  "7d": 604_800,
};

/**
 * Whether a row survives the filters.
 *
 * Every branch treats absence as *excluded from a positive filter*, never as
 * a match. A token whose risk was never assessed does not appear under "low
 * risk" — it was not measured, and quietly counting it as safe is the single
 * most dangerous default available here.
 */
export function matchesFilters(entry: RankedEntry, filters: ScannerFilters): boolean {
  if (filters.risk !== "all") {
    const band = riskBandFrom(entry.risk_band);
    if (!band || band.id !== filters.risk) return false;
  }

  if (filters.freshness === "priced" && !entry.market?.captured_at) return false;
  if (filters.freshness === "unpriced" && entry.market?.captured_at) return false;

  if (filters.age !== "all") {
    const age = entry.age_seconds;
    // Unknown age cannot satisfy "younger than an hour".
    if (age === null || age === undefined) return false;
    if (age > AGE_LIMIT[filters.age]) return false;
  }

  if (filters.minLiquidity > 0) {
    const liquidity = num(entry.market?.liquidity_usd);
    if (liquidity === null || liquidity < filters.minLiquidity) return false;
  }

  const query = filters.query.trim().toLowerCase();
  if (query) {
    const haystack = [entry.symbol, entry.name, entry.mint_address]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(query)) return false;
  }

  return true;
}

export function activeFilterCount(filters: ScannerFilters): number {
  let count = 0;
  if (filters.risk !== "all") count += 1;
  if (filters.freshness !== "all") count += 1;
  if (filters.age !== "all") count += 1;
  if (filters.minLiquidity > 0) count += 1;
  if (filters.query.trim()) count += 1;
  return count;
}

/** The risk options, in danger order, for the filter control. */
export const RISK_FILTER_OPTIONS = [
  { value: "all" as const, label: "Any" },
  ...Object.values(RISK_BANDS)
    .sort((a, b) => a.rank - b.rank)
    .map((band) => ({ value: band.id as RiskFilter, label: band.label })),
];

/* --------------------------------------------------------------------------
   Buy / sell pressure
   -------------------------------------------------------------------------- */

export interface BuySellPressure {
  buys: number;
  sells: number;
  total: number;
  /** Buy share of transactions, 0–100. */
  buyPct: number;
}

/**
 * Buy/sell split over the last 24 hours.
 *
 * **These are transaction counts, not people.** One wallet can produce a
 * hundred of them and the API cannot distinguish that, so nothing built on
 * this may say "buyers" — every surface rendering it says "transactions" or
 * "txns". Calling 68 buys "68 buyers" would be inventing a holder metric this
 * platform does not have.
 *
 * Returns `null` when either count is missing, and when both are zero: a token
 * with no transactions has no split, and 0/0 is not 50%. That guard is the
 * reason this is a function rather than an inline division.
 *
 * Note this is deliberately absent from the scanner table — the `/radar` list
 * response carries no transaction counts (see `MarketStripOut`). It is only
 * reachable per-token, so it appears in the quick-detail panel.
 */
export function buySellPressure(
  buys: number | null | undefined,
  sells: number | null | undefined,
): BuySellPressure | null {
  if (buys === null || buys === undefined) return null;
  if (sells === null || sells === undefined) return null;
  if (!Number.isFinite(buys) || !Number.isFinite(sells)) return null;
  if (buys < 0 || sells < 0) return null;

  const total = buys + sells;
  if (total === 0) return null;

  return { buys, sells, total, buyPct: (buys / total) * 100 };
}
