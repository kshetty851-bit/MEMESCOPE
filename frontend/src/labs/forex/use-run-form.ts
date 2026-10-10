"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  buildConfig,
  fieldsFor,
  initialValues,
  validate,
  valuesFromConfig,
  type FormState,
  type FormValues,
} from "./config";
import type { ConfigJson, DatasetOut, MetaOut, StrategyMeta } from "./types";

const isoDay = (iso: string) => iso.slice(0, 10);

/**
 * The configure form's state, owned by the page so it survives tab switches.
 * Created once `/meta` arrives; until then `form` is null.
 */
export function useRunForm(meta: MetaOut | undefined, datasets: DatasetOut[] | undefined) {
  const [form, setForm] = useState<FormState | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);

  useEffect(() => {
    if (!meta || form || meta.strategies.length === 0) return;
    const strategy = meta.strategies[0]!;
    setForm({
      strategyId: strategy.id,
      values: initialValues(meta, strategy),
      start: "",
      end: "",
      name: "",
      notes: "",
    });
  }, [meta, form]);

  const strategy: StrategyMeta | undefined = meta?.strategies.find(
    (s) => s.id === form?.strategyId,
  );

  // Default the date range to what is stored for the chosen market, once.
  useEffect(() => {
    if (!form || form.start || form.end || !datasets) return;
    const symbol = form.values["symbol"];
    const timeframe = form.values["timeframe"];
    const hit = datasets.find((d) => d.symbol === symbol && d.timeframe === timeframe);
    if (hit) setForm({ ...form, start: isoDay(hit.start), end: isoDay(hit.end) });
  }, [form, datasets]);

  const fields = useMemo(
    () => (meta && strategy ? fieldsFor(meta, strategy) : []),
    [meta, strategy],
  );
  const errors = useMemo(() => (form ? validate(fields, form.values) : {}), [fields, form]);

  const setValue = useCallback((path: string, value: string | boolean) => {
    setForm((f) => (f ? { ...f, values: { ...f.values, [path]: value } } : f));
    setVersionId(null);
  }, []);

  const patch = useCallback(
    (p: Partial<Pick<FormState, "start" | "end" | "name" | "notes">>) => {
      setForm((f) => (f ? { ...f, ...p } : f));
    },
    [],
  );

  const setStrategy = useCallback(
    (id: string) => {
      if (!meta) return;
      const next = meta.strategies.find((s) => s.id === id);
      if (!next) return;
      setForm((f) => {
        if (!f) return f;
        // Keep what the reader set for the market, risk and costs; the new
        // strategy brings its own parameters and its own timeframe.
        const fresh = initialValues(meta, next);
        const kept: FormValues = { ...fresh };
        for (const shared of meta.shared_fields) {
          if (shared.path !== "timeframe" && f.values[shared.path] !== undefined) {
            kept[shared.path] = f.values[shared.path]!;
          }
        }
        return { ...f, strategyId: id, values: kept };
      });
      setVersionId(null);
    },
    [meta],
  );

  const reset = useCallback(() => {
    if (!meta || !strategy) return;
    setForm((f) => (f ? { ...f, values: initialValues(meta, strategy) } : f));
    setVersionId(null);
  }, [meta, strategy]);

  const load = useCallback(
    (config: ConfigJson, id: number | null) => {
      if (!meta) return;
      const next = meta.strategies.find((s) => s.id === config.strategy);
      if (!next) return;
      setForm((f) =>
        f
          ? {
              ...f,
              strategyId: next.id,
              values: valuesFromConfig(config, fieldsFor(meta, next)),
            }
          : f,
      );
      setVersionId(id);
    },
    [meta],
  );

  const config = useMemo(
    () => (strategy && form ? buildConfig(strategy, fields, form.values) : null),
    [strategy, fields, form],
  );

  return {
    form,
    strategy,
    fields,
    errors,
    config,
    versionId,
    setValue,
    patch,
    setStrategy,
    reset,
    load,
  };
}

export type RunForm = ReturnType<typeof useRunForm>;
