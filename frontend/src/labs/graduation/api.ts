import { api } from "@/lib/api-client";

import type {
  FreshHeld,
  GraduationStatus,
  Leaderboard,
  PaperBook,
  Returns,
} from "./types";

/**
 * GRADUATION LAB CLIENT
 *
 * Fetches and nothing else. Every figure arrives already computed — the
 * funnel, the signal split, the derived RPC rate. There is no write: the lab
 * records on its own tick and the backend router has no non-GET route.
 */
export function fetchStatus(): Promise<GraduationStatus> {
  return api.get<GraduationStatus>("/labs/graduation/status");
}

/**
 * Every closed trade, not the handful `/status` carries. Its own call because
 * the board polls status every thirty seconds and this list only grows.
 */
export function fetchPaperTrades(
  book: string,
  size?: { ticket: number; split: number },
): Promise<PaperBook> {
  const wallet = size
    ? `&ticket=${encodeURIComponent(size.ticket)}&split=${encodeURIComponent(size.split)}`
    : "";
  return api.get<PaperBook>(
    `/labs/graduation/paper/trades?book=${encodeURIComponent(book)}${wallet}`,
  );
}

/**
 * One of Karthik's fresh books, by its arm's name: its trades since it started,
 * open and closed, each stamped with what its wallet made on it. The server
 * fixes the start and the wallet, so the name is all there is to pass.
 */
export function fetchFreshTrades(book: string): Promise<PaperBook> {
  return api.get<PaperBook>(
    `/labs/graduation/paper/trades?fresh=${encodeURIComponent(book)}`,
  );
}

/**
 * A fresh book's closed coins as if it had never sold, every pool read
 * on-chain by the server (cached two minutes there).
 */
export function fetchFreshHeld(book: string): Promise<FreshHeld> {
  return api.get<FreshHeld>(
    `/labs/graduation/fresh/held?book=${encodeURIComponent(book)}`,
  );
}

/**
 * The peak-multiple distribution. Its own call because it scans the whole
 * sample table and the board polls every thirty seconds.
 */
export function fetchReturns(): Promise<Returns> {
  return api.get<Returns>("/labs/graduation/returns");
}

/** The fifty-arm leaderboard, controls included. */
export function fetchTournament(): Promise<Leaderboard> {
  return api.get<Leaderboard>("/labs/graduation/tournament");
}
