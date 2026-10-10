"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";

import { Select } from "./controls";
import { count, pct, utc, utcDate } from "./format";
import { CodedList, Section } from "./generic";
import { useForexData, useImportCsv, useQuality, useRun, useStartFetch } from "./hooks";
import { ErrorLine, RunStatus } from "./run-status";
import type {
  CsvFormat,
  DatasetOut,
  ImportBatch,
  MetaOut,
  ProviderOut,
  QualityGap,
  QualityReport,
} from "./types";

/** Reads a chosen file in the browser; the server only ever sees its text. */
export function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("The file could not be read."));
    reader.readAsText(file);
  });
}

const gradeTone = (g: string) => (g <= "B" ? "safe" : g <= "C" ? "warn" : "danger");

function QualityView({ q }: { q: QualityReport }) {
  const gapColumns: Column<QualityGap>[] = [
    { key: "start", header: "From", cell: (g) => <span data-numeric>{utc(g.start)}</span> },
    { key: "end", header: "To", cell: (g) => <span data-numeric>{utc(g.end)}</span> },
    {
      key: "missing",
      header: "Missing bars",
      align: "right",
      cell: (g) => <span data-numeric>{count(g.missing_bars)}</span>,
    },
    { key: "kind", header: "Kind", cell: (g) => g.kind },
  ];
  return (
    <div className="flex flex-col gap-4" data-testid="quality-view">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <span className="flex items-center gap-2">
          Grade <Badge tone={gradeTone(q.grade)}>{q.grade}</Badge>
        </span>
        <span>
          Coverage <span data-numeric>{pct(q.coverage_pct)}</span>
        </span>
        <span>
          Bars <span data-numeric>{count(q.bars)}</span> of{" "}
          <span data-numeric>{count(q.expected_bars)}</span> expected
        </span>
        <span>
          {q.derived_from === "stored"
            ? "Stored candles"
            : `Derived: ${q.derived_from.replace(/_/g, " ")}`}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-ink-3 sm:grid-cols-4 xl:grid-cols-8">
        {(
          [
            ["Duplicates", q.duplicates],
            ["Misaligned", q.misaligned],
            ["Non-UTC", q.non_utc],
            ["OHLC violations", q.ohlc_violations],
            ["Out of order", q.out_of_order],
            ["Missing bars", q.missing_bars],
            ["Gaps", q.gap_count],
            ["Largest gap (bars)", q.largest_gap_bars],
          ] as const
        ).map(([label, v]) => (
          <span key={label}>
            {label}{" "}
            <span data-numeric className="text-ink-2">
              {count(v)}
            </span>
          </span>
        ))}
      </div>
      <DataTable
        caption="Gaps in the stored candles"
        columns={gapColumns}
        rows={q.gaps}
        getRowId={(g) => `${g.start}-${g.end}`}
        stickyHeader={false}
        empty={
          <p className="px-3 py-6 text-center text-sm text-ink-3">
            No gaps in this window.
          </p>
        }
      />
      <CodedList items={q.notes} testId="quality-notes" />
    </div>
  );
}

function ImportResult({ batch }: { batch: ImportBatch }) {
  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="import-result">
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <span>
          Accepted{" "}
          <span data-numeric data-testid="rows-accepted">
            {count(batch.rows_accepted)}
          </span>
        </span>
        <span>
          Inserted{" "}
          <span data-numeric data-testid="rows-inserted">
            {count(batch.rows_inserted)}
          </span>
        </span>
        <span>
          Already stored{" "}
          <span data-numeric data-testid="rows-existing">
            {count(batch.rows_existing)}
          </span>
        </span>
        <span>
          Errors{" "}
          <span data-numeric data-testid="rows-errors">
            {count(batch.error_count)}
          </span>
        </span>
        <span className="text-ink-3">Format {batch.detected_format}</span>
      </div>
      <p className="text-xs text-ink-3">
        Stored candles are never overwritten; rows already present are counted, not
        replaced.
      </p>
      {batch.errors.length > 0 ? (
        <ul
          className="flex max-h-40 flex-col gap-1 overflow-auto text-xs text-down"
          data-testid="import-errors"
        >
          {batch.errors.map((e) => (
            <li key={`${e.line}-${e.message}`}>
              Line {e.line}: {e.message}
            </li>
          ))}
        </ul>
      ) : null}
      <CodedList items={batch.notes} />
    </div>
  );
}

