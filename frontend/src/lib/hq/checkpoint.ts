/**
 * THE CHECKPOINT — the thirty checks a coin passes before the real wallet buys
 * it, drawn as thirty robots (Karthik, 2026-10-02: "show this 30 checks as 30
 * agents look like robots and name them").
 *
 * Each robot owns the refusal codes it is responsible for, so its "stopped"
 * counter is read from the records (`/real-wallet/checkpoint`), never made up.
 * The wallet gate's robots own no codes: their refusals are not recorded, so
 * they say what they guard instead of showing a number.
 */

import type {
  Accessory, BodyType, CharacterLook, Emotion, HairStyle, HeadShape, Outfit, Pose,
} from "@/lib/hq/characters";

export type StageId = "rule" | "gate" | "safety";

export interface Robot {
  id: string;
  name: string;
  /** The person who runs this check (2026-10-03: "look like human"). */
  first: string;
  /** What they shout when they stop a coin — their job, in their voice. */
  stopLine: string;
  stage: StageId;
  /** What it checks, in one plain line. */
  job: string;
  /** Refusal codes counted as this robot's stops. */
  codes: readonly string[];
}

export const STAGES: readonly { id: StageId; title: string; blurb: string }[] = [
  { id: "rule", title: "Hall 1 · The Rule", blurb: "Picks the coin, ~30s after graduation" },
  { id: "gate", title: "Hall 2 · The Wallet Gate", blurb: "Can this wallet buy it right now?" },
  { id: "safety", title: "Hall 3 · The Safety Lab", blurb: "Seconds before signing" },
];

