"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { FeedbackWidget } from "@/components/alpha/feedback-widget";
import { SiteNav } from "@/components/layout/site-nav";
import { useRequireAuth } from "@/hooks/use-auth";
import { ALPHA_ACCESS } from "@/lib/env";
import { cn } from "@/lib/utils";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isReady } = useRequireAuth();
  const [alphaReady, setAlphaReady] = useState(false);
  const [enteredFromAlpha, setEnteredFromAlpha] = useState(false);

  useEffect(() => {
    if (window.localStorage.getItem(ALPHA_ACCESS.storageKey) !== "granted") {
      router.replace("/");
      return;
    }

    setAlphaReady(true);
    const justUnlocked = window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey) === "true";
    if (justUnlocked) {
      window.sessionStorage.removeItem(ALPHA_ACCESS.transitionKey);
      setEnteredFromAlpha(true);
    }
  }, [pathname, router]);

  // Hold the shell until the session resolves, so protected content never
  // flashes before a redirect. Plain text rather than an animated core: a
  // loading state should say what is happening, not perform.
  if (!isReady || !alphaReady) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-ink-faint">Loading…</p>
      </div>
    );
  }

  return (
    <div className={cn("min-h-screen", enteredFromAlpha && "alpha-dashboard-enter")}>
      <SiteNav />
      {/* Bottom padding clears the mobile tab bar, which is fixed. */}
      <main className="mx-auto max-w-[1120px] px-6 pb-24 pt-6 md:pb-12">
        {children}
      </main>
      {/* Every page, because the moment a tester notices something is the only
          moment they will report it. */}
      <FeedbackWidget />
    </div>
  );
}
