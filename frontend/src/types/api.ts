/** Types mirroring the backend's Pydantic schemas. */

export type UserRole = "user" | "analyst" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface MessageResponse {
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
  request_id: string | null;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload extends LoginPayload {
  display_name?: string;
}

export interface HealthStatus {
  status: string;
  version: string;
  environment: string;
  checks: Record<string, { status: string; detail?: string }>;
}

/* --- Token discovery ------------------------------------------------------ */

export type MetadataStatus = "pending" | "resolved" | "failed";

export interface DiscoveredToken {
  id: string;
  mint_address: string;
  name: string | null;
  symbol: string | null;
  decimals: number | null;
  metadata_uri: string | null;
  creator_address: string | null;
  signature: string;
  slot: number;
  /** On-chain creation time. */
  block_time: string | null;
  /** When MemeScope first saw the token. */
  discovered_at: string;
  source_program: string | null;
  metadata_status: MetadataStatus;
}

export interface TokenPage {
  items: DiscoveredToken[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** Frames pushed over the token stream WebSocket. */
export type TokenStreamEvent =
  | { type: "connection.ready"; message?: string }
  | { type: "ping" }
  | { type: "token.discovered"; data: DiscoveredToken };

/* --- Market enrichment ---------------------------------------------------- */

export type TradingStatus = "unknown" | "trading" | "inactive";

/**
 * Money arrives as a JSON string, not a number.
 *
 * The backend stores NUMERIC and Pydantic serialises Decimal as a string;
 * parsing to a JS number would silently lose precision on prices like
 * 1e-12. Keep it a string and only convert at the point of formatting.
 */
export type DecimalString = string;

export interface MarketSnapshot {
  id: string;
  mint_address: string;
  /** Last updated timestamp for this observation. */
  captured_at: string;

  price_usd: DecimalString | null;
  price_native: DecimalString | null;
  liquidity_usd: DecimalString | null;
  fully_diluted_valuation: DecimalString | null;
  market_cap: DecimalString | null;

  volume_24h: DecimalString | null;
  volume_1h: DecimalString | null;
  volume_5m: DecimalString | null;

  buy_count_24h: number | null;
  sell_count_24h: number | null;

  dex_name: string | null;
  trading_pair: string | null;
  pool_address: string | null;

  trading_status: TradingStatus;
  is_verified: boolean;

  provider: string;
  provider_latency_ms: number | null;
}

export interface TokenMarket {
  mint_address: string;
  /** Null until the provider has indexed a pool for this token. */
  market: MarketSnapshot | null;
  snapshot_count: number;
  last_refreshed_at: string | null;
  next_refresh_at: string | null;
  enrichment_status: string | null;
  tier: string | null;
}

export interface MarketHistoryPage {
  mint_address: string;
  items: MarketSnapshot[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TrendingEntry {
  token: DiscoveredToken;
  market: MarketSnapshot;
}

export interface TrendingPage {
  items: TrendingEntry[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  sort_by: string;
}
