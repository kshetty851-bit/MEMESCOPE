"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

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

/** Redirects to `/login` once the session has resolved as anonymous. */
export function useRequireAuth(redirectTo = "/login") {
  const router = useRouter();
  const { status, user } = useAuthStore();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(redirectTo);
    }
  }, [status, router, redirectTo]);

  return { user, isReady: status === "authenticated" };
}
