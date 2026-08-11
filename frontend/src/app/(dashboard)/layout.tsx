"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { FeedbackWidget } from "@/components/alpha/feedback-widget";
import { ActivityHeartbeat } from "@/components/alpha/activity-heartbeat";
import { AppShell } from "@/components/layout/app-shell";
import { LiveUpdatesProvider } from "@/hooks/use-live-updates";
import { ALPHA_ACCESS } from "@/lib/env";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { AlphaSessionStatus } from "@/types/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [alphaReady, setAlphaReady] = useState(false);
  const [enteredFromAlpha, setEnteredFromAlpha] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void api
      .get<AlphaSessionStatus>("/alpha/session", { skipAuthRetry: true })
      .then((session) => {
        if (cancelled) return;
        if (!session.authenticated) {
          router.replace("/");
          return;
        }

        setAlphaReady(true);
        const justUnlocked = window.sessionStorage.getItem(ALPHA_ACCESS.transitionKey) === "true";
        if (justUnlocked) {
          window.sessionStorage.removeItem(ALPHA_ACCESS.transitionKey);
          setEnteredFromAlpha(true);
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/");
      });

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  // Alpha Access is the only temporary private gate. Hold the shell until the
  // browser-level access grant is confirmed so the dashboard never flashes
  // before redirecting back to the launch screen.
  if (!alphaReady) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <p className="text-sm text-ink-3">Loading…</p>
      </div>
    );
  }

  return (
    // The live-update socket is mounted here rather than at the document root,
    // and only once alpha access is confirmed. The API refuses the stream
    // without an alpha cookie and closes with 1008, so opening it any earlier
    // guaranteed a refusal — which is exactly what the public landing page was
    // doing on a reconnect backoff before this moved.
    <LiveUpdatesProvider>
      <div className={cn(enteredFromAlpha && "alpha-dashboard-enter")}>
        <AppShell>{children}</AppShell>
        <ActivityHeartbeat />
        {/* Every page, because the moment a tester notices something is the
            only moment they will report it. */}
        <FeedbackWidget />
      </div>
    </LiveUpdatesProvider>
  );
}
