"use client";

import { create } from "zustand";

import { api, setAccessToken } from "@/lib/api-client";
import { AUTH_BYPASS } from "@/lib/env";
import type { AuthResponse, LoginPayload, RegisterPayload, User } from "@/types/api";

/**
 * Stand-in identity used while `AUTH_BYPASS` is on.
 *
 * Mirrors the principal the backend hands out under the same flag, so the UI
 * and the API agree on who is signed in without a token ever existing. Never
 * reached in a production build.
 */
const DEVELOPER_USER: User = {
  id: "00000000-0000-4000-8000-00000000d0e5",
  email: "developer@memescope.local",
  display_name: "Developer",
  role: "admin",
  is_active: true,
  is_verified: true,
  last_login_at: null,
  created_at: new Date(0).toISOString(),
};

/**
 * Session state.
 *
 * Nothing here is persisted. On a page load `bootstrap()` calls the refresh
 * endpoint; if the httpOnly cookie is still valid the session comes back, and
 * if not the user is simply signed out. That keeps the browser free of any
 * long-lived credential an XSS payload could read.
 */
interface AuthState {
  user: User | null;
  status: "idle" | "loading" | "authenticated" | "unauthenticated";
  error: string | null;

  bootstrap: () => Promise<void>;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => {
  const applySession = (session: AuthResponse) => {
    setAccessToken(session.access_token);
    set({ user: session.user, status: "authenticated", error: null });
  };

  const clearSession = () => {
    setAccessToken(null);
    set({ user: null, status: "unauthenticated" });
  };

  return {
    user: null,
    status: "idle",
    error: null,

    bootstrap: async () => {
      // Development bypass: resolve to a developer session synchronously and
      // make no request at all. Returning before the fetch is what keeps the
      // network free of auth traffic, rather than merely ignoring its result.
      if (AUTH_BYPASS) {
        set({ user: DEVELOPER_USER, status: "authenticated", error: null });
        return;
      }

      set({ status: "loading" });
      try {
        applySession(
          await api.post<AuthResponse>("/auth/refresh", undefined, {
            skipAuthRetry: true,
          }),
        );
      } catch {
        // No valid refresh cookie: an anonymous visitor, not an error state.
        clearSession();
      }
    },

    login: async (payload) => {
      set({ status: "loading", error: null });
      try {
        applySession(await api.post<AuthResponse>("/auth/login", payload));
      } catch (error) {
        clearSession();
        set({ error: error instanceof Error ? error.message : "Sign in failed." });
        throw error;
      }
    },

    register: async (payload) => {
      set({ status: "loading", error: null });
      try {
        applySession(await api.post<AuthResponse>("/auth/register", payload));
      } catch (error) {
        clearSession();
        set({ error: error instanceof Error ? error.message : "Sign up failed." });
        throw error;
      }
    },

    logout: async () => {
      try {
        await api.post<{ message: string }>("/auth/logout");
      } catch {
        // Even if the server call fails, drop local state — the user asked to leave.
      } finally {
        clearSession();
      }
    },

    clearError: () => set({ error: null }),
  };
});
