"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/feed", label: "Live Feed" },
];

export function AppHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  async function handleSignOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="border-b border-border bg-surface/60 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-6">
          <span className="text-sm font-semibold tracking-tight text-brand">
            {env.NEXT_PUBLIC_APP_NAME}
          </span>
          <nav className="flex items-center gap-4">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={pathname === item.href ? "page" : undefined}
                className={cn(
                  "text-sm transition-colors",
                  pathname === item.href
                    ? "text-content"
                    : "text-muted hover:text-content",
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

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
