"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { env } from "@/lib/env";

export function AppHeader() {
  const router = useRouter();
  const { user, logout } = useAuth();

  async function handleSignOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="border-b border-border bg-surface/60 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <span className="text-sm font-semibold tracking-tight text-brand">
          {env.NEXT_PUBLIC_APP_NAME}
        </span>

        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-muted sm:inline">
            {user?.display_name ?? user?.email}
          </span>
          <Button variant="ghost" size="sm" onClick={handleSignOut}>
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
