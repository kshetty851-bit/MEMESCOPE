"use client";

import { create } from "zustand";

import { api, setAccessToken } from "@/lib/api-client";
import type { AuthResponse, LoginPayload, RegisterPayload, User } from "@/types/api";

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
