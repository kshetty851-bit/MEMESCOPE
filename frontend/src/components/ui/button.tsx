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
    "bg-plasma text-void font-medium shadow-[0_0_0_1px_color-mix(in_oklch,var(--color-plasma)_60%,transparent),0_8px_32px_-8px_color-mix(in_oklch,var(--color-plasma)_70%,transparent)] hover:brightness-110 active:brightness-95",
  surface:
    "bg-elevated/80 text-ink border border-line hover:border-line-bright hover:bg-raised/80",
  ghost: "text-ink-dim hover:text-ink hover:bg-elevated/60",
  outline:
    "border border-plasma/40 text-plasma hover:bg-plasma/10 hover:border-plasma/70",
  danger: "bg-danger/15 text-danger border border-danger/35 hover:bg-danger/25",
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
        "inline-flex items-center justify-center rounded-chip whitespace-nowrap",
        "transition-[transform,filter,background-color,border-color,color] duration-150 ease-[var(--ease-instrument)]",
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
