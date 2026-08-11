"use client";

import { useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * TABS — the APG tabs pattern, controlled.
 *
 * The app currently builds tab strips out of loose `<button>`s with
 * `aria-pressed`, which is a different control: `aria-pressed` says "this
 * toggle is on", not "this is the selected view of several". A screen reader
 * user gets no tab count and no position, and arrow keys do nothing.
 *
 * Roving tabindex, so the strip is a single tab stop and Left/Right moves
 * between views — which is also the fastest way for a keyboard user to flip
 * between Open and Closed positions without leaving the table.
 *
 * Use this where selecting changes a *panel*. For filters that narrow a list
 * in place, use `SegmentedControl` — a filter is a toggle, not a view.
 */

export interface TabItem<T extends string> {
  value: T;
  label: ReactNode;
  /** Right-aligned count, e.g. the number of open positions. */
  count?: number;
  disabled?: boolean;
}

export interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  /** id of the element this strip controls, for `aria-controls`. */
  panelId?: string;
  "aria-label": string;
  className?: string;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  panelId,
  "aria-label": ariaLabel,
  className,
}: TabsProps<T>) {
  const refs = useRef(new Map<T, HTMLButtonElement>());

  const focusable = items.filter((item) => !item.disabled);

  function onKeyDown(event: React.KeyboardEvent) {
    const keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();

    const index = focusable.findIndex((item) => item.value === value);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % focusable.length;
    if (event.key === "ArrowLeft") next = (index - 1 + focusable.length) % focusable.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = focusable.length - 1;

    const target = focusable[next];
    if (!target) return;
    onChange(target.value);
    refs.current.get(target.value)?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn("inline-flex items-center gap-0.5", className)}
    >
      {items.map((item) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            ref={(node) => {
              if (node) refs.current.set(item.value, node);
              else refs.current.delete(item.value);
            }}
            type="button"
            role="tab"
            id={`tab-${item.value}`}
            aria-selected={selected}
            aria-controls={panelId}
            // Roving tabindex: only the selected tab is in the tab order.
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-xs",
              "transition-colors duration-[var(--duration-instant)]",
              "disabled:pointer-events-none disabled:opacity-40",
              selected
                ? "bg-raised text-ink"
                : "text-ink-3 hover:bg-surface hover:text-ink-2",
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span
                data-numeric
                className={cn("tabular-nums", selected ? "text-ink-2" : "text-ink-3")}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** The panel a `Tabs` strip controls. Pairs `aria-labelledby` to the tab. */
export function TabPanel({
  id,
  value,
  children,
  className,
}: {
  id: string;
  value: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      id={id}
      role="tabpanel"
      aria-labelledby={`tab-${value}`}
      tabIndex={0}
      className={cn("outline-none", className)}
    >
      {children}
    </div>
  );
}
