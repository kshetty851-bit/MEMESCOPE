import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * TOOLBAR — the control strip above a data surface.
 *
 * Every screen currently hand-rolls this as a `flex flex-wrap items-center
 * justify-between gap-3` with slightly different gaps and a different heading
 * size, and on the pages that scroll, the controls scroll away with the
 * header — so filtering a 400-row record means scrolling back to the top to
 * change the filter.
 *
 * `sticky` fixes that. It is off by default because a sticky toolbar on a
 * short page is just a bar that never moves.
 */

export interface ToolbarProps {
  /** Small caps eyebrow above the title. */
  eyebrow?: ReactNode;
  title?: ReactNode;
  /** One sentence. Kept short — a toolbar is not a place for prose. */
  description?: ReactNode;
  /** Controls: filters, search, density, live status. */
  actions?: ReactNode;
  /** Second row, for filters that do not fit beside the title. */
  filters?: ReactNode;
  sticky?: boolean;
  className?: string;
}

export function Toolbar({
  eyebrow,
  title,
  description,
  actions,
  filters,
  sticky = false,
  className,
}: ToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3",
        // `bg-canvas` rather than a translucent surface: a sticky bar that
        // lets rows show through it is the single worst thing to do to a
        // scrolling table, and it costs a backdrop-filter to achieve.
        sticky && "sticky top-0 z-30 -mx-4 bg-canvas px-4 py-3",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="text-label font-medium uppercase text-ink-3">{eyebrow}</p>
          ) : null}
          {title ? (
            <h1 className="mt-1 text-lg font-medium tracking-tight text-ink">{title}</h1>
          ) : null}
          {description ? (
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-ink-2">
              {description}
            </p>
          ) : null}
        </div>

        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>

      {filters ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line-subtle pt-3">
          {filters}
        </div>
      ) : null}
    </div>
  );
}

/**
 * A hairline group separator inside a toolbar, for splitting unrelated
 * controls without spending a whole row on them.
 */
export function ToolbarDivider({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn("h-4 w-px shrink-0 bg-line", className)} />
  );
}
