"use client";

import { useEffect } from "react";

import { AgentSigil } from "@/components/brand/agent-sigil";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/panel";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled UI error", error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <div className="flex size-16 items-center justify-center rounded-full border border-sentinel/30 bg-sentinel/10 text-sentinel">
        <AgentSigil agent="sentinel" size={30} />
      </div>

      <div className="max-w-md space-y-3">
        <Label>Containment</Label>
        <h1 className="text-title font-semibold text-ink">
          SENTINEL halted this view
        </h1>
        <p className="text-sm text-ink-faint">
          Something failed while rendering. The scanner and enrichment engine are
          unaffected and still running.
        </p>
        {error.digest && (
          <p data-numeric className="text-xs text-ink-faint/70">
            REF {error.digest}
          </p>
        )}
      </div>

      <Button variant="primary" onClick={reset}>
        Re-establish view
      </Button>
    </main>
  );
}
