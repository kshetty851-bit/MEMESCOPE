import { api } from "@/lib/api-client";
import type {
  ManualSellPreview,
  ManualSellResult,
  PaperAudit,
  PaperPerformance,
  PaperPosition,
  PaperPositions,
  PaperStrategies,
  PaperWallet,
  PaperWalletContext,
} from "@/types/paper";

/**
 * PAPER WALLET CLIENT
 *
 * Fetches and formats. **It never decides.** The strategy's rules, the exit
 * reasons and the benchmark differences all arrive already computed — a
 * threshold applied here would be a second, unpublished rule competing with the
 * one the simulation actually followed.
 *
 * Manual writes are limited to paper-only exits. There is still no manual
 * entry, no real execution and no client-side pricing.
 */

export function fetchPaperWallet(): Promise<PaperWallet> {
  return api.get<PaperWallet>("/paper");
}

export function fetchPaperWalletContext(roiPct?: string | null): Promise<PaperWalletContext> {
  const url = roiPct ? `/paper/context?roi_pct=${encodeURIComponent(roiPct)}` : "/paper/context";
  return api.get<PaperWalletContext>(url);
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

/** Immutable completed-trade returns grouped by UTC exit date. */
export function fetchPaperPerformance(): Promise<PaperPerformance> {
  return api.get<PaperPerformance>("/paper/performance");
}

export function previewManualSell(mint: string): Promise<ManualSellPreview> {
  return api.get<ManualSellPreview>(`/paper/positions/${mint}/manual-sell`);
}

export function sellPaperPosition(mint: string): Promise<ManualSellResult> {
  return api.post<ManualSellResult>(`/paper/positions/${mint}/manual-sell`);
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
  manual: "Manual sell",
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

export function paperStateFor(position: PaperPosition | undefined): PaperTokenState {
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

/**
 * DETECTION → ENTRY → EXIT
 *
 * The three stored moments a track record row is made of, and the one figure
 * derived from them. Nothing here invents a timestamp: a mint whose discovery
 * record the backend could not find renders as unavailable, and the delay is
 * withheld with it. Substituting the entry time for a missing detection would
 * make every such row read "+0s", which is the one wrong answer that looks
 * like a right one.
 *
 * Times render in the reader's own zone, like every other clock in MEMESCOPE.
 * The backend keeps UTC; `Date` does the conversion, and `stamp()` carries the
 * unambiguous version into the title for anyone comparing against the API.
 */
export function clock(iso: string | null | undefined): string | null {
  const date = iso ? new Date(iso) : null;
  if (!date || !Number.isFinite(date.getTime())) return null;
  return date.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** The same moment, spelled out — for `title`, where space is not scarce. */
export function stamp(iso: string | null | undefined): string | null {
  const date = iso ? new Date(iso) : null;
  if (!date || !Number.isFinite(date.getTime())) return null;
  const local = date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${local} · ${date.toISOString().replace("T", " ").replace(".000Z", "Z")}`;
}

/** Milliseconds since epoch, or null — the sort key for a column of times. */
export function epoch(iso: string | null | undefined): number | null {
  const date = iso ? new Date(iso) : null;
  if (!date || !Number.isFinite(date.getTime())) return null;
  return date.getTime();
}

/**
 * Entry delay in seconds: how long the platform held the token between seeing
 * it and taking it. Null unless *both* moments are stored.
 */
export function entryDelaySeconds(
  detectedAt: string | null | undefined,
  openedAt: string | null | undefined,
): number | null {
  const from = epoch(detectedAt);
  const to = epoch(openedAt);
  if (from === null || to === null) return null;
  return (to - from) / 1000;
}

/**
 * `+22m 33s`. Signed, and the sign is not decorative — an entry recorded
 * before its own detection is a data fault worth seeing, not one worth
 * clamping to zero.
 */
export function formatDelay(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;

  const sign = seconds < 0 ? "−" : "+";
  const total = Math.round(Math.abs(seconds));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600) % 24;
  const d = Math.floor(total / 86400);

  if (d > 0) return `${sign}${d}d ${h}h`;
  if (h > 0) return `${sign}${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${sign}${m}m ${String(s).padStart(2, "0")}s`;
  return `${sign}${s}s`;
}
