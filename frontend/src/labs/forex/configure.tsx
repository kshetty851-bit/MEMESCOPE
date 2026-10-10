"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { buildRunBody, dateError, researchOptions, sessionToString } from "./config";
import { Checkbox, Select, humanOption } from "./controls";
import { Section } from "./generic";
import { useCreateRun, useCreateVersion, useVersions } from "./hooks";
import { ErrorLine } from "./run-status";
import type { RunForm } from "./use-run-form";
import type { FieldSpec, MetaOut, RunOut } from "./types";

const GROUPS: Array<{ id: string; title: string; match: (path: string) => boolean }> = [
  {
    id: "market",
    title: "Market and direction",
    match: (p) => ["symbol", "timeframe", "direction", "session_filter"].includes(p),
  },
  { id: "risk", title: "Risk", match: (p) => p.startsWith("risk.") },
  { id: "costs", title: "Costs", match: (p) => p.startsWith("costs.") },
  { id: "params", title: "Strategy parameters", match: (p) => p.startsWith("params.") },
];

function SessionInput({
  field,
  value,
  error,
  onChange,
}: {
  field: FieldSpec;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  // "07:00-10:00" in the form; two time inputs for the reader. Blank is allowed
  // for the optional session filter and means "any time".
  const [from = "", to = ""] = value.split("-");
  const set = (a: string, b: string) => onChange(a || b ? `${a}-${b}` : "");
  return (
    <fieldset className="flex flex-col gap-2" data-testid={`field-${field.path}`}>
      <legend className="text-label font-medium uppercase text-ink-3">{field.label}</legend>
      <div className="flex items-center gap-2">
        <input
          type="time"
          aria-label={`${field.label} start (UTC)`}
          value={from}
          onChange={(e) => set(e.target.value, to)}
          className="h-9 rounded-md border border-line-control bg-sunken px-2 text-sm"
        />
        <span className="text-ink-3">to</span>
        <input
          type="time"
          aria-label={`${field.label} end (UTC)`}
          value={to}
          onChange={(e) => set(from, e.target.value)}
          className="h-9 rounded-md border border-line-control bg-sunken px-2 text-sm"
        />
        <span className="text-xs text-ink-3">UTC</span>
      </div>
      {error ? (
        <p className="text-xs text-down">{error}</p>
      ) : field.help ? (
        <p className="text-xs text-ink-3">{field.help}</p>
      ) : null}
    </fieldset>
  );
}

function FieldControl({
  field,
  meta,
  value,
  error,
  onChange,
}: {
  field: FieldSpec;
  meta: MetaOut;
  value: string | boolean;
  error?: string;
  onChange: (v: string | boolean) => void;
}) {
  const hint = field.help || undefined;
  const text = String(value);

  if (field.kind === "bool") {
    return (
      <Checkbox
        name={field.path}
        label={field.label}
        hint={hint}
        checked={Boolean(value)}
        onChange={onChange}
      />
    );
  }
  if (field.kind === "session") {
    return (
      <SessionInput
        field={field}
        value={text || sessionToString(null)}
        error={error}
        onChange={onChange}
      />
    );
  }

  let options: string[] | null = null;
  if (field.path === "symbol") {
    options = meta.instruments.filter((i) => i.enabled).map((i) => i.symbol);
  } else if (field.path === "timeframe") options = meta.timeframes;
  else if (field.path === "risk.risk_per_trade_pct") options = meta.risk_options_pct;
  else if (field.kind === "enum") options = field.options ?? [];

  if (options) {
    const list = options.includes(text) || text === "" ? options : [...options, text];
    return (
      <Select
        name={field.path}
        label={field.label}
        hint={hint}
        error={error}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        options={list.map((o) => ({
          value: o,
          label: field.path === "risk.risk_per_trade_pct" ? `${o}%` : humanOption(o),
        }))}
      />
    );
  }

  const isLeverage = field.path === "risk.max_leverage";
  return (
    <Input
      name={field.path}
      label={field.label}
      type="number"
      inputMode="decimal"
      value={text}
      min={field.min ?? (isLeverage ? 1 : undefined)}
      max={field.max ?? (isLeverage ? 20 : undefined)}
      step={field.step ?? (field.kind === "int" ? 1 : "any")}
      hint={hint}
      error={error}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** Configure and run. Research and paper only: there is no order to place. */
export function Configure({
  meta,
  form: f,
  onStarted,
}: {
  meta: MetaOut;
  form: RunForm;
  onStarted: (run: RunOut) => void;
}) {
  const create = useCreateRun();
  const saveVersion = useCreateVersion();
  const versions = useVersions();
  const [notice, setNotice] = useState<string | null>(null);

  const { form, strategy, fields, errors, config } = f;
  if (!form || !strategy || !config) return null;

  const dateProblem = dateError(form.start, form.end);
  const blocked = Object.keys(errors).length > 0 || dateProblem !== null;

  function run(kind: "backtest" | "research") {
    if (!config || !form || !strategy) return;
    setNotice(null);
    create.mutate(
      buildRunBody(
        kind,
        config,
        form,
        kind === "research" ? researchOptions(strategy) : undefined,
        f.versionId,
      ),
      { onSuccess: onStarted },
    );
  }

  function save() {
    if (!config || !form) return;
    setNotice(null);
    saveVersion.mutate(
      {
        name: form.name.trim(),
        config,
        ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
      },
      { onSuccess: (v) => setNotice(`Saved ${v.name} version ${v.version}.`) },
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="configure">
      <Section title="Strategy" testId="strategy-section">
        <div className="grid gap-4 md:grid-cols-2">
          <Select
            name="strategy"
            label="Strategy"
            value={form.strategyId}
            onChange={(e) => f.setStrategy(e.target.value)}
            options={meta.strategies.map((s) => ({ value: s.id, label: s.name }))}
            hint={strategy.description}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              name="start"
              label="Start date (UTC)"
              type="date"
              value={form.start}
              onChange={(e) => f.patch({ start: e.target.value })}
            />
            <Input
              name="end"
              label="End date (UTC)"
              type="date"
              value={form.end}
              onChange={(e) => f.patch({ end: e.target.value })}
            />
          </div>
        </div>
        {dateProblem ? <p className="mt-2 text-xs text-ink-3">{dateProblem}</p> : null}
      </Section>

      {GROUPS.map((group) => {
        const list = fields.filter((fl) => group.match(fl.path));
        if (list.length === 0) return null;
        return (
          <Section title={group.title} testId={`group-${group.id}`} key={group.id}>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {list.map((field) => (
                <FieldControl
                  key={field.path}
                  field={field}
                  meta={meta}
                  value={form.values[field.path] ?? ""}
                  error={errors[field.path]}
                  onChange={(v) => f.setValue(field.path, v)}
                />
              ))}
            </div>
          </Section>
        );
      })}

      <Section
        title="Run"
        hint="Replays stored candles through the strategy. Nothing is sent to any broker."
        testId="run-section"
      >
        <div className="flex flex-wrap items-end gap-3">
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={blocked}
            onClick={() => run("backtest")}
          >
            Run backtest
          </Button>
          <Button
            variant="outline"
            loading={create.isPending}
            disabled={blocked}
            onClick={() => run("research")}
          >
            Run research (OOS + walk-forward)
          </Button>
          <Button variant="ghost" onClick={f.reset}>
            Reset to defaults
          </Button>
        </div>
        <div className="mt-3">
          <ErrorLine error={create.error} action="run backtests" />
        </div>
      </Section>

      <Section
        title="Strategy versions"
        hint="A saved version is immutable; saving again under the same name makes the next version."
        testId="versions-section"
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-3">
            <Input
              name="version-name"
              label="Name"
              value={form.name}
              onChange={(e) => f.patch({ name: e.target.value })}
            />
            <Input
              name="version-notes"
              label="Notes"
              value={form.notes}
              onChange={(e) => f.patch({ notes: e.target.value })}
            />
            <div>
              <Button
                disabled={!form.name.trim() || blocked}
                loading={saveVersion.isPending}
                onClick={save}
              >
                Save as version
              </Button>
            </div>
            <ErrorLine error={saveVersion.error} action="save a version" />
            {notice ? (
              <p className="text-sm text-ink-2" data-testid="version-notice">
                {notice}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2" data-testid="saved-versions">
            <span className="text-label font-medium uppercase text-ink-3">
              Saved versions
            </span>
            {(versions.data?.versions ?? []).length === 0 ? (
              <p className="text-sm text-ink-3">No saved versions yet.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {versions.data!.versions.map((v) => (
                  <li
                    key={v.id}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span>
                      {v.name}{" "}
                      <span className="text-ink-3">
                        v{v.version} · {v.strategy}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => f.load(v.config, v.id)}
                      aria-label={`Load ${v.name} version ${v.version}`}
                    >
                      Load
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Section>
    </div>
  );
}
