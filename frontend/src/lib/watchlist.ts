/**
 * Watchlist 2.0 — watching requires a reason.
 *
 * A bare list of saved tokens answers "what did I click?" and nothing else. A
 * week later the user cannot remember why any of them are there, so the list
 * stops being useful and starts being noise.
 *
 * Recording the reason turns the watchlist into a set of open questions the
 * platform can answer on every visit: *you were watching this for a breakout —
 * here is whether that happened.* The status attached to each reason is what
 * makes the list worth reopening.
 *
 * Client-side, for the same reason as `changes.ts`: Phase 12 is a presentation
 * phase and a `watchlists` table would be the backend change it rules out. The
 * limitation is real — clearing browser storage clears the list — and the UI
 * says so rather than implying an account-backed list.
 */

export type WatchReason =
  | "breakout"
  | "accumulation"
  | "recovery"
  | "liquidity"
  | "exit_signals"
  | "conviction";

export const WATCH_REASON_LABEL: Record<WatchReason, string> = {
  breakout: "Watching breakout",
  accumulation: "Watching accumulation",
  recovery: "Watching recovery",
  liquidity: "Watching liquidity",
  exit_signals: "Watching exit signals",
  conviction: "Watching conviction increase",
};

/** The question each reason is really asking. Shown under "Why?". */
export const WATCH_REASON_QUESTION: Record<WatchReason, string> = {
  breakout: "Has price moved above its prior observed high with volume behind it?",
  accumulation: "Is structure improving while the market has not yet moved?",
  recovery: "Has this recovered any of the ground it lost since detection?",
  liquidity: "Is there more capital available to trade against than before?",
  exit_signals: "Has Exit Watch started reporting deterioration?",
  conviction: "Has the engine moved this into a stronger band?",
};

export interface WatchEntry {
  mint: string;
  reasons: WatchReason[];
  addedAt: string;
  /** What the token looked like when the user started watching. */
  baseline: {
    score: number | null;
    grade: string | null;
    liquidity: number | null;
    currentMultiple: number | null;
  };
}

export type WatchStatus = "answered" | "unchanged" | "reversed" | "unknown";

export interface WatchOutcome {
  reason: WatchReason;
  status: WatchStatus;
  detail: string;
}

const KEY = "memescope.watchlist";

function read(): Record<string, WatchEntry> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, WatchEntry>) : {};
  } catch {
    return {};
  }
}

function write(entries: Record<string, WatchEntry>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries));
  } catch {
    // Blocked or full storage degrades the feature, never the page.
  }
}

export function watchlist(): WatchEntry[] {
  return Object.values(read()).sort((a, b) => b.addedAt.localeCompare(a.addedAt));
}

export function isWatched(mint: string): boolean {
  return Boolean(read()[mint]);
}

export function watchEntry(mint: string): WatchEntry | undefined {
  return read()[mint];
}

export function addWatch(entry: WatchEntry): void {
  const entries = read();
  const existing = entries[entry.mint];
  entries[entry.mint] = existing
    ? // Merge reasons rather than replacing: a user watching for liquidity who
      // later also watches for breakout is asking two questions, not swapping one.
      { ...existing, reasons: [...new Set([...existing.reasons, ...entry.reasons])] }
    : entry;
  write(entries);
}

export function removeWatch(mint: string): void {
  const entries = read();
  delete entries[mint];
  write(entries);
}

/**
 * Answer each watch reason against the token's current state.
 *
 * Every branch compares the user's own baseline against a current backend
 * figure. No band is invented: `conviction` asks the backend-supplied grade
 * whether it changed, it does not decide what a good grade is.
 */
export function evaluateWatch(
  entry: WatchEntry,
  current: {
    score: number | null;
    grade: string | null;
    liquidity: number | null;
    currentMultiple: number | null;
    exitSeverity: string | null;
    isBreakout: boolean;
  },
): WatchOutcome[] {
  return entry.reasons.map((reason) => {
    switch (reason) {
      case "breakout":
        return {
          reason,
          status: current.isBreakout ? "answered" : "unchanged",
          detail: current.isBreakout
            ? "The Radar currently classifies this as a breakout."
            : "The Radar has not classified this as a breakout.",
        };

      case "liquidity": {
        if (entry.baseline.liquidity === null || current.liquidity === null) {
          return { reason, status: "unknown", detail: "Liquidity is not reported for this pool." };
        }
        const grew = current.liquidity > entry.baseline.liquidity;
        return {
          reason,
          status: grew ? "answered" : "reversed",
          detail: grew
            ? "Liquidity is higher than when you started watching."
            : "Liquidity is at or below where it was when you started watching.",
        };
      }

      case "recovery": {
        if (entry.baseline.currentMultiple === null || current.currentMultiple === null) {
          return { reason, status: "unknown", detail: "No return is recorded for this token." };
        }
        const recovered = current.currentMultiple > entry.baseline.currentMultiple;
        return {
          reason,
          status: recovered ? "answered" : "unchanged",
          detail: recovered
            ? "The return since detection has improved since you started watching."
            : "The return since detection has not improved since you started watching.",
        };
      }

      case "exit_signals": {
        if (!current.exitSeverity) {
          return { reason, status: "unknown", detail: "Exit Watch has no assessment for this token." };
        }
        const clear = current.exitSeverity === "clear";
        return {
          reason,
          status: clear ? "unchanged" : "answered",
          detail: clear
            ? "Exit Watch reports nothing at present."
            : `Exit Watch is reporting ${current.exitSeverity}. It is a warning, not a sell signal.`,
        };
      }

      case "conviction": {
        if (!entry.baseline.grade || !current.grade) {
          return { reason, status: "unknown", detail: "This token is not scored." };
        }
        const moved = entry.baseline.grade !== current.grade;
        return {
          reason,
          status: moved ? "answered" : "unchanged",
          detail: moved
            ? `The engine moved this from ${entry.baseline.grade} to ${current.grade}.`
            : "The engine has kept this in the same band.",
        };
      }

      case "accumulation":
      default:
        return {
          reason,
          status: "unknown",
          detail:
            "Accumulation needs holder and wallet data, which MEMESCOPE does not " +
            "collect. This watch cannot be answered yet.",
        };
    }
  });
}
