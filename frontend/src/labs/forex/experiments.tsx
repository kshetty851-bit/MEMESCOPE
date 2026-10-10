"use client";

import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/skeleton";

import { dec, pct, signedDec, utc } from "./format";
import { Section } from "./generic";
import { useRuns } from "./hooks";
import { StatusBadge } from "./run-status";
import type { RunOut } from "./types";

/** Saved experiments: every run the lab has stored. Click one to open it. */
export function Experiments({ onOpen }: { onOpen: (run: RunOut) => void }) {
  const runs = useRuns();

  const columns: Column<RunOut>[] = [
    { key: "id", header: "#", cell: (r) => <span data-numeric>{r.id}</span> },
    { key: "kind", header: "Kind", cell: (r) => r.kind },
    {
      key: "name",
      header: "Name",
      // A real button: the row click is a convenience, this is the focusable control.
      cell: (r) => (
        <button
          type="button"
          className="text-left text-accent underline-offset-2 hover:underline"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(r);
          }}
        >
          {r.name ?? `Run ${r.id}`}
        </button>
      ),
    },
    {
      key: "created",
      header: "Created",
      cell: (r) => <span data-numeric>{utc(r.created_at)}</span>,
    },
    { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
    {
      key: "summary",
      header: "Summary",
      cell: (r) =>
        r.summary ? (
          <span data-numeric className="text-xs text-ink-2">
            {pct(r.summary.net_return_pct, { signed: true })} ·{" "}
            {r.summary.total_trades ?? "—"} trades · exp {signedDec(r.summary.expectancy_r)}
            R · DD {pct(r.summary.max_drawdown_pct)} · PF {dec(r.summary.profit_factor)}
          </span>
        ) : (
          <span className="text-ink-3">—</span>
        ),
    },
  ];

  if (runs.isLoading) return <Skeleton className="h-48 w-full" />;
  if (runs.isError || !runs.data) {
    return (
      <ErrorState
        title="Could not load saved experiments"
        body="The runs endpoint did not answer."
        onRetry={() => void runs.refetch()}
      />
    );
  }
  if (runs.data.runs.length === 0) {
    return (
      <EmptyState
        title="No experiments yet"
        body="Runs you start appear here and stay, failed ones included."
      />
    );
  }

  return (
    <Section
      title="Saved experiments"
      hint="Newest first. Select a row to open it."
      testId="experiments"
    >
      <DataTable
        caption="Saved runs"
        columns={columns}
        rows={runs.data.runs}
        getRowId={(r) => String(r.id)}
        onRowClick={onOpen}
        stickyHeader={false}
        minWidth="800px"
      />
    </Section>
  );
}
