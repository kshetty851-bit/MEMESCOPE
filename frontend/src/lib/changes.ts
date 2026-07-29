/**
 * What changed since the user last looked.
 *
 * ## Why this is client-side
 *
 * "Since your last visit" is a fact about *this browser*, not about the token.
 * The platform has no accounts-with-history yet, and Phase 12 is explicitly a
 * presentation phase — adding a `user_seen_state` table would be exactly the
 * backend change the brief rules out. So the last-seen snapshot lives in
 * `localStorage`, keyed per surface.
 *
 * The consequence is honest and worth stating in the UI: clear the browser
 * storage and the feed resets. That is a real limitation of doing it this way,
 * and it is preferable to inventing a per-user table this phase was told not to
 * build.
 *
 * ## What counts as a change
 *
 * Only movements the user could act on. A score drifting 0.4 is noise — the
 * engine's own materiality rule already treats a 2.0 move as the threshold for
 * writing history, so this module reuses that number rather than inventing a
 * second opinion about what "material" means.
 */

import type { ScoreGrade } from "@/types/score";

/**
 * The engine's own materiality threshold for a score movement, from
 * `services/scoring/materiality.py`. Reused rather than re-decided.
 */
export const MATERIAL_SCORE_DELTA = 2.0;

/** The minimum relative move before a market figure is worth reporting. */
export const MATERIAL_RATIO = 0.1;

export interface TokenSnapshotMemory {
  score: number | null;
  grade: ScoreGrade | null;
  liquidity: number | null;
  volume24h: number | null;
  currentMultiple: number | null;
  exitSeverity: string | null;
}

export type ChangeDirection = "up" | "down" | "none";

export interface Change {
  code: string;
  label: string;
  direction: ChangeDirection;
  /** Rendered for display, e.g. "+18%" or "Watch → Elevated". */
  display: string;
  /** Why this is worth surfacing. */
  detail: string;
}

function pctChange(before: number, after: number): number {
  if (before === 0) return 0;
  return (after - before) / Math.abs(before);
}

function formatPct(fraction: number): string {
  const pct = Math.round(fraction * 100);
  return `${pct > 0 ? "+" : ""}${pct}%`;
}

/**
 * Diff two observations of the same token.
 *
 * Returns only movements that clear the materiality bar, so a user opening the
 * page twice in a minute sees nothing rather than a list of rounding noise.
 */
export function diffToken(
  before: TokenSnapshotMemory | undefined,
  after: TokenSnapshotMemory,
): Change[] {
  if (!before) return [];

  const changes: Change[] = [];

  if (before.score !== null && after.score !== null) {
    const delta = after.score - before.score;
    if (Math.abs(delta) >= MATERIAL_SCORE_DELTA) {
      changes.push({
        code: "SCORE_MOVED",
        label: "Score",
        direction: delta > 0 ? "up" : "down",
        display: `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`,
        detail:
          "The engine re-evaluated this token and its score moved by more than " +
          "the amount it treats as material.",
      });
    }
  }

  if (before.grade && after.grade && before.grade !== after.grade) {
    changes.push({
      code: "GRADE_CHANGED",
      label: "Conviction",
      direction: "none",
      display: `${before.grade} → ${after.grade}`,
      detail: "The engine moved this token into a different band.",
    });
  }

  if (before.liquidity !== null && after.liquidity !== null) {
    const change = pctChange(before.liquidity, after.liquidity);
    if (Math.abs(change) >= MATERIAL_RATIO) {
      changes.push({
        code: "LIQUIDITY_MOVED",
        label: "Liquidity",
        direction: change > 0 ? "up" : "down",
        display: formatPct(change),
        detail:
          change > 0
            ? "More capital is available to trade against than when you last looked."
            : "Less capital is available to trade against than when you last looked.",
      });
    }
  }

  if (before.volume24h !== null && after.volume24h !== null) {
    const change = pctChange(before.volume24h, after.volume24h);
    if (Math.abs(change) >= MATERIAL_RATIO) {
      changes.push({
        code: "VOLUME_MOVED",
        label: "Volume",
        direction: change > 0 ? "up" : "down",
        display: formatPct(change),
        detail: "Reported 24-hour volume has moved since your last visit.",
      });
    }
  }

  if (before.currentMultiple !== null && after.currentMultiple !== null) {
    const change = pctChange(before.currentMultiple, after.currentMultiple);
    if (Math.abs(change) >= MATERIAL_RATIO) {
      changes.push({
        code: "RETURN_MOVED",
        label: "Return since detection",
        direction: change > 0 ? "up" : "down",
        display: `${after.currentMultiple.toFixed(2)}×`,
        detail:
          "Measured from LETZMOON's first detection, never from the token's launch.",
      });
    }
  }

  if (before.exitSeverity && after.exitSeverity && before.exitSeverity !== after.exitSeverity) {
    changes.push({
      code: "EXIT_WATCH_CHANGED",
      label: "Exit Watch",
      direction: after.exitSeverity === "clear" ? "up" : "down",
      display: `${before.exitSeverity} → ${after.exitSeverity}`,
      detail:
        "Exit Watch is a warning system, never a sell signal. It reports " +
        "deterioration it can observe; it knows nothing about your position.",
    });
  }

  return changes;
}

// --- Visit memory ----------------------------------------------------------

const VISIT_KEY = "memescope.lastVisit";
const MEMORY_KEY = "memescope.tokenMemory";

interface StoredMemory {
  at: string;
  tokens: Record<string, TokenSnapshotMemory>;
}

function readStore(): StoredMemory | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(MEMORY_KEY);
    return raw ? (JSON.parse(raw) as StoredMemory) : null;
  } catch {
    // Corrupt or unavailable storage must never break the page: the feed
    // degrades to "first visit", which is the truthful fallback.
    return null;
  }
}

export function lastVisitAt(): Date | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(VISIT_KEY);
  return raw ? new Date(raw) : null;
}

export function rememberedTokens(): Record<string, TokenSnapshotMemory> {
  return readStore()?.tokens ?? {};
}

/** Persist what the user has just been shown, for the next visit to diff against. */
export function rememberVisit(tokens: Record<string, TokenSnapshotMemory>, now: Date): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      MEMORY_KEY,
      JSON.stringify({ at: now.toISOString(), tokens } satisfies StoredMemory),
    );
    window.localStorage.setItem(VISIT_KEY, now.toISOString());
  } catch {
    // Storage full or blocked. The product still works; it just cannot
    // personalise, which is a degradation rather than a failure.
  }
}

export function clearVisitMemory(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(MEMORY_KEY);
  window.localStorage.removeItem(VISIT_KEY);
}
