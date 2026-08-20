/**
 * EVENT PRESSURE, NOT EVENTS.
 *
 * MEMESCOPE's stream is not a trickle. The enrichment loop commits an
 * observation roughly once a second and every commit fans out into
 * `market.changed`, `radar.score_updated` and `paper.changed` — the numbers are
 * documented in `use-live-updates.tsx`, which had to learn the same lesson
 * about invalidations that this module has to learn about animations.
 *
 * So HQ never reacts to an event. It measures how many arrived in the last
 * minute and reads a *rate*, and the rate is what a character responds to. One
 * hundred `market.changed` in three seconds is one fact — the market desk is
 * busy — and it produces one state, not one hundred queued reactions.
 *
 * WHY A RING AND NOT A COUNTER
 *
 * A plain counter cannot expire. Something has to say "that was a minute ago
 * and no longer describes now", and the cheapest honest way is to keep the
 * arrival times and drop the old ones. The array is capped: past the cap the
 * reading is already "as busy as this scale goes", and buying a longer array
 * would add memory without adding meaning.
 *
 * NOTHING HERE TOUCHES REACT
 *
 * `record` is called from a stream subscription at whatever rate the stream
 * runs; `snapshot` is called on a slow timer by the hook. That split is the
 * storm protection: the number of renders is set by the timer, never by the
 * number of events.
 */

/** The kinds HQ can read. Anything else on the stream is deliberately ignored. */
export type HqEventKind = "discovery" | "market" | "score" | "radar" | "paper";

export const EVENT_KINDS: HqEventKind[] = ["discovery", "market", "score", "radar", "paper"];

/** The rolling window every count covers. */
export const EVENT_WINDOW_MS = 60_000;

/**
 * Most arrivals kept per kind.
 *
 * Four a second for a minute. Past this the desk is saturated by any reading
 * anyone would take, and the only thing a longer buffer would change is the
 * memory profile during an incident — which is the worst moment to spend it.
 */
export const EVENT_CAP = 240;

/**
 * Which stream events HQ reads, and as what.
 *
 * `real_wallet.changed` and `real_wallet.dry_run.changed` are deliberately
 * absent. Real Wallet is the Vault's subject, not Rex's, and a mapping here
 * would be the shortest path to a paper trader appearing to move real money.
 * A test asserts this table does not grow one.
 */
const EVENT_KIND_BY_TYPE: Record<string, HqEventKind> = {
  "token.discovered": "discovery",
  "market.changed": "market",
  "score.changed": "score",
  "radar.score_updated": "score",
  "radar.changed": "radar",
  "radar.ranking_changed": "radar",
  "paper.changed": "paper",
};

export function kindOf(eventType: string): HqEventKind | null {
  return EVENT_KIND_BY_TYPE[eventType] ?? null;
}

export interface EventActivity {
  /** Arrivals in the last `windowMs`, per kind. Capped at `EVENT_CAP`. */
  counts: Record<HqEventKind, number>;
  /** When each kind last arrived. `null` means "not since this page loaded". */
  lastAt: Record<HqEventKind, number | null>;
  windowMs: number;
  /**
   * Whether the meter has been listening long enough for a zero to mean
   * anything. A count of zero in the first seconds after mount says nothing
   * about the system, and must not read as "quiet".
   */
  settled: boolean;
}

/** A meter that has heard nothing yet. Zero counts, and not settled. */
export function emptyActivity(windowMs = EVENT_WINDOW_MS): EventActivity {
  return {
    counts: { discovery: 0, market: 0, score: 0, radar: 0, paper: 0 },
    lastAt: { discovery: null, market: null, score: null, radar: null, paper: null },
    windowMs,
    settled: false,
  };
}

export interface EventMeter {
  /** Record one arrival. Cheap: a push and an occasional trim. */
  record(eventType: string, now: number): void;
  /** Read the current window. Trims as it goes. */
  snapshot(now: number): EventActivity;
}

export function createEventMeter(
  startedAt: number,
  windowMs = EVENT_WINDOW_MS,
): EventMeter {
  const arrivals: Record<HqEventKind, number[]> = {
    discovery: [],
    market: [],
    score: [],
    radar: [],
    paper: [],
  };
  const lastAt: Record<HqEventKind, number | null> = {
    discovery: null,
    market: null,
    score: null,
    radar: null,
    paper: null,
  };

  function trim(kind: HqEventKind, now: number) {
    const list = arrivals[kind];
    const cutoff = now - windowMs;
    let drop = 0;
    while (drop < list.length && list[drop]! < cutoff) drop += 1;
    if (drop > 0) list.splice(0, drop);
    if (list.length > EVENT_CAP) list.splice(0, list.length - EVENT_CAP);
  }

  return {
    record(eventType, now) {
      const kind = kindOf(eventType);
      if (!kind) return;
      arrivals[kind].push(now);
      lastAt[kind] = now;
      trim(kind, now);
    },
    snapshot(now) {
      const counts = {} as Record<HqEventKind, number>;
      for (const kind of EVENT_KINDS) {
        trim(kind, now);
        counts[kind] = arrivals[kind].length;
      }
      return {
        counts,
        lastAt: { ...lastAt },
        windowMs,
        // One full window of listening before a zero is allowed to mean quiet.
        settled: now - startedAt >= windowMs,
      };
    },
  };
}
