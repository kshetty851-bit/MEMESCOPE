import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * Buttons.
 *
 * `primary` is the only element on a screen permitted a plasma glow, and there
 * is at most one per view. Everything else is a surface or a hairline. Scarcity
 * is what makes the primary action read as inevitable.
 */

type Variant = "primary" | "surface" | "ghost" | "outline" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-void font-medium shadow-[0_0_0_1px_color-mix(in_oklch,var(--color-accent)_60%,transparent),0_8px_32px_-8px_color-mix(in_oklch,var(--color-accent)_70%,transparent)] hover:brightness-110 active:brightness-95",
  surface:
    "bg-raised/80 text-ink border border-line hover:border-line-strong hover:bg-raised/80",
  ghost: "text-ink-2 hover:text-ink hover:bg-raised/60",
  outline: "border border-accent/40 text-accent hover:bg-accent/10 hover:border-accent/70",
  danger: "bg-down/15 text-down border border-down/35 hover:bg-down/25",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-[0.9375rem] gap-2.5",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export function Button({
  variant = "surface",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      aria-busy={loading}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center rounded-sm whitespace-nowrap",
        "transition-[transform,filter,background-color,border-color,color] duration-150 ease-[var(--ease-standard)]",
        "active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && (
        <span
          aria-hidden
          className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}
