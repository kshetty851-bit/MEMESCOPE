import { cn } from "@/lib/utils";

/**
 * The MEMESCOPE mark: an aperture.
 *
 * A ring of segments closing on a single lit point — an instrument iris the
 * moment it resolves a signal. It carries the whole product thesis (something
 * is watching, and it has found something) in a shape that survives being
 * 16px in a browser tab.
 */
export function LogoMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <circle
        cx="16"
        cy="16"
        r="13"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeDasharray="4.6 3.4"
        opacity="0.55"
      />
      <circle cx="16" cy="16" r="8" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="3.2" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "text-[0.9375rem] font-semibold tracking-[0.16em] text-ink",
        className,
      )}
    >
      MEMESCOPE
    </span>
  );
}

export function Logo({
  className,
  size = 22,
  showWordmark = true,
}: {
  className?: string;
  size?: number;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark size={size} className="text-plasma" />
      {showWordmark && <Wordmark />}
    </span>
  );
}
