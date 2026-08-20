import type { EmployeeId } from "./employees";
import type { SupportId } from "./support";

/**
 * WHAT PEOPLE SAY WHEN THEY ARE NOT REPORTING.
 *
 * ── THE RULE THAT SHAPES THIS WHOLE FILE ────────────────────────────────
 *
 * **Not one line here is operational.** No number, no status, no claim about a
 * queue, a token, a feed or a position. That is not squeamishness: HQ's
 * standing product rule is that a sentence about the system must be traceable
 * to a reading, and an ambient routine has no reading behind it — it fires on
 * a timer, in an office that may be an hour stale.
 *
 * The brief's own examples are exactly the sentences this refuses. "Feeds
 * stable" is a claim about the feeds. "Queue looks normal" is a claim about
 * the queue. "New candidate" is a claim that a token was discovered. If those
 * were said on a timer they would be false roughly as often as they were true,
 * and a reader has no way to tell an ambient bubble from a reported one.
 *
 * So the split is:
 *
 *   ambient  → this file. Social, neutral, about the person and never the
 *              system. Fires whenever.
 *   reported → `reactions.ts`. One line per real observed change, and it says
 *              what changed. Fires only when the adapter saw it happen.
 *
 * Both draw the same bubble. Only one of them is allowed to mention the work.
 *
 * ── WHY THE LINES ARE DULL ──────────────────────────────────────────────
 *
 * Deliberately. A character who says something memorable says it again four
 * minutes later, and the room stops reading as an office and starts reading as
 * a screensaver with jokes in it. These are the half-sentences people actually
 * say to each other across a desk.
 */

/** A line, and the routines it is allowed to appear on. */
export interface Chatter {
  /** Whose mouth it comes out of. */
  actor: EmployeeId | SupportId;
  lines: string[];
}

/**
 * Deliberately short. A bubble is on screen for one frame's hold, and a line
 * that needs a second read is a line nobody finishes.
 */
export const MAX_CHATTER_LENGTH = 34;

export const CHATTER: Chatter[] = [
  { actor: "nova", lines: ["Morning, all.", "How's it going?", "Good work.", "I'll be around."] },
  { actor: "radar", lines: ["Back in a sec.", "Long morning.", "Need a refill.", "Nearly there."] },
  { actor: "luna", lines: ["One moment.", "Let me read that again.", "Noted.", "Mm-hmm."] },
  { actor: "dex", lines: ["Four screens, one coffee.", "Give me a minute.", "Right, right.", "Busy one."] },
  { actor: "atlas", lines: ["Hm.", "Not yet.", "Let me check first.", "I'd rather be sure."] },
  { actor: "milo", lines: ["Thinking.", "Long game.", "Fair enough.", "Let's see."] },
  { actor: "rex", lines: ["Standing by.", "On it.", "Understood.", "Sure thing."] },
  { actor: "echo", lines: ["Two seconds.", "Coming through.", "Almost done.", "On my way."] },
  { actor: "byte", lines: ["Rebooting my brain.", "Coffee first.", "Yep.", "Give it a moment."] },
  { actor: "sage", lines: ["Interesting.", "Let me plot that.", "Later, maybe.", "Hm, alright."] },
  { actor: "maya", lines: ["Won't be a minute.", "Nearly finished.", "Mind the floor."] },
  { actor: "sam", lines: ["I'll fix it.", "Spare's in the back.", "That'll do it."] },
];

export const CHATTER_BY_ACTOR = new Map<string, string[]>(
  CHATTER.map((entry) => [entry.actor, entry.lines]),
);

/**
 * Pick a line for an actor, or `null` if they have none.
 *
 * Not used by the scheduler, which rotates deterministically. Kept for
 * surfaces that want one line and do not care which.
 */
export function pickChatter(actor: string, random: () => number = Math.random): string | null {
  const lines = CHATTER_BY_ACTOR.get(actor);
  if (!lines || lines.length === 0) return null;
  return lines[Math.floor(random() * lines.length)] ?? null;
}

/**
 * How often a routine that *could* carry a bubble actually does: one in three.
 *
 * Every routine speaking fills the room with text; none speaking is the office
 * it already was. A third is roughly how often somebody crossing a room says
 * something out loud.
 *
 * Counted rather than rolled — see `withChatter` in the scheduler for why a
 * probability broke two unrelated tests.
 */
export const CHATTER_EVERY = 3;
