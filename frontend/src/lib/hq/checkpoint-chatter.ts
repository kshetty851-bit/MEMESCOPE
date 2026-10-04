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

/** Marco's team leader (2026-10-04: "marco has one team leader who reads out
 *  all profit loss and congrats the team motivating them"). */
export const TEAM_LEAD = { first: "Layla", name: "Team Leader" } as const;

export const LEAD_LOOK: CharacterLook = {
  id: "checkpoint-lead", bodyType: "slim", headShape: "oval", skinTone: "s2", hair: "ponytail",
  hairTone: "h1", outfit: "turtleneck", accessory: "tablet", palette: "teal", defaultPose: "standing",
};

/** Who is talking: a person's index, the manager, or his team leader. */
export type Speaker = number | "manager" | "lead";
export interface Line { who: Speaker; text: string; mood: Emotion }

/** A small deterministic pick, so a test can pin every line. */
export function pick<T>(items: readonly T[], seed: number): T {
  return items[Math.abs(Math.floor(seed)) % items.length]!;
}

// --- the manager, on real events -------------------------------------------
// 2026-10-04: "add more 100s of audios among all, looks fun". Every pool below
// is filled with {name}/{coin}/{job} at speak time, so a few dozen templates
// per pool become hundreds of different lines across thirty people.

const fill = (t: string, v: Record<string, string>) =>
  t.replace(/\{(\w+)\}/g, (_, k: string) => v[k] ?? "");

