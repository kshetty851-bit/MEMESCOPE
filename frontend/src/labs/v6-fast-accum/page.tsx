"use client";

import { Panel, PanelHeader, PanelTitle } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

import { useV6Latest } from "./hooks";
import type { Fold, GateCheck, Metrics, RunResult } from "./types";

/**
 * V6 FAST-ACCUMULATION LAB — RESEARCH ONLY.
 *
 * Does "reaches ~15% of the bonding curve fast, starts above 30 SOL, has a
 * Telegram" beat the uncontrolled launch universe to +100%?
 *
 * This page REPORTS a pre-registered experiment. It applies no threshold of its
 * own — a rule written here would be a second, unpublished rule competing with
 * the one the simulator followed, and the two would disagree the first time
 * either moved.
 *
 * Two things are given the same prominence as the headline result, because a
 * reader who misses either will misread everything else:
 *
 *  - the CENSORING panel, because the collector stops watching tokens for
 *    reasons that correlate with them dying, which biases profit UPWARD;
 *  - the UNAVAILABLE overlay notice, because one of the hypothesis's three
 *    legs is not collected at all.
 */

function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function usd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "good" | "bad" | "warn";
}) {
  const colour =
    tone === "good"
      ? "text-up"
      : tone === "bad"
        ? "text-danger"
        : tone === "warn"
          ? "text-warn"
          : "text-ink";
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-ink-dim">{label}</span>
      <span className={`text-lg font-semibold tabular-nums ${colour}`}>{value}</span>
      {note ? <span className="text-xs text-ink-dim">{note}</span> : null}
    </div>
  );
}

