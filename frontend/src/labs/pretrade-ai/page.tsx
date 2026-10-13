"use client";

import { useMemo, useRef, useState } from "react";
import demo from "./demo-scores.json";
import { decisions, labels, MAX_BYTES, parseScores } from "./data";
import type { Decision, Score } from "./data";

const button =
  "rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 disabled:opacity-50";
const colors: Record<Decision, string> = {
  ACCEPT: "border-emerald-500/25 bg-emerald-500/10 text-emerald-400",
  REVIEW: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  REJECT: "border-rose-500/25 bg-rose-500/10 text-rose-300",
  INSUFFICIENT_DATA: "border-slate-500/25 bg-slate-500/10 text-slate-300",
};
function Badge({ decision }: { decision: Decision }) {
  return (
    <span
      className={`inline-block rounded-md border px-2 py-1 text-xs ${colors[decision]}`}
    >
      {labels[decision]}
    </span>
  );
}
function short(value: string) {
  return value.length > 22 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
}
function timestamp(value: string) {
  return new Date(value).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function PretradeAIPage() {
  const [rows, setRows] = useState<Score[]>([]);
  const [source, setSource] = useState("");
  const [sample, setSample] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Decision | "ALL">("ALL");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Score | null>(null);
  const [limit, setLimit] = useState(50);
  const input = useRef<HTMLInputElement>(null);
  const filtered = useMemo(
    () =>
      rows
        .filter(
          (row) =>
            (filter === "ALL" || row.decision === filter) &&
            `${row.mint} ${row.pool} ${row.opportunity_id}`
              .toLowerCase()
              .includes(search.toLowerCase()),
        )
        .sort((a, b) => b.score - a.score),
    [rows, filter, search],
  );
  function load(records: Score[], name: string, isSample: boolean) {
    setRows(records);
    setSource(name);
    setSample(isSample);
    setError("");
    setSelected(null);
    setFilter("ALL");
    setSearch("");
    setLimit(50);
  }
  async function openFile(file?: File) {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      if (file.size > MAX_BYTES) throw new Error("Choose a file smaller than 5 MB.");
      load(parseScores(await file.text()), file.name, false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open this file.");
    } finally {
      setLoading(false);
      if (input.current) input.current.value = "";
    }
  }
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 pb-12">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-widest text-amber-400">
            Research · Entry selection
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            Pre-trade AI Lab
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-dim">
            Review candidate quality, missing evidence, and creator risk before an entry.
            Every decision here is advisory.
          </p>
        </div>
        <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-400">
          Isolated lab · No execution
        </span>
      </header>

      <section
        className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-5"
        aria-label="Connection status"
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-medium text-ink">Live candidate feed is not connected</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-dim">
              The review interface is ready. Open a score export from the offline lab, or
              explore a synthetic example. Existing strategies and wallets operate
              independently.
            </p>
          </div>
          <span className="text-xs text-amber-300">Forward validation pending</span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className={`${button} border-amber-500/40 bg-amber-500/10`}
            disabled={loading}
            onClick={() => input.current?.click()}
          >
            {loading ? "Opening…" : "Open score export"}
          </button>
          <button
            className={button}
            disabled={loading}
            onClick={() =>
              load(
                parseScores(demo.map((row) => JSON.stringify(row)).join("\n")),
                "Synthetic held-out example",
                true,
              )
            }
          >
            Explore sample
          </button>
          {rows.length > 0 && (
            <button
              className={button}
              disabled={loading}
              onClick={() => load([], "", false)}
            >
              Clear results
            </button>
          )}
          <input
            ref={input}
            type="file"
            accept=".jsonl,.ndjson,application/x-ndjson,text/plain"
            className="sr-only"
            aria-label="Open advisory score export"
            onChange={(event) => void openFile(event.target.files?.[0])}
          />
        </div>
        <p className="mt-3 text-xs text-ink-dim">
          Files stay in your browser. JSONL format · Up to 5 MB · No orders or wallet
          actions.
        </p>
      </section>
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300"
        >
          {error} {rows.length ? "Previous results remain displayed." : ""}
        </p>
      )}
      {rows.length > 0 && (
        <div
          role="status"
          className={`rounded-lg border px-4 py-3 text-sm ${sample ? "border-amber-500/30 bg-amber-500/10 text-amber-200" : "border-line text-ink-dim"}`}
        >
          <strong>
            {sample
              ? "SYNTHETIC SAMPLE — not trading performance."
              : "Imported export — historical snapshot, not a live signal."}
          </strong>
          <span className="ml-2 break-all">
            {source} · {rows.length} candidates
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {decisions.map((decision) => (
          <div key={decision} className="rounded-xl border border-line bg-white/[0.02] p-4">
            <p className="text-xs text-ink-dim">{labels[decision]}</p>
            <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
              {rows.length ? rows.filter((row) => row.decision === decision).length : "—"}
            </p>
            <p className="mt-2 text-xs text-ink-dim">
              {rows.length
                ? sample
                  ? "Sample candidates"
                  : "Imported candidates"
                : "Awaiting score export"}
            </p>
          </div>
        ))}
      </div>

      <section
        className="overflow-hidden rounded-xl border border-line"
        aria-labelledby="candidates-title"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
          <div>
            <h2 id="candidates-title" className="font-medium text-ink">
              Candidate review
            </h2>
            <p className="mt-1 text-xs text-ink-dim">
              Highest score first. A passing score is a research result, not an order.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="Search candidates"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setLimit(50);
              }}
              placeholder="Search mint, pool or ID"
              className="min-w-0 rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink"
            />
            <select
              aria-label="Filter decisions"
              value={filter}
              onChange={(event) => {
                setFilter(event.target.value as Decision | "ALL");
                setLimit(50);
              }}
              className="rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink"
            >
              <option value="ALL">All decisions</option>
              {decisions.map((decision) => (
                <option key={decision} value={decision}>
                  {labels[decision]}
                </option>
              ))}
            </select>
          </div>
        </div>
        {!rows.length ? (
          <div className="px-6 py-16 text-center">
            <p className="text-lg font-medium text-ink">
              Your research starts with evidence
            </p>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-dim">
              Open the lab’s scores.jsonl to inspect its decisions. No candidates or
              performance numbers are shown until you load a dataset.
            </p>
            <button
              className={`${button} mt-5`}
              onClick={() =>
                load(
                  parseScores(demo.map((row) => JSON.stringify(row)).join("\n")),
                  "Synthetic held-out example",
                  true,
                )
              }
            >
              Explore the sample
            </button>
          </div>
        ) : !filtered.length ? (
          <p className="p-10 text-center text-sm text-ink-dim">
            No candidates match these filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-xs text-ink-dim">
                <tr>
                  {[
                    "Candidate / decision time",
                    "Decision",
                    "Score",
                    "Risk",
                    "Evidence",
                    "",
                  ].map((heading, i) => (
                    <th
                      scope="col"
                      key={i}
                      className="whitespace-nowrap px-4 py-3 font-medium"
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, limit).map((row) => (
                  <tr
                    key={row.opportunity_id}
                    className="border-b border-line last:border-0 hover:bg-white/[0.02]"
                  >
                    <td className="px-4 py-4">
                      <p className="font-mono text-xs text-ink" title={row.mint}>
                        {short(row.mint)}
                      </p>
                      <p className="mt-1 whitespace-nowrap text-xs text-ink-dim">
                        {timestamp(row.decision_ts)}
                      </p>
                    </td>
                    <td className="px-4 py-4">
                      <Badge decision={row.decision} />
                    </td>
                    <td className="px-4 py-4 font-medium tabular-nums text-ink">
                      {row.score.toFixed(1)}
                      <span className="text-xs text-ink-dim"> / 100</span>
                    </td>
                    <td className="px-4 py-4 tabular-nums text-ink-dim">
                      {row.creator_funder_risk_score.toFixed(1)}
                    </td>
                    <td className="px-4 py-4 tabular-nums text-ink-dim">
                      {Math.round(row.feature_completeness * 100)}%
                    </td>
                    <td className="px-4 py-4">
                      <button
                        className={button}
                        aria-label={`Review ${row.opportunity_id}`}
                        onClick={() => setSelected(row)}
                      >
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {filtered.length > limit && (
          <div className="p-4">
            <button className={button} onClick={() => setLimit(limit + 50)}>
              Show 50 more ({filtered.length - limit} remaining)
            </button>
          </div>
        )}
      </section>

      {selected && (
        <section
          aria-label="Candidate details"
          className="rounded-xl border border-amber-500/25 bg-amber-500/[0.03] p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-ink-dim">
                Decision explanation
              </p>
              <h2 className="mt-2 break-all font-mono text-sm text-ink">{selected.mint}</h2>
            </div>
            <button className={button} onClick={() => setSelected(null)}>
              Close details
            </button>
          </div>
          <div className="my-4">
            <Badge decision={selected.decision} />
          </div>
          <ul className="space-y-2 text-sm text-ink-dim">
            {selected.reasons.map((reason, index) => (
              <li key={index}>• {reason}</li>
            ))}
          </ul>
          <dl className="mt-5 grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-dim">Model</dt>
              <dd className="mt-1 break-all text-ink">{selected.model_version}</dd>
            </div>
            <div>
              <dt className="text-ink-dim">Model output</dt>
              <dd className="mt-1 text-ink">
                {selected.model_probability === null
                  ? "Rules only"
                  : `${(selected.model_probability * 100).toFixed(1)}% (not a calibrated win rate)`}
              </dd>
            </div>
            <div>
              <dt className="text-ink-dim">Pool</dt>
              <dd className="mt-1 break-all font-mono text-xs text-ink">{selected.pool}</dd>
            </div>
          </dl>
        </section>
      )}
      <section className="grid gap-4 md:grid-cols-3" aria-label="How the lab works">
        {[
          [
            "01",
            "Point-in-time evidence",
            "Features must have been available before the entry decision. Unknown evidence stays missing.",
          ],
          [
            "02",
            "Independent assessment",
            "The offline lab combines candidate quality with liquidity context and dated creator or funder risk.",
          ],
          [
            "03",
            "Review before connection",
            "Training runs offline. Real-data mapping and forward validation are still required before live use.",
          ],
        ].map(([step, title, body]) => (
          <div key={step} className="rounded-xl border border-line p-5">
            <p className="text-xs font-medium text-amber-400">{step}</p>
            <h2 className="mt-3 text-sm font-medium text-ink">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-ink-dim">{body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
