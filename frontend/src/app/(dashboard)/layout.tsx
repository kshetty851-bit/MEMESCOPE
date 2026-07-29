"use client";

import { AlphaBar } from "@/components/alpha/alpha-bar";
import { FeedbackWidget } from "@/components/alpha/feedback-widget";
import { Universe } from "@/components/brand/universe/universe";
import { CommandNav } from "@/components/layout/command-nav";
import { AiCore } from "@/components/brand/ai-core";
import { useRequireAuth } from "@/hooks/use-auth";

export default function CommandLayout({ children }: { children: React.ReactNode }) {
  const { isReady } = useRequireAuth();

  // Hold the shell until the session resolves, so protected content never
  // flashes before a redirect. The Core doubles as the loading state — the
  // instrument is booting, not "please wait".
  if (!isReady) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6">
        <AiCore size={200} showAgents={false} label="Establishing session" />
        <p className="text-label uppercase text-ink-faint">Establishing secure link</p>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen lg:pl-[68px]">
      <Universe />
      <CommandNav />
      {/* Above the content rather than pinned: an alpha notice that floats over
          the instrument would cover data on every page for the whole session. */}
      <AlphaBar />
      <main className="mx-auto max-w-[1600px] px-5 pb-24 pt-6 lg:px-8 lg:pb-12">
        {children}
      </main>
      {/* Every page, because the moment a tester notices something is the only
          moment they will report it. */}
      <FeedbackWidget />
    </div>
  );
}
