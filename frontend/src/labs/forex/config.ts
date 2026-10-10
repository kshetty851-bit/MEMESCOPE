import type {
  ConfigJson,
  DirectionMode,
  FieldSpec,
  MetaOut,
  RunIn,
  RunOptions,
  SessionJson,
  StrategyMeta,
} from "./types";

/**
 * THE CONFIG FORM, as pure functions.
 *
 * The form holds every value as a string (or a boolean), keyed by its dotted
 * path in the config (`risk.initial_capital`). `buildConfig` turns that back
 * into the exact `BacktestConfig` JSON the API records.
 *
 * Two rules decide the type of each value, and they matter more than they look:
 *
 *  - Money-like fields (`initial_capital`, commission, swap, risk percent,
 *    daily loss percent, margin close-out) go out as decimal STRINGS. Sending
 *    them as JSON numbers would round-trip through a float, which is exactly
 *    what the "money is NUMERIC, never float" rule exists to stop.
 *  - A field is a string on the wire if the server's default for it is a string,
 *    even when the field spec calls it a float. The default is the contract.
 */

export type FormValues = Record<string, string | boolean>;

export interface FormState {
  strategyId: string;
  values: FormValues;
  /** `YYYY-MM-DD`, UTC. */
  start: string;
  end: string;
  name: string;
  notes: string;
}

export const MAX_LEVERAGE = 20;

/** Fields every form needs, added when `/meta` does not list them. */
const CORE_FIELDS: FieldSpec[] = [
  { path: "symbol", label: "Instrument", kind: "enum", help: "" },
  { path: "timeframe", label: "Timeframe", kind: "enum", help: "" },
  {
    path: "direction",
    label: "Direction",
    kind: "enum",
    options: ["both", "long_only", "short_only"] satisfies DirectionMode[],
    help: "",
  },
  {
    path: "risk.risk_per_trade_pct",
    label: "Risk per trade (%)",
    kind: "decimal",
    help: "",
  },
];

export function getPath(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (typeof cur !== "object" || cur === null) return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function setPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split(".");
  let cur = obj;
  for (const part of parts.slice(0, -1)) {
    const next = cur[part];
    if (typeof next !== "object" || next === null) cur[part] = {};
    cur = cur[part] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]!] = value;
}

/** Shared fields first (core ones guaranteed), then the strategy's own. */
export function fieldsFor(meta: MetaOut, strategy: StrategyMeta): FieldSpec[] {
  const shared = [...meta.shared_fields];
  for (const core of CORE_FIELDS) {
    if (!shared.some((f) => f.path === core.path)) shared.unshift(core);
  }
  const seen = new Set<string>();
  return [...shared, ...strategy.param_fields].filter((f) => {
    if (seen.has(f.path)) return false;
    seen.add(f.path);
    return true;
  });
}

export function sessionToString(s: SessionJson | null | undefined): string {
  if (!s) return "";
  const hh = (n: number) => String(n).padStart(2, "0");
  return `${hh(s.start_hour)}:${hh(s.start_minute)}-${hh(s.end_hour)}:${hh(s.end_minute)}`;
}

export function parseSession(text: string): SessionJson | null {
  const m = /^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!m) return null;
  return {
    start_hour: Number(m[1]),
    start_minute: Number(m[2]),
    end_hour: Number(m[3]),
    end_minute: Number(m[4]),
  };
}

function toFormValue(field: FieldSpec, raw: unknown): string | boolean {
  if (field.kind === "bool") return Boolean(raw);
  if (field.kind === "session") return sessionToString(raw as SessionJson | null);
  return raw === null || raw === undefined ? "" : String(raw);
}

export function valuesFromConfig(config: ConfigJson, fields: FieldSpec[]): FormValues {
  const values: FormValues = {};
  for (const field of fields)
    values[field.path] = toFormValue(field, getPath(config, field.path));
  return values;
}

