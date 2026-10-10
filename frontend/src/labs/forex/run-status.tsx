"use client";

import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api-client";

import { isActive } from "./hooks";
import type { RunOut } from "./types";

/** What a failed mutation says. 401 is a sign-in prompt; anything else is verbatim. */
export function errorMessage(error: unknown, action: string): string {
  if (error instanceof ApiError && error.status === 401) return `Sign in to ${action}.`;
  if (error instanceof Error && error.message) return error.message;
  return "The request failed.";
}

export function ErrorLine({ error, action }: { error: unknown; action: string }) {
  if (!error) return null;
  return (
    <p role="alert" data-testid="error-line" className="text-sm text-down">
      {errorMessage(error, action)}
    </p>
  );
}

const STATUS_TONE = {
  queued: "neutral",
  running: "plasma",
  done: "safe",
  failed: "danger",
} as const;

export function StatusBadge({ status }: { status: RunOut["status"] }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}

/**
 * Progress while a run is queued or running; the error, verbatim, when it
 * failed. A finished run renders nothing here: its result is the display.
 */
export function RunStatus({ run }: { run: RunOut }) {
  if (run.status === "failed") {
    return (
      <div
        role="alert"
        data-testid="run-failed"
        className="rounded-md border border-down/35 bg-down/10 px-3 py-2 text-sm text-down"
      >
        <p className="font-medium">Run {run.id} failed</p>
        {/* Verbatim: the engine's own message is the diagnosis. */}
        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs">
          {run.error ?? "No error message was recorded."}
        </pre>
      </div>
    );
  }
  if (!isActive(run.status)) return null;

  const value = Math.max(0, Math.min(100, run.progress));
  return (
    <div data-testid="run-progress" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="flex items-center gap-2">
          <StatusBadge status={run.status} />
          <span className="text-ink-2">{run.message ?? "Working"}</span>
        </span>
        <span data-numeric className="text-ink-3">
          {Math.round(value)}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`Run ${run.id} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
        className="h-1.5 overflow-hidden rounded-full bg-sunken"
      >
        <div className="h-full bg-accent transition-[width] duration-300" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
