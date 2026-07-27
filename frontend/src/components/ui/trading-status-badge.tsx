import { cn } from "@/lib/utils";
import type { TradingStatus } from "@/types/api";

const STYLES: Record<TradingStatus, string> = {
  trading: "bg-brand/15 text-brand",
  inactive: "bg-danger/15 text-danger",
  // "unknown" means the provider has not indexed a pool yet, which is the
  // normal state for a token seconds old — it must not read as an error.
  unknown: "bg-surface-raised text-muted",
};

const LABELS: Record<TradingStatus, string> = {
  trading: "Trading",
  inactive: "Inactive",
  unknown: "Pending",
};

export function TradingStatusBadge({
  status,
  className,
}: {
  status: TradingStatus | null | undefined;
  className?: string;
}) {
  const value: TradingStatus = status ?? "unknown";
  return (
    <span
      className={cn(
        "inline-flex rounded px-2 py-0.5 text-xs font-medium",
        STYLES[value],
        className,
      )}
    >
      {LABELS[value]}
    </span>
  );
}
