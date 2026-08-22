"use client";

import { STALE_AFTER_MS, fresh, type Source } from "@/lib/hq/adapter";
import type { HqOperations, Incident, IncidentAction } from "@/lib/hq/operations";
import { Panel } from "@/components/ui/panel";

/**
 * INCIDENTS, THE AUTONOMOUS AUDIT TRAIL, AND WHAT ONLY THE OWNER MAY APPROVE.
 *
 * Three panels over one source. Every value is a field the backend published;
 * nothing here computes a verdict, and nothing implies an action that has no
 * row behind it.
 *
 * ── THE ALLOWLIST IS RENDERED, NOT DESCRIBED ────────────────────────────
 *
 * The footer lists exactly what HQ is permitted to do, read from the API's own
 * response rather than restated in this file. A hard-coded copy could claim a
 * capability the backend would refuse, and a panel that overstates what a
 * system can do is the specific failure this whole feature exists to avoid.
 * If the backend's allowlist shrinks, this shrinks with it.
 *
 * ── WHY THERE IS NO APPROVE BUTTON ──────────────────────────────────────
 *
 * The owner queue displays what is waiting and why. It does not carry a
 * control that executes anything, because the things that land in it are the
 * RED class — strategy, sizing, wallet permissions — and those already have
 * their own confirmation architecture elsewhere in MEMESCOPE. Adding a second
 * path to them from a monitoring panel would weaken the first one. This shows
 * the request and points at the existing controls.
 */

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--color-down)",
  degraded: "var(--color-warn)",
  info: "var(--color-accent)",
};

const OUTCOME_COLOR: Record<string, string> = {
  succeeded: "var(--color-up)",
  failed: "var(--color-down)",
  skipped: "var(--color-ink-3, var(--color-ink))",
  attempted: "var(--color-warn)",
  rolled_back: "var(--color-warn)",
};

function clock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function Shell({
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

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-3 text-xs text-[var(--color-ink-3,var(--color-ink))]">{children}</p>
  );
}

/* ── incidents ───────────────────────────────────────────────────────── */

function IncidentRow({ incident }: { incident: Incident }) {
  const repairs = incident.actions.filter(
    (action) => action.action !== "diagnostics.reprobe",
  );
  return (
    <article className="border-b border-[var(--color-line)] py-2 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-xs text-[var(--color-ink)]">{incident.code}</span>
        <span
          className="shrink-0 font-mono text-[10px] uppercase tracking-wide"
          style={{ color: SEVERITY_COLOR[incident.severity] ?? "var(--color-ink-3)" }}
        >
          {incident.severity} · {incident.status.replace(/_/g, " ")}
        </span>
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
        {String(incident.symptoms.summary ?? incident.component)}
      </p>
      <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-[var(--color-ink-3,var(--color-ink))]">
        <div className="flex gap-1">
          <dt className="opacity-70">Detected</dt>
          <dd className="font-mono">{clock(incident.detected_at)}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="opacity-70">Component</dt>
          <dd className="font-mono">{incident.component}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="opacity-70">Agent</dt>
          <dd className="font-mono">{incident.agent ?? "unassigned"}</dd>
        </div>
        <div className="flex gap-1">
          <dt className="opacity-70">Repairs</dt>
          <dd className="font-mono">{repairs.length}</dd>
        </div>
        {/* Root cause is shown only when something established one. An
            incident with no root cause says so rather than borrowing its
            symptom and presenting it as a diagnosis. */}
        <div className="flex gap-1">
          <dt className="opacity-70">Root cause</dt>
          <dd className="font-mono">{incident.root_cause ?? "UNKNOWN"}</dd>
        </div>
      </dl>
      {incident.owner_rationale ? (
        <p className="mt-1 text-[10px] leading-snug text-[var(--color-warn)]">
          {incident.owner_rationale}
        </p>
      ) : null}
    </article>
  );
}

export function IncidentBoard({
  operations,
  now,
}: {
  operations: Source<HqOperations>;
  now: number;
}) {
  const data = fresh(operations, STALE_AFTER_MS.operations, now);

  if (!data) {
    return (
      <Shell
        title="Incidents"
        subtitle="Open operational work, as recorded by the production watch."
      >
        <Empty>No data — the operations surface did not answer.</Empty>
      </Shell>
    );
  }

  const open = data.incidents.filter((incident) => incident.kind === "incident");
  const closed = data.recent.filter((incident) => incident.kind === "incident");

  return (
    <Shell
      title="Incidents"
      subtitle="Open operational work, as recorded by the production watch. Every row is a database row."
    >
      {open.length === 0 ? (
        <Empty>No open incidents.</Empty>
      ) : (
        open.map((incident) => <IncidentRow key={incident.code} incident={incident} />)
      )}
      {closed.length > 0 ? (
        <>
          <h3 className="mt-3 text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))] opacity-70">
            Closed in the last 24 hours
          </h3>
          {closed.map((incident) => (
            <IncidentRow key={incident.code} incident={incident} />
          ))}
        </>
      ) : null}
    </Shell>
  );
}

