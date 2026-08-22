"use client";

import { STALE_AFTER_MS, fresh, type Source } from "@/lib/hq/adapter";
import type {
  DefectCheck,
  KarthikAction,
  KarthikIncident,
  KarthikReport,
  KarthikState,
  ScreenReading,
} from "@/lib/hq/karthik";
import { Panel } from "@/components/ui/panel";

/**
 * KARTHIK LAB — THE FULL READ.
 *
 * §14's eight sections over one source. Every value is a field the backend
 * published; nothing here computes a verdict, derives a figure, or implies an
 * action that has no audit row behind it.
 *
 * ── THE BRANCH THAT MATTERS IS `measured`, AND IT COMES FIRST ───────────
 *
 * Every section asks whether its reading was measured *before* it touches
 * `values`. That ordering is the whole honesty of the panel: a screen that was
 * not measured has an empty `values` object, and a component that read
 * `values.cash_usd ?? 0` would render `$0.00` for a wallet that does not
 * exist. `Unmeasured` renders the backend's own sentence instead, which always
 * says why.
 *
 * ── THE WALLET DOES NOT EXIST, AND THIS PANEL SAYS SO ───────────────────
 *
 * At the time of writing there is no Karthik Paper Wallet. Every figure
 * section therefore renders its `detail` — "No Karthik Paper Wallet is
 * designated" — rather than a zero, an em-dash or a skeleton. That is not a
 * placeholder state to be replaced later; it is the correct rendering of the
 * response, and it is what the panel will keep doing for any screen whose
 * source stops answering after the wallet exists.
 *
 * ── NO CONTROLS ─────────────────────────────────────────────────────────
 *
 * There is no approve button, no repair button and no arm-autonomy toggle.
 * The things in Karthik's owner queue are the ones §17 classifies
 * OWNER_REQUIRED — accounting truth, historical trades, strategy — and adding
 * a second path to them from a monitoring panel would weaken the first one.
 * Arming autonomy is an environment variable and §23 makes it a separate,
 * deliberate decision; a switch here would make it a click.
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

const RECTIFICATION_COLOR: Record<string, string> = {
  AUTO_FIX: "var(--color-up)",
  OWNER_REQUIRED: "var(--color-down)",
  OBSERVE_ONLY: "var(--color-warn)",
};

function clock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/**
 * Money, as the backend spelled it.
 *
 * Parsed only to place the separators, and the raw string is returned
 * unchanged if it will not parse. A price stored to eighteen places must not
 * be silently rounded by a formatter, and `NaN` must never reach the screen.
 */
function usd(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return String(raw);
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function Section({
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
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">{title}</h3>
          <p className="text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
            {subtitle}
          </p>
        </header>
        <div className="flex flex-col">{children}</div>
      </section>
    </Panel>
  );
}

/**
 * What a section renders when its reading was not measured.
 *
 * One component, used everywhere, so no section can quietly grow its own
 * friendlier empty state. The `detail` is the backend's sentence verbatim —
 * it is the only part of this that is a fact.
 */
function Unmeasured({ reading }: { reading: { detail: string } }) {
  return (
    <p
      className="py-3 text-xs leading-snug text-[var(--color-ink-3,var(--color-ink))]"
      data-testid="karthik-unmeasured"
    >
      <span className="font-mono text-[10px] uppercase tracking-wide opacity-70">
        Not measured —{" "}
      </span>
      {reading.detail}
    </p>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-3 text-xs text-[var(--color-ink-3,var(--color-ink))]">{children}</p>
  );
}

/** A label/value row. `null` renders NOT AVAILABLE, never a dash and never 0. */
function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] py-1 first:border-t-0">
      <span className="text-[11px] text-[var(--color-ink-3,var(--color-ink))]">{label}</span>
      <span className="font-mono text-xs text-[var(--color-ink)]">
        {value ?? (
          <span className="text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
            NOT AVAILABLE
          </span>
        )}
      </span>
    </div>
  );
}

/* ── 1. overview ─────────────────────────────────────────────────────── */