/** The headline. Deliberately unmissable and deliberately plain-spoken. */
function Verdict({ result }: { result: RunResult }) {
  const passed = result.gate.passed;
  return (
    <Panel>
      <div className="flex flex-col gap-3 p-6">
        <span className="text-xs uppercase tracking-widest text-ink-dim">
          Acceptance gate — pre-registered, {result.walk_forward.fold} folds
        </span>
        <span
          className={`text-2xl font-bold ${passed ? "text-up" : "text-danger"}`}
        >
          {passed ? "PASS — EDGE SUPPORTED" : "NO RELIABLE EDGE IDENTIFIED"}
        </span>
        {result.gate.reason === "INSUFFICIENT_HISTORY" ? (
          <p className="max-w-3xl text-sm text-ink-dim">
            Stopped at the data layer, not the edge layer. The archive spans{" "}
            <strong className="text-ink">
              {fmt(result.window.span_hours, 1)} hours
            </strong>
            , and the gate is judged on weekly walk-forward folds. The hypothesis
            has not been tested and has not been refuted.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-dim">
          <span>experiment {result.experiment_id}</span>
          <span>config {result.config_hash}</span>
          <span>dataset {result.dataset_version}</span>
          <span>seed {result.random_seed}</span>
          {result.git_sha ? <span>git {result.git_sha.slice(0, 7)}</span> : null}
        </div>
      </div>
    </Panel>
  );
}

function GateTable({ checks }: { checks: GateCheck[] }) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Acceptance gate</PanelTitle>
      </PanelHeader>
      <div className="divide-y divide-line">
        {checks.map((c) => (
          <div
            key={c.condition}
            className="flex items-start justify-between gap-4 px-4 py-3"
          >
            <div className="flex flex-col">
              <span className="font-mono text-sm text-ink">{c.condition}</span>
              <span className="text-xs text-ink-dim">{c.detail}</span>
            </div>
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
                c.status === "PASS"
                  ? "bg-up/15 text-up"
                  : c.status === "FAIL"
                    ? "bg-danger/15 text-danger"
                    : "bg-warn/15 text-warn"
              }`}
            >
              {c.status}
            </span>
          </div>
        ))}
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        A condition that cannot be evaluated is <strong>NOT_EVALUABLE</strong> and
        counts as a failure. &ldquo;No evidence against&rdquo; is not
        &ldquo;satisfied&rdquo;.
      </p>
    </Panel>
  );
}

const METRIC_ROWS: { key: keyof Metrics; label: string; fmt?: (m: Metrics) => string }[] = [
  { key: "trades", label: "Signals" },
  { key: "censored", label: "Censored" },
  { key: "win_rate", label: "Win rate %", fmt: (m) => fmt(m.win_rate, 1) },
  { key: "profit_factor", label: "Profit factor", fmt: (m) => fmt(m.profit_factor) },
  { key: "expectancy", label: "Expectancy", fmt: (m) => usd(m.expectancy) },
  { key: "cumulative_pnl", label: "Cumulative PnL", fmt: (m) => usd(m.cumulative_pnl) },
  { key: "max_drawdown", label: "Max drawdown", fmt: (m) => usd(m.max_drawdown) },
  { key: "rate_2x", label: "Reached 2x %", fmt: (m) => fmt(m.rate_2x, 1) },
];

function Comparison({
  title,
  note,
  arms,
}: {
  title: string;
  note?: string;
  arms: Record<string, Metrics>;
}) {
  // Entries, not keys-then-index: `noUncheckedIndexedAccess` makes `arms[n]`
  // `Metrics | undefined`, and the narrowing is real — a name list and a map
  // can disagree.
  const entries = Object.entries(arms);
  if (!entries.length) return null;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>{title}</PanelTitle>
      </PanelHeader>
      {note ? <p className="px-4 pt-3 text-xs text-ink-dim">{note}</p> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink-dim">
              <th className="px-4 py-2 font-medium">Metric</th>
              {entries.map(([n]) => (
                <th key={n} className="px-4 py-2 font-medium">
                  {n}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {METRIC_ROWS.map((row) => (
              <tr key={String(row.key)}>
                <td className="px-4 py-2 text-ink-dim">{row.label}</td>
                {entries.map(([n, m]) => (
                  <td key={n} className="px-4 py-2 tabular-nums text-ink">
                    {row.fmt ? row.fmt(m) : String(m[row.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/**
 * The panel that decides how the rest of the page should be read.
 *
 * Eviction takes the least-progressed token when the watch set fills; silence
 * takes one whose reserves stopped moving. Both describe a token that is dying.
 * If the censored trades come disproportionately from those reasons then the
 * resolved sample has had its losers removed, and every profit figure above is
 * biased upward — the false-positive direction.
 */
function Censoring({ result }: { result: RunResult }) {
  const c = result.censoring;
  const share = c.censored_share * 100;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Censoring — why this bias points upward</PanelTitle>
      </PanelHeader>
      <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3">
        <Stat
          label="Censored"
          value={`${fmt(share, 1)}%`}
          note={`${c.censored_total} of ${c.censored_total + c.resolved_total} signals`}
          tone={share > 25 ? "bad" : "warn"}
        />
        <Stat label="Resolved" value={String(c.resolved_total)} note="TP / SL / graduation / full horizon" />
        <Stat label="Never zero-filled" value="by design" note="a censored trade has a null return" />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink-dim">
              <th className="px-4 py-2 font-medium">Why polling stopped</th>
              <th className="px-4 py-2 font-medium">Censored</th>
              <th className="px-4 py-2 font-medium">Resolved</th>
              <th className="px-4 py-2 font-medium">% of censored</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {c.by_reason.map((r) => (
              <tr key={r.reason}>
                <td className="px-4 py-2 font-mono text-xs text-ink">{r.reason}</td>
                <td className="px-4 py-2 tabular-nums">{r.censored}</td>
                <td className="px-4 py-2 tabular-nums">{r.resolved}</td>
                <td className="px-4 py-2 tabular-nums">
                  {fmt(r.censored_pct_of_censored, 1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        <strong className="text-warn">Read this before the numbers above.</strong>{" "}
        <span className="font-mono">evicted</span> drops the least-progressed
        token when the watch set fills;{" "}
        <span className="font-mono">silent</span> drops one whose reserves stopped
        moving. Both remove tokens that stopped accumulating — losers. Censoring
        correlated with the outcome deletes losers and biases profit factor
        upward.
      </p>
    </Panel>
  );
}

function WalkForward({
  folds,
  status,
  label,
  exploratory,
}: {
  folds: Fold[];
  status: string;
  label: string;
  exploratory?: boolean;
}) {
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>
          Walk-forward — {label}
          {exploratory ? " (exploratory, not gating)" : ""}
        </PanelTitle>
      </PanelHeader>
      {status === "INSUFFICIENT_HISTORY" || !folds.length ? (
        <div className="p-4">
          <EmptyState
            title="No out-of-sample period exists"
            body={`The archive is too short to form a train/test pair at ${label} width. This is a fact about the data, not a result about the strategy.`}
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-dim">
                <th className="px-4 py-2 font-medium">Fold</th>
                <th className="px-4 py-2 font-medium">Selected on train</th>
                <th className="px-4 py-2 font-medium">Test trades</th>
                <th className="px-4 py-2 font-medium">PF</th>
                <th className="px-4 py-2 font-medium">Expectancy</th>
                <th className="px-4 py-2 font-medium">PnL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {folds.map((f) => (
                <tr key={f.index}>
                  <td className="px-4 py-2 text-ink-dim">
                    {f.test_start.slice(0, 10)}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">
                    {f.selected_config ?? "—"}
                  </td>
                  <td className="px-4 py-2 tabular-nums">{f.test.trades}</td>
                  <td className="px-4 py-2 tabular-nums">
                    {fmt(f.test.profit_factor)}
                  </td>
                  <td className="px-4 py-2 tabular-nums">
                    {usd(f.test.expectancy)}
                  </td>
                  <td
                    className={`px-4 py-2 tabular-nums ${
                      f.test.cumulative_pnl >= 0 ? "text-up" : "text-danger"
                    }`}
                  >
                    {usd(f.test.cumulative_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {exploratory ? (
        <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
          Shown because an archive too short for weeks still has something to
          report. It cannot turn a fail into a pass: the gate reads the weekly
          folds.
        </p>
      ) : null}
    </Panel>
  );
}

function Unavailable({ result }: { result: RunResult }) {
  const entries = Object.entries(result.unavailable_overlays);
  if (!entries.length) return null;
  return (
    <Panel>
      <PanelHeader>
        <PanelTitle>Unavailable overlays</PanelTitle>
      </PanelHeader>
      <div className="divide-y divide-line">
        {entries.map(([name, why]) => (
          <div key={name} className="flex flex-col gap-1 px-4 py-3">
            <span className="font-mono text-sm text-warn">{name} — UNAVAILABLE</span>
            <span className="text-xs text-ink-dim">{why}</span>
          </div>
        ))}
      </div>
      <p className="border-t border-line px-4 py-3 text-xs text-ink-dim">
        With the Telegram overlay missing the control design partly collapses:
        the base rule already runs without Telegram, so{" "}
        <strong className="text-ink">base is CONTROL-B</strong>, and{" "}
        <strong className="text-ink">CONTROL-C is CONTROL-D</strong>. Reported
        rather than presented as four independent arms.
      </p>
    </Panel>
  );
}

export function V6FastAccumLabPage() {
  const { data, isLoading, isError, refetch } = useV6Latest();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6">
        <ErrorState
          title="Could not load the research run"
          body="The lab&rsquo;s read-only API did not answer."
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!data?.has_run || !data.result) {
    return (
      <div className="p-6">
        <EmptyState
          title="The experiment has not been run"
          body="No run row exists yet. This is different from a run that found nothing — the lab is started by an operator command, not by loading this page."
        />
      </div>
    );
  }

  const r = data.result;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-ink">
            V6 Fast-Accumulation Lab
          </h1>
          <span className="rounded bg-warn/15 px-2 py-0.5 text-xs font-semibold text-warn">
            RESEARCH ONLY
          </span>
        </div>
        <p className="max-w-3xl text-sm text-ink-dim">
          Does a token that reaches the curve threshold fast, starts above 30 SOL
          and carries a Telegram link reach +100% more often than the
          uncontrolled launch universe? No wallet, no execution path, no
          production strategy — this reads the graduation lab&rsquo;s tables and
          simulates.
        </p>
      </header>

      <Verdict result={r} />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat
          label="Archive span"
          value={`${fmt(r.window.span_hours, 1)} h`}
          note={`${r.window.tokens.toLocaleString()} tokens`}
          tone={r.window.span_hours < 24 * 14 ? "warn" : undefined}
        />
        <Stat
          label="OOS trades"
          value={String(r.oos.trades - r.oos.censored)}
          note={`gate wants ≥ 100`}
        />
        <Stat
          label="Leakage audit"
          value={r.leakage.passed ? "PASS" : "FAIL"}
          tone={r.leakage.passed ? "good" : "bad"}
          note="feature timestamps only"
        />
        <Stat
          label="Pruned tokens"
          value={r.data_quality.tokens_pruned.toLocaleString()}
          note="curve series deleted at 24h"
          tone={r.data_quality.tokens_pruned > 0 ? "warn" : undefined}
        />
      </div>

      <Censoring result={r} />
      <GateTable checks={r.gate.checks} />
      <Comparison title="Pre-registered candidates" arms={r.strategies} />
      <Comparison
        title="Controls"
        note="Each control differs from the base in exactly one respect, which is what makes incremental attribution possible."
        arms={r.controls}
      />
      <WalkForward
        folds={r.walk_forward.folds}
        status={r.walk_forward.status}
        label={r.walk_forward.fold}
      />
      <WalkForward
        folds={r.walk_forward_secondary.folds}
        status={r.walk_forward_secondary.status}
        label={r.walk_forward_secondary.fold}
        exploratory
      />
      <Unavailable result={r} />
    </div>
  );
}
