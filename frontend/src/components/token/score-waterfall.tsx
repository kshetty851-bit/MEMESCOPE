"use client";

import { useMemo } from "react";

import { DataTable, type Column } from "@/components/ui/data-table";
import { Num } from "@/components/ui/num";
import { InfoTip } from "@/components/ui/tooltip";
import { num } from "@/lib/design/bands";
import { cn } from "@/lib/utils";
import type { ScoreComponent, TokenScore } from "@/types/score";

/**
 * HOW THE SCORE WAS BUILT.
 *
 * This replaces the "Mission Report", which staged the same numbers as seven
 * named characters speaking in turn, each with a coloured sigil and its own
 * hue. The data underneath was real — component scores, declared and effective
 * weights, contributions, and which signals have no source yet — but it was
 * dressed as a cast list, which is the single loudest piece of theatre left
 * inside the product.
 *
 * The arithmetic is the artifact. A reader who wants to check a score wants to
 * see which signals moved it and by how much, in a column they can compare down
 * — so it is a table, aligned on the decimal.
 *
 * **Unavailable signals are rows, not omissions.** A component the model
 * declares but cannot evaluate keeps its declared weight and says it has no
 * source. Dropping those rows would quietly turn a 65%-complete model into one
 * that looks finished, and would make the coverage figure beside it
 * unexplainable.
 *
 * Nothing here recomputes anything. Every figure is read from `/scores/{mint}`.
 */

/** Component ids as readable labels. Presentation only — no logic. */
function labelOf(id: string): string {
  return id
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function pct(value: string | null | undefined): string | null {
  const parsed = num(value);
  if (parsed === null) return null;
  // Weights arrive as a 0–1 fraction.
  return `${(parsed * 100).toFixed(0)}%`;
}

export function ScoreWaterfall({
  score,
  isPending,
  className,
}: {
  score: TokenScore | null;
  isPending: boolean;
  className?: string;
}) {
  /** The first rendered sentence the API published for a component, if any. */
  const reasonFor = useMemo(() => {
    if (!score) return () => null;
    return (component: ScoreComponent): string | null => {
      if (component.reasons.length === 0) return null;
      const rendered = score.reasons.find((reason) =>
        component.reasons.includes(reason.code),
      );
      return rendered?.message ?? null;
    };
  }, [score]);

  const columns = useMemo<Column<ScoreComponent>[]>(
    () => [
      {
        key: "signal",
        header: "Signal",
        width: "40%",
        cell: (row) => (
          <div className="flex min-w-0 flex-col">
            <span
              className={cn(
                "truncate text-sm",
                row.available ? "text-ink" : "text-ink-3",
              )}
            >
              {labelOf(row.id)}
            </span>
            {/* The backend's own sentence, displayed verbatim. */}
            {reasonFor(row) ? (
              <span className="truncate text-xs text-ink-3">{reasonFor(row)}</span>
            ) : !row.available ? (
              <span className="text-xs text-ink-4">No data source yet</span>
            ) : null}
          </div>
        ),
      },
      {
        key: "score",
        header: "Score",
        align: "right",
        width: "72px",
        cell: (row) =>
          row.available ? (
            <Num
              value={row.score}
              format={(v) => Math.round(Number(v)).toString()}
              className="text-sm"
            />
          ) : (
            // Not zero. A signal with no source did not score zero.
            <Num value={null} absentLabel="not evaluated" />
          ),
      },
      {
        key: "declared",
        header: "Declared",
        align: "right",
        width: "80px",
        // Dropped on narrow screens. Measured at 375px the four numeric columns
        // consumed the whole panel and left the Signal column at zero width;
        // Applied and Points are the two that carry the argument, so Declared
        // is the one that goes.
        headerClassName: "hidden md:table-cell",
        cellClassName: "hidden md:table-cell",
        cell: (row) => (
          <Num value={row.declared_weight} display={pct(row.declared_weight)} tone="muted" className="text-xs" />
        ),
      },
      {
        key: "effective",
        header: "Applied",
        align: "right",
        width: "80px",
        cell: (row) => (
          <Num
            value={row.effective_weight}
            display={pct(row.effective_weight)}
            tone={row.available ? "flat" : "muted"}
            className="text-xs"
          />
        ),
      },
      {
        key: "contribution",
        header: "Points",
        align: "right",
        width: "80px",
        cell: (row) =>
          row.available ? (
            <Num
              value={row.contribution}
              format={(v) => Number(v).toFixed(2)}
              className="text-sm font-medium"
            />
          ) : (
            <Num value={null} absentLabel="no contribution" />
          ),
      },
    ],
    [reasonFor],
  );

  const components = score?.components ?? [];

  return (
    <section className={cn("flex flex-col gap-2.5", className)}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-1.5 text-sm font-medium tracking-tight text-ink">
          How the score was built
          <InfoTip
            label="the score breakdown"
            content="Declared is the signal's weight in the published model. Applied is the weight it actually carried for this token — a signal with no data cannot contribute, and the difference is what the coverage figure measures."
          />
        </h2>
        {score ? (
          <p className="flex items-baseline gap-3 text-xs text-ink-3">
            <span>
              Model <span data-numeric>{score.model_version}</span>
            </span>
            <span>
              Composite{" "}
              <Num
                value={score.opportunity_raw}
                format={(v) => Number(v).toFixed(1)}
                tone="flat"
              />
            </span>
            {num(score.risk.deduction) ? (
              <span>
                Risk deduction{" "}
                <Num
                  value={score.risk.deduction}
                  format={(v) => `−${Number(v).toFixed(1)}`}
                  tone="down"
                />
              </span>
            ) : null}
          </p>
        ) : null}
      </header>

      <DataTable
        columns={columns}
        rows={components}
        getRowId={(row) => row.id}
        caption="Score components, their weights and what each contributed"
        density="compact"
        stickyHeader={false}
        minWidth="420px"
        isPending={isPending}
        pendingRows={6}
        empty={
          <p className="px-3 py-8 text-center text-sm text-ink-3">
            No component breakdown has been published for this token.
          </p>
        }
      />
    </section>
  );
}