function Overview({ state }: { state: KarthikState }) {
  const wallet = state.screens.wallet;
  const value = (key: string): string | null =>
    wallet.measured && wallet.values[key] !== null && wallet.values[key] !== undefined
      ? String(wallet.values[key])
      : null;

  return (
    <Section
      title="Overview"
      subtitle="Which wallet Karthik operates, under what authority, and what it is worth."
    >
      <Row label="Wallet" value={state.binding.readable ? state.binding.detail : null} />
      <Row
        label="Binding"
        value={state.binding.state.replace(/_/g, " ").toUpperCase()}
      />
      <Row label="Autonomy mode" value={state.autonomy} />
      <Row
        label="Experiment integrity"
        value={
          state.integrity.score === null
            ? state.integrity.band
            : `${state.integrity.score} / 100 · ${state.integrity.band}`
        }
      />
      {wallet.measured ? (
        <>
          <Row label="Starting capital" value={usd(value("starting_capital_usd"))} />
          <Row label="Cash" value={usd(value("cash_usd"))} />
          <Row label="Allocated" value={usd(value("allocated_usd"))} />
          <Row label="Realised P&L" value={usd(value("realised_pnl_usd"))} />
          <Row label="Unrealised P&L" value={usd(value("unrealised_pnl_usd"))} />
          <Row label="Open positions" value={value("open_positions")} />
          <Row label="Closed positions" value={value("closed_positions")} />
        </>
      ) : (
        <Unmeasured reading={wallet} />
      )}
      {/* Only when the binding needs a person. On an ordinary unbound
          deployment the wallet screen above already carries this exact
          sentence, and printing it twice in one card reads as a bug rather
          than as emphasis. A forbidden or missing binding is different: it is
          a misconfiguration, it is styled as one, and it earns the repetition. */}
      {state.binding.needs_owner ? (
        <p
          className="mt-2 text-[11px] leading-snug text-[var(--color-down)]"
          data-testid="karthik-binding-detail"
        >
          {state.binding.detail}
        </p>
      ) : null}
    </Section>
  );
}

/* ── 2. while you were away ──────────────────────────────────────────── */

function WhileAway({ state }: { state: KarthikState }) {
  const away = state.while_away;
  return (
    <Section
      title="What happened while you were away?"
      subtitle="Since your previous visit on this device. Not a fixed window."
    >
      {away.measured ? (
        <>
          <Row label="Since" value={away.since ? new Date(away.since).toLocaleString() : null} />
          <Row label="Track Record opportunities" value={away.opportunities?.toString() ?? null} />
          <Row label="New trades" value={away.new_trades?.toString() ?? null} />
          <Row label="Targets hit" value={away.targets_hit?.toString() ?? null} />
          <Row label="Dead positions" value={away.dead_positions?.toString() ?? null} />
          <Row label="P&L change" value={usd(away.pnl_usd)} />
          <Row
            label="Biggest winner"
            value={away.biggest_winner ? String(away.biggest_winner.mint) : null}
          />
          <Row
            label="Biggest loss"
            value={away.biggest_loss ? String(away.biggest_loss.mint) : null}
          />
          <Row label="Bugs found" value={away.bugs_found?.toString() ?? null} />
          <Row label="Bugs fixed automatically" value={away.bugs_fixed?.toString() ?? null} />
          <Row label="Owner-attention items" value={away.owner_attention?.toString() ?? null} />
          <Row label="Integrity score" value={away.integrity_score?.toString() ?? null} />
        </>
      ) : (
        <Unmeasured reading={away} />
      )}
    </Section>
  );
}

/* ── 3. live feed, 4. positions ──────────────────────────────────────── */

