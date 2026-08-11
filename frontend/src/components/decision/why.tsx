"use client";

import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Why — the affordance that makes every badge accountable.
 *
 * Phase 12's rule is that nothing on screen may be unexplained: every badge,
 * warning and band has to be able to say where it came from. A tooltip is the
 * wrong shape for that (it vanishes, it fails on touch, and it is invisible to
 * a screen reader), so this is a real disclosure — a button and a region that
 * stays open until dismissed.
 *
 * Deliberately unstyled beyond the trigger. It wraps whatever explanation the
 * caller has, which in almost every case is a sentence the backend rendered.
 */
export function Why({
  children,
  label = "Why?",
  className,
}: {
  children: React.ReactNode;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "rounded-sm border border-line px-1.5 py-0.5 text-label font-medium",
          "uppercase tracking-[0.08em] text-ink-3 transition-colors",
          "hover:border-line hover:text-ink-2",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-accent",
        )}
      >
        {label}
      </button>
      {open ? (
        <span
          id={id}
          className="block max-w-prose text-xs leading-relaxed text-ink-2"
        >
          {children}
        </span>
      ) : null}
    </span>
  );
}
