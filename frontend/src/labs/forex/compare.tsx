"use client";

import { DataTable, type Column } from "@/components/ui/data-table";

import { DASH, dec, humanize, pct, signedDec, toNumber, utcDate } from "./format";
import { FlagBadges, Section, isPlainObject } from "./generic";
import { RunStatus } from "./run-status";
import type { Loose, RunDetail, Scorecard } from "./types";

/** A value of unpinned shape, in one line: a scalar, its `text`, or a few `key value` pairs. */
// Keys are relabelled "positive": a comparison table never calls a strategy,
// or a month in its summary, "profitable".
export function compact(value: unknown): string {
  if (value === null || value === undefined || value === "") return DASH;
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : dec(value, 2);
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  if (isPlainObject(value)) {
    if (typeof value.text === "string") return value.text;
    return (
      Object.entries(value)
        .filter(([, v]) => v !== null && typeof v !== "object")
        .slice(0, 4)
        .map(
          ([k, v]) =>
            `${humanize(k.replace(/profitable/gi, "positive"))} ${typeof v === "number" && !Number.isInteger(v) ? dec(v, 2) : String(v)}`,
        )
        .join(" · ") || DASH
    );
  }
  return DASH;
}

const field = (obj: Loose | undefined, ...keys: string[]): unknown => {
  for (const key of keys) if (obj && key in obj) return obj[key];
  return undefined;
};
const num = (v: unknown) => toNumber(v as number | string | null | undefined);

/** Ranked scorecards. Ordered by the API's rank; verdict text is the API's. */
export function CompareView({ detail }: { detail: RunDetail }) {
  const { run, result } = detail;
  if (!result || result.type !== "compare") return <RunStatus run={run} />;

  const cards = [...result.scorecards].sort((a, b) => a.rank - b.rank);

  const columns: Column<Scorecard>[] = [
    { key: "rank", header: "Rank", cell: (c) => <span data-numeric>{c.rank}</span> },
    {
      key: "name",
      header: "Strategy",
      cell: (c) => <span className="font-medium">{c.name}</span>,
    },
    {
      key: "score",
      header: "Robustness",
      align: "right",
      cell: (c) => (
        <span data-numeric>
          {c.robustness_score === null ? DASH : dec(c.robustness_score, 0)}
        </span>
      ),
    },
    {
      key: "verdict",
      header: "Verdict",
      cellClassName: "max-w-[28ch] whitespace-normal",
      cell: (c) => <span data-testid="verdict">{c.verdict.text}</span>,
    },
    {
      key: "flags",
      header: "Flags",
      cellClassName: "min-w-[14rem]",
      cell: (c) => <FlagBadges flags={c.flags} />,
    },
    {
      key: "ret",
      header: "Net return",
      align: "right",
      cell: (c) => (
        <span data-numeric>
          {pct(num(field(c.full, "net_return_pct")), { signed: true })}
        </span>
      ),
    },
    {
      key: "monthly",
      header: "Monthly distribution",
      cellClassName: "max-w-[24ch] whitespace-normal text-xs",
      cell: (c) =>
        compact(
          field(c.full, "monthly", "monthly_summary", "months", "monthly_distribution"),
        ),
    },
    {
      key: "dd",
      header: "Max DD",
      align: "right",
      cell: (c) => <span data-numeric>{pct(num(field(c.full, "max_drawdown_pct")))}</span>,
    },
    {
      key: "pf",
      header: "PF",
      align: "right",
      cell: (c) => <span data-numeric>{dec(num(field(c.full, "profit_factor")))}</span>,
    },
    {
      key: "wr",
      header: "Win rate",
      align: "right",
      cell: (c) => <span data-numeric>{pct(num(field(c.full, "win_rate_pct")))}</span>,
    },
    {
      key: "exp",
      header: "Expectancy R",
      align: "right",
      cell: (c) => (
        <span data-numeric>{signedDec(num(field(c.full, "expectancy_r")))}</span>
      ),
    },
    {
      key: "trades",
      header: "Trades",
      align: "right",
      cell: (c) => (
        <span data-numeric>{compact(field(c.full, "total_trades", "trades"))}</span>
      ),
    },
    {
      key: "oos",
      header: "OOS expectancy R",
      align: "right",
      cell: (c) => (
        <span data-numeric>{signedDec(num(field(c.out_of_sample, "expectancy_r")))}</span>
      ),
    },
    {
      key: "stressed",
      header: "Stressed result",
      align: "right",
      cell: (c) => (
        <span data-numeric>
          {pct(num(field(c.stressed, "net_return_pct")), { signed: true })}
        </span>
      ),
    },
    {
      key: "stability",
      header: "Stability",
      cellClassName: "max-w-[20ch] whitespace-normal text-xs",
      cell: (c) =>
        compact(field(c.stability, "score", "stability_score", "summary") ?? c.stability),
    },
  ];

  return (
    <Section
      title="Strategy comparison"
      hint={`Window ${utcDate(result.window.start)} to ${utcDate(result.window.end)}. Ranked by the API; the verdict is its wording.`}
      testId="compare-view"
    >
      <DataTable
        caption="Strategy scorecards ranked by robustness"
        columns={columns}
        rows={cards}
        getRowId={(c) => `${c.strategy}-${c.rank}`}
        stickyHeader={false}
        minWidth="1500px"
        empty={
          <p className="px-3 py-8 text-center text-sm text-ink-3">
            No scorecards in this run.
          </p>
        }
      />
    </Section>
  );
}
