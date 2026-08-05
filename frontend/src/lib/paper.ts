import { api } from "@/lib/api-client";
import type {
  Lab,
  LabStrategy,
  LabTokens,
  PaperAudit,
  PaperPosition,
  PaperPositions,
  PaperStrategies,
  PaperWallet,
} from "@/types/paper";

/**
 * PAPER WALLET CLIENT
 *
 * Fetches and formats. **It never decides.** The strategy's rules, the exit
 * reasons and the benchmark differences all arrive already computed — a
 * threshold applied here would be a second, unpublished rule competing with the
 * one the simulation actually followed.
 *
 * There is no write function, because there is no write endpoint. Nothing in
 * this product opens a position by hand.
 */

export function fetchPaperWallet(): Promise<PaperWallet> {
  return api.get<PaperWallet>("/paper");
}

export function fetchPaperPositions(): Promise<PaperPositions> {
  return api.get<PaperPositions>("/paper/positions");
}

export function fetchPaperStrategies(): Promise<PaperStrategies> {
  return api.get<PaperStrategies>("/paper/strategies");
}

/**
 * The permanent record.
 *
 * Read-only, like everything else here, and deliberately a separate request
 * from the wallet: the summary polls on the review cadence, and the log only
 * changes when a trade closes.
 */
export function fetchPaperAudit(limit = 100): Promise<PaperAudit> {
  return api.get<PaperAudit>(`/paper/audit?limit=${limit}`);
}

// --- Presentation ------------------------------------------------------------

function n(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Money to the cent. Returns null so callers render their own dash. */
export function usd(value: string | null | undefined): string | null {
  const amount = n(value);
  if (amount === null) return null;
  const sign = amount < 0 ? "-" : "";
  return `${sign}$${Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** A signed percentage. Null in, null out — never a flat 0%. */
export function pct(value: string | null | undefined): string | null {
  const amount = n(value);
  if (amount === null) return null;
  return `${amount > 0 ? "+" : ""}${amount.toFixed(2)}%`;
}

export function tone(
  value: string | null | undefined,
): "positive" | "negative" | "neutral" {
  const amount = n(value);
  if (amount === null || amount === 0) return "neutral";
  return amount > 0 ? "positive" : "negative";
}

/** Hours, compactly: 6h, 2d. */
export function hours(value: string | null | undefined): string | null {
  const amount = n(value);
  if (amount === null) return null;
  if (amount < 48) return `${amount.toFixed(1)}h`;
  return `${(amount / 24).toFixed(1)}d`;
}

/**
 * Exit reasons in plain language.
 *
 * The stored value is a stable code. An unrecognised one renders as nothing
 * rather than as itself — printing `expiry` raw is worse than printing nothing,
 * and a new reason shipping before its label is a deploy away from correct.
 */
const EXIT_LABEL: Record<string, string> = {
  target: "Hit target",
  // The live strategy has one exit, and `stop` is what it records. "Trailing
  // stop" rather than "hit stop": the level moved with the price, and calling
  // it a stop would suggest a fixed one the strategy does not have.
  stop: "Trailing stop",
  expiry: "Held to expiry",
};

export function exitLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return EXIT_LABEL[reason] ?? null;
}

/**
 * What the strategy can say about one token, for surfaces outside the wallet.
 *
 * Deliberately never returns an actionable state. The strategy enters on its
 * own rule with no manual step, so a token the wallet has not taken is "not
 * held", never "available to buy" — there is no button, and implying one would
 * be the manual intervention this design excludes.
 */
export type PaperTokenState = "open" | "closed" | "not-held";

export function paperStateFor(
  position: PaperPosition | undefined,
): PaperTokenState {
  if (!position) return "not-held";
  return position.status === "closed" ? "closed" : "open";
}

export const PAPER_STATE_LABEL: Record<PaperTokenState, string> = {
  open: "Position open",
  closed: "Traded",
  "not-held": "Not traded",
};

/** Index positions by mint, for pages that ask "was this token traded?". */
export function byMint(items: PaperPosition[]): Map<string, PaperPosition> {
  return new Map(items.map((item) => [item.mint_address, item]));
}

// --- Strategy Lab -------------------------------------------------------------

export function fetchLab(): Promise<Lab> {
  return api.get<Lab>("/paper/lab");
}

export function fetchLabTokens(limit = 100): Promise<LabTokens> {
  return api.get<LabTokens>(`/paper/lab/tokens?limit=${limit}`);
}

/**
 * Sorting the comparison table.
 *
 * Formats and orders; it never re-scores. The rank the backend assigned is the
 * published one, and a second ranking computed here could disagree with the
 * findings served beside it.
 */
export type LabSortKey =
  | "rank"
  | "total"
  | "realised"
  | "net"
  | "win"
  | "drawdown"
  | "profit"
  | "trades";

export function sortLab(items: LabStrategy[], key: LabSortKey): LabStrategy[] {
  const value = (item: LabStrategy): number => {
    switch (key) {
      case "total":
        return n(item.total_return_pct) ?? -Infinity;
      case "realised":
        return n(item.realised_return_pct) ?? -Infinity;
      case "net":
        return n(item.net_return_pct) ?? -Infinity;
      case "win":
        return n(item.win_rate_pct) ?? -Infinity;
      case "drawdown":
        // Least drawdown first — a smaller fall is the better outcome.
        return -(n(item.max_drawdown_pct) ?? Infinity);
      case "profit":
        return n(item.profit_factor) ?? -Infinity;
      case "trades":
        return item.closed_count;
      default:
        return -item.rank;
    }
  };
  return [...items].sort((a, b) => value(b) - value(a) || a.rank - b.rank);
}

/** Exit reasons in the order they are always displayed, so columns line up. */
export const EXIT_ORDER = ["target", "stop", "expiry"] as const;
