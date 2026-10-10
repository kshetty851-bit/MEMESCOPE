"use client";

import { DataTable, type Column } from "@/components/ui/data-table";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Stat } from "@/components/ui/stat";

import { CodedList, isPlainObject } from "./generic";
import { DASH, count, isCoded, monthLabel, pct, toNumber } from "./format";
import type { Coded, Loose, TargetReport } from "./types";

/**
 * MONTHLY TARGET ANALYSIS. What fraction of the months in a historical window
 * reached 5/10/20/50/100%, beside what a random re-ordering of the same trades
 * would have reached.
 *
 * This is a description of history. The panel says so in the largest type on
 * it, and the strategy is never sized up to reach a target: the position size
 * in every run comes from the risk-per-trade setting alone.
 *
 * The contract fixes the content but not every key, so reads go through
 * `pick`, which takes the first spelling present. Nothing is computed here.
 */

export const FALLBACK_DISCLAIMER =
  "Historical observation, not a forecast. Position size is never increased to reach a target.";

function pick(obj: Loose | null | undefined, ...keys: string[]): unknown {
  if (!obj) return undefined;
  for (const key of keys) if (key in obj && obj[key] !== undefined) return obj[key];
  return undefined;
}

interface TargetRow {
  target: number | null;
  hit: number | null;
  hitRate: number | null;
  simulated: number | null;
}

function readRows(report: Loose): TargetRow[] {
  const raw = pick(report, "rows", "targets", "target_rows", "by_target");
  let list: Loose[] = [];
  if (Array.isArray(raw)) list = raw.filter(isPlainObject);
  else if (isPlainObject(raw)) {
    list = Object.entries(raw).map(([key, value]) =>
      isPlainObject(value) ? { target_pct: Number(key), ...value } : { target_pct: Number(key) },
    );
  }
  return list.map((row) => ({
    target: toNumber(pick(row, "target_pct", "target", "pct") as number | string | null),
    hit: toNumber(pick(row, "months_hit", "hit_months", "hits", "months") as number | string | null),
    hitRate: toNumber(
      pick(row, "hit_rate_pct", "hit_rate", "observed_rate_pct", "observed_rate") as number | string | null,
    ),
    simulated: toNumber(
      pick(row, "simulated_rate_pct", "simulated_rate", "sim_rate_pct", "simulated_hit_rate_pct") as
        | number
        | string
        | null,
    ),
  }));
}

/** A best/worst month arrives as `{month, return_pct}` or as a bare number. */
function monthCell(value: unknown): string {
  if (value === null || value === undefined) return DASH;
  if (isPlainObject(value)) {
    const label = pick(value, "month", "label");
    const ret = pick(value, "return_pct", "pct", "value");
    const body = pct(ret as number | string | null, { signed: true });
    return typeof label === "string" ? `${monthLabel(label)} ${body}` : body;
  }
  return pct(value as number | string, { signed: true });
}

function ruinParts(report: Loose): { value: unknown; assumptions: Coded[] } {
  const raw = pick(report, "risk_of_ruin", "ruin");
  if (isPlainObject(raw)) {
    const assumptions = pick(raw, "assumptions");
    return {
      value: pick(raw, "pct", "probability_pct", "risk_pct", "value", "probability"),
      assumptions: Array.isArray(assumptions)
        ? assumptions.map((a, i) =>
            isCoded(a) ? a : { code: `a${i}`, text: String(a) },
          )
        : [],
    };
  }
  const outer = pick(report, "ruin_assumptions", "risk_of_ruin_assumptions");
  return {
    value: raw,
    assumptions: Array.isArray(outer)
      ? outer.map((a, i) => (isCoded(a) ? a : { code: `a${i}`, text: String(a) }))
      : [],
  };
}

export function TargetPanel({
  title,
  report,
  disclaimer,
  testId,
}: {
  title: string;
  report: TargetReport | null | undefined;
  /** The API's disclaimer (`/meta`), shown ahead of every table. */
  disclaimer?: Coded | null;
  testId?: string;
}) {
  const text = disclaimer?.text || FALLBACK_DISCLAIMER;
  const empty = !report || Object.keys(report).length === 0;
  const rows = empty ? [] : readRows(report);
  const ruin = empty ? null : ruinParts(report);
  const ruinValue = toNumber(ruin?.value as number | string | null | undefined);

  const columns: Column<TargetRow>[] = [
    {
      key: "target",
      header: "Monthly target",
      cell: (row) => <span data-numeric>{row.target === null ? DASH : `${row.target}%`}</span>,
    },
    {
      key: "hit",
      header: "Months hit",
      align: "right",
      cell: (row) => <span data-numeric>{count(row.hit)}</span>,
    },
    {
      key: "rate",
      header: "Hit rate",
      align: "right",
      cell: (row) => <span data-numeric>{pct(row.hitRate)}</span>,
    },
    {
      key: "sim",
      header: "Simulated rate",
      align: "right",
      cell: (row) => <span data-numeric>{pct(row.simulated)}</span>,
    },
  ];

  return (
    <Panel data-testid={testId ?? "target-panel"}>
      <PanelHeader>
        <PanelTitle>{title}</PanelTitle>
      </PanelHeader>

      <p
        role="note"
        data-testid="target-disclaimer"
        className="mb-4 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm font-medium text-warn"
      >
        {text}
      </p>

      {empty ? (
        <p className="text-sm text-ink-3">No target analysis for this window.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <DataTable
            caption={`${title}: months reaching each target`}
            columns={columns}
            rows={rows}
            getRowId={(row) => String(row.target)}
            stickyHeader={false}
          />

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            <Stat boxed size="sm" label="Months" display={count(toNumber(pick(report, "months", "months_total", "total_months") as number | string | null))} />
            <Stat boxed size="sm" label="Profitable months" display={count(toNumber(pick(report, "profitable_months", "months_positive") as number | string | null))} />
            <Stat boxed size="sm" label="Losing months" display={count(toNumber(pick(report, "losing_months", "months_negative") as number | string | null))} />
            <Stat boxed size="sm" label="Best month" display={monthCell(pick(report, "best_month", "best"))} />
            <Stat boxed size="sm" label="Worst month" display={monthCell(pick(report, "worst_month", "worst"))} />
            <Stat boxed size="sm" label="Max drawdown" display={pct(pick(report, "max_drawdown_pct", "max_dd_pct") as number | string | null)} />
          </div>

          <div data-testid="risk-of-ruin" className="flex flex-col gap-2">
            <Stat
              size="sm"
              label="Risk of ruin"
              display={ruinValue === null ? null : pct(ruinValue)}
              hint={ruinValue === null ? "Not estimated for this window." : undefined}
            />
            <CodedList items={ruin?.assumptions} />
          </div>
        </div>
      )}
    </Panel>
  );
}
