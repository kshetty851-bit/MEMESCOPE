"use client";

import { useEffect, useState } from "react";

import { BUILD } from "@/lib/env";
import { cn } from "@/lib/utils";

/**
 * ALPHA BAR
 *
 * Tells a private-alpha tester three things: that this is an alpha, exactly
 * which build they are looking at, and where to send what they find.
 *
 * The build identifier is the point. Alpha feedback arrives hours later as
 * "the scores looked wrong" — without a SHA in the report there is no way to
 * know which code produced it, and the tester is the only one who can supply
 * it. Putting it on screen means it lands in the screenshot.
 *
 * Renders nothing unless `NEXT_PUBLIC_ALPHA` is on, so production-after-alpha
 * needs a flag change rather than a code change, and local development is not
 * cluttered by it.
 *
 * Dismissal is remembered per build: a tester should not have to close this on
 * every navigation, but a new deployment is worth re-announcing because the
 * thing they are testing has changed.
 */

const STORAGE_PREFIX = "memescope:alpha-dismissed:";

export function AlphaBar() {
  const [dismissed, setDismissed] = useState(true);

  // Starts dismissed and is revealed on the client. Reading localStorage during
  // render would mismatch the server-rendered HTML; showing it first and hiding
  // it afterwards would flash the bar at someone who already closed it.
  useEffect(() => {
    if (!BUILD.isAlpha) return;
    try {
      setDismissed(window.localStorage.getItem(`${STORAGE_PREFIX}${BUILD.sha}`) === "1");
    } catch {
      // Private browsing: show the bar. Erring towards displaying it is right —
      // the cost is mild annoyance, the cost of hiding it is a tester who does
      // not know this is alpha software.
      setDismissed(false);
    }
  }, []);

  if (!BUILD.isAlpha || dismissed) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(`${STORAGE_PREFIX}${BUILD.sha}`, "1");
    } catch {
      /* the choice simply will not survive a reload */
    }
  }

  return (
    <div
      role="region"
      aria-label="Alpha programme notice"
      className="relative z-40 border-b border-warn/25 bg-warn/[0.07]"
    >
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2 lg:px-8">
        <span className="rounded-chip border border-warn/40 px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-warn">
          Private alpha
        </span>

        <p className="min-w-0 flex-1 text-xs text-ink-dim">
          Scores are produced by a v1 model with four signals still unavailable.
          Intelligence, not advice.
        </p>

        <VersionBadge />

        {BUILD.feedbackUrl !== "" && (
          <a
            href={BUILD.feedbackUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="rounded-chip border border-line px-2 py-1 text-xs text-ink-dim transition-colors hover:border-line-bright hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma"
          >
            Send feedback
          </a>
        )}

        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss alpha notice"
          className="rounded-chip px-1.5 py-1 text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className="size-3.5"
          >
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/**
 * Version and build identifier.
 *
 * Monospace because it is a figure to be read character by character and
 * copied into a bug report, not prose.
 */
export function VersionBadge({ className }: { className?: string }) {
  return (
    <span
      data-numeric
      title={`Version ${BUILD.version} · build ${BUILD.sha} · ${BUILD.environment}`}
      className={cn("font-mono text-[0.625rem] text-ink-faint", className)}
    >
      v{BUILD.version}
      <span className="mx-1 opacity-40">·</span>
      {BUILD.sha}
    </span>
  );
}
