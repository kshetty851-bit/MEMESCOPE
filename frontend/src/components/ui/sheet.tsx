"use client";

import { useCallback, useEffect, useId, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * SHEET — the side detail panel foundation.
 *
 * Replaces the pattern in the (now removed) opportunity drawer, which opened a
 * panel over the page with no focus management at all: `Escape` did nothing,
 * `Tab` walked straight out of the panel and into the page behind it, and on
 * close, focus was dropped to `<body>` — so a keyboard user who opened a token
 * detail had to tab from the top of the document to get back where they were.
 *
 * What this handles, per the APG dialog pattern:
 *
 *  - focus moves into the sheet on open, and returns to the trigger on close;
 *  - `Tab` and `Shift+Tab` cycle inside the sheet;
 *  - `Escape` closes;
 *  - the page behind is inert to pointer input and does not scroll;
 *  - `aria-modal` + `aria-labelledby` so it is announced as a dialog with a
 *    name rather than an anonymous region.
 *
 * The scrim is a flat wash, not a blur. Blurring a full-page backdrop is the
 * most expensive effect available and it buys nothing over an opacity that
 * already separates the layers.
 */

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  /** Announced as the dialog's name. */
  title: ReactNode;
  /** Small caps eyebrow above the title. */
  eyebrow?: ReactNode;
  /** Pinned under the header — actions, status, identity. */
  header?: ReactNode;
  /** Pinned to the bottom, outside the scroll area. */
  footer?: ReactNode;
  children: ReactNode;
  side?: "right" | "bottom";
  width?: string;
  className?: string;
}

export function Sheet({
  open,
  onClose,
  title,
  eyebrow,
  header,
  footer,
  children,
  side = "right",
  width = "min(30rem, 100vw)",
  className,
}: SheetProps) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement | null>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;

      const nodes = Array.from(
        panel.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((node) => node.offsetParent !== null);
      if (nodes.length === 0) {
        event.preventDefault();
        return;
      }

      const first = nodes[0]!;
      const last = nodes[nodes.length - 1]!;
      const current = document.activeElement;

      if (event.shiftKey && current === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;

    restoreTo.current = document.activeElement as HTMLElement | null;

    // Focus the panel itself rather than its first control: landing on a
    // "Close" button means a screen reader announces the escape hatch before
    // the content, which is backwards.
    panel.current?.focus();

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown, true);

    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKeyDown, true);
      restoreTo.current?.focus?.();
    };
  }, [open, onKeyDown]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex" role="presentation">
      <button
        type="button"
        aria-label="Close panel"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-canvas/70"
      />

      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={side === "right" ? { width } : undefined}
        className={cn(
          "relative z-10 flex flex-col bg-surface shadow-e3 outline-none",
          side === "right"
            ? "ml-auto h-full max-w-full border-l border-line"
            : "mt-auto max-h-[85vh] w-full border-t border-line",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {eyebrow ? (
              <p className="text-label font-medium uppercase text-ink-3">{eyebrow}</p>
            ) : null}
            <h2
              id={titleId}
              className="mt-0.5 truncate text-md font-medium tracking-tight text-ink"
            >
              {title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className={cn(
              "grid size-7 shrink-0 place-items-center rounded-sm text-ink-3",
              "transition-colors duration-[var(--duration-instant)]",
              "hover:bg-raised hover:text-ink",
            )}
          >
            <span aria-hidden>✕</span>
          </button>
        </div>

        {header ? (
          <div className="border-b border-line-subtle px-4 py-3">{header}</div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>

        {footer ? (
          <div className="border-t border-line px-4 py-3">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}
