"use client";

import { useId, type SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** A labelled select in the same skin as the shared `Input`. */
export function Select({
  label,
  hint,
  error,
  options,
  className,
  id,
  ...props
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> & {
  label: string;
  hint?: string;
  error?: string;
  options: Array<{ value: string; label: string }>;
}) {
  const generated = useId();
  const selectId = id ?? generated;
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={selectId} className="text-label font-medium uppercase text-ink-3">
        {label}
      </label>
      <select
        id={selectId}
        aria-invalid={error ? true : undefined}
        className={cn(
          "h-9 rounded-md border bg-sunken px-2 text-sm text-ink",
          error ? "border-down" : "border-line-control hover:border-line-strong",
          className,
        )}
        {...props}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error ? (
        <p role="alert" className="text-xs text-down">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-ink-3">{hint}</p>
      ) : null}
    </div>
  );
}

export function Checkbox({
  label,
  hint,
  checked,
  onChange,
  name,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  name?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="flex items-center gap-2 text-sm text-ink">
        <input
          id={id}
          name={name}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
      {hint ? <p className="text-xs text-ink-3">{hint}</p> : null}
    </div>
  );
}

export const humanOption = (value: string) =>
  value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
