"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Stat } from "@/components/ui/stat";
import { ApiError } from "@/lib/api-client";

import { EquityCurve } from "./charts";
import { whenDate } from "./format";
import { MetricsStats, SideTable, TradesTable } from "./metrics";
import { useRunBacktest } from "./hooks";
import type {
  BacktestIn,
  BacktestOut,
  ConfigOut,
  FieldBounds,
  StrategyConfigOut,
} from "./types";
import { defaultWindow, validateField, validateWindow, windowToIso } from "./validate";

type Values = Record<string, string | boolean>;
type Key = keyof StrategyConfigOut;

const GROUPS: Array<{ id: FieldBounds["group"]; title: string }> = [
  { id: "range", title: "Range detection" },
  { id: "entries", title: "Entries and exits" },
  { id: "account", title: "Account and costs" },
];

function initialValues(config: ConfigOut): Values {
  const values: Values = {};
  for (const key of Object.keys(config.bounds) as Key[]) {
    const raw = config.defaults[key];
    values[key] = typeof raw === "boolean" ? raw : String(raw);
  }
  return values;
}

/** Ints become numbers, decimals stay strings, bools stay bools. */
function toConfigBody(config: ConfigOut, values: Values): Partial<StrategyConfigOut> {
  const body: Record<string, number | string | boolean> = {};
  for (const [key, bounds] of Object.entries(config.bounds) as Array<[Key, FieldBounds]>) {
    const raw = values[key];
    if (bounds.kind === "bool") body[key] = Boolean(raw);
    else if (bounds.kind === "int") body[key] = Number.parseInt(String(raw).trim(), 10);
    else body[key] = String(raw).trim();
  }
  return body as Partial<StrategyConfigOut>;
}

function formatConfigValue(bounds: FieldBounds, value: unknown): string {
  if (bounds.kind === "bool") return value ? "Yes" : "No";
  return String(value);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "The backtest request failed.";
}

/** Tab 2. A form built from the server's own bounds, so a new tunable needs no client change. */
export function StrategyLab({ config }: { config: ConfigOut }) {
  const fields = useMemo(
    () => Object.entries(config.bounds) as Array<[Key, FieldBounds]>,
    [config.bounds],
  );
  const [values, setValues] = useState<Values>(() => initialValues(config));
  const [window_, setWindow] = useState(() =>
    defaultWindow(config.data_first_at, config.data_last_at),
  );
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [attempted, setAttempted] = useState(false);
  const backtest = useRunBacktest();

  const fieldErrors = useMemo(() => {
    const out: Partial<Record<Key, string>> = {};
    for (const [key, bounds] of fields) {
      const message = validateField(bounds, values[key]);
      if (message) out[key] = message;
    }
    return out;
  }, [fields, values]);
  const windowErrors = validateWindow(
    window_.start,
    window_.end,
    config.data_first_at,
    config.data_last_at,
  );
  const invalid =
    Object.keys(fieldErrors).length > 0 || Boolean(windowErrors.start || windowErrors.end);

  const show = (key: string) => attempted || touched.has(key);
  const touch = (key: string) => setTouched((prev) => new Set(prev).add(key));

  function reset() {
    setValues(initialValues(config));
    setWindow(defaultWindow(config.data_first_at, config.data_last_at));
    setTouched(new Set());
    setAttempted(false);
    backtest.reset();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setAttempted(true);
    if (invalid) return;
    const body: BacktestIn = {
      config: toConfigBody(config, values),
      ...windowToIso(window_.start, window_.end, config.data_first_at, config.data_last_at),
    };
    backtest.mutate(body);
  }

  const first = config.data_first_at?.slice(0, 10);
  const last = config.data_last_at?.slice(0, 10);

  return (
    <div className="flex flex-col gap-4">
      <form
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
        aria-label="Backtest settings"
      >
        {GROUPS.map((group) => {
          const groupFields = fields.filter(([, b]) => b.group === group.id);
          if (groupFields.length === 0) return null;
          return (
            <Panel key={group.id} density="compact" data-testid={`group-${group.id}`}>
              <PanelHeader className="mb-3">
                <PanelTitle>{group.title}</PanelTitle>
              </PanelHeader>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {groupFields.map(([key, bounds]) => {
                  const error = show(key) ? fieldErrors[key] : undefined;
                  if (bounds.kind === "bool") {
                    return (
                      <label key={key} className="flex items-start gap-2.5 text-sm">
                        <input
                          type="checkbox"
                          name={key}
                          className="mt-0.5 size-4 accent-[var(--color-accent)]"
                          checked={Boolean(values[key])}
                          onChange={(e) =>
                            setValues((v) => ({ ...v, [key]: e.target.checked }))
                          }
                        />
                        <span className="flex flex-col gap-0.5">
                          <span className="text-label font-medium uppercase text-ink-3">
                            {bounds.label}
                          </span>
                          <span className="text-xs text-ink-3">{bounds.help}</span>
                        </span>
                      </label>
                    );
                  }
                  return (
                    <Input
                      key={key}
                      name={key}
                      type="number"
                      inputMode={bounds.kind === "int" ? "numeric" : "decimal"}
                      label={bounds.label}
                      hint={`${bounds.help} (${bounds.min} to ${bounds.max})`}
                      min={bounds.min}
                      max={bounds.max}
                      step={bounds.step}
                      value={String(values[key] ?? "")}
                      error={error}
                      onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                      onBlur={() => touch(key)}
                    />
                  );
                })}
              </div>
            </Panel>
          );
        })}

        <Panel density="compact" data-testid="group-window">
          <PanelHeader className="mb-3">
            <PanelTitle>Window</PanelTitle>
            <span className="text-xs text-ink-3">
              {first && last
                ? `Stored candles: ${first} to ${last} (UTC days)`
                : "No stored candles yet"}
            </span>
          </PanelHeader>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Input
              name="start"
              type="date"
              label="Start date"
              min={first}
              max={last}
              value={window_.start}
              error={show("start") ? (windowErrors.start ?? undefined) : undefined}
              onChange={(e) => setWindow((w) => ({ ...w, start: e.target.value }))}
              onBlur={() => touch("start")}
            />
            <Input
              name="end"
              type="date"
              label="End date"
              min={first}
              max={last}
              value={window_.end}
              error={show("end") ? (windowErrors.end ?? undefined) : undefined}
              onChange={(e) => setWindow((w) => ({ ...w, end: e.target.value }))}
              onBlur={() => touch("end")}
            />
          </div>
        </Panel>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" loading={backtest.isPending}>
            Run backtest
          </Button>
          <Button
            type="button"
            variant="surface"
            onClick={reset}
            disabled={backtest.isPending}
          >
            Reset to defaults
          </Button>
          {attempted && invalid ? (
            <p role="alert" className="text-sm text-down">
              Fix the highlighted fields before running.
            </p>
          ) : null}
        </div>
      </form>

      {backtest.isError ? (
        <div
          role="alert"
          className="rounded-md border border-down/40 bg-down/10 p-3 text-sm text-down"
        >
          The backtest could not run: {errorMessage(backtest.error)}
        </div>
      ) : null}

      {backtest.data ? (
        <BacktestResults result={backtest.data} bounds={config.bounds} />
      ) : null}
    </div>
  );
}

