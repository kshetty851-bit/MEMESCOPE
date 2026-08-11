"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * FILTERS — segmented controls and filter groups.
 *
 * The Track Record's "Reached / Sort" strips and the wallet's "Open / Closed"
 * strip are all the same control built three times, each with its own padding,
 * its own active treatment (`bg-plasma/15` in one place, `border-line-bright`
 * in another) and, in two of the three, no accessible name for the group at
 * all — a screen reader hears "All, button" with no idea what it filters.
 *
 * One control. The group is a real `radiogroup` when the options are mutually
 * exclusive, which gives arrow-key navigation and announces "2 of 4".
 */

export interface FilterOption<T extends string> {
  value: T;
  label: ReactNode;
  /** Announced instead of `label` when the label is a glyph or abbreviation. */
  srLabel?: string;
  disabled?: boolean;
}

export interface SegmentedControlProps<T extends string> {
  /** Names the group. Required — this is the fix, not a nicety. */
  label: string;
  options: FilterOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Renders the label beside the control rather than only for screen readers. */
  showLabel?: boolean;
  size?: "sm" | "md";
  className?: string;
}

export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  showLabel = true,
  size = "sm",
  className,
}: SegmentedControlProps<T>) {
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();

    const usable = options.filter((option) => !option.disabled);
    const index = usable.findIndex((option) => option.value === value);
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % usable.length
        : (index - 1 + usable.length) % usable.length;
    const target = usable[next];
    if (target) onChange(target.value);
  }

  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      {showLabel ? (
        <span className="text-label font-medium uppercase text-ink-3">{label}</span>
      ) : null}

      <div
        role="radiogroup"
        aria-label={label}
        onKeyDown={onKeyDown}
        // `line-control`, not `line`: this is the perceivable boundary of an
        // interactive control, so it carries the 3:1 requirement.
        className="inline-flex items-center gap-0.5 rounded-md border border-line-control bg-sunken p-0.5"
      >
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              // Roving tabindex keeps the whole group to one tab stop.
              tabIndex={selected ? 0 : -1}
              disabled={option.disabled}
              onClick={() => onChange(option.value)}
              className={cn(
                "rounded-sm transition-colors duration-[var(--duration-instant)]",
                "disabled:pointer-events-none disabled:opacity-40",
                size === "sm" ? "px-2 py-1 text-xs" : "px-2.5 py-1.5 text-sm",
                selected
                  ? "bg-raised text-ink"
                  : "text-ink-3 hover:text-ink-2",
              )}
            >
              {option.srLabel ? (
                <>
                  <span aria-hidden>{option.label}</span>
                  <span className="sr-only">{option.srLabel}</span>
                </>
              ) : (
                option.label
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * A row of filter controls with a shared baseline.
 *
 * Exists so filter strips stop being ad-hoc flex containers with different gap
 * values on every page.
 */
export function FilterBar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2", className)}>
      {children}
    </div>
  );
}
