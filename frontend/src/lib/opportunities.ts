import { api } from "@/lib/api-client";
import { num } from "@/lib/scores";
import type {
  Opportunity,
  OpportunityBoard,
  OpportunityStage,
  PriorityBand,
} from "@/types/opportunity";

/**
 * OPPORTUNITY BOARD CLIENT
 *
 * Parses, labels, filters and sorts. **It never decides.** The same rule
 * `lib/radar.ts` and `lib/scores.ts` carry: a threshold applied here would be a
 * second, unversioned opinion that could disagree with the engine about the
 * same token. Confidence, priority, stage and every explanation arrive already
 * decided.
 *
 * Search, the confidence/priority filters and sorting run **client-side** over
 * the fetched page. `GET /api/v1/opportunities` supports `signal_type` and
 * `stage` server-side and nothing else, and Sprint 6 may not change the API.
 * That is sound because a live board is small by construction — every signal
 * carries a TTL, so the board holds hours of detections rather than a table —
 * but it is a real limit: filtering narrows what was fetched, not the whole
 * board. `BOARD_PAGE_SIZE` is the endpoint's maximum for that reason.
 */

/** The endpoint's `page_size` ceiling. */
export const BOARD_PAGE_SIZE = 100;

export function fetchOpportunities(params: {
  signalType?: string | null;
  stage?: OpportunityStage | null;
  page?: number;
  pageSize?: number;
} = {}): Promise<OpportunityBoard> {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? BOARD_PAGE_SIZE),
  });
  if (params.signalType) query.set("signal_type", params.signalType);
  if (params.stage) query.set("stage", params.stage);
  return api.get<OpportunityBoard>(`/opportunities?${query.toString()}`);
}

// --- Presentation ------------------------------------------------------------

export const STAGE_LABEL: Record<OpportunityStage, string> = {
  unknown: "Stage unknown",
  pre_graduation: "Pre-graduation",
  near_graduation: "Near graduation",
  fresh_graduation: "Fresh graduation",
  established: "Established",
};

/**
 * Stage hues map to the division that owns the question, not to sentiment.
 * A stage is a fact about where the token is, never a verdict on it.
 */
export const STAGE_TONE: Record<OpportunityStage, string> = {
  unknown: "var(--color-ink-faint)",
  pre_graduation: "var(--color-scout)",
  near_graduation: "var(--color-pulse)",
  fresh_graduation: "var(--color-plasma)",
  established: "var(--color-oracle)",
};

export const PRIORITY_LABEL: Record<PriorityBand, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const PRIORITY_TONE: Record<PriorityBand, string> = {
  low: "var(--color-ink-faint)",
  medium: "var(--color-oracle)",
  high: "var(--color-pulse)",
  critical: "var(--color-apex)",
};

/** Ordering for the priority filter and for sorting bands. Worst first. */
export const PRIORITY_ORDER: PriorityBand[] = ["low", "medium", "high", "critical"];

/**
 * A signal type as a display label.
 *
 * Derived rather than enumerated: the engine can register a provider emitting a
 * type this build has never heard of, and a card showing `whale_accumulation`
 * is far better than one that crashes or silently drops the badge.
 */
export function signalLabel(signalType: string): string {
  const known: Record<string, string> = {
    fresh_graduation: "Fresh graduation",
    near_graduation: "Near graduation",
    liquidity_expansion: "Liquidity expanding",
    volume_expansion: "Volume expanding",
    pre_breakout: "Pre-breakout",
    breakout: "Breakout",
    accumulation: "Accumulation",
    holder_growth: "Holder growth",
    community_surge: "Community surge",
    builder_activity: "Builder activity",
    whale_accumulation: "Whale accumulation",
    smart_money_entry: "Smart money entry",
    narrative_acceleration: "Narrative accelerating",
  };
  if (known[signalType]) return known[signalType];
  return signalType.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** The distinct signal types present on a board, for the filter chips. */
export function signalTypesIn(items: Opportunity[]): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    for (const signal of item.signals) seen.add(signal.signal_type);
  }
  return [...seen].sort();
}

