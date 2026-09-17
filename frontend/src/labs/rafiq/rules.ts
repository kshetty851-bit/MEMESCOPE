/**
 * Each book's rules in plain words.
 *
 * Transcribed from the backend's frozen specs: `backend/app/labs/rafiq/`
 * `registry.py`, the `strategies/` profiles, `entry_gate.py` and
 * `g1/strategy_G1.json`. Those are digest-locked (changing a number there
 * starts a new record), so this text only changes when they do.
 */

export interface PlainRules {
  idea: string;
  buys: string[];
  sells: string[];
  /** The sell rules are checked top to bottom and the first match wins. */
  sellsInOrder?: boolean;
  also?: string[];
}

/** What every book does, whatever its own rules say. */
export const SHARED_RULES: string[] = [
  "Paper money only. Each book starts with $1,000 and no real order is ever placed.",
  "It only looks at tokens the Radar admitted in the last 15 minutes, after the book started, and needs a price no older than 15 minutes. One position per token per book.",
  "Every buy and every sell pays a 0.3% swap fee plus the price impact for that pool's size, so all results are after costs.",
  "Obvious price glitches are ignored. If a token's pool dies, whatever is still held in it is worth $0.",
  "A halt only stops new buys. Nothing is ever force-sold.",
];

const SHARED_FILTER = [
  "The pool holds at least $50k and the market cap is at least $200k.",
  "The buy would move the price 1.5% or less and is no more than 0.5% of the pool.",
];

const DAILY_BREAKER =
  "Daily breaker: no new buys for the rest of the day (UTC) once the book is down 5% on the day, counting open trades, or has lost 8% on trades closed that day.";

export const PLAIN_RULES: Record<string, PlainRules> = {
  A2: {
    idea: "The baseline: the shared entry filter with a plain +30% target.",
    buys: [
      "Radar score is 70 or higher.",
      ...SHARED_FILTER,
      "Bets up to $50, sized so hitting the stop costs at most 1% of the book.",
    ],
    sells: [
      "Everything at +30%.",
      "Everything if the price falls 12% below the buy price.",
      "Once in profit, everything if it gives back 20% of its best gain.",
      "Whatever is left after 12 hours, at the market price.",
    ],
  },
  B2: {
    idea: "Quick trades: a small target and a short clock.",
    buys: [
      "Radar score is 68 or higher.",
      ...SHARED_FILTER,
      "Bets up to $25, sized so hitting the stop costs at most 0.5% of the book.",
    ],
    sells: [
      "Everything at +20%.",
      "Everything if the price falls 10% below the buy price.",
      "Whatever is left after 2 hours, at the market price. No trailing stop.",
    ],
  },
  C2: {
    idea: "Half takes a sure +30%, the other half is left to run.",
    buys: [
      "Radar score is 70 or higher.",
      ...SHARED_FILTER,
      "Bets up to $50, sized so hitting the stop costs at most 1% of the book, split into two halves.",
    ],
    sells: [
      "The first half at +30%.",
      "The second half has no target: once in profit, it sells if it gives back 25% of its best gain.",
      "Both halves if the price falls 12% below the buy price.",
      "Whatever is left after 4 hours, at the market price.",
    ],
  },
  D2: {
    idea: "No profit cap: let winners run and protect them with a trail.",
    buys: [
      "Radar score is 70 or higher.",
      ...SHARED_FILTER,
      "Bets up to $50, sized so hitting the stop costs at most 1% of the book.",
    ],
    sells: [
      "No profit target.",
      "Once in profit, everything if it gives back 25% of its best gain.",
      "Everything if the price falls 12% below the buy price.",
      "Whatever is left after 4 hours, at the market price.",
    ],
  },
  E2: {
    idea: "The strictest filter: fewer trades, in deeper and cleaner pools.",
    buys: [
      "Radar score is 70 or higher.",
      "The pool holds at least $150k and the market cap is at least $500k.",
      "The buy would move the price 0.75% or less and is no more than 0.25% of the pool.",
      "The token passes the platform's safety check, and on-chain or DEX activity also looks healthy, all read in the last 15 minutes.",
      "No sign of manipulation: sellers don't outnumber buyers more than 3 to 1, there are no more than 8 trades per wallet, and 5-minute volume stays under half the market cap.",
      "The stop is set from pool depth: about 10% at a $150k pool, 8% at $225k and deeper. Bets up to $50, sized so hitting the stop costs at most 1% of the book.",
    ],
    sells: [
      "Everything at +30%.",
      "Everything if the price falls to the stop.",
      "Once in profit, everything if it gives back 20% of its best gain.",
      "Whatever is left after 8 hours, at the market price.",
    ],
    also: [DAILY_BREAKER],
  },
  G1: {
    idea: "Moonshot: decide fast, bank most of a winner at +30%, and let a quarter ride with no cap.",
    buys: [
      "Radar score is 70 or higher.",
      "The pool holds at least $200k. The market cap must be at least $200k when it is known; an unknown market cap doesn't block the buy.",
      "The buy would move the price 1.5% or less.",
      "Bets 1% of the current book ($10 at $1,000), so the bet grows and shrinks with the book.",
    ],
    sellsInOrder: true,
    sells: [
      "Everything left if the price falls 12% below the buy price.",
      "From 10 minutes on, everything if it is up less than 8% (only before the +30% sale).",
      "At +30%, sell 75%. That returns about 97.5% of the stake, and the last 25% rides on.",
      "That last 25% has no target. It sells if the price drops 45% from its highest point.",
      "Whatever is left after 45 minutes, at the market price.",
    ],
    also: [
      "A floor that only moves up: it starts at $950, and each new high for the book lifts it to 3% below that high. At or below the floor, no new buys; open trades carry on.",
      DAILY_BREAKER,
      "Learning: after at least 40 closed trades, and only on statistically clear evidence, it moves the 8% line one point at a time (kept between 3% and 15%). If far fewer trades than usual reach +30%, it halves the bet until that recovers. It never bets more than normal. Every change is logged.",
    ],
  },
};
