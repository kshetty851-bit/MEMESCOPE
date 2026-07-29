"use client";

import { Panel } from "@/components/ui/panel";
import { Why } from "@/components/decision/why";
import { QUALITY_LABEL, QUALITY_TONE, type MarketAssessment } from "@/lib/market-quality";
import { MISSION_LABEL, type MissionState } from "@/lib/mission";

/**
 * The Mission Brief — the first thing on the page and, on a poor day, the only
 * thing a user needs to read.
 *
 * A briefing is defined as much by what it declines to say. When nothing
 * qualifies, this panel says so in a sentence and the board below is short.
 * That is the trust mechanism: a product that finds five opportunities every
 * single day is not assessing anything, and users work that out faster than
 * they forgive it.
 *
 * Everything here is counted, never estimated. `analysed` is the engine's own
 * total, the state counts are tallies over classified projects, and the two
 * movers are the largest observed changes since the user's last visit.
 */
export function MissionBrief({
  analysed,
  market,
  worthInvestigating,
  stateCounts,
  cloneWarnings,
  biggestGain,
  biggestDrop,
}: {
  analysed: number;
  market: MarketAssessment;
  worthInvestigating: number;
  stateCounts: Partial<Record<MissionState, number>>;
  cloneWarnings: number;
  biggestGain?: { label: string; detail: string } | null;
  biggestDrop?: { label: string; detail: string } | null;
}) {
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <Panel density="comfortable" className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-xs uppercase tracking-[0.14em] text-brand-accent">Mission brief</p>
          <Why>
            Generated from what the platform observed, not written in advance.
            Every figure here is a count over the projects LETZMOON scored and
            tracked — none of it is estimated, and none of it is a forecast.
          </Why>
        </div>
        <h1 className="text-balance text-3xl font-medium tracking-tight text-ink">
          {greeting}, Commander
        </h1>
        <p className="font-mono text-sm text-ink-faint" data-numeric>
          {analysed.toLocaleString()} projects analysed
        </p>
      </header>

      {/* --- Today's market quality -------------------------------------- */}
      <section className="flex flex-col gap-3 rounded-panel border border-line/50 bg-elevated/25 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <span className="text-[0.625rem] uppercase tracking-[0.1em] text-ink-faint">
              Market quality
            </span>
            <span
              className="text-xl font-medium tracking-tight"
              style={{ color: QUALITY_TONE[market.quality] }}
            >
              {QUALITY_LABEL[market.quality]}
            </span>
          </div>
          <Why label="How this is measured">
            <div className="flex flex-col gap-1.5">
              <p>
                A transparent sum of five counts, {market.score} of 100. Price
                direction is deliberately not one of them — a broad rally lifts
                failing projects too, so breadth of price says nothing about
                whether today is worth your research time.
              </p>
              <ul className="flex flex-col gap-0.5">
                {market.factors.map((factor) => (
                  <li key={factor.label} className="font-mono text-[0.6875rem]">
                    {factor.label}: {factor.points}/{factor.of} — {factor.value}
                  </li>
                ))}
              </ul>
            </div>
          </Why>
        </div>
        <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">{market.summary}</p>
      </section>

      {/* --- What that means for the day --------------------------------- */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-sm text-ink">
            <span
              data-numeric
              className="font-mono text-2xl tabular-nums"
              style={{
                color:
                  worthInvestigating > 0
                    ? "var(--color-brand-secondary)"
                    : "var(--color-ink-faint)",
              }}
            >
              {worthInvestigating}
            </span>{" "}
            <span className="text-ink-dim">
              {worthInvestigating === 1 ? "project deserves" : "projects deserve"} investigation
              today
            </span>
          </p>
        </div>

        {worthInvestigating === 0 ? (
          <p className="max-w-2xl text-sm leading-relaxed text-ink-dim">
            Nothing on the board clears the bar for research attention today.
            Saying so is the point — a briefing that always finds five
            opportunities is not assessing anything.
          </p>
        ) : (
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(["ascent", "orbit", "launch_window", "re_entry"] as MissionState[]).map(
              (state) => (
                <div
                  key={state}
                  className="flex flex-col gap-0.5 rounded-panel border border-line/40 px-3 py-2"
                >
                  <dt className="text-[0.625rem] uppercase tracking-[0.09em] text-ink-faint">
                    {MISSION_LABEL[state]}
                  </dt>
                  <dd data-numeric className="font-mono text-lg tabular-nums text-ink">
                    {stateCounts[state] ?? 0}
                  </dd>
                </div>
              ),
            )}
          </dl>
        )}
      </section>

      {/* --- Movers and warnings ----------------------------------------- */}
      <section className="grid gap-3 sm:grid-cols-3">
        <Mover
          label="Biggest improvement"
          entry={biggestGain}
          tone="var(--color-brand-secondary)"
          empty="Nothing improved materially since your last visit."
        />
        <Mover
          label="Biggest deterioration"
          entry={biggestDrop}
          tone="var(--color-danger)"
          empty="Nothing deteriorated materially since your last visit."
        />
        <div className="flex flex-col gap-1 rounded-panel border border-line/40 px-3 py-2.5">
          <p className="text-[0.625rem] uppercase tracking-[0.09em] text-ink-faint">
            Clone warnings
          </p>
          <p
            data-numeric
            className="font-mono text-lg tabular-nums"
            style={{
              color: cloneWarnings > 0 ? "var(--color-warn)" : "var(--color-ink-dim)",
            }}
          >
            {cloneWarnings}
          </p>
          <p className="text-[0.6875rem] leading-snug text-ink-faint">
            On today&rsquo;s board, trading on a name an earlier token used first.
          </p>
        </div>
      </section>
    </Panel>
  );
}

function Mover({
  label,
  entry,
  tone,
  empty,
}: {
  label: string;
  entry?: { label: string; detail: string } | null;
  tone: string;
  empty: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-panel border border-line/40 px-3 py-2.5">
      <p className="text-[0.625rem] uppercase tracking-[0.09em] text-ink-faint">{label}</p>
      {entry ? (
        <>
          <p className="text-lg font-medium tracking-tight" style={{ color: tone }}>
            {entry.label}
          </p>
          <p className="text-[0.6875rem] leading-snug text-ink-faint">{entry.detail}</p>
        </>
      ) : (
        <p className="text-[0.6875rem] leading-snug text-ink-faint">{empty}</p>
      )}
    </div>
  );
}