/**
 * "Expires in 47h", "Expires in 12m", "Expired".
 *
 * Coarse on purpose. A countdown to the second implies the expiry moment
 * matters to the reader; it does not — what matters is roughly how long the
 * claim still stands.
 */
export function formatExpiresIn(seconds: number): string {
  if (seconds <= 0) return "Expired";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}m`;
  if (seconds < 172_800) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86_400)}d`;
}

/** "just now", "8m ago", "3h ago", "2d ago". */
export function formatAgo(seconds: number): string {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

/** Seconds between an ISO timestamp and now. Floored at zero for clock skew. */
export function secondsSince(iso: string, now: number = Date.now()): number {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return 0;
  return Math.max(0, Math.round((now - parsed) / 1000));
}

/** The strongest live signal on an opportunity, by confidence. */
export function leadSignal(opportunity: Opportunity) {
  return (
    [...opportunity.signals].sort(
      (a, b) => num(b.confidence) - num(a.confidence),
    )[0] ?? null
  );
}

// --- Client-side narrowing ---------------------------------------------------

export type SortKey = "priority" | "confidence" | "newest";

export interface BoardFilters {
  search: string;
  stage: OpportunityStage | null;
  signalType: string | null;
  /** Minimum confidence, 0–100. */
  minConfidence: number;
  /** Bands to include. Empty means every band. */
  priorities: PriorityBand[];
}

export const NO_FILTERS: BoardFilters = {
  search: "",
  stage: null,
  signalType: null,
  minConfidence: 0,
  priorities: [],
};

export function hasActiveFilters(filters: BoardFilters): boolean {
  return (
    filters.search.trim() !== "" ||
    filters.stage !== null ||
    filters.signalType !== null ||
    filters.minConfidence > 0 ||
    filters.priorities.length > 0
  );
}

/**
 * Matches a token by mint, name or symbol, case-insensitively.
 *
 * Mint matching is a substring rather than a prefix so a pasted partial
 * address from the middle of a string still finds its token.
 */
export function matchesSearch(opportunity: Opportunity, search: string): boolean {
  const term = search.trim().toLowerCase();
  if (!term) return true;
  return (
    opportunity.mint_address.toLowerCase().includes(term) ||
    (opportunity.name ?? "").toLowerCase().includes(term) ||
    (opportunity.symbol ?? "").toLowerCase().includes(term)
  );
}

export function applyFilters(
  items: Opportunity[],
  filters: BoardFilters,
): Opportunity[] {
  return items.filter((item) => {
    if (!matchesSearch(item, filters.search)) return false;
    if (filters.stage && item.stage !== filters.stage) return false;
    if (
      filters.signalType &&
      !item.signals.some((signal) => signal.signal_type === filters.signalType)
    ) {
      return false;
    }
    if (num(item.confidence) < filters.minConfidence) return false;
    if (
      filters.priorities.length > 0 &&
      !filters.priorities.includes(item.priority_band)
    ) {
      return false;
    }
    return true;
  });
}

/**
 * Sorting is total, always.
 *
 * `mint_address` breaks every tie. A partial order means a card swapping places
 * between two 60-second polls for no reason the user can see — the same
 * discipline the backend's own board query holds, and the reason the score
 * sweep's unordered `LIMIT` starved for days.
 */
export function sortOpportunities(
  items: Opportunity[],
  sort: SortKey,
): Opportunity[] {
  const byMint = (a: Opportunity, b: Opportunity) =>
    a.mint_address.localeCompare(b.mint_address);

  return [...items].sort((a, b) => {
    if (sort === "newest") {
      const delta = Date.parse(b.detected_at) - Date.parse(a.detected_at);
      return delta !== 0 ? delta : byMint(a, b);
    }
    if (sort === "confidence") {
      const delta = num(b.confidence) - num(a.confidence);
      return delta !== 0 ? delta : byMint(a, b);
    }
    const delta = num(b.priority) - num(a.priority);
    return delta !== 0 ? delta : byMint(a, b);
  });
}