export const ROBOTS: readonly Robot[] = [
  // Hall 1 — the rule and the rug blocks.
  { id: "hatch", first: "Hana", stopLine: "Not graduated yet!", name: "Hatch", stage: "rule", job: "It has just graduated from pump.fun", codes: [] },
  { id: "depth", first: "Diego", stopLine: "Pool's too shallow!", name: "Depth", stage: "rule", job: "The pool holds at least $50,000", codes: [] },
  { id: "hush", first: "Hiro", stopLine: "Too noisy in there!", name: "Hush", stage: "rule", job: "The pool is still quiet: under 100 trades", codes: [] },
  { id: "recall", first: "Rosa", stopLine: "Seen these ruggers before!", name: "Recall", stage: "rule", job: "Not from wallets behind repeat rugs", codes: ["repeat_rug_operator"] },
  { id: "tracer", first: "Tariq", stopLine: "Linked to a recent rug!", name: "Tracer", stage: "rule", job: "Not linked to a recent rug", codes: ["linked_to_recent_rug"] },
  { id: "coinsniff", first: "Sofia", stopLine: "That's rug money!", name: "Sniff", stage: "rule", job: "Not paid for with known rug money", codes: ["known_rug_money"] },
  { id: "nametag", first: "Nia", stopLine: "Same name rugged today!", name: "Nametag", stage: "rule", job: "No coin by this name rugged in the last 3 hours", codes: ["same_name_as_recent_rug"] },
  // Hall 2 — the wallet's own gate (refusals not recorded).
  { id: "switch", first: "Sam", stopLine: "Switch is off!", name: "Switch", stage: "gate", job: "The wallet is switched on (users: and the main one)", codes: [] },
  { id: "brake", first: "Bea", stopLine: "Emergency brake!", name: "Brake", stage: "gate", job: "No emergency stop is pulled", codes: [] },
  { id: "fresh", first: "Femi", stopLine: "Signal's gone stale!", name: "Fresh", stage: "gate", job: "The buy signal is under a minute old", codes: [] },
  { id: "once", first: "Omar", stopLine: "Already bought this one!", name: "Once", stage: "gate", job: "This wallet has not bought this coin already", codes: [] },
  { id: "purse", first: "Priya", stopLine: "Not enough balance!", name: "Purse", stage: "gate", job: "There is enough balance for the trade", codes: [] },
  { id: "limit", first: "Leo", stopLine: "We're already holding one!", name: "Limit", stage: "gate", job: "Open trades and money at risk stay under the caps", codes: [] },
  { id: "capper", first: "Carmen", stopLine: "Too much in one coin!", name: "Capper", stage: "gate", job: "No more than $250 in one coin across user wallets", codes: [] },
  { id: "band", first: "Ben", stopLine: "Wrong coin size for this wallet!", name: "Band", stage: "gate", job: "The coin's market cap is in the wallet's chosen range", codes: [] },
  // Hall 3 — the safety check.
  { id: "probe", first: "Pablo", stopLine: "Can't verify that pool!", name: "Probe", stage: "safety", job: "Reads the pool's price straight from the chain", codes: ["PROVENANCE_UNVERIFIED", "VENUE_UNSUPPORTED"] },
  { id: "ticker", first: "Tess", stopLine: "These prices are stale!", name: "Ticker", stage: "safety", job: "The market data is fresh", codes: ["MARKET_DATA_STALE", "MARKET_DATA_MISSING"] },
  { id: "sanity", first: "Sana", stopLine: "Numbers don't add up!", name: "Sanity", stage: "safety", job: "Price and liquidity make sense", codes: ["PRICE_INVALID", "LIQUIDITY_INVALID", "TRADING_STATUS_UNSAFE"] },
  { id: "historian", first: "Henry", stopLine: "Seen this before!", name: "Historian", stage: "safety", job: "This name never rugged", codes: ["SYMBOL_RUGGED_BEFORE", "CREATOR_LAUNCHED_BEFORE"] },
  { id: "ledger", first: "Lena", stopLine: "Follow the money — it's dirty!", name: "Ledger", stage: "safety", job: "Checks where the money came from, again", codes: ["LINKED_TO_RECENT_RUG", "KNOWN_RUG_MONEY", "SOURCES_UNREADABLE"] },
  { id: "forge", first: "Farah", stopLine: "They can still mint more!", name: "Forge", stage: "safety", job: "Nobody can mint new tokens", codes: ["MINT_AUTHORITY_ACTIVE"] },
  { id: "frost", first: "Finn", stopLine: "They could freeze us!", name: "Frost", stage: "safety", job: "Nobody can freeze your tokens", codes: ["FREEZE_AUTHORITY_ACTIVE"] },
  { id: "typo", first: "Theo", stopLine: "Weird token type!", name: "Typo", stage: "safety", job: "A normal, supported token type", codes: ["UNSUPPORTED_TOKEN_PROGRAM", "UNSUPPORTED_TOKEN_EXTENSION", "TOKEN_CONFIGURATION_UNKNOWN", "TOKEN_SUPPLY_UNREADABLE"] },
  { id: "scale", first: "Sara", stopLine: "Too big for this pool!", name: "Scale", stage: "safety", job: "The trade is not too big for the pool", codes: ["POSITION_TOO_LARGE_FOR_LIQUIDITY"] },
  { id: "supply", first: "Sunil", stopLine: "Too much of the supply!", name: "Supply", stage: "safety", job: "The trade is not too big for the token supply", codes: ["POSITION_TOO_LARGE_FOR_SUPPLY"] },
  { id: "quote", first: "Qiana", stopLine: "No fair quote!", name: "Quote", stage: "safety", job: "A buy quote is available", codes: ["BUY_QUOTE_UNAVAILABLE", "QUOTE_INVALID"] },
  { id: "exit", first: "Ezra", stopLine: "No way out — no sell route!", name: "Exit", stage: "safety", job: "A sell route exists, so it can always sell", codes: ["SELL_ROUTE_UNAVAILABLE"] },
  { id: "impact", first: "Imani", stopLine: "We'd move the price too much!", name: "Impact", stage: "safety", job: "Buying and selling won't move the price too far", codes: ["BUY_PRICE_IMPACT_TOO_HIGH", "SELL_PRICE_IMPACT_TOO_HIGH"] },
  { id: "mirror", first: "Mei", stopLine: "That quote's way off!", name: "Mirror", stage: "safety", job: "The quoted price is close to the market price", codes: ["EXECUTION_PRICE_DEVIATION_TOO_HIGH"] },
  { id: "roundtrip", first: "Rafa", stopLine: "Round trip costs too much!", name: "Roundtrip", stage: "safety", job: "Buying and selling at once would not lose too much", codes: ["ROUND_TRIP_LOSS_TOO_HIGH", "SAFETY_CALCULATION_FAILED"] },
];

export interface CheckpointEvent {
  kind: "bought" | "stopped";
  symbol: string | null;
  at: string;
  code: string | null;
  rugged: boolean | null;
}

export interface Checkpoint {
  stopped_by: Record<string, number>;
  safety_checked: number;
  safety_allowed: number;
  feed: CheckpointEvent[];
  /** The main wallet's buys that rugged in the last day (2026-10-04): the
   *  only thing the office's manager scolds for. */
  rugged_buys?: { symbol: string | null; at: string }[];
}

const BY_CODE = new Map(ROBOTS.flatMap((r, i) => r.codes.map((c) => [c, i] as const)));

/** The robot that stopped a coin; the last one for a coin that got through. */
export function robotIndexFor(event: CheckpointEvent): number {
  if (event.kind === "bought") return ROBOTS.length - 1;
  const at = event.code ? BY_CODE.get(event.code) : undefined;
  return at ?? ROBOTS.length - 1;
}

/** How many coins a robot stopped, or null when its refusals go unrecorded. */
export function stoppedBy(robot: Robot, data: Checkpoint | undefined): number | null {
  if (!robot.codes.length || !data) return null;
  return robot.codes.reduce((n, code) => n + (data.stopped_by[code] ?? 0), 0);
}

