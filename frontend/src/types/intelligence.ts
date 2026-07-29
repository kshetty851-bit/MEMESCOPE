/**
 * Exit Watch and permanent-record contracts.
 *
 * Mirrors `backend/app/exit_signals/schemas.py`. Decimals arrive as strings.
 */

export type ExitSeverity = "clear" | "watch" | "elevated";

export interface ExitSignal {
  code: string;
  label: string;
  agent: string;
  /** Rendered by the backend. The client never composes these. */
  message: string;
  triggered: boolean;
  /** False when the signal could not be checked — never a pass. */
  available: boolean;
  magnitude: string | null;
}

export interface ExitAssessment {
  mint_address: string;
  severity: ExitSeverity;
  coverage: string;
  summary: string;
  signals: ExitSignal[];
  current_multiple: string | null;
  peak_multiple: string | null;
  evaluated_at: string;
}

export interface ExitWatchPage {
  items: ExitAssessment[];
  total: number;
  /** Carried on every response so no view can render the list without it. */
  disclaimer: string;
}

export interface HallEntry {
  mint_address: string;
  category: string;
  original_category: string;
  first_detected_at: string;
  first_market_cap: string | null;
  first_price: string | null;
  peak_market_cap: string | null;
  peak_price: string | null;
  peak_multiple: string | null;
  peak_at: string | null;
  current_market_cap: string | null;
  current_price: string | null;
  current_multiple: string | null;
  days_since_detection: string;
  days_to_peak: string | null;
  opportunity_score: string;
  confidence: string;
  is_active: boolean;
}

export interface LeaderboardBoard {
  id: string;
  label: string;
  description: string;
  entries: HallEntry[];
}

export interface Leaderboard {
  boards: LeaderboardBoard[];
  smart_money_available: boolean;
  smart_money_note: string;
}

export interface SmartMoneyBlock {
  mint_address: string;
  /** All null while wallet data is uncollected. Null, never zero. */
  smart_wallet_count: number | null;
  average_wallet_quality: string | null;
  net_accumulation: string | null;
  accumulation_trend: string | null;
  distribution_trend: string | null;
  largest_recent_buyer: string | null;
  largest_recent_seller: string | null;
  unavailable_reason: string;
}
