/**
 * The Checkpoint's talk (Karthik, 2026-10-04: "i want those 30 agents to talk
 * to each other in bubble text and audio ... 1 manager agent to look after
 * them and to push them motivate them award them scold them").
 *
 * Two kinds of line, kept apart on purpose (the HQ rule):
 * - The MANAGER's praise, awards and scolding are about REAL events only: a
 *   coin a person stopped, a coin all 30 passed, a bought coin that rugged,
 *   the stop counts on record. Nothing he says about the work is invented.
 * - The idle BANTER is about the people themselves — readiness, coffee, their
 *   own job — and never claims anything happened.
 */
import type { CharacterLook, Emotion } from "@/lib/hq/characters";
import { ROBOTS, stoppedBy, type Checkpoint } from "@/lib/hq/checkpoint";

export const MANAGER = { first: "Marco", name: "Floor Manager" } as const;

export const MANAGER_LOOK: CharacterLook = {
  id: "checkpoint-manager", bodyType: "broad", headShape: "square", skinTone: "s4", hair: "swept",
  hairTone: "h2", outfit: "blazer", accessory: "clipboard", palette: "brass", defaultPose: "standing",
};

/** Who is talking: a person's index, or the manager. */
export type Speaker = number | "manager";
export interface Line { who: Speaker; text: string; mood: Emotion }

/** A small deterministic pick, so a test can pin every line. */
export function pick<T>(items: readonly T[], seed: number): T {
  return items[Math.abs(Math.floor(seed)) % items.length]!;
}

// --- the manager, on real events -------------------------------------------

export function praiseStop(index: number, symbol: string | null, seed: number): Line {
  const r = ROBOTS[index]!;
  const coin = symbol ?? "that one";
  return { who: "manager", mood: "happy", text: pick([
    `Good catch, ${r.first}! ${coin} stays out.`,
    `${r.first} stopped ${coin}. That's the job — well done.`,
    `Nice, ${r.first}! ${r.name} doing exactly what it's for.`,
    `${coin} blocked by ${r.first}. Keep those eyes sharp, team.`,
  ], seed) };
}

export function praiseBuy(symbol: string | null, seed: number): Line {
  const coin = symbol ?? "That coin";
  return { who: "manager", mood: "happy", text: pick([
    `${coin} passed all 30 checks — into the wallet. Great teamwork!`,
    `All thirty said yes to ${coin}. Clean work, everyone.`,
    `${coin} cleared every hall. That's how we do it.`,
  ], seed) };
}

/** Scolding is for a REAL miss only: a coin we bought that went on to rug. */
export function scoldRug(symbol: string | null, seed: number): Line {
  const coin = symbol ?? "a coin";
  return { who: "manager", mood: "angry", text: pick([
    `We bought ${coin} and it rugged. Hall 1, Hall 3 — tighter checks!`,
    `${coin} rugged on us. Rosa, Tariq, Sofia — what did we miss? Sharper!`,
    `A rug got through: ${coin}. Nobody relaxes until the next one is clean.`,
  ], seed) };
}

/** Whoever has stopped the most coins on record, or null. */
export function topStopper(data: Checkpoint | undefined): { index: number; count: number } | null {
  if (!data) return null;
  let best: { index: number; count: number } | null = null;
  ROBOTS.forEach((r, i) => {
    const n = stoppedBy(r, data) ?? 0;
    if (n > (best?.count ?? 0)) best = { index: i, count: n };
  });
  return best;
}

/** The award, from the stop counts on record. */
export function award(data: Checkpoint | undefined, seed: number): Line | null {
  const top = topStopper(data);
  if (!top) return null;
  const r = ROBOTS[top.index]!;
  const count = top.count;
  return { who: "manager", mood: "happy", text: pick([
    `🏆 Employee of the day: ${r.first} — ${count.toLocaleString("en-US")} coins stopped!`,
    `🏆 Top stopper is still ${r.first} with ${count.toLocaleString("en-US")}. Who's catching up?`,
    `Round of applause for ${r.first}: ${count.toLocaleString("en-US")} stops on record. 🏆`,
  ], seed) };
}

/** A push or a nudge to someone, about THEM, not about the market. */
export function motivate(seed: number): Line {
  const r = ROBOTS[Math.abs(seed) % ROBOTS.length]!;
  return { who: "manager", mood: pick<Emotion>(["neutral", "smug", "happy"], seed), text: pick([
    `${r.first}, coffee's done — eyes on the belt!`,
    `Stay sharp, everyone. One rug undoes a week of wins.`,
    `${r.first}, stretch break's over. Next coin could be anytime.`,
    `Thirty checks, zero shortcuts. That's the rule.`,
    `${r.first}, I see you yawning. Look alive!`,
    `Quiet belt doesn't mean quiet minds. Stay ready.`,
  ], seed) };
}

// --- idle banter between neighbours ------------------------------------------

const ASK = [
  "{b}, ready for the next one?",
  "{b}, coffee after this shift?",
  "How's the {job} desk, {b}?",
  "{b}, did you clean your desk today?",
  "{b}, I'll race you to the next coin.",
];
const ANSWER = [
  "Always ready.",
  "Only if Marco isn't watching.",
  "My checklist says: {job}. All good.",
  "Spotless. Unlike yours.",
  "You're on. Loser buys lunch.",
];

/** Two neighbours in the same hall: one asks, the other answers. */
export function banter(seed: number): [Line, Line] {
  const a = Math.abs(seed) % ROBOTS.length;
  const hall = ROBOTS.map((r, i) => ({ r, i })).filter(({ r }) => r.stage === ROBOTS[a]!.stage);
  const b = hall[(hall.findIndex(({ i }) => i === a) + 1) % hall.length]!.i;
  const k = Math.abs(Math.floor(seed / 7)) % ASK.length;
  const fill = (t: string, who: number) => t
    .replace("{b}", ROBOTS[b]!.first)
    .replace("{job}", ROBOTS[who]!.name.toLowerCase());
  return [
    { who: a, mood: "neutral", text: fill(ASK[k]!, b) },
    { who: b, mood: pick<Emotion>(["happy", "smug", "neutral"], seed), text: fill(ANSWER[k]!, b) },
  ];
}

/** The voice each speaker gets: a pitch and rate of their own. */
export function voiceOf(who: Speaker): { pitch: number; rate: number } {
  if (who === "manager") return { pitch: 0.75, rate: 0.95 };
  return { pitch: 0.8 + ((who * 37) % 60) / 100, rate: 0.95 + ((who * 13) % 20) / 100 };
}
