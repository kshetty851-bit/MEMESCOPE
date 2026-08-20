"use client";

import type { HqState, Source } from "@/lib/hq/adapter";
import { SECURED_STRATEGY_ID, STALE_AFTER_MS, fresh } from "@/lib/hq/adapter";
import type { ExecutionPosture, TokenSecuritySummary, VaultState } from "@/lib/hq/pipeline";
import type { PaperWallet } from "@/types/paper";
import { Panel } from "@/components/ui/panel";

/**
 * THE THREE BOARDS: Execution Vault, Mission Board, Performance Lab.
 *
 * All three are pure renderers of `HqState` plus the two sources the office
 * already fetches. None of them reads the network, and none of them computes
 * a verdict the backend did not publish — the same rule the stage and the
 * card stack follow.
 *
 * ── THE RULE THAT MATTERS MOST HERE ─────────────────────────────────────
 *
 * A board is a summary, and a summary is where an honest system most easily
 * starts lying: four true rows and one missing one, averaged into a green
 * headline. So every value here is either a real reading or the string
 * "No data", and no row is ever omitted because it was unavailable — an
 * absent row reads as "nothing to worry about", which is precisely the
 * impression an unmeasured subsystem must not give.
 */

/* ── shared primitives ───────────────────────────────────────────────── */

type Tone = "good" | "warn" | "bad" | "muted" | "info";

function Row({
  label,
  value,
  tone = "muted",
  note,
  source,
}: {
  label: string;
  value: string | null;
  tone?: Tone;
  note?: string;
  source?: string;
}) {
  const unavailable = value === null;
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--color-line)] py-1.5 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-xs text-[var(--color-ink-3,var(--color-ink))]">{label}</span>
        {note ? (
          <span className="text-[10px] leading-tight text-[var(--color-ink-3,var(--color-ink))] opacity-70">
            {note}
          </span>
        ) : null}
      </div>
      <span
        className="shrink-0 text-right font-mono text-xs tabular-nums"
        data-tone={unavailable ? "muted" : tone}
        title={source}
        style={{ color: unavailable ? "var(--color-ink-3, var(--color-ink))" : TONE_COLOR[tone] }}
      >
        {unavailable ? "No data" : value}
      </span>
    </div>
  );
}

const TONE_COLOR: Record<Tone, string> = {
  good: "var(--color-up)",
  warn: "var(--color-warn)",
  bad: "var(--color-down)",
  info: "var(--color-accent)",
  muted: "var(--color-ink-3, var(--color-ink))",
};

function Board({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <Panel>
      <section className="flex flex-col gap-2 p-4" aria-label={title}>
        <header className="flex flex-col gap-0.5">
          <h2 className="text-sm font-semibold text-[var(--color-ink)]">{title}</h2>
          <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
            {subtitle}
          </p>
        </header>
        <div className="flex flex-col">{children}</div>
      </section>
    </Panel>
  );
}

