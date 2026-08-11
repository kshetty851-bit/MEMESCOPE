import { ApiError, api } from "@/lib/api-client";
import type {
  Watchlist,
  WatchlistCreate,
  WatchlistItem,
  WatchlistItemCreate,
} from "@/types/watchlist";

/**
 * WATCHLIST API CLIENT.
 *
 * Thin, like every other client here — it parses and calls, it never decides.
 *
 * ONE THING WORTH KNOWING BEFORE READING ANY OF THIS
 *
 * Watchlists are the first genuinely *user-owned* resource in MEMESCOPE. Every
 * route is scoped to the authenticated user in SQL, which means they need a
 * real account row — not the alpha cookie, which is a gate rather than an
 * identity.
 *
 * With `DEVELOPMENT_BYPASS_AUTH=true` the backend issues a fixed synthetic
 * principal that is deliberately never written to `users`
 * (`_developer_principal` in `api/deps.py`). Reads work and return nothing;
 * the first write hits `_require_persisted` and comes back 409 with a message
 * explaining exactly that. `isUnpersistedAccount` recognises it so the UI can
 * say so plainly instead of rendering "something went wrong".
 */

export function fetchWatchlists(): Promise<Watchlist[]> {
  return api.get<Watchlist[]>("/watchlists");
}

export function createWatchlist(payload: WatchlistCreate): Promise<Watchlist> {
  return api.post<Watchlist>("/watchlists", {
    name: payload.name,
    description: payload.description ?? null,
    alert_on: payload.alert_on ?? [],
  });
}

export function deleteWatchlist(listId: string): Promise<void> {
  return api.delete<void>(`/watchlists/${listId}`);
}

export function fetchWatchlistTokens(listId: string): Promise<WatchlistItem[]> {
  return api.get<WatchlistItem[]>(`/watchlists/${listId}/tokens`);
}

export function addWatchlistToken(
  listId: string,
  payload: WatchlistItemCreate,
): Promise<WatchlistItem> {
  return api.post<WatchlistItem>(`/watchlists/${listId}/tokens`, {
    mint_address: payload.mint_address,
    note: payload.note ?? null,
  });
}

export function removeWatchlistToken(listId: string, mint: string): Promise<void> {
  return api.delete<void>(`/watchlists/${listId}/tokens/${mint}`);
}

/* --------------------------------------------------------------------------
   Error shapes worth naming
   -------------------------------------------------------------------------- */

/**
 * The 409 raised when the authenticated principal has no `users` row.
 *
 * A configuration state, not a user error, and the difference matters: telling
 * someone "that failed" when the real answer is "this environment runs with the
 * auth bypass and watchlists need a real account" costs them an afternoon.
 */
export function isUnpersistedAccount(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    /development auth bypass|real account/i.test(error.message)
  );
}

/** The 409 raised when a mint is already on the list. Benign — treat as success. */
export function isAlreadyWatched(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    /already on this watchlist/i.test(error.message)
  );
}
