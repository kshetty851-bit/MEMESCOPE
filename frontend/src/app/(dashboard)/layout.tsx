"use client";

import { FeedbackWidget } from "@/components/alpha/feedback-widget";
import { SiteNav } from "@/components/layout/site-nav";
import { useRequireAuth } from "@/hooks/use-auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isReady } = useRequireAuth();

  // Hold the shell until the session resolves, so protected content never
  // flashes before a redirect. Plain text rather than an animated core: a
  // loading state should say what is happening, not perform.
  if (!isReady) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-ink-faint">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
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