/** A coin on the live belt (`/real-wallet/checkpoint/live`), 2026-10-02. */
export interface LiveCoin {
  symbol: string | null;
  graduated_at: string;
  status: "checking" | "stopped" | "bought";
  /** A robot's id, or "wallet" for a bought coin. */
  robot: string | null;
  /** A refusal code, mapped to its robot here. */
  code: string | null;
  note: string;
}

export interface LiveBelt {
  now: string;
  coins: LiveCoin[];
}

const BY_ID = new Map(ROBOTS.map((r, i) => [r.id, i] as const));

/** Where a live coin sits on the belt; -1 when no robot can honestly be named. */
export function liveIndex(coin: LiveCoin): number {
  if (coin.robot === "wallet") return ROBOTS.length - 1;
  if (coin.robot) return BY_ID.get(coin.robot) ?? -1;
  if (coin.code) return BY_CODE.get(coin.code) ?? -1;
  return -1;
}

export function coinKey(coin: LiveCoin): string {
  return `${coin.graduated_at}|${coin.symbol ?? ""}`;
}

// --- The people (2026-10-03: "I want them to look like human, with lots of
// animation and colors, expression, emotions, name") ----------------------
// Drawn with HQ's own character rig, so they are the same kind of person as
// the main floor's staff. Every axis steps at a different stride, so no two
// neighbours share a silhouette; clothes take their hall's colours.

const BODIES: readonly BodyType[] = ["slim", "broad", "tall", "compact"];
const HEADS: readonly HeadShape[] = ["round", "oval", "square"];
const HAIRS: readonly HairStyle[] = [
  "cropped", "bun", "wavy", "curly-short", "long-straight", "tuft", "buzz", "ponytail", "swept",
  "locs", "flat-top", "shaggy", "braid", "undercut", "low-tie", "halo", "twin-braid"];
const OUTFITS: readonly Outfit[] = [
  "blazer", "field-jacket", "cardigan", "vest", "yoke", "hoodie", "rolled-shirt", "utility",
  "long-coat", "turtleneck", "coveralls", "parka", "wrap-top", "track-jacket", "sealed-coat",
  "puffer", "shawl"];
const ACCESSORIES: readonly Accessory[] = [
  "tablet", "headset", "glasses", "clipboard", "mug", "stylus", "loupe", "checklist", "visor",
  "headphones", "pager", "wrist-terminal", "chart-roll"];
const SKINS = ["s1", "s2", "s3", "s4", "s5"] as const;
const HAIR_TONES = ["h1", "h2", "h3", "h4", "h5"] as const;
const HALL_COLOURS: Record<StageId, readonly string[]> = {
  rule: ["cyan", "teal", "ice", "cobalt", "mint", "indigo", "slate"],
  gate: ["amber", "orange", "brass", "khaki", "rust", "clay"],
  safety: ["violet", "plum", "magenta", "crimson", "lime", "forest", "indigo"],
};

export function lookOf(index: number): CharacterLook {
  const robot = ROBOTS[index]!;
  const colours = HALL_COLOURS[robot.stage];
  return {
    id: `checkpoint-${robot.id}`,
    bodyType: BODIES[index % BODIES.length]!,
    headShape: HEADS[(index * 2 + 1) % HEADS.length]!,
    skinTone: SKINS[(index * 2) % SKINS.length]!,
    hair: HAIRS[(index * 7) % HAIRS.length]!,
    hairTone: HAIR_TONES[(index * 3 + 1) % HAIR_TONES.length]!,
    outfit: OUTFITS[(index * 5 + 3) % OUTFITS.length]!,
    accessory: ACCESSORIES[(index * 3 + 1) % ACCESSORIES.length]!,
    palette: colours[index % colours.length]!,
    defaultPose: "standing",
  };
}

/** The holder check, switched off: Walt, asleep at his desk. */
export const WHALE: CharacterLook = {
  id: "checkpoint-whale", bodyType: "broad", headShape: "round", skinTone: "s3", hair: "shaggy",
  hairTone: "h4", outfit: "puffer", accessory: "mug", palette: "steel", defaultPose: "seated_lounge",
};

/**
 * What someone feels and does between coins: their own mood and pose, on
 * their own rhythm, about THEMSELVES only (the HQ rule: an idle face never
 * says anything about MEMESCOPE).
 */
const IDLE_MOODS: readonly Emotion[] = ["neutral", "happy", "neutral", "smug", "neutral", "surprised", "happy"];
const IDLE_POSES: readonly Pose[] = ["standing", "holding_tablet", "coffee_idle", "standing", "talking_briefly", "stretching"];

export function idleOf(index: number, nowMs: number): { emotion: Emotion; pose: Pose } {
  const beat = Math.floor((nowMs / 1000 + index * 2.3) / 7);
  const slow = Math.floor((nowMs / 1000 + index * 3.7) / 17);
  return {
    emotion: IDLE_MOODS[(beat + index) % IDLE_MOODS.length]!,
    pose: IDLE_POSES[(slow + index) % IDLE_POSES.length]!,
  };
}
