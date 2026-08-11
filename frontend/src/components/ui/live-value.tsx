"use client";

import { useChangeFlash } from "@/hooks/use-motion";
import { cn } from "@/lib/utils";

/**
 * A number that says when it moved.
 *
 * The wash is on the **background**, not the text: recolouring the digits
 * would fight the meaning the colour already carries elsewhere on the row,
 * where green and red mean profit and loss rather than "this just changed".
 * A token can tick up while still being down 40% from entry, and those two
 * facts must not use the same channel.
 *
 * The flash decays rather than toggling, so a run of ticks reads as activity
 * instead of a strobe.
 */
export function LiveValue({
  value,
  display,
  className,
}: {
  /** Raw decimal string — the change is detected on this, not on `display`. */
  value: string | null | undefined;
  /** What the reader sees. Formatted by the caller. */
  display: string | null;
  className?: string;
}) {
  const flash = useChangeFlash(value);

  return (
    <span
      className={cn(
        "-mx-1 rounded px-1 transition-colors duration-[180ms] ease-[var(--ease-standard)]",
        flash === "up" && "bg-up/20",
        flash === "down" && "bg-down/20",
        flash === "none" && "bg-transparent",
        className,
      )}
    >
      {display ?? "—"}
    </span>
  );
}
