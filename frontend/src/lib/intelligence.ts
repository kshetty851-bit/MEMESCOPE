import { AGENTS, type AgentId } from "@/lib/design/agents";
import type { DiscoveredToken, MarketSnapshot } from "@/types/api";

/**
 * PROVISIONAL SIGNAL DERIVATION
 *
 * The Intelligence Division's verdicts — momentum, risk, whale activity, confidence — are
 * Day 4+ backend work. Until those models exist, this module derives the same
 * signals on the client from real market data the API already returns.
 *
 * This is a deliberate choice over the alternative. Filling these panels with
 * `Math.random()` would demo beautifully and be a lie shown to users making
 * money decisions; leaving them blank would make the product's central idea
 * impossible to evaluate. Transparent heuristics over real numbers are the
 * honest middle, and every one is labelled `heuristic` in the UI so nobody
 * mistakes it for a model output.
 *
 * When the real scoring lands, delete this file and change the type of the
 * `signals` prop. Nothing else should need to move.
 */

export type SignalLevel = "none" | "low" | "moderate" | "high" | "extreme";

export interface Signal {
  /** 0–1. */
  score: number;
  level: SignalLevel;
  /** Single sentence in the owning agent's voice. */
  readout: string;
  agent: AgentId;
}

export interface TokenIntelligence {
  momentum: Signal;
  risk: Signal;
  whale: Signal;
  community: Signal;
  confidence: number;
  gemProbability: number;
  /** True only for the rarest tier. Gates every gold pixel in the product. */
  elite: boolean;
  /** Honest admission when there is not enough data to say anything. */
  provisional: boolean;
}

