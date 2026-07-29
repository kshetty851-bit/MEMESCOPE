import { API_V1 } from "@/lib/env";
import type { ApiErrorBody } from "@/types/api";

/**
 * Typed fetch wrapper.
 *
 * Auth model: the access token lives in memory only (never localStorage, which
 * is readable by any injected script). The refresh token is an httpOnly cookie
 * the browser attaches automatically, so `credentials: "include"` is required.
 *
 * On a 401 the client transparently refreshes once and replays the request.
 * Concurrent 401s share a single in-flight refresh via `refreshPromise`, so a
 * page issuing six requests does not trigger six rotations — which, with
 * reuse-detection on the server, would log the user out.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }
}

type TokenListener = (token: string | null) => void;

let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;
const listeners = new Set<TokenListener>();

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((listener) => listener(token));
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function onTokenChange(listener: TokenListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Set for the refresh call itself, to stop it recursing on its own 401. */
  skipAuthRetry?: boolean;
}

async function parseError(response: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> = {};
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    // Non-JSON error (proxy timeout, HTML error page) — fall through.
  }
  return new ApiError(
    response.status,
    body.error?.code ?? "unknown_error",
    body.error?.message ?? response.statusText ?? "Request failed",
    body.error?.details ?? {},
    body.request_id ?? response.headers.get("X-Request-ID"),
  );
}

async function refreshAccessToken(): Promise<string | null> {
  refreshPromise ??= (async () => {
    try {
      const response = await fetch(`${API_V1}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!response.ok) {
        setAccessToken(null);
        return null;
      }
      const data = (await response.json()) as { access_token: string };
      setAccessToken(data.access_token);
      return data.access_token;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Round-trip duration of the most recent API call, in milliseconds.
 *
 * Recorded here so the telemetry bar can report real latency without issuing a
 * request purely to time one. Subscribers are notified rather than polled, so a
 * displayed figure always corresponds to a call the app actually made.
 */
let lastLatencyMs: number | null = null;
const latencyListeners = new Set<(ms: number | null) => void>();

export function onLatencySample(listener: (ms: number | null) => void): () => void {
  latencyListeners.add(listener);
  return () => latencyListeners.delete(listener);
}

export function getLastLatency(): number | null {
  return lastLatencyMs;
}

function recordLatency(ms: number | null) {
  lastLatencyMs = ms;
  for (const listener of latencyListeners) listener(ms);
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, skipAuthRetry = false, headers, ...rest } = options;

  const send = async (token: string | null): Promise<Response> =>
    fetch(`${API_V1}${path}`, {
      ...rest,
      credentials: "include",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  const startedAt = performance.now();
  let response: Response;
  try {
    response = await send(accessToken);
  } catch (error) {
    recordLatency(null);
    throw error;
  }
  recordLatency(Math.round(performance.now() - startedAt));

  if (response.status === 401 && !skipAuthRetry) {
    const renewed = await refreshAccessToken();
    if (renewed) {
      response = await send(renewed);
    }
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
