"use client";

import { useObservatoryMode } from "@/hooks/use-observatory-mode";
import { cn } from "@/lib/utils";

/**
 * Mode switch.
 *
 * A two-position segmented control rather than a checkbox: both modes are
 * legitimate destinations, and a toggle would imply one is "off".
 */
export function ModeToggle({ compact = false }: { compact?: boolean }) {
  const { mode, setMode } = useObservatoryMode();

  const options = [
    {
      id: "observatory" as const,
      label: "Observatory",
      short: "OBS",
      icon: (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          className="size-3.5"
        >
          <circle cx="8" cy="8" r="2.4" />
          <circle cx="8" cy="8" r="6" strokeDasharray="2 2.5" />
        </svg>
      ),
    },
    {
      id: "command" as const,
      label: "Command",
      short: "CMD",
      icon: (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          className="size-3.5"
        >
          <path d="M2 4h12M2 8h12M2 12h8" strokeLinecap="round" />
        </svg>
      ),
    },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Display mode"
      className="inline-flex items-center gap-0.5 rounded-chip border border-line bg-abyss/70 p-0.5"
    >
      {options.map((option) => {
        const active = mode === option.id;
        return (
          <button
            key={option.id}
            role="radio"
            aria-checked={active}
            title={`${option.label} mode`}
            onClick={() => setMode(option.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[4px] px-2 py-1 text-label uppercase",
              "transition-colors duration-150 ease-[var(--ease-precise)]",
              active ? "bg-elevated text-ink" : "text-ink-faint hover:text-ink-dim",
            )}
          >
            {option.icon}
            {/* Icon-only below `sm`: the full bar does not fit a 375px
                viewport once the logo and sign-out are accounted for. The
                title and aria-checked keep it fully labelled either way. */}
            <span className={compact ? "sr-only" : "hidden sm:inline"}>
              {compact ? option.label : option.short}
            </span>
          </button>
        );
      })}
    </div>
  );
}
