import { STALE_AFTER_MS, fresh, type HqState } from "./adapter";
import type { EmployeeId } from "./employees";

/**
 * TODAY AT HQ.
 *
 * ── WHY THIS IS ONLY PAPER TRADES ───────────────────────────────────────
 *
 * The brief sketches a timeline with discovery, scoring, security and
 * execution rows. Only one of those has a real event log behind it.
 *
 * `health/pipeline` publishes `last_discovery`, `last_score` and
 * `last_snapshot` — one timestamp each, the newest, with no history. There is
 * no endpoint anywhere that lists "tokens discovered today" as events. Turning
 * a single latest mark into a row that reads "18:42 Radar discovered token"
 * would be inventing a history from a scalar, and every reload would produce a
 * different, equally fictional timeline.
 *
 * The permanent Paper audit is different: every completed trade is a written
 * row with its own entry and exit instants, and it is never rewritten. So this
 * builds the timeline from the audit and says so in its own heading. A short
 * true list beats a long invented one, and the brief said exactly that:
 * *if evidence is insufficient, omit it.*
 *
 * Pure, like everything else that reads `HqState`. No fetch, no clock of its
 * own — `state.now` decides what "today" means, so the list and the report
 * that sits above it can never disagree about the day.
 */

export interface TodayEvent {
  /** Epoch ms. Sorting key, and what the row prints. */
  at: number;
  /** Whose desk this belongs to, for the portrait beside the row. */
  who: EmployeeId;
  label: string;
  /** The token, when there is one. */
  symbol: string | null;
  mint: string | null;
}

/** UTC midnight before `now`, matching how the backend buckets its own days. */
function startOfDay(now: number): number {
  const date = new Date(now);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

function parse(value: string | null | undefined): number | null {
  if (!value) return null;
  const at = Date.parse(value);
  return Number.isFinite(at) ? at : null;
}

export function buildToday(state: HqState): TodayEvent[] {
  const audit = fresh(state.sources.paperAudit, STALE_AFTER_MS.paper, state.now);
  if (!audit) return [];
  const since = startOfDay(state.now);
  const events: TodayEvent[] = [];

  for (const item of audit.items) {
    const entry = parse(item.entry_at);
    const exit = parse(item.exit_at);
    const label = item.symbol ?? `${item.mint_address.slice(0, 4)}…`;

    // Rex opens and closes; the row says which. No adjective — "a good exit"
    // is a judgement, and the net figure is already on the Track Record.
    if (entry !== null && entry >= since) {
      events.push({
        at: entry,
        who: "rex",
        label: `Paper entry — ${label}`,
        symbol: item.symbol,
        mint: item.mint_address,
      });
    }
    if (exit !== null && exit >= since) {
      const reason = item.exit_reason ? ` (${item.exit_reason})` : "";
      events.push({
        at: exit,
        who: "rex",
        label: `Paper exit${reason} — ${label}`,
        symbol: item.symbol,
        mint: item.mint_address,
      });
    }
  }

  // Newest last, so the column reads down the day the way a log does.
  return events.sort((a, b) => a.at - b.at || a.label.localeCompare(b.label));
}