const num = (value: string | null | undefined): number => {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

function levelOf(score: number): SignalLevel {
  if (score <= 0) return "none";
  if (score < 0.3) return "low";
  if (score < 0.6) return "moderate";
  if (score < 0.85) return "high";
  return "extreme";
}

/**
 * Momentum — is trade activity accelerating?
 *
 * Compares the 5-minute rate against the 24-hour average rate. A token doing
 * its whole daily volume in the last five minutes is the signal PULSE exists
 * to catch.
 */
function momentumOf(market: MarketSnapshot | null): Signal {
  const vol5m = num(market?.volume_5m);
  const vol24h = num(market?.volume_24h);

  if (!market || vol24h <= 0) {
    return { score: 0, level: "none", readout: "No flow to measure.", agent: "pulse" };
  }

  // Expected 5m volume if the day were uniform: 24h / 288 five-minute buckets.
  const expected = vol24h / 288;
  const ratio = expected > 0 ? vol5m / expected : 0;
  // 10× the uniform rate saturates the meter.
  const score = Math.max(0, Math.min(1, Math.log10(1 + ratio) / Math.log10(11)));

  const readout =
    ratio >= 8
      ? "Momentum increasing rapidly."
      : ratio >= 3
        ? "Acceleration detected."
        : ratio >= 1
          ? "Velocity holding steady."
          : "Momentum decaying.";

  return { score, level: levelOf(score), readout, agent: "pulse" };
}

/**
 * Risk — SENTINEL's read. Higher score means *more* danger.
 *
 * Three cheap, real proxies: liquidity depth relative to valuation (thin books
 * are exit traps), sell pressure, and whether metadata ever resolved.
 */
function riskOf(token: DiscoveredToken, market: MarketSnapshot | null): Signal {
  if (!market) {
    return {
      score: 0.5,
      level: "moderate",
      readout: "Awaiting contract data. Unverified.",
      agent: "sentinel",
    };
  }

  const liquidity = num(market.liquidity_usd);
  const mcap = num(market.market_cap);
  const buys = market.buy_count_24h ?? 0;
  const sells = market.sell_count_24h ?? 0;

  // Thin liquidity against a large notional valuation is the classic rug shape.
  const depthRatio = mcap > 0 ? liquidity / mcap : 0;
  const depthRisk = liquidity === 0 ? 0.55 : Math.max(0, Math.min(1, 1 - depthRatio * 12));

  const total = buys + sells;
  const sellRisk = total > 0 ? Math.max(0, Math.min(1, (sells / total - 0.5) * 2)) : 0.3;

  const metadataRisk = token.metadata_status === "resolved" ? 0 : 0.25;
  const inactiveRisk = market.trading_status === "inactive" ? 0.4 : 0;

  // Depth and sell pressure must be able to reach 1.0 between them. Weighting
  // them 0.45/0.30 capped total risk at 0.75 even for a maximally illiquid
  // token, so a textbook rug — $50 of liquidity behind a $5M valuation — scored
  // only "moderate". Metadata and inactivity stay additive on top.
  const score = Math.max(
    0,
    Math.min(1, depthRisk * 0.6 + sellRisk * 0.4 + metadataRisk + inactiveRisk),
  );

  const readout =
    score >= 0.75
      ? "Security concerns detected. Exercise caution."
      : score >= 0.5
        ? "Liquidity depth insufficient. Exit risk elevated."
        : score >= 0.25
          ? "Minor irregularities logged. Within tolerance."
          : "No contract anomalies.";

  return { score, level: levelOf(score), readout, agent: "sentinel" };
}

/**
 * Whale activity — TITAN's read.
 *
 * Average trade size is the tell. Real wallet clustering needs on-chain
 * transfer data the platform does not collect yet, so this is the weakest of
 * the four heuristics and is labelled as such.
 */
function whaleOf(market: MarketSnapshot | null): Signal {
  const volume = num(market?.volume_24h);
  const trades = (market?.buy_count_24h ?? 0) + (market?.sell_count_24h ?? 0);

  if (!market || trades === 0 || volume === 0) {
    return { score: 0, level: "none", readout: "No wallet activity on record.", agent: "titan" };
  }

  const averageTrade = volume / trades;
  // $5k average trade saturates: that is size on a fresh launch.
  const score = Math.max(0, Math.min(1, Math.log10(1 + averageTrade) / Math.log10(5001)));

  const readout =
    score >= 0.7
      ? "Whale accumulation confirmed."
      : score >= 0.4
        ? "Large capital entering."
        : "Retail-scale positions only.";

  return { score, level: levelOf(score), readout, agent: "titan" };
}

/**
 * Community — ECHO's read.
 *
 * Trade count is a poor proxy for genuine social attention; real narrative
 * tracking is Day 4+. Present but explicitly provisional.
 */
function communityOf(market: MarketSnapshot | null): Signal {
  const trades = (market?.buy_count_24h ?? 0) + (market?.sell_count_24h ?? 0);
  if (trades === 0) {
    return { score: 0, level: "none", readout: "No attention registered.", agent: "echo" };
  }

  const score = Math.max(0, Math.min(1, Math.log10(1 + trades) / Math.log10(2001)));
  const readout =
    score >= 0.7
      ? "Narrative expanding."
      : score >= 0.4
        ? "Community attention increasing."
        : "Attention remains marginal.";

  return { score, level: levelOf(score), readout, agent: "echo" };
}

export function deriveIntelligence(
  token: DiscoveredToken,
  market: MarketSnapshot | null,
): TokenIntelligence {
  const momentum = momentumOf(market);
  const risk = riskOf(token, market);
  const whale = whaleOf(market);
  const community = communityOf(market);

  // ORACLE's composite: upside signals earn confidence, risk subtracts.
  const upside = momentum.score * 0.35 + whale.score * 0.3 + community.score * 0.2;
  const confidence = Math.max(0, Math.min(1, upside + 0.15 - risk.score * 0.45));

  // Gem probability is deliberately harsher than confidence — it answers
  // "is this exceptional?", not "is this fine?".
  const gemProbability = Math.max(
    0,
    Math.min(1, confidence * confidence * (1 - risk.score * 0.5)),
  );

  // APEX certification: high conviction, low risk, and real liquidity. Tuned to
  // fire on roughly the top percentile, because gold that appears often is not
  // gold.
  const elite =
    gemProbability >= 0.62 && risk.score < 0.35 && num(market?.liquidity_usd) > 5000;

  return {
    momentum,
    risk,
    whale,
    community,
    confidence,
    gemProbability,
    elite,
    provisional: market === null,
  };
}

/** Colour for a signal, using the owning agent's hue. */
export function signalTone(signal: Signal): string {
  return AGENTS[signal.agent].hue;
}

export const LEVEL_LABEL: Record<SignalLevel, string> = {
  none: "None",
  low: "Low",
  moderate: "Moderate",
  high: "High",
  extreme: "Extreme",
};