function Feed({ reading }: { reading: ScreenReading }) {
  return (
    <Section
      title="Live feed"
      subtitle="Track Record admissions since the wallet started, and what Karthik did about each."
    >
      {!reading.measured ? (
        <Unmeasured reading={reading} />
      ) : reading.rows.length === 0 ? (
        <Empty>No Track Record admissions in this window.</Empty>
      ) : (
        <ul className="flex flex-col">
          {reading.rows.map((row, i) => (
            <li
              key={`${String(row.mint)}-${i}`}
              className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] py-1 first:border-t-0"
            >
              <span className="truncate font-mono text-[11px] text-[var(--color-ink)]">
                {String(row.mint)}
              </span>
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
                {String(row.outcome)} · {clock(String(row.detected_at))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Positions({ positions, targets }: { positions: ScreenReading; targets: ScreenReading }) {
  return (
    <Section
      title="Positions and targets"
      subtitle="Open positions, their multiple, and how close each is to the 1.25x target."
    >
      {!positions.measured ? (
        <Unmeasured reading={positions} />
      ) : positions.rows.length === 0 ? (
        <Empty>No open positions.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
              <tr>
                <th scope="col" className="py-1 pr-3 font-normal">Mint</th>
                <th scope="col" className="py-1 pr-3 font-normal">Multiple</th>
                <th scope="col" className="py-1 pr-3 font-normal">Target</th>
                <th scope="col" className="py-1 font-normal">Quote age</th>
              </tr>
            </thead>
            <tbody>
              {positions.rows.map((row, i) => (
                <tr key={`${String(row.mint)}-${i}`} className="border-t border-[var(--color-line)]">
                  <td className="truncate py-1 pr-3 font-mono text-[var(--color-ink)]">
                    {String(row.mint)}
                  </td>
                  <td className="py-1 pr-3 font-mono text-[var(--color-ink)]">
                    {row.multiple === null || row.multiple === undefined
                      ? "NOT AVAILABLE"
                      : `${Number(row.multiple).toFixed(3)}x`}
                  </td>
                  <td className="py-1 pr-3 font-mono text-[var(--color-ink)]">
                    {usd(row.target_price) ?? "NOT AVAILABLE"}
                  </td>
                  {/* Stale is called out rather than left for the reader to
                      work out from a number: a position valued on a stale
                      quote is a position whose multiple is not current, and
                      that is the whole reason the column exists. */}
                  <td
                    className="py-1 font-mono"
                    style={{ color: row.quote_stale ? "var(--color-warn)" : undefined }}
                  >
                    {row.quote_age_seconds === null || row.quote_age_seconds === undefined
                      ? "NO QUOTE"
                      : `${Math.round(Number(row.quote_age_seconds))}s${row.quote_stale ? " · STALE" : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {targets.measured ? (
        <p className="mt-2 text-[10px] text-[var(--color-ink-3,var(--color-ink))]">
          {targets.detail} Lifetime target hits:{" "}
          <span className="font-mono">{String(targets.values.target_hits_lifetime ?? "—")}</span>
        </p>
      ) : null}
    </Section>
  );
}

/* ── 5. performance / integrity ──────────────────────────────────────── */

function Integrity({ state }: { state: KarthikState }) {
  const { integrity } = state;
  return (
    <Section
      title="Experiment integrity"
      subtitle="Whether the result is trustworthy — not whether it is profitable."
    >
      <div className="flex items-baseline gap-3 pb-2">
        <span className="font-mono text-2xl text-[var(--color-ink)]" data-testid="karthik-integrity-score">
          {integrity.score === null ? "—" : `${integrity.score} / 100`}
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
          {integrity.band}
        </span>
      </div>
      <p className="pb-2 text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
        {integrity.headline}
        {integrity.unmeasured > 0
          ? ` ${integrity.unmeasured} of ${integrity.deductions.length} factors could not be measured; an unmeasured factor deducts nothing and is not counted as clean.`
          : ""}
      </p>
      {integrity.deductions.map((deduction) => (
        <div
          key={deduction.factor}
          className="flex flex-col gap-0.5 border-t border-[var(--color-line)] py-1.5"
        >
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[11px] text-[var(--color-ink)]">{deduction.label}</span>
            <span
              className="shrink-0 font-mono text-[10px] uppercase tracking-wide"
              style={{
                color: !deduction.measured
                  ? "var(--color-ink-3, var(--color-ink))"
                  : deduction.penalty > 0
                    ? "var(--color-warn)"
                    : "var(--color-up)",
              }}
            >
              {deduction.measured ? `−${deduction.penalty}` : "NOT MEASURED"}
            </span>
          </div>
          <p className="text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
            {deduction.detail}
          </p>
        </div>
      ))}
    </Section>
  );
}

/* ── 6. system health ────────────────────────────────────────────────── */

function Health({ reading, accounting }: { reading: ScreenReading; accounting: ScreenReading }) {
  return (
    <Section
      title="System health"
      subtitle="The shared infrastructure probe, plus Karthik's own loop and the accounting invariant."
    >
      {reading.measured ? (
        <>
          <Row label="Overall" value={String(reading.values.overall ?? "")} />
          <Row label="Database" value={String(reading.values.database ?? "")} />
          <Row label="Redis" value={String(reading.values.redis ?? "")} />
          <Row label="Worker" value={String(reading.values.worker ?? "")} />
          <Row label="Scheduler" value={String(reading.values.scheduler ?? "")} />
          <Row label="Disk" value={String(reading.values.disk ?? "")} />
          <Row label="Karthik loop" value={String(reading.values.karthik_loop ?? "")} />
        </>
      ) : (
        <Unmeasured reading={reading} />
      )}
      <div className="mt-2 border-t border-[var(--color-line)] pt-2">
        <p className="pb-1 text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
          Accounting invariant · cash + executable open value ≈ equity
        </p>
        {accounting.measured ? (
          <>
            <Row label="Cash" value={usd(accounting.values.cash_usd)} />
            <Row label="Open value" value={usd(accounting.values.open_value_usd)} />
            <Row label="Equity" value={usd(accounting.values.equity_usd)} />
          </>
        ) : (
          <Unmeasured reading={accounting} />
        )}
      </div>
    </Section>
  );
}

/* ── 7. incidents and the owner queue ────────────────────────────────── */

function IncidentRow({ incident }: { incident: KarthikIncident }) {
  return (
    <article className="border-t border-[var(--color-line)] py-2 first:border-t-0">
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
          <dt className="opacity-70">Actions</dt>
          <dd className="font-mono">{incident.actions.length}</dd>
        </div>
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

function Incidents({ state }: { state: KarthikState }) {
  const owner = state.incidents.filter((i) => i.kind === "karthik_approval");
  const rest = state.incidents.filter((i) => i.kind !== "karthik_approval");
  return (
    <Section
      title="Needs your attention"
      subtitle="Findings only the owner may decide, and the operational work beneath them."
    >
      {owner.length === 0 ? (
        <Empty>Nothing is waiting on you.</Empty>
      ) : (
        owner.map((incident) => <IncidentRow key={incident.code} incident={incident} />)
      )}
      {rest.length > 0 ? (
        <div className="mt-3 border-t border-[var(--color-line)] pt-2">
          <p className="pb-1 text-[10px] uppercase tracking-wide text-[var(--color-ink-3,var(--color-ink))]">
            Open operational findings
          </p>
          {rest.map((incident) => (
            <IncidentRow key={incident.code} incident={incident} />
          ))}
        </div>
      ) : null}
    </Section>
  );
}

/* ── 8. the action log, the allowlist and the checks ─────────────────── */

function ActionRow({ action }: { action: KarthikAction }) {
  return (
    <div className="border-t border-[var(--color-line)] py-1.5 first:border-t-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate font-mono text-[11px] text-[var(--color-ink)]">
          {action.action}
        </span>
        <span
          className="shrink-0 font-mono text-[10px] uppercase tracking-wide"
          style={{ color: OUTCOME_COLOR[action.outcome] ?? "var(--color-ink-3)" }}
        >
          {action.outcome} · {clock(action.at)}
        </span>
      </div>
      <p className="text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
        {action.reason}
      </p>
      <p className="font-mono text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
        {action.autonomy}
        {typeof action.result.detail === "string" ? ` — ${action.result.detail}` : ""}
      </p>
    </div>
  );
}

function ActionLog({ state }: { state: KarthikState }) {
  return (
    <Section
      title="Action log"
      subtitle="Detected → diagnosed → action → result → evidence. Append-only; refusals included."
    >
      {state.actions.length === 0 ? (
        <Empty>
          No action has been attempted. In {state.autonomy} nothing executes, so this stays empty
          until a finding gives Karthik something to record.
        </Empty>
      ) : (
        state.actions.map((action, i) => <ActionRow key={`${action.at}-${i}`} action={action} />)
      )}
    </Section>
  );
}

function Authority({ state }: { state: KarthikState }) {
  return (
    <Section
      title="What Karthik is permitted to do"
      subtitle="Read from the API's own allowlist, not restated here. If the backend's list shrinks, this shrinks with it."
    >
      <p className="pb-2 text-[11px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
        Mode <span className="font-mono text-[var(--color-ink)]">{state.autonomy}</span>.{" "}
        {state.autonomy === "OBSERVE_ONLY"
          ? "Karthik detects, diagnoses, records and recommends. He executes nothing."
          : "Allowlisted repairs may execute after a fresh precondition check."}
      </p>
      {state.allowlist.map((repair) => (
        <div key={repair.key} className="border-t border-[var(--color-line)] py-1.5">
          <p className="font-mono text-[11px] text-[var(--color-ink)]">{repair.key}</p>
          <p className="text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))]">
            {repair.summary}
          </p>
          <p className="text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))] opacity-75">
            Precondition: {repair.precondition}
          </p>
        </div>
      ))}
    </Section>
  );
}

function Checks({ checks }: { checks: DefectCheck[] }) {
  const gaps = checks.filter((check) => !check.detectable);
  return (
    <Section
      title="What Karthik checks for"
      subtitle="Every condition on the list, including the ones no available evidence can establish."
    >
      {checks.map((check) => (
        <div
          key={check.key}
          className="flex items-baseline justify-between gap-3 border-t border-[var(--color-line)] py-1 first:border-t-0"
        >
          <span className="text-[11px] text-[var(--color-ink)]">
            {check.label}
            {!check.detectable ? (
              <span className="ml-1 font-mono text-[10px] uppercase text-[var(--color-warn)]">
                not checkable
              </span>
            ) : null}
          </span>
          <span
            className="shrink-0 font-mono text-[10px] uppercase tracking-wide"
            style={{ color: RECTIFICATION_COLOR[check.rectification] }}
          >
            {check.rectification.replace(/_/g, " ")}
          </span>
        </div>
      ))}
      {gaps.length > 0 ? (
        <div className="mt-2 border-t border-[var(--color-line)] pt-2">
          {gaps.map((gap) => (
            <p
              key={gap.key}
              className="pb-1 text-[10px] leading-snug text-[var(--color-ink-3,var(--color-ink))]"
            >
              <span className="font-mono">{gap.label}:</span> {gap.gap}
            </p>
          ))}
        </div>
      ) : null}
    </Section>
  );
}

/* ── 9. reports ──────────────────────────────────────────────────────── */

function ReportCard({ report }: { report: KarthikReport }) {
  if (!report.measured) {
    return (
      <div className="border-t border-[var(--color-line)] py-2 first:border-t-0">
        <p className="pb-0.5 text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink)]">
          {report.window}
        </p>
        <Unmeasured reading={report} />
      </div>
    );
  }
  return (
    <div className="border-t border-[var(--color-line)] py-2 first:border-t-0">
      <p className="pb-0.5 text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink)]">
        {report.window}
      </p>
      <Row label="P&L" value={usd(report.pnl_usd)} />
      <Row label="Entered" value={report.entered?.toString() ?? null} />
      <Row label="Targets hit" value={report.targets_hit?.toString() ?? null} />
      <Row label="Dead / zero" value={report.dead_zero?.toString() ?? null} />
      <Row label="Closed" value={report.closed_positions?.toString() ?? null} />
      <Row
        label="Target-hit rate"
        value={
          report.target_hit_rate === null
            ? null
            : `${(report.target_hit_rate * 100).toFixed(1)}%`
        }
      />
      <Row
        label="Average hold"
        value={
          report.average_hold_seconds === null
            ? null
            : `${Math.round(report.average_hold_seconds / 60)} min`
        }
      />
      <Row label="Bugs detected" value={report.bugs_detected?.toString() ?? null} />
      <Row label="Repairs performed" value={report.repairs_performed?.toString() ?? null} />
    </div>
  );
}

function Reports({ state }: { state: KarthikState }) {
  const windows = ["daily", "weekly", "lifetime"];
  return (
    <Section
      title="Reports"
      subtitle="Derived on read from the position rows, so a report can never disagree with the trades it summarises."
    >
      {windows.map((window) => {
        const report = state.reports[window];
        return report ? <ReportCard key={window} report={report} /> : null;
      })}
    </Section>
  );
}

/* ── the panel ───────────────────────────────────────────────────────── */

/**
 * The whole of §14, over one source.
 *
 * Rendered from the same `Source` wrapper every board uses, so `fresh()` is
 * still the single gate deciding what counts as current — the panel cannot
 * read past a staleness window the room respects.
 */
export function KarthikPanel({
  source,
  now,
  onClose,
}: {
  source: Source<KarthikState>;
  now: number;
  onClose: () => void;
}) {
  const state = fresh(source, STALE_AFTER_MS.karthik, now);

  if (!state) {
    return (
      <Panel>
        <div className="flex items-start justify-between gap-4 p-4">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">Karthik Lab</h2>
            <p className="mt-1 text-xs text-[var(--color-ink-3,var(--color-ink))]">
              No current reading from <span className="font-mono">GET /karthik</span>. Nothing is
              shown rather than a stale one.
            </p>
          </div>
          <CloseButton onClose={onClose} />
        </div>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="karthik-panel">
      <Panel>
        <div className="flex items-start justify-between gap-4 p-4">
          <div>
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">
              Karthik Lab — Track Record Wallet Operations
            </h2>
            <p className="mt-1 max-w-2xl text-xs leading-snug text-[var(--color-ink-3,var(--color-ink))]">
              Karthik monitors, audits and reports on the Karthik Paper Wallet only. He cannot
              change its rules, its sizing, its target, its history or any other wallet on the
              platform, and this panel reads nothing from them.
            </p>
          </div>
          <CloseButton onClose={onClose} />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Overview state={state} />
        <WhileAway state={state} />
        <Feed reading={state.screens.feed} />
        <Positions positions={state.screens.positions} targets={state.screens.targets} />
        <Integrity state={state} />
        <Health reading={state.screens.health} accounting={state.accounting} />
        <Incidents state={state} />
        <ActionLog state={state} />
        <Authority state={state} />
        <Checks checks={state.checks} />
        <Reports state={state} />
      </div>
    </div>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      className="shrink-0 rounded-md border border-[var(--color-line)] px-2 py-1 text-xs text-[var(--color-ink)]"
    >
      Close
    </button>
  );
}
