import type { ReactNode } from "react";

import { HeroMascot } from "@/components/alpha/hero-mascot";
import { cn } from "@/lib/utils";

const COPY = {
  scanning: {
    title: "Scanning...",
    body: "MEMESCOPE is sweeping the live Pump.fun field. New signals appear here when they clear the model's bar.",
  },
  waiting: {
    title: "Waiting for opportunities...",
    body: "The system is live, but nothing currently qualifies. Empty is a measured state.",
  },
  "no-positions": {
    title: "No active positions...",
    body: "Capital is ready. The paper wallet opens only when the published rule finds a qualified Radar token.",
  },
  capital: {
    title: "Capital ready...",
    body: "Cash is available and waiting for the next eligible signal.",
  },
  unavailable: {
    title: "Signal temporarily unavailable...",
    body: "The last known record is safe. This view will recover when the stream resolves.",
  },
} as const;

export type MascotStateKind = keyof typeof COPY;

export function MascotState({
  kind,
  action,
  className,
}: {
  kind: MascotStateKind;
  action?: ReactNode;
  className?: string;
}) {
  const copy = COPY[kind];
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 px-6 py-14 text-center",
        className,
      )}
    >
      <HeroMascot compact />
      <div className="max-w-sm space-y-1.5">
        <p className="text-heading font-medium text-ink">{copy.title}</p>
        <p className="text-sm text-ink-faint">{copy.body}</p>
      </div>
      {action}
    </div>
  );
}