/* ── the audit trail ─────────────────────────────────────────────────── */

function ActionRow({ action }: { action: IncidentAction }) {
  const invariants = (action.verification as { invariants?: { held?: boolean } })
    .invariants;
  return (
    <li className="flex flex-col gap-0.5 border-b border-[var(--color-line)] py-1.5 last:border-b-0">
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 font-mono text-[10px] text-[var(--color-ink-3,var(--color-ink))]">
          {clock(action.at)}
        </span>
        <span className="font-mono text-[11px] text-[var(--color-ink)]">{action.agent}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--color-ink-3,var(--color-ink))]">
          {action.action}
        </span>
        <span
          className="shrink-0 font-mono text-[10px] uppercase"
          style={{ color: OUTCOME_COLOR[action.outcome] ?? "var(--color-ink-3)" }}
        >
          {action.outcome}
        </span>
      </div>
      <p className="pl-[3.2rem] text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))] opacity-80">
        {action.reason}
        {invariants?.held === false ? (
          <strong className="ml-1 text-[var(--color-down)]">
            Protected trading rules changed — action failed.
          </strong>
        ) : null}
      </p>
    </li>
  );
}

export function AutonomousActivity({
  operations,
  now,
}: {
  operations: Source<HqOperations>;
  now: number;
}) {
  const data = fresh(operations, STALE_AFTER_MS.operations, now);

  return (
    <Shell
      title="Autonomous activity"
      subtitle="Every action HQ attempted, whatever the outcome. Written before the action ran, so a failure still leaves a record."
    >
      {/* The mode, first and unmissable. A trail of past repairs above a
          system that is currently executing nothing would imply it still
          is — and the whole point of this panel is that it cannot imply
          anything the backend has not published. */}
      {data ? (
        <p
          className="mb-2 rounded border px-2 py-1 text-[10px] leading-snug"
          style={{
            borderColor: data.autonomy_enabled
              ? "var(--color-up)"
              : "var(--color-ink-3, var(--color-ink))",
            color: data.autonomy_enabled
              ? "var(--color-up)"
              : "var(--color-ink-3, var(--color-ink))",
          }}
        >
          {data.autonomy_enabled
            ? "ARMED — permitted repairs execute automatically."
            : "OBSERVE-ONLY — HQ detects, records and closes incidents, but executes nothing."}
        </p>
      ) : null}
      {!data ? (
        <Empty>No data — the operations surface did not answer.</Empty>
      ) : data.activity.length === 0 ? (
        <Empty>HQ has taken no autonomous actions.</Empty>
      ) : (
        <ul className="flex flex-col">
          {data.activity.map((action, index) => (
            <ActionRow key={`${action.at}-${index}`} action={action} />
          ))}
        </ul>
      )}

      {data ? (
        <footer className="mt-3 border-t border-[var(--color-line)] pt-2">
          <h3 className="text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))] opacity-70">
            Everything HQ is permitted to do
          </h3>
          <ul className="mt-1 flex flex-col gap-0.5">
            {data.allowlist.map((entry) => (
              <li
                key={entry.key}
                className="flex items-baseline gap-2 text-[10px] text-[var(--color-ink-3,var(--color-ink))]"
              >
                <span className="font-mono text-[var(--color-up)]">{entry.autonomy}</span>
                <span className="font-mono">{entry.key}</span>
                <span className="min-w-0 flex-1 truncate opacity-70">{entry.summary}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))] opacity-60">
            Read from the backend, not restated here. Nothing outside this list can run:
            no shell, no code changes, no container control, no wallet access.
            {data.autonomy_enabled ? null : " In observe-only mode none of it runs at all."}
          </p>
        </footer>
      ) : null}
    </Shell>
  );
}

/* ── the owner's queue ───────────────────────────────────────────────── */

export function OwnerInbox({
  operations,
  now,
}: {
  operations: Source<HqOperations>;
  now: number;
}) {
  const data = fresh(operations, STALE_AFTER_MS.operations, now);
  const waiting = (data?.incidents ?? []).filter(
    (incident) => incident.kind === "approval" || incident.status === "awaiting_owner",
  );

  return (
    <Shell
      title="Owner approval"
      subtitle="Work HQ classified as needing a person. Nothing here can be executed from this panel."
    >
      {!data ? (
        <Empty>No data — the operations surface did not answer.</Empty>
      ) : waiting.length === 0 ? (
        <Empty>Nothing is waiting on you.</Empty>
      ) : (
        waiting.map((incident) => <IncidentRow key={incident.code} incident={incident} />)
      )}
      <p className="mt-2 border-t border-[var(--color-line)] pt-2 text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))] opacity-70">
        Strategy, position sizing, entry and exit policy, the security gate, the 6-hour
        hold and Real Wallet permissions are never modified autonomously. They keep the
        controls they already had; this panel reports, it does not execute.
      </p>
    </Shell>
  );
}
