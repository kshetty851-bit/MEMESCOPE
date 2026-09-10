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
  { actor: "nova", lines: ["Morning, all.", "How's it going?", "Good work.", "I'll be around.", "Keep at it.", "Anything you need?", "Nice one."] },
  { actor: "radar", lines: ["Back in a sec.", "Long morning.", "Need a refill.", "Nearly there.", "One more pass.", "Where'd I put that.", "Right, again."] },
  { actor: "atlas", lines: ["Hm.", "Not yet.", "Let me check first.", "I'd rather be sure.", "Slow down.", "Say that again.", "I want it in writing."] },
  { actor: "milo", lines: ["Thinking.", "Long game.", "Fair enough.", "Let's see.", "Give it time.", "No rush.", "That'll keep."] },
  { actor: "rex", lines: ["Standing by.", "On it.", "Understood.", "Sure thing.", "Ready when you are.", "Say the word.", "Clean."] },
  { actor: "echo", lines: ["Two seconds.", "Coming through.", "Almost done.", "On my way.", "Behind you.", "Just squeezing past.", "Got it, got it."] },
  { actor: "byte", lines: ["Rebooting my brain.", "Coffee first.", "Yep.", "Give it a moment.", "Kettle's on.", "Don't ask.", "It's a Monday thing."] },
  // The reliability trio. Same rule as everyone else: nothing here may hint
  // that something is wrong, because these fire on a timer. "All quiet" would
  // be a claim; "Long shift" is a person.
  { actor: "sentinel", lines: ["Long shift.", "Still here.", "Mm.", "I'll keep watching.", "Quiet one.", "I'll take the late half.", "Go on, then."] },
  { actor: "patch", lines: ["Give me a minute.", "Almost had it.", "Right then.", "Where'd that go?", "Nearly.", "Ah — there.", "Hand me that."] },
  { actor: "quinn", lines: ["Run it again.", "Not convinced.", "Show me.", "Once more.", "Prove it.", "Twice, ideally.", "I'll wait."] },
  // Karthik. Neutral by the same rule as everybody else's: not one of these
  // mentions a wallet, a target, a position or a figure. "Target hit" is a
  // real reaction and lives in the event routines, where a reading is behind
  // it — saying it on a timer would be the exact fabrication §22 forbids.
  { actor: "karthik", lines: ["One second.", "Bear with me.", "Almost.", "Not mine to change.", "Two minutes.", "Let me look.", "Out of my hands."] },
  // Vault. Held to the same rule and it bites hardest here: these fire on a
  // timer, so not one of them may hint at a balance, a barrier, a signature or
  // a state. "Still sealed" would be a claim about the one thing this desk
  // exists to report, and a claim made by a clock is a fabrication however true
  // it happens to be. What is left is a person with a quiet job.
  { actor: "vault", lines: ["Mm.", "Nothing from me.", "Door's shut.", "I'll be here.", "Long day.", "Same as ever.", "Carry on."] },
  // Rafiq Analytics. The hardest five lines in this file to write, and the
  // rule bites harder here than anywhere: these are ANALYSTS, so the natural
  // idle line for each of them is a fragment of an opinion about their book —
  // "that stop's too tight", "we're closer than last week" — and every one of
  // those is a business claim generated by a timer. None survives. What is
  // left is five people doing the physical parts of the job: reading, asking
  // for a minute, checking a column, waiting for a number. That is thinner
  // than it could be, and thin is the correct trade here.
  { actor: "anchor", lines: ["Reading it again.", "Give me a minute.", "Hm.", "Where's that from?", "One more pass.", "Not yet."] },
  { actor: "tempo", lines: ["Quick one.", "Right.", "On it.", "Give me ten seconds.", "Next.", "Got it."] },
  { actor: "sigma", lines: ["Slowly.", "Which column?", "Say that again.", "I want to see it.", "Not so fast.", "Mm-hm."] },
  { actor: "halt", lines: ["Watching.", "Nothing yet.", "Still here.", "Quiet.", "I'll say if it moves.", "Mm."] },
  { actor: "chorus", lines: ["What have you got?", "Anyone?", "Hold on.", "Say again?", "I'll wait.", "Ready when you are."] },
  { actor: "maya", lines: ["Won't be a minute.", "Nearly finished.", "Mind the floor.", "Nearly done in here.", "Watch the cable."] },
  { actor: "sam", lines: ["I'll fix it.", "Spare's in the back.", "That'll do it.", "Bit of tape'll do.", "Seen worse."] },
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
