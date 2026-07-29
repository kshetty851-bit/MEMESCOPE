import { api } from "@/lib/api-client";
import type {
  ScoreGrade,
  ScoreHistoryPage,
  ScoringModel,
  TokenScore,
  TokenScoreEnvelope,
  TopScorePage,
} from "@/types/score";

/**
 * SCORE API CLIENT
 *
 * The only place the frontend talks to the scoring service, and the only place
 * that knows the shape of its responses.
 *
 * Nothing here computes a score. The engine is deterministic, versioned and
 * auditable on the backend; deriving anything from these numbers on the client
 * would produce a second, unversioned opinion that could disagree with the one
 * the API just served. The functions below parse and present — they never
 * decide.
 */

/** Ranking rows carry no component breakdown; the per-token endpoint does. */
export function fetchTopScores(params: {
  pageSize?: number;
  minScore?: number;
  includeVetoed?: boolean;
  sort?: string;
  order?: "asc" | "desc";
}): Promise<TopScorePage> {
  const query = new URLSearchParams({
    page_size: String(params.pageSize ?? 20),
    sort: params.sort ?? "score",
    order: params.order ?? "desc",
  });
  if (params.minScore !== undefined) query.set("min_score", String(params.minScore));
  if (params.includeVetoed) query.set("include_vetoed", "true");
  return api.get<TopScorePage>(`/scores/top?${query.toString()}`);
}

export function fetchTokenScore(mint: string): Promise<TokenScoreEnvelope> {
  return api.get<TokenScoreEnvelope>(`/scores/${mint}`);
}

export function fetchScoreHistory(mint: string, pageSize = 25): Promise<ScoreHistoryPage> {
  return api.get<ScoreHistoryPage>(`/scores/${mint}/history?page_size=${pageSize}`);
}

export function fetchScoringModel(): Promise<ScoringModel> {
  return api.get<ScoringModel>("/scores/model");
}

// --- Presentation ------------------------------------------------------------
//
// Parsing and labelling only. If a function here ever needs a threshold that
// changes a verdict, it belongs in the engine instead.

/** Parse a Decimal-as-string. Returns 0 for null, empty, or unparseable input. */
export function num(value: string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** A 0–100 backend figure as the 0–1 fraction the `Meter` primitive expects. */
export function ratio(value: string | null | undefined): number {
  return Math.max(0, Math.min(1, num(value) / 100));
}

export const GRADE_LABEL: Record<ScoreGrade, string> = {
  critical: "Critical",
  weak: "Weak",
  watch: "Watch",
  strong: "Strong",
  high_conviction: "High Conviction",
};

/**
 * Colour per grade, from the existing design tokens.
 *
 * Gold (`apex`) is deliberately absent: it is reserved for Elite certification,
 * which is a separate gate the grade alone never earns.
 */
export const GRADE_TONE: Record<ScoreGrade, string> = {
  critical: "var(--color-danger)",
  weak: "var(--color-ink-faint)",
  watch: "var(--color-ink-dim)",
  strong: "var(--color-oracle)",
  high_conviction: "var(--color-safe)",
};

/** Why a token has no score, in the user's words. Backend states, not guesses. */
export const STATUS_MESSAGE: Record<string, string> = {
  awaiting_market: "Awaiting first market observation.",
  not_scored: "Discovered — division analysing.",
  insufficient_data: "Too little data to score this token.",
  scoring_disabled: "Scoring engine is offline.",
};

/**
 * The freshness figure as a short label.
 *
 * Freshness is computed per request by the backend from the age of the
 * underlying snapshot, so a stalled token reads as stale without anything
 * having to rewrite its row.
 */
export function freshnessLabel(freshness: number): string {
  if (freshness >= 0.9) return "Live";
  if (freshness >= 0.6) return "Recent";
  if (freshness > 0) return "Ageing";
  return "Stale";
}

/** Elite is a backend gate. This only asks the score object what it decided. */
export function isElite(score: TokenScore | null | undefined): boolean {
  return score?.is_elite === true;
}
