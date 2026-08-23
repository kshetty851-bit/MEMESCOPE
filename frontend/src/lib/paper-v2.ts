import { api } from "@/lib/api-client";

/**
 * PAPER WALLET V2 CLIENT — a separate experiment, on a separate endpoint.
 *
 * Deliberately not a variant flag on the V1 client. V2 shares no capital with
 * the original wallet, and a shared fetcher is one bad branch away from
 * rendering V1's numbers under a V2 heading.
 */

export interface V2Rung {
  multiple: string;
  fraction: string;
}

export interface V2Fill {
  rung_index: number | null;
  reason: string;
  filled_at: string;
  quantity: string;
  execution_price: string;
  observed_price: string;
  gross_proceeds: string;
  net_proceeds: string;
  fee_usd: string | null;
  impact_usd: string | null;
}

export interface V2Position {
  mint_address: string;
  status: string;
  opened_at: string;
  expires_at: string;
  seconds_to_expiry: number | null;
  entry_price: string;
  current_price: string | null;
  current_multiple: string | null;
  initial_notional: string;
  remaining_quantity: string;
  remaining_pct: string;
  position_value: string | null;
  realised_proceeds: string;
  unrealised_pnl: string | null;
  target_status: string[];
  runner_pct: string;
  final_exit_reason: string | null;
  fills: V2Fill[];
}

export interface PaperV2Wallet {
  experimental: boolean;
  mode: "disabled" | "observe" | "paper_active";
  started: boolean;
  strategy: {
    id: string;
    name: string;
    version: string;
    summary: string;
    rungs: V2Rung[];
    runner_fraction: string;
    hold_hours: number;
    trade_size_usd: string | null;
  };
  metrics: {
    starting_balance: string | null;
    cash: string | null;
    equity: string | null;
    capital_allocated: string | null;
    realised_pnl: string | null;
    unrealised_pnl: string | null;
    return_usd: string | null;
    roi_pct: string | null;
    open_positions: number;
    closed_positions: number;
    win_rate_pct: string | null;
    profit_factor: string | null;
    max_drawdown_pct: string | null;
    capital_utilisation_pct: string | null;
  };
  positions: V2Position[];
  disclosure: string;
  observed_at: string;
}

export function fetchPaperV2() {
  return api.get<PaperV2Wallet>("/paper-v2");
}

/** Renders a nullable server figure. "—" means unmeasured, never zero. */
export function v2usd(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function v2pct(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(2)}%` : "—";
}

export function countdown(seconds: number | null): string {
  if (seconds === null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}