const PRAISE_STOP = [
  "Good catch, {name}! {coin} stays out.",
  "{name} stopped {coin}. That's the job — well done.",
  "Nice, {name}! {job} doing exactly what it's for.",
  "{coin} blocked by {name}. Keep those eyes sharp, team.",
  "That's my {name}! {coin}, denied.",
  "Textbook stop, {name}. {coin} goes in the bin.",
  "{name}, you just saved us from {coin}. Gold star.",
  "Look at {name} go! {coin} never stood a chance.",
  "Everyone see that? {name} spotted {coin}. That's focus.",
  "{coin}? Not on {name}'s watch.",
  "Clean stop, {name}. I'm writing that down.",
  "{name} with the save! {coin} is out.",
  "Thank you, {name}. {coin} would not have been fun.",
  "Sharp work, {name}. {job} pays for itself today.",
  "{name}, that's why you sit at that desk. {coin} rejected.",
  "And {name} stops {coin}. Crowd goes wild!",
  "{coin} tried it. {name} said no. Love it.",
  "High five, {name}! {coin} stays outside the wallet.",
  "Brilliant, {name}. One less risk for the wallet.",
  "{name} is on fire today. {coin}, gone.",
];
const PRAISE_BUY = [
  "{coin} passed all 30 checks — into the wallet. Great teamwork!",
  "All thirty said yes to {coin}. Clean work, everyone.",
  "{coin} cleared every hall. That's how we do it.",
  "Thirty green lights for {coin}. Beautiful.",
  "{coin} is in. Every desk did its part.",
  "Team, {coin} made it through. Proud of you.",
  "Rule, gate, safety — {coin} passed them all. Nice.",
  "{coin} bought. Smooth as butter, people.",
  "That's a full house of yeses for {coin}!",
  "{coin} earned its place. Good checking, all of you.",
  "From graduation to wallet: {coin}. Teamwork!",
  "Everyone, {coin} passed. Back to your desks, next one's coming.",
];
const SCOLD = [
  "We bought {coin} and it rugged. Hall 1, Hall 3 — tighter checks!",
  "{coin} rugged on us. Rosa, Tariq, Sofia — what did we miss? Sharper!",
  "A rug got through: {coin}. Nobody relaxes until the next one is clean.",
  "{coin}. Rugged. I don't want to see that again, team.",
  "Meeting at my desk about {coin}. Bring your notes.",
  "{coin} slipped past thirty of you. Thirty! Focus, people.",
  "We lost money on {coin}. Every desk, double-check your routine.",
  "That {coin} rug is on all of us. Learn from it.",
];
const AWARD = [
  "🏆 Employee of the day: {name} — {count} coins stopped!",
  "🏆 Top stopper is still {name} with {count}. Who's catching up?",
  "Round of applause for {name}: {count} stops on record. 🏆",
  "🏆 {name} leads the board with {count}. Legend.",
  "The trophy stays with {name}: {count} stops. Anyone want it?",
  "🏆 {count} stops, {name}. Coffee's on me today.",
  "Board update: {name} on top with {count}. Respect. 🏆",
  "{name}, {count} stops. Frame that number. 🏆",
];
const MOTIVATE = [
  "{name}, coffee's done — eyes on the belt!",
  "Stay sharp, everyone. One rug undoes a week of wins.",
  "{name}, stretch break's over. Next coin could be anytime.",
  "Thirty checks, zero shortcuts. That's the rule.",
  "{name}, I see you yawning. Look alive!",
  "Quiet belt doesn't mean quiet minds. Stay ready.",
  "{name}, phone down, please. We're working.",
  "Every coin gets the full treatment. No exceptions.",
  "{name}, your desk looks like a storm hit it. Tidy up!",
  "Remember: we'd rather miss a winner than buy a rug.",
  "{name}, great energy today. Keep it up.",
  "Hall 2, you're quiet. Everyone awake back there?",
  "{name}, is that a nap? On my floor?",
  "Small wins add up. Rugs add down. Stay careful.",
  "{name}, what's your check? Say it out loud. Good.",
  "Who wants to be employee of the day? Earn it.",
  "{name}, I believe in you. Don't make me regret it.",
  "Safety Lab, you're the last line. Act like it.",
  "{name}, less chatting, more checking!",
  "If you're unsure, say no. That's always allowed.",
  "{name}, nice posture today. Professional.",
  "Hall 1, you set the tone. Pick well.",
  "{name}, the trophy is still up for grabs.",
  "No coin is too small to check twice.",
  "{name}, stop admiring your stop count and watch the belt.",
  "I want clean hands and sharp eyes, people.",
  "{name}, you're doing great. Seriously.",
  "Coffee machine is not a workstation, {name}.",
  "Breathe, focus, check. Repeat.",
  "{name}, you missed a spot on your desk. Kidding. Focus.",
];
const ASK_ANSWER: readonly [string, string][] = [
  ["{b}, ready for the next one?", "Always ready."],
  ["{b}, coffee after this shift?", "Only if Marco isn't watching."],
  ["How's the {job} desk, {b}?", "My checklist says: {job}. All good."],
  ["{b}, did you clean your desk today?", "Spotless. Unlike yours."],
  ["{b}, I'll race you to the next coin.", "You're on. Loser buys lunch."],
  ["{b}, what's for lunch?", "Same as yesterday. Sandwiches and focus."],
  ["{b}, did you see Marco's tie?", "Shh, he'll hear you."],
  ["{b}, how many coffees so far?", "Three. Maybe four. Who's counting?"],
  ["{b}, want to swap desks for a day?", "Never. Mine has the good chair."],
  ["{b}, can you check my notes?", "Already did. You spelled 'rug' wrong."],
  ["{b}, ever dream about coins?", "Every night. Mostly the rugs."],
  ["{b}, who's winning the trophy?", "Not you, that's for sure."],
  ["{b}, is my badge straight?", "Perfectly crooked."],
  ["{b}, did you bring snacks?", "Crisps in my drawer. Don't tell Marco."],
  ["{b}, favourite part of the job?", "Saying no to bad coins."],
  ["{b}, how's your back?", "Better since the new chair."],
  ["{b}, what's your secret?", "Double-check everything. Twice."],
  ["{b}, are you humming?", "It helps me think."],
  ["{b}, nice jacket.", "Thanks! Hall colours, of course."],
  ["{b}, weekend plans?", "Sleep. Then more sleep."],
  ["{b}, did you hear Marco's speech?", "Every word. He repeats them a lot."],
  ["{b}, can I borrow a pen?", "Bring it back this time."],
  ["{b}, how do you stay so calm?", "Deep breaths and good checklists."],
  ["{b}, think we'll get a raise?", "Only if we stop every rug."],
  ["{b}, is it lunch yet?", "It's never lunch yet."],
  ["{b}, you look focused.", "That's my thinking face."],
  ["{b}, guess my favourite colour.", "Whatever colour our hall is."],
  ["{b}, can you hear the belt?", "It hums when it's happy."],
  ["{b}, do you ever get bored?", "Not with thirty of us chatting."],
  ["{b}, who trained you?", "Marco. Hence the strictness."],
  ["{b}, ready to say no today?", "No is my favourite word."],
  ["{b}, do you trust the safety lab?", "With my life. And my coins."],
  ["{b}, any tips for a newbie?", "When in doubt, stop it."],
  ["{b}, how's the coffee today?", "Strong enough to check twice."],
  ["{b}, did you water the plant?", "It's plastic. But yes."],
  ["{b}, best stop you ever made?", "Can't say. Marco would get jealous."],
  ["{b}, are we the best team?", "Obviously. Thirty out of thirty."],
  ["{b}, should we sing?", "Please don't."],
  ["{b}, what time is it in New York?", "Coffee time, probably."],
  ["{b}, if you weren't checking coins?", "I'd be checking something else."],
];
const SOLO = [
  "Ready when you are, belt.",
  "Note to self: never skip a step.",
  "Stretch, sip, focus.",
  "Desk tidy. Mind tidy.",
  "One coin at a time. Wait, several now.",
  "I love this job.",
  "Who moved my stapler?",
  "Deep breath. Next.",
  "Hmm, where did I put my coffee?",
  "Checklist: memorised.",
  "Eyes open, coffee warm.",
  "Today feels like a good day.",
  "I should get a bigger mug.",
  "Is it just me or is it quiet?",
  "Practising my 'no' face.",
  "Tap tap. Screen's working.",
  "Somebody's humming again.",
  "My chair squeaks. I'll live.",
  "Focus mode: on.",
  "Thirty friends, one job.",
];

