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

export type StageId = "rule" | "gate" | "safety";

export interface Robot {
  id: string;
  name: string;
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
  { id: "hatch", name: "Hatch", stage: "rule", job: "It has just graduated from pump.fun", codes: [] },
  { id: "depth", name: "Depth", stage: "rule", job: "The pool holds at least $75,000", codes: [] },
  { id: "hush", name: "Hush", stage: "rule", job: "The pool is still quiet: under 100 trades", codes: [] },
  { id: "recall", name: "Recall", stage: "rule", job: "Not from wallets behind repeat rugs", codes: ["repeat_rug_operator"] },
  { id: "tracer", name: "Tracer", stage: "rule", job: "Not linked to a recent rug", codes: ["linked_to_recent_rug"] },
  { id: "coinsniff", name: "Sniff", stage: "rule", job: "Not paid for with known rug money", codes: ["known_rug_money"] },
  { id: "nametag", name: "Nametag", stage: "rule", job: "No coin by this name rugged in the last 3 hours", codes: ["same_name_as_recent_rug"] },
  // Hall 2 — the wallet's own gate (refusals not recorded).
  { id: "switch", name: "Switch", stage: "gate", job: "The wallet is switched on (users: and the main one)", codes: [] },
  { id: "brake", name: "Brake", stage: "gate", job: "No emergency stop is pulled", codes: [] },
  { id: "fresh", name: "Fresh", stage: "gate", job: "The buy signal is under a minute old", codes: [] },
  { id: "once", name: "Once", stage: "gate", job: "This wallet has not bought this coin already", codes: [] },
  { id: "purse", name: "Purse", stage: "gate", job: "There is enough balance for the trade", codes: [] },
  { id: "limit", name: "Limit", stage: "gate", job: "Open trades and money at risk stay under the caps", codes: [] },
  { id: "capper", name: "Capper", stage: "gate", job: "No more than $250 in one coin across user wallets", codes: [] },
  { id: "band", name: "Band", stage: "gate", job: "The coin's market cap is in the wallet's chosen range", codes: [] },
  // Hall 3 — the safety check.
  { id: "probe", name: "Probe", stage: "safety", job: "Reads the pool's price straight from the chain", codes: ["PROVENANCE_UNVERIFIED", "VENUE_UNSUPPORTED"] },
  { id: "ticker", name: "Ticker", stage: "safety", job: "The market data is fresh", codes: ["MARKET_DATA_STALE", "MARKET_DATA_MISSING"] },
  { id: "sanity", name: "Sanity", stage: "safety", job: "Price and liquidity make sense", codes: ["PRICE_INVALID", "LIQUIDITY_INVALID", "TRADING_STATUS_UNSAFE"] },
  { id: "historian", name: "Historian", stage: "safety", job: "This name never rugged before", codes: ["SYMBOL_RUGGED_BEFORE"] },
  { id: "ledger", name: "Ledger", stage: "safety", job: "Checks where the money came from, again", codes: ["LINKED_TO_RECENT_RUG", "KNOWN_RUG_MONEY", "SOURCES_UNREADABLE"] },
  { id: "forge", name: "Forge", stage: "safety", job: "Nobody can mint new tokens", codes: ["MINT_AUTHORITY_ACTIVE"] },
  { id: "frost", name: "Frost", stage: "safety", job: "Nobody can freeze your tokens", codes: ["FREEZE_AUTHORITY_ACTIVE"] },
  { id: "typo", name: "Typo", stage: "safety", job: "A normal, supported token type", codes: ["UNSUPPORTED_TOKEN_PROGRAM", "UNSUPPORTED_TOKEN_EXTENSION", "TOKEN_CONFIGURATION_UNKNOWN", "TOKEN_SUPPLY_UNREADABLE"] },
  { id: "scale", name: "Scale", stage: "safety", job: "The trade is not too big for the pool", codes: ["POSITION_TOO_LARGE_FOR_LIQUIDITY"] },
  { id: "supply", name: "Supply", stage: "safety", job: "The trade is not too big for the token supply", codes: ["POSITION_TOO_LARGE_FOR_SUPPLY"] },
  { id: "quote", name: "Quote", stage: "safety", job: "A buy quote is available", codes: ["BUY_QUOTE_UNAVAILABLE", "QUOTE_INVALID"] },
  { id: "exit", name: "Exit", stage: "safety", job: "A sell route exists, so it can always sell", codes: ["SELL_ROUTE_UNAVAILABLE"] },
  { id: "impact", name: "Impact", stage: "safety", job: "Buying and selling won't move the price too far", codes: ["BUY_PRICE_IMPACT_TOO_HIGH", "SELL_PRICE_IMPACT_TOO_HIGH"] },
  { id: "mirror", name: "Mirror", stage: "safety", job: "The quoted price is close to the market price", codes: ["EXECUTION_PRICE_DEVIATION_TOO_HIGH"] },
  { id: "roundtrip", name: "Roundtrip", stage: "safety", job: "Buying and selling at once would not lose too much", codes: ["ROUND_TRIP_LOSS_TOO_HIGH", "SAFETY_CALCULATION_FAILED"] },
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
