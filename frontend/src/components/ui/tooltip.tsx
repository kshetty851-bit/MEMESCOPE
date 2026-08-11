"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * TOOLTIP — the replacement for `title=""`.
 *
 * The audit found information carried *only* by the native `title` attribute
 * in more than thirty places, eleven of them on the Radar row alone: what the
 * evidence dots mean, why a change is a dash instead of 0%, when a signal
 * expires, what "Alive" is actually claiming. Native `title` fails four ways
 * at once — it never appears on touch, it is unreachable by keyboard, screen
 * reader support is inconsistent, and the ~1s browser delay means it is
 * effectively invisible to anyone scanning.
 *
 * This component fixes all four:
 *
 *  - opens on hover **and** on focus, so the keyboard reaches it;
 *  - toggles on tap, so touch reaches it;
 *  - wires `aria-describedby`, so assistive tech reaches it;
 *  - `Escape` closes it, per the APG disclosure pattern.
 *
 * The trigger must be focusable. Wrap text in the `InfoTip` variant below
 * rather than putting a tooltip on a bare `<span>` — a tooltip nobody can
 * focus is the problem this file exists to solve, wearing a nicer style.
 */

type Side = "top" | "bottom";

export interface TooltipProps {
  /** Tooltip body. Keep it to a sentence or two. */
  content: ReactNode;
  children: ReactNode;
  side?: Side;
  className?: string;
}

export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    // A tap elsewhere dismisses, which is the only way to close it on touch.
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    <span
      ref={wrapper}
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) {
          setOpen(false);
        }
      }}
    >
      <span aria-describedby={open ? id : undefined} className="inline-flex">
        {children}
      </span>

      {open ? (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "absolute left-1/2 z-50 w-max max-w-[16rem] -translate-x-1/2",
            "rounded-md border border-line bg-overlay px-2.5 py-1.5",
            "text-xs leading-snug text-ink shadow-e2",
            side === "top" ? "bottom-[calc(100%+6px)]" : "top-[calc(100%+6px)]",
          )}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}

/**
 * A labelled help affordance for a field name.
 *
 * This is the shape most of the migrated `title=""` call sites want: a column
 * header or a stat label that needs a sentence of explanation. The button is
 * real, so it is tabbable and announced, and it carries the field name in its
 * accessible label rather than a bare "more information".
 */
export function InfoTip({
  label,
  content,
  side = "top",
  className,
}: {
  /** The field this explains, e.g. "Evidence". Used in the accessible name. */
  label: string;
  content: ReactNode;
  side?: Side;
  className?: string;
}) {
  return (
    <Tooltip content={content} side={side} className={className}>
      <button
        type="button"
        aria-label={`About ${label}`}
        className={cn(
          "grid size-3.5 place-items-center rounded-full border border-line",
          "text-[0.5625rem] leading-none text-ink-3",
          "transition-colors duration-[var(--duration-instant)]",
          "hover:border-line-strong hover:text-ink-2",
        )}
      >
        <span aria-hidden>?</span>
      </button>
    </Tooltip>
  );
}
