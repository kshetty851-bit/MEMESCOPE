"use client";

import { Label } from "@/components/ui/panel";
import {
  PRIORITY_LABEL,
  PRIORITY_ORDER,
  PRIORITY_TONE,
  STAGE_LABEL,
  STAGE_TONE,
  signalLabel,
  type BoardFilters,
  type SortKey,
} from "@/lib/opportunities";
import { cn } from "@/lib/utils";
import type { OpportunityStage, PriorityBand } from "@/types/opportunity";

/**
 * Search, filters and sorting for the board.
 *
 * Signal chips are built from the signals actually present rather than from the
 * full enum. A filter that can only ever return nothing would imply the
 * platform is looking for something it is not — the same reason the Radar
 * disables categories its model cannot award.
 */

const STAGES: OpportunityStage[] = [
  "fresh_graduation",
  "near_graduation",
  "pre_graduation",
  "established",
];

const SORTS: { id: SortKey; label: string }[] = [
  { id: "priority", label: "Priority" },
  { id: "confidence", label: "Confidence" },
  { id: "newest", label: "Newest" },
];

const CONFIDENCE_STEPS = [0, 25, 50, 75];

export function BoardFilterBar({
  filters,
  onChange,
  sort,
  onSortChange,
  availableSignals,
}: {
  filters: BoardFilters;
  onChange: (next: BoardFilters) => void;
  sort: SortKey;
  onSortChange: (next: SortKey) => void;
  availableSignals: string[];
}) {
  const set = <K extends keyof BoardFilters>(key: K, value: BoardFilters[K]) =>
    onChange({ ...filters, [key]: value });

  const togglePriority = (band: PriorityBand) =>
    set(
      "priorities",
      filters.priorities.includes(band)
        ? filters.priorities.filter((item) => item !== band)
        : [...filters.priorities, band],
    );

  return (
    <div className="flex flex-col gap-3">
      <div>
        <label htmlFor="board-search" className="sr-only">
          Search by token, symbol or mint address
        </label>
        <input
          id="board-search"
          type="search"
          value={filters.search}
          onChange={(event) => set("search", event.target.value)}
          placeholder="Search token, symbol or mint…"
          className={cn(
            "h-10 w-full max-w-md rounded-card border border-line bg-abyss/70 px-3.5 text-sm text-ink",
            "transition-colors duration-150 ease-[var(--ease-precise)]",
            "placeholder:text-ink-faint/60 hover:border-line-bright focus:border-plasma focus:outline-none",
          )}
        />
      </div>

      <FilterGroup label="Stage">
        <Chip active={filters.stage === null} onClick={() => set("stage", null)} label="Any" />
        {STAGES.map((stage) => (
          <Chip
            key={stage}
            active={filters.stage === stage}
            onClick={() => set("stage", filters.stage === stage ? null : stage)}
            label={STAGE_LABEL[stage]}
            tone={STAGE_TONE[stage]}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Signal">
        <Chip
          active={filters.signalType === null}
          onClick={() => set("signalType", null)}
          label="Any"
        />
        {availableSignals.map((signal) => (
          <Chip
            key={signal}
            active={filters.signalType === signal}
            onClick={() =>
              set("signalType", filters.signalType === signal ? null : signal)
            }
            label={signalLabel(signal)}
          />
        ))}
        {availableSignals.length === 0 && (
          <span className="text-xs text-ink-faint">No signals on the board yet</span>
        )}
      </FilterGroup>

      <FilterGroup label="Minimum confidence">
        {CONFIDENCE_STEPS.map((step) => (
          <Chip
            key={step}
            active={filters.minConfidence === step}
            onClick={() => set("minConfidence", step)}
            label={step === 0 ? "Any" : `${step}+`}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Priority">
        {[...PRIORITY_ORDER].reverse().map((band) => (
          <Chip
            key={band}
            active={filters.priorities.includes(band)}
            onClick={() => togglePriority(band)}
            label={PRIORITY_LABEL[band]}
            tone={PRIORITY_TONE[band]}
          />
        ))}
      </FilterGroup>

      <FilterGroup label="Sort">
        {SORTS.map((option) => (
          <Chip
            key={option.id}
            active={sort === option.id}
            onClick={() => onSortChange(option.id)}
            label={option.label}
          />
        ))}
      </FilterGroup>
    </div>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      <Label className="mr-1 w-28 shrink-0">{label}</Label>
      {children}
    </div>
  );
}

/**
 * Deliberately the same chip the Radar uses. Two visually identical controls
 * with different focus rings or hover states is the kind of drift that makes an
 * interface feel assembled rather than machined.
 */
function Chip({
  active,
  onClick,
  label,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  tone?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-chip border px-2.5 py-1 text-xs transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-plasma",
        active && "border-plasma/40 bg-plasma/12 text-plasma",
        !active && "border-line text-ink-faint hover:border-line-bright hover:text-ink-dim",
      )}
      style={
        active && tone
          ? {
              color: tone,
              borderColor: `color-mix(in oklch, ${tone} 40%, transparent)`,
              background: `color-mix(in oklch, ${tone} 12%, transparent)`,
            }
          : undefined
      }
    >
      {label}
    </button>
  );
}