export function praiseStop(index: number, symbol: string | null, seed: number): Line {
  const r = ROBOTS[index]!;
  return { who: "manager", mood: "happy",
           text: fill(pick(PRAISE_STOP, seed), { name: r.first, coin: symbol ?? "that one", job: r.name }) };
}

export function praiseBuy(symbol: string | null, seed: number): Line {
  return { who: "manager", mood: "happy", text: fill(pick(PRAISE_BUY, seed), { coin: symbol ?? "That coin" }) };
}

/** Scolding is for a REAL miss only: a coin we bought that went on to rug. */
export function scoldRug(symbol: string | null, seed: number): Line {
  return { who: "manager", mood: "angry", text: fill(pick(SCOLD, seed), { coin: symbol ?? "a coin" }) };
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
  return { who: "manager", mood: "happy", text: fill(pick(AWARD, seed), {
    name: ROBOTS[top.index]!.first, count: top.count.toLocaleString("en-US") }) };
}

/** A push or a nudge to someone, about THEM, not about the market. */
export function motivate(seed: number): Line {
  const r = ROBOTS[Math.abs(Math.floor(seed * 7)) % ROBOTS.length]!;
  return { who: "manager", mood: pick<Emotion>(["neutral", "smug", "happy", "surprised"], seed),
           text: fill(pick(MOTIVATE, seed), { name: r.first }) };
}

// --- idle banter between neighbours ------------------------------------------

/** Two neighbours in the same hall: one asks, the other answers. */
export function banter(seed: number): [Line, Line] {
  const a = Math.abs(Math.floor(seed)) % ROBOTS.length;
  const hall = ROBOTS.map((r, i) => ({ r, i })).filter(({ r }) => r.stage === ROBOTS[a]!.stage);
  const b = hall[(hall.findIndex(({ i }) => i === a) + 1 + (Math.abs(Math.floor(seed / 3)) % (hall.length - 1))) % hall.length]!.i;
  const [ask, answer] = pick(ASK_ANSWER, Math.floor(seed / 7));
  const v = { b: ROBOTS[b]!.first, job: ROBOTS[b]!.name.toLowerCase() };
  return [
    { who: a, mood: pick<Emotion>(["neutral", "happy", "surprised"], seed), text: fill(ask, v) },
    { who: b, mood: pick<Emotion>(["happy", "smug", "neutral"], seed + 1), text: fill(answer, v) },
  ];
}

/** Someone thinking aloud, about themselves. */
export function solo(seed: number): Line {
  return { who: Math.abs(Math.floor(seed * 3)) % ROBOTS.length,
           mood: pick<Emotion>(["neutral", "happy", "smug"], seed), text: pick(SOLO, Math.floor(seed / 2)) };
}

/** How many different templates the office can say (for the page's tests). */
export const LINE_TEMPLATES = PRAISE_STOP.length + PRAISE_BUY.length + SCOLD.length + AWARD.length
  + MOTIVATE.length + ASK_ANSWER.length * 2 + SOLO.length;

