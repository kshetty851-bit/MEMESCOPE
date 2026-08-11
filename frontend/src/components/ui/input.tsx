"use client";

import type { InputHTMLAttributes } from "react";
import { useId } from "react";

import { cn } from "@/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export function Input({ label, error, hint, className, id, ...props }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={inputId} className="text-label font-medium uppercase text-ink-3">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "h-9 rounded-md border bg-sunken px-3 text-sm text-ink",
          "transition-colors duration-[var(--duration-instant)]",
          // `focus:outline-none` is deliberately absent. The global
          // `:focus-visible` ring is the only focus treatment in the product,
          // and removing it here left a border colour change as the sole
          // indicator — which is a 3:1 non-text contrast requirement met by
          // accident rather than a focus indicator.
          "placeholder:text-ink-4",
          // A control boundary, not a divider: `line-control` clears 3:1
          // against every surface an input can sit on.
          error
            ? "border-down"
            : "border-line-control hover:border-line-strong",
          className,
        )}
        {...props}
      />
      {error ? (
        <p id={`${inputId}-error`} role="alert" className="text-xs text-down">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-xs text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