function money(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pct(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function num(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : String(value);
}

/* ── 1. EXECUTION VAULT ──────────────────────────────────────────────── */

/**
 * The vault door, and the only thing in HQ that describes real money.
 *
 * `UNLOCKED` is the state this panel must never show by accident, so the
 * copy for every other state says plainly what cannot happen. There is no
 * control here and there is no code path from this component to anything
 * that could change the posture — the endpoint behind it is a GET with no
 * siblings.
 */
const VAULT_TONE: Record<VaultState, Tone> = {
  HALTED: "bad",
  LOCKED: "good",
  ARMED: "warn",
  UNLOCKED: "bad",
  UNKNOWN: "muted",
};

const VAULT_HEADLINE: Record<VaultState, string> = {
  HALTED: "HALTED",
  LOCKED: "LOCKED",
  ARMED: "ARMED",
  UNLOCKED: "UNLOCKED",
  UNKNOWN: "UNKNOWN",
};

export function ExecutionVault({ source, now }: { source: Source<ExecutionPosture>; now: number }) {
  const posture = fresh(source, STALE_AFTER_MS.executionPosture, now);
  const state: VaultState = posture?.state ?? "UNKNOWN";
  const active = posture?.kill_switches?.filter((row) => row.active) ?? [];

  return (
    <Board
      title="Execution Vault"
      subtitle="Whether real execution is possible. Read-only — HQ has no control that can change this."
    >
      <Row
        label="Vault"
        value={VAULT_HEADLINE[state]}
        tone={VAULT_TONE[state]}
        note={
          posture?.detail ??
          "The posture could not be read, so HQ cannot say whether execution is possible."
        }
        source="real-wallet-safety · execution-posture"
      />
      <Row label="Execution mode" value={posture?.mode ?? null} tone="info" />
      <Row
        label="Execution enabled"
        value={posture ? (posture.execution_enabled ? "Yes" : "No") : null}
        tone={posture?.execution_enabled ? "bad" : "good"}
      />
      <Row
        label="Autotrade"
        value={posture ? (posture.autotrade_enabled ? "Yes" : "No") : null}
        tone={posture?.autotrade_enabled ? "bad" : "good"}
      />
      <Row label="Network" value={posture?.network ?? null} tone="info" />
      <Row
        label="Kill switches active"
        value={num(posture?.active_kill_switches)}
        tone={active.length > 0 ? "bad" : "good"}
        note={active.length > 0 ? active.map((row) => row.kind).join(", ") : undefined}
      />
    </Board>
  );
}

/* ── 2. MISSION BOARD ────────────────────────────────────────────────── */

/**
 * One line per subsystem, taken from the employee whose desk owns it.
 *
 * Reading the employees rather than the raw health payload is deliberate:
 * the adapter has already decided what UNKNOWN means for each source, and a
 * board that re-derived status from the payload would be a second opinion
 * that could disagree with the room it sits under.
 */
const MISSION_ROWS: Array<{ id: keyof HqState["employees"]; label: string }> = [
  { id: "radar", label: "Scanner / discovery" },
  { id: "dex", label: "Market data" },
  { id: "echo", label: "Enrichment queue" },
  { id: "luna", label: "Scoring" },
  { id: "milo", label: "Paper Wallet" },
  { id: "atlas", label: "Security gate" },
  { id: "rex", label: "Paper execution" },
  { id: "byte", label: "Platform / stream" },
  { id: "sage", label: "Track record" },
  { id: "nova", label: "Office roll-up" },
];

const STATE_TONE: Record<string, Tone> = {
  alert: "bad",
  error: "bad",
  offline: "warn",
  busy: "info",
  working: "good",
  reviewing: "info",
  success: "good",
  idle: "muted",
  unknown: "muted",
};

export function MissionBoard({ state }: { state: HqState }) {
  return (
    <Board
      title="Mission Board"
      subtitle="Every subsystem, as its own desk reports it. Unmeasured reads UNKNOWN, never healthy."
    >
      <Row
        label="Office activity"
        value={state.activity}
        tone={state.activity === "HIGH_ALERT" ? "bad" : state.activity === "UNKNOWN" ? "muted" : "info"}
        source="hq · derived"
      />
      {MISSION_ROWS.map(({ id, label }) => {
        const reading = state.employees[id];
        return (
          <Row
            key={id}
            label={label}
            value={reading.state.toUpperCase()}
            tone={STATE_TONE[reading.state] ?? "muted"}
            note={reading.detail}
          />
        );
      })}
    </Board>
  );
}

/* ── 3. PERFORMANCE LAB ──────────────────────────────────────────────── */

/**
 * The Paper Wallet's own figures, and the generation they belong to.
 *
 * Every field here is served by `GET /paper`; nothing is computed in the
 * browser. `equity` is null whenever any holding is unpriced, and this panel
 * propagates that null rather than substituting cost — an equity figure that
 * silently fell back to entry price would understate a loss.
 */
export function PerformanceLab({
  wallet,
  security,
  now,
}: {
  wallet: Source<PaperWallet>;
  security: Source<TokenSecuritySummary>;
  now: number;
}) {
  const paper = fresh(wallet, STALE_AFTER_MS.paper, now);
  const metrics = paper?.metrics ?? null;
  const summary = fresh(security, STALE_AFTER_MS.tokenSecurity, now);

  return (
    <Board
      title="Performance Lab"
      subtitle="Paper Wallet figures as the backend publishes them. Simulated trades only — no real capital."
    >
      <Row
        label="Generation"
        value={paper ? `Gen ${paper.generation}` : null}
        tone="info"
        note={paper?.strategy?.name ?? undefined}
      />
      <Row
        label="Security gate"
        value={
          paper ? (paper.strategy?.id === SECURED_STRATEGY_ID ? "STRICT" : "NOT ENFORCED") : null
        }
        tone={paper?.strategy?.id === SECURED_STRATEGY_ID ? "good" : "warn"}
        note={
          paper?.strategy?.id === SECURED_STRATEGY_ID
            ? "Every new entry requires mint authority, freeze authority, token program, venue and liquidity security to pass."
            : "This generation takes entries without a security precondition."
        }
      />
      <Row label="Wallet enabled" value={paper ? (paper.enabled ? "Yes" : "No") : null}
           tone={paper?.enabled ? "good" : "warn"} />
      <Row label="Equity" value={money(metrics?.equity)} tone="info"
           note={metrics && metrics.unpriced_positions > 0
             ? `${metrics.unpriced_positions} holding(s) unpriced — equity is withheld rather than estimated`
             : undefined} />
      <Row label="Cash" value={money(metrics?.cash)} tone="info" />
      <Row label="Open value" value={money(metrics?.open_value)} tone="info" />
      <Row label="Invested (at cost)" value={money(metrics?.invested_usd)} tone="muted" />
      <Row label="Realised P/L" value={money(metrics?.realised_pnl)}
           tone={Number(metrics?.realised_pnl ?? 0) >= 0 ? "good" : "bad"} />
      <Row label="Return" value={pct(metrics?.roi_pct)}
           tone={Number(metrics?.roi_pct ?? 0) >= 0 ? "good" : "bad"} />
      <Row label="Win rate" value={pct(metrics?.win_rate_pct)} tone="info" />
      <Row label="Profit factor" value={metrics?.profit_factor ?? null} tone="info"
           note={metrics && metrics.profit_factor === null ? "Undefined while nothing has lost" : undefined} />
      <Row label="Open positions" value={num(metrics?.open_positions)} tone="info" />
      <Row label="Closed trades" value={num(metrics?.closed_positions)} tone="info" />
      <Row
        label="Security-blocked candidates"
        value={summary ? String(summary.failed_count + summary.unknown_count) : null}
        tone={summary && summary.failed_count > 0 ? "bad" : "warn"}
        note={
          summary
            ? `${summary.verified_count} verified, ${summary.failed_count} failed, ${summary.unknown_count} unverified in the last ${summary.window_hours}h`
            : undefined
        }
        source="token-security · summary"
      />
    </Board>
  );
}
