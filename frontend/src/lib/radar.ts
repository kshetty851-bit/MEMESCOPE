import { api } from "@/lib/api-client";
import { num } from "@/lib/scores";
import type {
  RadarCategory,
  RadarDetail,
  RadarHistory,
  RadarModel,
  RadarPage,
  RadarBenchmark,
  RadarPerformance,
  RadarTimelineEvent,
} from "@/types/radar";

/**
 * RADAR API CLIENT
 *
 * Parses and labels. **It never decides.** The same rule `lib/scores.ts`
 * carries, and for the same reason: a threshold applied here would be a second,
 * unversioned opinion that could disagree with the engine about the same token.
 * Categories, scores and confidence all arrive already decided.
 */

export function fetchRadar(params: {
  category?: RadarCategory | null;
  includeInactive?: boolean;
  sort?: "score" | "detected" | "peak" | "current";
  page?: number;
  pageSize?: number;
}): Promise<RadarPage> {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 25),
    sort: params.sort ?? "score",
  });
  if (params.category) query.set("category", params.category);
  if (params.includeInactive) query.set("include_inactive", "true");
  return api.get<RadarPage>(`/radar?${query.toString()}`);
}

export function fetchRadarEntry(mint: string): Promise<RadarDetail> {
  return api.get<RadarDetail>(`/radar/${mint}`);
}

export function fetchRadarHistory(mint: string, limit = 100): Promise<RadarHistory> {
  return api.get<RadarHistory>(`/radar/${mint}/history?limit=${limit}`);
}

export function fetchRadarTimeline(limit = 50): Promise<RadarTimelineEvent[]> {
  return api.get<RadarTimelineEvent[]>(`/radar/timeline?limit=${limit}`);
}

export function fetchRadarBenchmark(): Promise<RadarBenchmark> {
  return api.get<RadarBenchmark>("/radar/benchmark");
}

export function fetchRadarPerformance(): Promise<RadarPerformance> {
  return api.get<RadarPerformance>("/radar/performance");
}

export function fetchRadarLeaderboard(limit = 25) {
  return api.get<RadarDetail[]>(`/radar/leaderboard?limit=${limit}`);
}

export function fetchRadarModel(): Promise<RadarModel> {
  return api.get<RadarModel>("/radar/categories");
}

// --- Presentation ------------------------------------------------------------

export const CATEGORY_LABEL: Record<RadarCategory, string> = {
  early_momentum: "Early Momentum",
  breakout: "Breakout",
  strong_community: "Strong Community",
  undervalued: "Undervalued",
  elite: "Elite",
};

/**
 * Colour per category.
 *
 * Gold (`apex`) goes to Elite and nothing else — the design system reserves it
 * for the rarest verdict, and spending it on a common category would devalue
 * the one thing meant to feel rare.
 */
export const CATEGORY_TONE: Record<RadarCategory, string> = {
  early_momentum: "var(--color-scout)",
  breakout: "var(--color-pulse)",
  strong_community: "var(--color-echo)",
  undervalued: "var(--color-oracle)",
  elite: "var(--color-apex)",
};

/**
 * A multiple as it should read on screen.
 *
 * Below 1 is a loss and is shown as such rather than hidden — the track record
 * is only evidence if it reports both directions.
 */
export function formatMultiple(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = num(value);
  if (parsed <= 0) return "—";
  return `${parsed.toFixed(parsed >= 10 ? 0 : 2)}×`;
}

/** Whether a multiple represents a gain, a loss, or nothing measurable. */
export function multipleTone(
  value: string | null | undefined,
): "positive" | "negative" | "neutral" {
  if (value === null || value === undefined || value === "") return "neutral";
  const parsed = num(value);
  if (parsed > 1) return "positive";
  if (parsed > 0 && parsed < 1) return "negative";
  return "neutral";
}

export function formatDays(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const days = num(value);
  if (days < 1) return "today";
  if (days < 2) return "1 day";
  return `${Math.floor(days)} days`;
}

/**
 * An elapsed duration as a complete phrase.
 *
 * Separate from `formatDays` because callers were appending " ago" to its
 * output, which rendered "today ago". A phrase that only reads correctly when
 * the caller remembers to decorate it is a phrase that will eventually read
 * wrong somewhere.
 */
export function formatAgo(value: string | null | undefined): string {
  const days = formatDays(value);
  if (days === "—") return "—";
  if (days === "today") return "today";
  return `${days} ago`;
}