/** What a backtest returned. `available: false` is the server saying why, verbatim. */
export function BacktestResults({
  result,
  bounds,
}: {
  result: BacktestOut;
  bounds: ConfigOut["bounds"];
}) {
  if (!result.available) {
    return (
      <Panel density="compact" data-testid="backtest-unavailable">
        <PanelHeader className="mb-2">
          <PanelTitle>Backtest unavailable</PanelTitle>
        </PanelHeader>
        <p className="text-sm text-ink-2">
          {result.reason ?? "The server gave no reason."}
        </p>
      </Panel>
    );
  }

  const fields = Object.entries(bounds) as Array<[Key, FieldBounds]>;

  return (
    <div className="flex flex-col gap-4" data-testid="backtest-results">
      <Panel density="compact">
        <PanelHeader className="mb-3">
          <PanelTitle>Backtest result</PanelTitle>
          <span className="text-xs text-ink-3">
            {whenDate(result.start)} to {whenDate(result.end)} · {result.candles} candles
          </span>
        </PanelHeader>
        <MetricsStats metrics={result.metrics} />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel density="compact">
          <PanelHeader className="mb-3">
            <PanelTitle>LONG vs SHORT</PanelTitle>
          </PanelHeader>
          <SideTable long={result.long} short={result.short} />
        </Panel>
        <Panel density="compact">
          <PanelHeader className="mb-3">
            <PanelTitle>Equity</PanelTitle>
          </PanelHeader>
          <EquityCurve points={result.equity_curve} />
        </Panel>
      </div>

      <Panel density="compact" data-testid="signal-counts">
        <PanelHeader className="mb-3">
          <PanelTitle>Calls made</PanelTitle>
        </PanelHeader>
        <div className="grid grid-cols-3 gap-3">
          <Stat
            boxed
            label="LONG"
            display={String(result.signal_counts.long)}
            value={result.signal_counts.long}
          />
          <Stat
            boxed
            label="SHORT"
            display={String(result.signal_counts.short)}
            value={result.signal_counts.short}
          />
          <Stat
            boxed
            label="WAIT"
            display={String(result.signal_counts.wait)}
            value={result.signal_counts.wait}
          />
        </div>
        {result.wait_reasons.length > 0 ? (
          <div
            className="mt-4 overflow-x-auto rounded-md border border-line"
            data-testid="wait-reasons"
          >
            <table className="w-full text-sm tabular-nums">
              <caption className="sr-only">Reasons for WAIT calls, with counts</caption>
              <thead>
                <tr className="bg-sunken text-label uppercase text-ink-3">
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    Reason for WAIT
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Count
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.wait_reasons.map((reason) => (
                  <tr key={reason.code} className="border-t border-line-subtle bg-surface">
                    <td className="px-3 py-1.5 text-ink-2">{reason.text}</td>
                    <td className="px-3 py-1.5 text-right">{reason.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>

      <Panel density="compact">
        <PanelHeader className="mb-3">
          <PanelTitle>Trades</PanelTitle>
          <span className="text-xs text-ink-3">oldest first · Dubai time</span>
        </PanelHeader>
        <TradesTable trades={result.trades} caption="Backtest trades, oldest first" />
      </Panel>

      <Panel density="compact" data-testid="config-run">
        <PanelHeader className="mb-3">
          <PanelTitle>Config that was run</PanelTitle>
        </PanelHeader>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3 lg:grid-cols-4">
          {fields.map(([key, b]) => (
            <div key={key} className="flex min-w-0 flex-col gap-0.5">
              <dt className="truncate text-label uppercase text-ink-3">{b.label}</dt>
              <dd data-numeric data-key={key}>
                {formatConfigValue(b, result.config[key])}
              </dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}
