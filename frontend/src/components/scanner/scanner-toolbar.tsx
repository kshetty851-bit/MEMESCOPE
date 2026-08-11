"use client";

import { IconSearch } from "@/components/layout/nav-icons";
import { FilterBar, SegmentedControl } from "@/components/ui/filters";
import { InfoTip } from "@/components/ui/tooltip";
import {
  DEFAULT_FILTERS,
  RISK_FILTER_OPTIONS,
  activeFilterCount,
  type AgeFilter,
  type RiskFilter,
  type ScannerFilters,
} from "@/lib/scanner";
import { cn } from "@/lib/utils";

/**
 * SCANNER FILTERS.
 *
 * Five, chosen for decision speed rather than for looking thorough. Each one
 * answers a question a trader actually asks while scanning: *is this the token
 * I heard about* (search), *how dangerous is it* (risk), *how new is it* (age),
 * *can I get out* (liquidity), *is this even priced* (priced-only).
 *
 * An honesty note that shapes the whole control: `/radar` accepts only
 * `category`, `include_inactive` and `sort` as server-side parameters. Every
 * filter here is therefore applied **client-side over the page already
 * fetched**, which the row-count readout states plainly rather than implying a
 * search across the whole record.
 */

const AGE_OPTIONS: { value: AgeFilter; label: string }[] = [
  { value: "all", label: "Any" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

const LIQUIDITY_OPTIONS = [
  { value: "0", label: "Any" },
  { value: "1000", label: "$1K" },
  { value: "10000", label: "$10K" },
  { value: "50000", label: "$50K" },
];

export function ScannerToolbar({
  filters,
  onChange,
  shown,
  total,
  className,
}: {
  filters: ScannerFilters;
  onChange: (filters: ScannerFilters) => void;
  /** Rows surviving the filters. */
  shown: number;
  /** Rows fetched from the Radar. */
  total: number;
  className?: string;
}) {
  const active = activeFilterCount(filters);
  const set = <K extends keyof ScannerFilters>(key: K, value: ScannerFilters[K]) =>
    onChange({ ...filters, [key]: value });

  return (
    <div className={cn("flex flex-col gap-2.5", className)}>
      <FilterBar>
        <label className="relative flex items-center">
          <span className="sr-only">Filter by symbol, name or mint address</span>
          <IconSearch
            aria-hidden
            className="pointer-events-none absolute left-2 size-3.5 text-ink-4"
          />
          <input
            type="search"
            value={filters.query}
            onChange={(event) => set("query", event.target.value)}
            placeholder="Symbol, name or mint"
            className={cn(
              "h-7 w-52 rounded-md border border-line-control bg-sunken pl-7 pr-2",
              "text-xs text-ink placeholder:text-ink-4",
              "transition-colors duration-[var(--duration-instant)]",
              "hover:border-line-strong",
            )}
          />
        </label>

        <SegmentedControl
          label="Risk"
          options={RISK_FILTER_OPTIONS}
          value={filters.risk}
          onChange={(value) => set("risk", value as RiskFilter)}
        />

        <SegmentedControl
          label="Age"
          options={AGE_OPTIONS}
          value={filters.age}
          onChange={(value) => set("age", value)}
        />

        <SegmentedControl
          label="Min liquidity"
          options={LIQUIDITY_OPTIONS}
          value={String(filters.minLiquidity)}
          onChange={(value) => set("minLiquidity", Number(value))}
        />

        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          <input
            type="checkbox"
            checked={filters.freshness === "priced"}
            onChange={(event) => set("freshness", event.target.checked ? "priced" : "all")}
            className="size-3.5 rounded-sm border-line-control bg-sunken accent-[var(--color-accent)]"
          />
          Priced only
        </label>

        {active > 0 ? (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="rounded-sm px-1.5 py-1 text-xs text-ink-3 hover:text-ink"
          >
            Clear {active} filter{active === 1 ? "" : "s"}
          </button>
        ) : null}
      </FilterBar>

      <p className="flex items-center gap-1.5 text-xs text-ink-3">
        <span data-numeric>
          {shown} of {total}
        </span>
        <span>opportunities shown</span>
        <InfoTip
          label="the row count"
          content="Filters and column sorting apply to the opportunities already loaded, not to the whole Radar. Changing the ranking control below re-queries the server."
        />
      </p>
    </div>
  );
}
