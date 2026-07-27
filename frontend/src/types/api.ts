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