export function initialValues(meta: MetaOut, strategy: StrategyMeta): FormValues {
  return valuesFromConfig(strategy.default_config, fieldsFor(meta, strategy));
}

/** Rebuild the config JSON from the form: the strategy's defaults, overlaid. */
export function buildConfig(
  strategy: StrategyMeta,
  fields: FieldSpec[],
  values: FormValues,
): ConfigJson {
  const config = JSON.parse(JSON.stringify(strategy.default_config)) as ConfigJson;
  config.strategy = strategy.id;

  for (const field of fields) {
    const raw = values[field.path];
    if (raw === undefined) continue;
    const base = getPath(strategy.default_config, field.path);
    let out: unknown;

    if (field.kind === "bool") out = Boolean(raw);
    else if (field.kind === "session") out = parseSession(String(raw));
    else if (field.kind === "enum") out = String(raw);
    else {
      const text = String(raw).trim();
      const numeric = Number(text);
      const wantsString = field.kind === "decimal" || typeof base === "string";
      if (wantsString) out = text;
      else if (field.kind === "int" || field.path === "risk.max_leverage")
        out = text !== "" && Number.isFinite(numeric) ? Math.trunc(numeric) : text;
      else out = text !== "" && Number.isFinite(numeric) ? numeric : text;
    }
    setPath(config as unknown as Record<string, unknown>, field.path, out);
  }
  return config;
}

function bound(value: number | string | undefined, fallback?: number): number | undefined {
  if (value === undefined || value === "") return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/** Per-path error text. Empty means the form can run. */
export function validate(fields: FieldSpec[], values: FormValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const raw = values[field.path];
    if (field.kind === "bool" || raw === undefined) continue;
    const text = String(raw).trim();

    if (field.kind === "session") {
      if (text !== "" && !parseSession(text)) errors[field.path] = "Use HH:MM-HH:MM.";
      continue;
    }
    if (field.kind === "enum") {
      if (text === "") errors[field.path] = "Required.";
      continue;
    }
    if (text === "" || !Number.isFinite(Number(text))) {
      errors[field.path] = "Enter a number.";
      continue;
    }
    const n = Number(text);
    const min = bound(field.min);
    const max = bound(
      field.max,
      field.path === "risk.max_leverage" ? MAX_LEVERAGE : undefined,
    );
    if (field.path === "risk.max_leverage" && n > MAX_LEVERAGE) {
      errors[field.path] = `At most ${MAX_LEVERAGE}.`;
    } else if (min !== undefined && n < min) errors[field.path] = `At least ${min}.`;
    else if (max !== undefined && n > max) errors[field.path] = `At most ${max}.`;
    else if (field.kind === "int" && !Number.isInteger(n))
      errors[field.path] = "Whole numbers only.";
  }
  return errors;
}

export function windowToIso(start: string, end: string): { start: string; end: string } {
  return { start: `${start}T00:00:00Z`, end: `${end}T23:59:59Z` };
}

export function dateError(start: string, end: string): string | null {
  if (!start || !end) return "Choose a start and end date.";
  if (start > end) return "The start date must not be after the end date.";
  return null;
}

export function buildRunBody(
  kind: "backtest" | "research",
  config: ConfigJson,
  form: Pick<FormState, "start" | "end" | "name">,
  options?: RunOptions,
  versionId?: number | null,
): RunIn {
  const body: RunIn = { kind, config, ...windowToIso(form.start, form.end) };
  if (form.name.trim()) body.name = form.name.trim();
  if (versionId) body.strategy_version_id = versionId;
  if (kind === "research" && options) body.options = options;
  return body;
}

/** Research options: the contract's defaults, with the strategy's own grid. */
export function researchOptions(strategy: StrategyMeta): RunOptions {
  return {
    dev_pct: 60,
    val_pct: 20,
    grid: strategy.default_grid,
    walk_forward: { train_days: 90, test_days: 30 },
    mc_iterations: 1000,
    stress_multipliers: [1, 1.5, 2, 3],
  };
}
