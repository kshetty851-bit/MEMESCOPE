/**
 * Watchlist API contracts.
 *
 * Mirrors `backend/app/schemas/intelligence.py`. Decimals arrive as strings, as
 * everywhere else in this product.
 *
 * Two things this shape tells you that the nav item's singular label does not:
 * a user has *many* named lists, and a watched token carries a snapshot of its
 * state **at the moment it was added** alongside its current state. That pairing
 * is the whole point of the feature — it answers "what has changed since I
 * started watching this?" without the client re-deriving anything.
 */

export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  /**
   * Event codes this list would alert on. The backend stores it; **nothing
   * delivers alerts yet**, so no surface may present this as a working
   * notification setting.
   */
  alert_on: string[];
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItem {
  mint_address: string;
  note: string | null;

  /** State captured when the token was added. Written once, never updated. */
  added_mission_state: string | null;
  added_priority: string | null;
  added_score: string | null;
  created_at: string;

  /** State now. Null where that dimension has never been recorded. */
  current_mission_state: string | null;
  current_priority: string | null;
  current_score: string | null;

  /** The most recent recorded change, rendered by the backend. */
  last_change: string | null;
  last_change_at: string | null;
}

export interface WatchlistCreate {
  name: string;
  description?: string | null;
  alert_on?: string[];
}

export interface WatchlistItemCreate {
  mint_address: string;
  note?: string | null;
}