// --- Layla, reading out the money ---------------------------------------------
// Real figures only: Karthik's Lab's public summary (the paper book from 1 Oct)
// and, for a signed-in viewer, the real wallets' closed trades. She never
// reads a number she was not given.

export interface LabSummary {
  started_at: string; capital_usd: string; pnl_usd: string; trades: number; wins: number; rugs: number;
}
export interface WalletProfitRow {
  label: string; all_pnl_usd: string; today_pnl_usd: string; today_trades: number; today_won: number;
}

const money = (v: number) => `${v < 0 ? "minus " : "plus "}$${Math.abs(v).toFixed(2)}`;

const LAB_UP = [
  "Numbers! Karthik's Lab since 1 Oct: {pnl} on {cap}, {trades} trades, {wins} wins. Brilliant work, team!",
  "Lab update: {pnl} since 1 Oct over {trades} trades. That's your checking paying off. Well done!",
  "Karthik's Lab is {pnl} since 1 Oct. {wins} wins out of {trades}. Proud of every one of you!",
  "Report: {pnl} since 1 Oct, {rugs} rugs got through. Let's make that zero. Great job so far!",
];
const LAB_DOWN = [
  "Lab update: {pnl} since 1 Oct over {trades} trades. Heads up, team — every check counts!",
  "We're {pnl} since 1 Oct. {rugs} rugs hurt us. Sharper eyes and we'll turn it around!",
  "Karthik's Lab is {pnl} since 1 Oct. Not our best — let's earn it back, one clean coin at a time.",
];
const WALLETS = [
  "Real wallets since 28 Sep: {list}. {verdict}",
  "Money check! {list}. {verdict}",
  "Here's the real money: {list}. {verdict}",
];
const TODAY = [
  "Today so far: {trades} trades, {won} won, {pnl} on the main wallet. {verdict}",
  "Today's score on the main wallet: {won} wins from {trades} trades, {pnl}. {verdict}",
];
const UP_VERDICT = ["Keep it up!", "Fantastic, team!", "That's what thirty sharp eyes do!", "Marco, they deserve coffee!"];
const DOWN_VERDICT = ["Heads up, we can do better!", "Focus, team — we'll get it back!", "Tighter checks, everyone!"];

export function reportLab(lab: LabSummary | undefined, seed: number): Line | null {
  if (!lab) return null;
  const pnl = Number(lab.pnl_usd);
  return { who: "lead", mood: pnl >= 0 ? "happy" : "sad", text: fill(pick(pnl >= 0 ? LAB_UP : LAB_DOWN, seed), {
    pnl: money(pnl), cap: `$${Number(lab.capital_usd).toFixed(0)}`,
    trades: String(lab.trades), wins: String(lab.wins), rugs: String(lab.rugs) }) };
}

export function reportWallets(rows: WalletProfitRow[] | undefined, seed: number): Line | null {
  if (!rows?.length) return null;
  const total = rows.reduce((n, r) => n + Number(r.all_pnl_usd), 0);
  const list = rows.map((r) => `${r.label} ${money(Number(r.all_pnl_usd))}`).join(", ");
  return { who: "lead", mood: total >= 0 ? "happy" : "sad", text: fill(pick(WALLETS, seed), {
    list, verdict: pick(total >= 0 ? UP_VERDICT : DOWN_VERDICT, seed + 1) }) };
}

export function reportToday(rows: WalletProfitRow[] | undefined, seed: number): Line | null {
  const main = rows?.[0];
  if (!main || !main.today_trades) return null;
  const pnl = Number(main.today_pnl_usd);
  return { who: "lead", mood: pnl >= 0 ? "happy" : "sad", text: fill(pick(TODAY, seed), {
    trades: String(main.today_trades), won: String(main.today_won), pnl: money(pnl),
    verdict: pick(pnl >= 0 ? UP_VERDICT : DOWN_VERDICT, seed + 2) }) };
}

/** The voice each speaker gets: a pitch and rate of their own. */
export function voiceOf(who: Speaker): { pitch: number; rate: number } {
  if (who === "manager") return { pitch: 0.75, rate: 0.95 };
  if (who === "lead") return { pitch: 1.15, rate: 1.02 };
  return { pitch: 0.8 + ((who * 37) % 60) / 100, rate: 0.95 + ((who * 13) % 20) / 100 };
}
