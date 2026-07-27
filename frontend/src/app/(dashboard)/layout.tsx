"use client";

import { AppHeader } from "@/components/layout/app-header";
import { useRequireAuth } from "@/hooks/use-auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isReady } = useRequireAuth();

  // Hold the shell until the session resolves, so protected content never
  // flashes before a redirect.
  if (!isReady) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        Loading your session…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