function ImportForm({ meta }: { meta?: MetaOut }) {
  const instruments = meta?.instruments.filter((i) => i.enabled).map((i) => i.symbol) ?? [
    "EURUSD",
  ];
  const timeframes = meta?.timeframes ?? ["1m", "5m", "15m", "1h"];
  const [file, setFile] = useState<File | null>(null);
  const [symbol, setSymbol] = useState(instruments[0] ?? "EURUSD");
  const [timeframe, setTimeframe] = useState("5m");
  const [fmt, setFmt] = useState<CsvFormat>("auto");
  const [offset, setOffset] = useState("0");
  const [readError, setReadError] = useState<string | null>(null);
  const importCsv = useImportCsv();

  async function submit() {
    if (!file) return;
    setReadError(null);
    try {
      const content = await readFileAsText(file);
      importCsv.mutate({
        symbol,
        timeframe,
        fmt,
        utc_offset_minutes: Number.parseInt(offset, 10) || 0,
        filename: file.name,
        content,
      });
    } catch (error) {
      setReadError(error instanceof Error ? error.message : "The file could not be read.");
    }
  }

  return (
    <Section
      title="Import candles from CSV"
      hint="The file is read in your browser and sent as text. Candles already stored are kept as they are."
      testId="import-form"
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="flex flex-col gap-2">
          <label htmlFor="csv-file" className="text-label font-medium uppercase text-ink-3">
            CSV file
          </label>
          <input
            id="csv-file"
            type="file"
            accept=".csv,text/csv,text/plain"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
        </div>
        <Select
          label="Symbol"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          options={instruments.map((s) => ({ value: s, label: s }))}
        />
        <Select
          label="Timeframe"
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          options={timeframes.map((s) => ({ value: s, label: s }))}
        />
        <Select
          label="Format"
          value={fmt}
          onChange={(e) => setFmt(e.target.value as CsvFormat)}
          options={[
            { value: "auto", label: "Detect" },
            { value: "generic", label: "Generic" },
            { value: "histdata", label: "HistData" },
            { value: "metatrader", label: "MetaTrader" },
          ]}
        />
        <Input
          label="UTC offset (minutes)"
          type="number"
          value={offset}
          onChange={(e) => setOffset(e.target.value)}
          hint="Of the timestamps in the file."
        />
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <div>
          <Button
            variant="primary"
            disabled={!file}
            loading={importCsv.isPending}
            onClick={() => void submit()}
          >
            Import
          </Button>
        </div>
        {readError ? (
          <p role="alert" className="text-sm text-down">
            {readError}
          </p>
        ) : null}
        <ErrorLine error={importCsv.error} action="import data" />
        {importCsv.data ? <ImportResult batch={importCsv.data} /> : null}
      </div>
    </Section>
  );
}

