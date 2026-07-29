"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Label, Panel } from "@/components/ui/panel";

/**
 * HOW TO READ THIS DASHBOARD
 *
 * Shown once. A first-time user lands on a screen of scores, grades and
 * percentages with no idea which number to trust, and the single most common
 * misreading is treating the score as a verdict while ignoring the confidence
 * beside it. This says the three things that prevent that, then gets out of the
 * way permanently.
 *
 * Deliberately not a guided tour. A multi-step overlay on a live feed blocks the
 * thing the user came to look at, and a tour library is a dependency and a
 * maintenance burden for a message that fits in three sentences.
 *
 * Dismissal is permanent and not keyed to the build, unlike the alpha bar: the
 * alpha bar re-announces because what is being tested changed, but nobody needs
 * to be taught how to read a grade twice.
 */

const STORAGE_KEY = "memescope:primer-dismissed";

const POINTS: { term: string; body: string }[] = [
  {
    term: "Score and grade",
    body: "0–100, banded into Weak, Watch, Strong and High Conviction. It reads how the token looks right now — not a prediction, and not advice.",
  },
  {
    term: "Confidence",
    body: "How much of the model could be applied. Four of nine signals have no data source yet, so confidence runs low across the board. A high score with low confidence is a thin reading.",
  },
  {
    term: "Sentinel",
    body: "Reads the engine's output back to you in plain language. It never calculates anything of its own.",
  },
];

export function DashboardPrimer() {
  const [dismissed, setDismissed] = useState(true);

  // Hidden until the client confirms it has not been dismissed. Rendering it
  // first and hiding it afterwards would flash the panel at a returning user
  // on every single load.
  useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      setDismissed(false);
    }
  }, []);

  if (dismissed) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* the choice will not survive a reload, which is an acceptable failure */
    }
  }

  return (
    <Panel density="compact" className="border-plasma/20 bg-plasma/[0.03]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Label>New here</Label>
          <h2 className="mt-1 text-heading font-medium text-ink">
            How to read this dashboard
          </h2>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 rounded-chip px-1.5 py-1 text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma"
          aria-label="Dismiss the introduction"
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

      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        {POINTS.map((point) => (
          <div key={point.term}>
            <dt className="text-sm font-medium text-ink">{point.term}</dt>
            <dd className="mt-0.5 text-xs leading-relaxed text-ink-faint">{point.body}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3.5 flex flex-wrap items-center gap-4 border-t border-line/60 pt-3">
        <Link
          href="/about"
          className="text-xs text-plasma transition-colors hover:text-ink"
        >
          How scoring works →
        </Link>
        <button
          type="button"
          onClick={dismiss}
          className="text-xs text-ink-faint transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma"
        >
          Got it
        </button>
      </div>
    </Panel>
  );
}
