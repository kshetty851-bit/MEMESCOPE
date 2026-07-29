"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AUTH_BYPASS } from "@/lib/env";
import { useAuthStore } from "@/stores/auth-store";

export function useAuth() {
  const { user, status, error, login, register, logout, clearError } = useAuthStore();
  return {
    user,
    status,
    error,
    isAuthenticated: status === "authenticated",
    isLoading: status === "loading" || status === "idle",
    login,
    register,
    logout,
    clearError,
  };
}

/**
 * Redirects to `/login` once the session has resolved as anonymous.
 *
 * Under `AUTH_BYPASS` the guard is inert: it reports ready on the first render
 * and never redirects, so the dashboard paints immediately instead of holding
 * behind an "establishing session" state that would never resolve.
 */
export function useRequireAuth(redirectTo = "/login") {
  const router = useRouter();
  const { status, user } = useAuthStore();

  useEffect(() => {
    if (AUTH_BYPASS) return;
    if (status === "unauthenticated") {
      router.replace(redirectTo);
    }
  }, [status, router, redirectTo]);

  if (AUTH_BYPASS) {
    return { user, isReady: true };
  }

  return { user, isReady: status === "authenticated" };
}
