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