function FetchForm({ meta }: { meta?: MetaOut }) {
  const instruments = meta?.instruments.filter((i) => i.enabled).map((i) => i.symbol) ?? [
    "EURUSD",
  ];
  const [symbol, setSymbol] = useState(instruments[0] ?? "EURUSD");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const startFetch = useStartFetch();
  const runId = startFetch.data?.id ?? null;
  const run = useRun(runId);

  return (
    <Section
      title="Fetch from Dukascopy"
      hint="Free, no key. Days already fetched are skipped. At most 366 days per request."
      testId="fetch-form"
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Select
          label="Symbol"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          options={instruments.map((s) => ({ value: s, label: s }))}
        />
        <Input
          label="Start date"
          name="fetch-start"
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
        />
        <Input
          label="End date"
          name="fetch-end"
          type="date"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
        />
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <div>
          <Button
            variant="primary"
            disabled={!start || !end || start > end}
            loading={startFetch.isPending}
            onClick={() =>
              startFetch.mutate({
                provider: "dukascopy",
                symbol,
                start_date: start,
                end_date: end,
              })
            }
          >
            Fetch
          </Button>
        </div>
        <ErrorLine error={startFetch.error} action="fetch data" />
        {run.data ? (
          <>
            <RunStatus run={run.data.run} />
            {run.data.run.status === "done" ? (
              <p className="text-sm text-ink-2" data-testid="fetch-done">
                {run.data.run.message ?? "Fetch finished."}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </Section>
  );
}

function Providers({ providers }: { providers: ProviderOut[] }) {
  return (
    <Section title="Data providers" testId="providers">
      <ul className="flex flex-col gap-2 text-sm">
        {providers.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{p.name}</span>
            <Badge tone={p.free ? "safe" : "neutral"}>{p.free ? "free" : "paid"}</Badge>
            <Badge>{p.needs_key ? "key needed" : "no key"}</Badge>
            <span className="text-ink-3">{p.notes}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function DataPanel({ meta }: { meta?: MetaOut }) {
  const data = useForexData();
  const [picked, setPicked] = useState<{ symbol: string; timeframe: string } | null>(null);
  const active =
    picked ??
    (data.data?.datasets[0]
      ? { symbol: data.data.datasets[0].symbol, timeframe: data.data.datasets[0].timeframe }
      : null);
  const quality = useQuality(active?.symbol ?? null, active?.timeframe ?? null);

  const columns: Column<DatasetOut>[] = [
    {
      key: "symbol",
      header: "Symbol",
      cell: (d) => <span className="font-medium">{d.symbol}</span>,
    },
    { key: "tf", header: "Timeframe", cell: (d) => d.timeframe },
    {
      key: "bars",
      header: "Bars",
      align: "right",
      cell: (d) => <span data-numeric>{count(d.bars)}</span>,
    },
    {
      key: "range",
      header: "Range",
      cell: (d) => (
        <span data-numeric>
          {utcDate(d.start)} to {utcDate(d.end)}
        </span>
      ),
    },
    { key: "sources", header: "Sources", cell: (d) => d.sources.join(", ") || "—" },
    {
      key: "view",
      header: "Quality",
      cell: (d) => (
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={(e) => {
            e.stopPropagation();
            setPicked({ symbol: d.symbol, timeframe: d.timeframe });
          }}
          aria-label={`Show data quality for ${d.symbol} ${d.timeframe}`}
        >
          View
        </button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4" data-testid="data-panel">
      <Section title="Stored datasets" testId="datasets">
        {data.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : data.isError || !data.data ? (
          <ErrorState
            title="Could not load the datasets"
            body="The data endpoint did not answer."
            onRetry={() => void data.refetch()}
          />
        ) : (
          <>
            <DataTable
              caption="Stored datasets"
              columns={columns}
              rows={data.data.datasets}
              getRowId={(d) => `${d.symbol}-${d.timeframe}`}
              isRowActive={(d) =>
                d.symbol === active?.symbol && d.timeframe === active?.timeframe
              }
              stickyHeader={false}
              empty={
                <p className="px-3 py-8 text-center text-sm text-ink-3">
                  No candles stored. Import a CSV or fetch from Dukascopy below.
                </p>
              }
            />
            {data.data.fetch ? (
              <p className="mt-3 text-xs text-ink-3" data-testid="fetch-summary">
                {data.data.fetch.provider}: {data.data.fetch.days_ok} days fetched,{" "}
                {data.data.fetch.days_empty} empty, {data.data.fetch.days_failed} failed (
                {data.data.fetch.first_day ?? "—"} to {data.data.fetch.last_day ?? "—"})
              </p>
            ) : null}
          </>
        )}
      </Section>

      <Section
        title={
          active ? `Data quality: ${active.symbol} ${active.timeframe}` : "Data quality"
        }
        hint="Gaps and anomalies in the stored candles, graded by the API."
        testId="quality-section"
      >
        {!active ? (
          <p className="text-sm text-ink-3">Select a dataset to see its quality.</p>
        ) : quality.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : quality.isError || !quality.data ? (
          <p className="text-sm text-down">The quality report could not be loaded.</p>
        ) : (
          <QualityView q={quality.data} />
        )}
      </Section>

      <div className="grid gap-4 xl:grid-cols-2">
        <ImportForm meta={meta} />
        <FetchForm meta={meta} />
      </div>

      <Providers providers={data.data?.providers ?? meta?.providers ?? []} />

      {data.data && data.data.imports.length > 0 ? (
        <Section title="Recent imports" testId="imports">
          <DataTable
            caption="Recent imports"
            columns={[
              { key: "file", header: "File", cell: (b: ImportBatch) => b.filename },
              {
                key: "market",
                header: "Market",
                cell: (b: ImportBatch) => `${b.symbol} ${b.timeframe}`,
              },
              {
                key: "ins",
                header: "Inserted",
                align: "right",
                cell: (b: ImportBatch) => (
                  <span data-numeric>{count(b.rows_inserted)}</span>
                ),
              },
              {
                key: "ex",
                header: "Existing",
                align: "right",
                cell: (b: ImportBatch) => (
                  <span data-numeric>{count(b.rows_existing)}</span>
                ),
              },
              {
                key: "err",
                header: "Errors",
                align: "right",
                cell: (b: ImportBatch) => <span data-numeric>{count(b.error_count)}</span>,
              },
              {
                key: "at",
                header: "At",
                cell: (b: ImportBatch) => <span data-numeric>{utc(b.created_at)}</span>,
              },
            ]}
            rows={data.data.imports}
            getRowId={(b) => String(b.id)}
            stickyHeader={false}
          />
        </Section>
      ) : null}
    </div>
  );
}
