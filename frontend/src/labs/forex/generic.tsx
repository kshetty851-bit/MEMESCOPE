"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Num } from "@/components/ui/num";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

import {
  DASH,
  count,
  dec,
  humanize,
  isCoded,
  pct,
  signTone,
  toNumber,
  usd,
  utcDate,
} from "./format";
import type { Coded, Loose } from "./types";

/**
 * GENERIC RENDERERS for the parts of a result whose sub-shape the contract
 * leaves open (grid rows, folds, Monte Carlo, regimes, the baseline...).
 *
 * The alternative was to invent field names and render a blank page the day
 * the backend spelled one differently. These render whatever arrives, label
 * keys from the key itself, and take every sentence from the API (`{code,text}`
 * is shown as its text). Nothing here computes a figure.
 */

const ISO = /^\d{4}-\d{2}-\d{2}T/;
const NUMERIC = /^-?\d+(\.\d+)?$/;
const MONEY_KEY = /(pnl|profit|loss|balance|equity|usd|commission|cost|financing|capital)/i;
const SIGNED_KEY = /(return|pnl|net|expectancy|profit|delta|diff|excess)/i;

export function isPlainObject(value: unknown): value is Loose {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One scalar, formatted by what its key says it is. */
export function fmtScalar(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return DASH;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (/_pct$|pct$|rate|probability/i.test(key)) return pct(value);
    if (Number.isInteger(value)) return count(value);
    return dec(value, Math.abs(value) < 1 ? 3 : 2);
  }
  if (typeof value === "string") {
    if (ISO.test(value)) return utcDate(value);
    if (NUMERIC.test(value) && MONEY_KEY.test(key)) return usd(value);
    return value;
  }
  return String(value);
}

function toneClass(key: string, value: unknown): string {
  if (!SIGNED_KEY.test(key)) return "";
  const tone = signTone(value as string | number | null);
  return tone === "up" ? "text-up" : tone === "down" ? "text-down" : "";
}

/** One level of nested objects becomes dotted columns; arrays become text. */
function flatten(row: Loose): Loose {
  const out: Loose = {};
  for (const [key, value] of Object.entries(row)) {
    if (isPlainObject(value) && !isCoded(value)) {
      for (const [inner, innerValue] of Object.entries(value)) {
        out[`${key}.${inner}`] = innerValue;
      }
    } else {
      out[key] = value;
    }
  }
  return out;
}

export function Scalar({ name, value }: { name: string; value: unknown }) {
  if (isCoded(value)) return <span>{value.text}</span>;
  if (Array.isArray(value)) {
    return <span>{value.map((v) => (isCoded(v) ? v.text : fmtScalar(name, v))).join(", ")}</span>;
  }
  if (isPlainObject(value)) return <span>{JSON.stringify(value)}</span>;
  if (value === null || value === undefined || value === "") {
    return <Num value={null} />;
  }
  return (
    <span data-numeric className={cn("tabular-nums", toneClass(name, value))}>
      {fmtScalar(name, value)}
    </span>
  );
}

/** A table whose columns are the union of the rows' keys. */
export function RecordTable({
  rows,
  caption,
  maxColumns = 14,
  empty,
}: {
  rows: Loose[] | null | undefined;
  caption: string;
  maxColumns?: number;
  empty?: string;
}) {
  const flat = (rows ?? []).filter(isPlainObject).map(flatten);
  const keys: string[] = [];
  for (const row of flat) {
    for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key);
  }
  const columns: Column<Loose>[] = keys.slice(0, maxColumns).map((key) => {
    const numeric = flat.some((row) => typeof row[key] === "number");
    return {
      key,
      header: humanize(key),
      align: numeric ? ("right" as const) : ("left" as const),
      cell: (row) => <Scalar name={key} value={row[key]} />,
    };
  });

  return (
    <DataTable
      caption={caption}
      columns={columns}
      rows={flat}
      getRowId={(row) => String(flat.indexOf(row))}
      stickyHeader={false}
      density="compact"
      minWidth={columns.length > 6 ? `${columns.length * 96}px` : undefined}
      empty={
        <p className="px-3 py-6 text-center text-sm text-ink-3">{empty ?? "Nothing to show."}</p>
      }
    />
  );
}

/** Any JSON: scalars inline, objects as a definition list, arrays as a table. */
export function GenericValue({
  value,
  name = "",
  depth = 0,
}: {
  value: unknown;
  name?: string;
  depth?: number;
}): ReactNode {
  if (isCoded(value)) return <span>{value.text}</span>;
  if (Array.isArray(value)) {
    if (value.length > 0 && value.every(isPlainObject)) {
      return <RecordTable rows={value as Loose[]} caption={humanize(name || "rows")} />;
    }
    return <Scalar name={name} value={value} />;
  }
  if (isPlainObject(value)) {
    if (depth >= 4) return <Scalar name={name} value={value} />;
    return <KeyValues data={value} depth={depth + 1} />;
  }
  return <Scalar name={name} value={value} />;
}

export function KeyValues({ data, depth = 0 }: { data: Loose; depth?: number }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="text-sm text-ink-3">{DASH}</p>;
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 xl:grid-cols-3">
      {entries.map(([key, value]) => {
        const block =
          Array.isArray(value) && value.length > 0 && value.every(isPlainObject)
            ? true
            : isPlainObject(value) && !isCoded(value);
        return (
          <div
            key={key}
            className={cn("flex min-w-0 flex-col gap-0.5", block && "sm:col-span-2 xl:col-span-3")}
          >
            <dt className="text-label font-medium uppercase text-ink-3">{humanize(key)}</dt>
            <dd className="min-w-0 break-words text-ink">
              <GenericValue value={value} name={key} depth={depth} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** A titled panel. */
export function Section({
  title,
  hint,
  children,
  testId,
  className,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <Panel data-testid={testId} className={className}>
      <PanelHeader>
        <div className="flex flex-col gap-1">
          <PanelTitle>{title}</PanelTitle>
          {hint ? <p className="max-w-[75ch] text-xs text-ink-3">{hint}</p> : null}
        </div>
      </PanelHeader>
      {children}
    </Panel>
  );
}

/** Server-rendered sentences, as a plain list. */
export function CodedList({
  items,
  empty,
  testId,
}: {
  items: Coded[] | null | undefined;
  empty?: string;
  testId?: string;
}) {
  if (!items || items.length === 0) {
    return empty ? <p className="text-sm text-ink-3">{empty}</p> : null;
  }
  return (
    <ul className="flex flex-col gap-1.5 text-sm text-ink-2" data-testid={testId}>
      {items.map((item, i) => (
        <li key={`${item.code}-${i}`} className="flex gap-2">
          <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-3" />
          <span>{item.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Flags are the API's words; a flag is a caution, never a verdict of its own. */
export function FlagBadges({ flags }: { flags: Coded[] | null | undefined }) {
  if (!flags || flags.length === 0) {
    return <span className="text-xs text-ink-3">No flags</span>;
  }
  return (
    <span className="flex flex-wrap gap-1" data-testid="flags">
      {flags.map((flag) => (
        <Badge key={flag.code} tone="warn" className="whitespace-normal">
          {flag.text}
        </Badge>
      ))}
    </span>
  );
}

export { toNumber };
