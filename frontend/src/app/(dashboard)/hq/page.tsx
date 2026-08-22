"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { HqCards } from "@/components/hq/hq-cards";
import { Portrait } from "@/components/hq/portrait";
import { ReportPanel } from "@/components/hq/report-panel";
import { buildToday } from "@/lib/hq/today";
import { useAmbient } from "@/components/hq/use-ambient";
import { useReportMeeting } from "@/components/hq/use-report-meeting";
import { useDayPhase, useHqMotion } from "@/components/hq/use-hq-env";
import { useHqState } from "@/components/hq/use-hq-state";
import type { HqState } from "@/lib/hq/adapter";
import { useTokenCaseFile, useVisiblePackets } from "@/components/hq/use-token-cases";
import { CaseFilePanel } from "@/components/hq/case-file-panel";
import { RecentCases } from "@/components/hq/recent-cases";
import {
  ExecutionVault,
  InfrastructureBoard,
  MissionBoard,
  PerformanceLab,
} from "@/components/hq/hq-boards";
import {
  AutonomousActivity,
  IncidentBoard,
  OwnerInbox,
} from "@/components/hq/operations-panel";
import { CAT_BY_ID, type CatId } from "@/lib/hq/cats";
import { SUPPORT_BY_ID, type SupportId } from "@/lib/hq/support";
import { VISITOR_BY_ID, type VisitorId } from "@/lib/hq/visitors";
import type { ActorId } from "@/lib/hq/ambient-scheduler";
import { STATE_LABEL } from "@/lib/hq/employees";
import { CHARACTERS } from "@/lib/hq/characters";
import { ZONE_BY_ID } from "@/lib/hq/zones";
import { EMPLOYEE_BY_ID, type EmployeeId } from "@/lib/hq/employees";
import type { ZoneId } from "@/lib/hq/zones";
import { Panel } from "@/components/ui/panel";

/**
 * MEMESCOPE HQ.
 *
 * The system, drawn as the organisation it behaves like. Radar discovers, Luna
 * analyses, Atlas refuses, Rex executes — and in later phases each of those is
 * driven by state MEMESCOPE actually publishes, not by a timer.
 *
 * WHAT EXISTS SO FAR
 *
 * The floor plan and departments (HQ-1), and the cast: ten characters built
 * from one shared rig, each at a desk whose instruments say what they do
 * (HQ-2), ambient personality (HQ-3), and from HQ-4 the thing all of it was
 * for: the office is wired to what MEMESCOPE is actually doing. Radar works
 * when the scanner finds something, Dex raises an alert when tracked prices go
 * stale, Echo carries the enrichment queue, and Atlas still reports no data
 * because no endpoint can describe him yet.
 *
 * THIS PAGE OWNS THE QUERIES, AND NOTHING ELSE INTERPRETS THEM
 *
 * `useHqState` runs five queries and hands both surfaces one normalized
 * `HqState`. The room and the card stack are pure renderers of that object —
 * neither reads a backend field, so they cannot drift apart, and a change to a
 * health field is a change to `adapter.ts` and to nothing else.
 *
 * HQ-5 adds a second, independent read layer for individual tokens:
 * `useVisiblePackets` picks up to three real, currently-relevant mints and
 * `useTokenCaseFile` turns one mint into a `TokenCaseFile` via `case-file.ts`
 * — the same adapter discipline, applied one token at a time rather than to
 * the office as a whole. Selecting a packet and selecting an employee are
 * deliberately different pieces of state (`selectedMint` vs `selected`): a
 * case is not an actor, and mixing the two id spaces is exactly how a
 * click handler ends up guessing which panel to open.
 *
 * WHY THE STAGE IS DYNAMICALLY IMPORTED
 *
 * `HqStage` pulls in `hq.css` and the whole isometric scene. Importing it
 * normally would place it in the shared client chunk and it would ship with
 * /wallet and /command, which the plan forbids. `dynamic(..., { ssr: false })`
 * keeps it in its own chunk that only this route requests — and the scene is
 * pure presentation, so there is nothing to gain from server-rendering it.
 */

const HqStage = dynamic(
  () => import("@/components/hq/hq-stage").then((module) => module.HqStage),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-[320px] w-full animate-none rounded-xl border border-[var(--color-line)] bg-[var(--color-sunken)]"
        aria-hidden="true"
      />
    ),
  },
);

/** Below this the room is unreadable, so it is not drawn at all. */
const STAGE_MIN_WIDTH = 768;
/** Below this the room drops ambient detail to keep the element count down. */
const FULL_DENSITY_MIN_WIDTH = 1280;

type Viewport = "mobile" | "tablet" | "desktop";

export default function HqPage() {
  const viewport = useViewport();
  const state = useHqState();
  const motion = useHqMotion();
  const phase = useDayPhase();
  const [focusedZone, setFocusedZone] = useState<ZoneId | null>(null);
  const [selected, setSelected] = useState<ActorId | null>(null);
  const [selectedMint, setSelectedMint] = useState<string | null>(null);
  const { packets, overflow } = useVisiblePackets();

  // Exactly as many case-file fetches as §29 allows: one per visible packet
  // slot (a fixed count, so these stay legal hook calls regardless of how
  // many packets are actually present) plus, only when the reader opened a
  // mint that is not already one of the three, one more for that mint alone.
  // Never a fetch per row of a list — Recent Cases reads the batch responses
  // it already has, on purpose; see that component's own note.
  const packetMints: Array<string | null> = [
    packets[0]?.mint ?? null,
    packets[1]?.mint ?? null,
    packets[2]?.mint ?? null,
  ];
  const packetCase0 = useTokenCaseFile(packetMints[0]!);
  const packetCase1 = useTokenCaseFile(packetMints[1]!);
  const packetCase2 = useTokenCaseFile(packetMints[2]!);
  const packetCases = [packetCase0, packetCase1, packetCase2];
  const matchingPacketIndex = packetMints.indexOf(selectedMint);
  const standaloneCase = useTokenCaseFile(matchingPacketIndex === -1 ? selectedMint : null);
  const caseFile = matchingPacketIndex !== -1 ? packetCases[matchingPacketIndex]! : standaloneCase;
  const visibleCases = packetCases.filter((_, i) => packetMints[i] !== null);

  function openCase(mint: string) {
    setSelected(null);
    setSelectedMint(mint);
  }
  function openActor(id: ActorId) {
    setSelectedMint(null);
    setSelected(id);
  }

  // The office's staged life. The page owns it so the panels can say what a
  // clicked character is doing; the stage just draws the frames. Mobile never
  // creates the scheduler at all.
  const ambient = useAmbient(
    motion && viewport !== "mobile",
    state.operational,
    state.activity,
    phase,
  );
  const frames = ambient.frames;

  // "Provide updated report". The meeting animates on desktop and tablet with
  // motion allowed; mobile and reduced motion get the same report without the
  // walk, because the report is the point and the choreography is decoration.
  const meeting = useReportMeeting(state, ambient.scheduler, ambient.setOverride, {
    animate: motion && viewport !== "mobile",
  });

  const employee = selected ? EMPLOYEE_BY_ID.get(selected as EmployeeId) : null;
  const reading = employee && selected ? state.employees[selected as EmployeeId] : null;
  const supportNpc = !employee && selected ? SUPPORT_BY_ID.get(selected as SupportId) : null;
  const cat = !employee && !supportNpc && selected ? CAT_BY_ID.get(selected as CatId) : null;
  // A guest is clickable like everyone else on the floor. Without this the
  // panel silently showed nothing for them, which reads as a broken figure
  // rather than as a person who does not work here.
  const visitor =
    !employee && !supportNpc && !cat && selected
      ? VISITOR_BY_ID.get(selected as VisitorId)
      : null;
  const selectedFrame = selected ? frames[selected] : undefined;

  return (
    <div className="flex flex-col gap-6 p-4 lg:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">HQ</h1>
        <p className="max-w-2xl text-sm text-[var(--color-ink-3,var(--color-ink))]">
          MEMESCOPE drawn as the organisation it behaves like. Each desk is a
          subsystem.{" "}
          <strong className="font-medium text-[var(--color-ink)]">
            Anything unmeasured reads <em>No data</em>
          </strong>{" "}
          — never a healthy-looking guess.
        </p>
      </header>

      {/* `viewport` starts as null-ish on the server; rendering cards first and
          upgrading to the stage avoids a hydration mismatch and means a reader
          on a slow connection gets the readable version immediately. */}
      {viewport === "mobile" ? (
        <>
          <HqCards onSelectEmployee={openActor} state={state} showSummary={false} />
          <Boards state={state} />
          <RecentCases onSelectCase={openCase} />
        </>
      ) : (
        <>
          <HqStage
            focusedZone={focusedZone}
            onFocusZone={setFocusedZone}
            onSelectEmployee={openActor}
            density={viewport === "desktop" ? "full" : "reduced"}
            state={state}
            frames={frames}
            visibleCases={visibleCases}
            caseOverflow={overflow}
            onSelectCase={openCase}
          />
          {focusedZone ? (
            <button
              type="button"
              onClick={() => setFocusedZone(null)}
              className="self-start rounded-md border border-[var(--color-line)] px-3 py-1.5 text-xs text-[var(--color-ink)]"
            >
              Back to overview
            </button>
          ) : null}
          <Boards state={state} />
          <RecentCases onSelectCase={openCase} />
        </>
      )}

      <TodayAtHq state={state} />

      {/* Outside the viewport branch on purpose. Mobile does not render the
          animated meeting — see `useReportMeeting`'s `animate` flag — but it
          absolutely still gets the report, and a button that existed only on
          desktop would make the phone a second-class reader of the same
          facts. */}
      <ReportControl meeting={meeting} />

      {meeting.panelOpen && meeting.report ? (
        <ReportPanel
          report={meeting.report}
          transcript={meeting.said}
          onRefresh={meeting.refresh}
          onClose={meeting.close}
          live={meeting.phase === "meeting"}
        />
      ) : null}

      {selectedMint ? <CaseFilePanel file={caseFile} onClose={() => setSelectedMint(null)} /> : null}

      {employee ? (
        <Panel>
          <div className="flex flex-col gap-3 p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <Portrait id={employee.id} size={56} />
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                    {employee.name}
                  </h2>
                  <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                    {employee.role} ·{" "}
                    {ZONE_BY_ID.get(employee.zone)?.label ?? employee.zone}
                  </p>
                  <p className="mt-1 max-w-sm text-xs italic text-[var(--color-ink-3,var(--color-ink))] opacity-85">
                    {CHARACTERS[employee.id].personalityLine}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rounded-md border border-[var(--color-line)] px-2 py-1 text-xs text-[var(--color-ink)]"
              >
                Close
              </button>
            </div>

            <dl className="flex flex-col gap-2 text-xs">
              <div className="flex flex-col gap-0.5">
                <dt className="text-[var(--color-ink-3,var(--color-ink))]">Represents</dt>
                <dd className="text-[var(--color-ink)]">{employee.systemResponsibility}</dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-[var(--color-ink-3,var(--color-ink))]">Status</dt>
                <dd className="text-[var(--color-ink)]" data-testid="hq-panel-state">
                  {STATE_LABEL[reading?.state ?? "unknown"]} — {reading?.detail}
                </dd>
              </div>
            </dl>

            {/* Every figure names the field it came from. A metric without a
                source is a number a reader has to take on faith, and this room
                has to be checkable to be worth anything. A null renders NOT
                AVAILABLE rather than a dash, because a dash reads as zero. */}
            <table className="w-full text-left text-xs" data-testid="hq-panel-metrics">
              <tbody>
                {(reading?.metrics ?? []).map((metric) => (
                  <tr key={metric.label} className="border-t border-[var(--color-line)]">
                    <th
                      scope="row"
                      className="py-1 pr-3 font-normal text-[var(--color-ink-3,var(--color-ink))]"
                    >
                      {metric.label}
                    </th>
                    <td className="py-1 pr-3 text-[var(--color-ink)]">
                      {metric.value ?? (
                        <span className="text-[var(--color-ink-3,var(--color-ink))]">
                          NOT AVAILABLE
                        </span>
                      )}
                    </td>
                    <td className="py-1 text-[10px] text-[var(--color-ink-3,var(--color-ink))] opacity-75">
                      {metric.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

      {/* The personality panel for the office's non-operational residents.
          Deliberately no status chip, no metrics table and no state word: Maya,
          Sam and the cats are not measured, and their panel is a joke and a
          sentence about what the drawing is doing. The one structural rule is
          that "Currently:" reads from the same ambient frames the room draws,
          so the panel can never claim an activity the reader cannot see. */}
      {supportNpc || cat || visitor ? (
        <Panel>
          <div className="flex flex-col gap-3 p-4" data-testid="hq-life-panel">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                  {supportNpc?.name ?? cat?.name ?? visitor?.name}
                </h2>
                <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                  {supportNpc?.role ?? cat?.title ?? (visitor ? `Visiting from ${visitor.from}` : null)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rounded-md border border-[var(--color-line)] px-2 py-1 text-xs text-[var(--color-ink)]"
              >
                Close
              </button>
            </div>
            <dl className="flex flex-col gap-0.5 text-xs">
              <dt className="text-[var(--color-ink-3,var(--color-ink))]">Currently</dt>
              <dd className="text-[var(--color-ink)]">
                {selectedFrame?.detail ??
                  supportNpc?.restingDetail ??
                  cat?.restingDetail ??
                  visitor?.restingDetail}
              </dd>
            </dl>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

/**
 * Which of the three experiences to render.
 *
 * Starts as `mobile` on purpose. The server has no viewport, so the first paint
 * must be the version that is correct everywhere — the card stack works on a
 * desktop, whereas an isometric room does not work on a phone. Upgrading after
 * mount is the safe direction.
 */
/**
 * The report button, centred below the scene.
 *
 * Disabled for the whole of a meeting rather than only on the click that
 * starts one: the guard that actually prevents a second meeting is inside the
 * hook, and this is the affordance that says so. The label changes with the
 * phase because a button that looks pressable and does nothing reads as broken
 * — "Gathering the team" is what is happening, and it is worth a sentence.
 */
/**
 * Today at HQ.
 *
 * Rendered only when there is something to show. An empty timeline with a
 * "nothing yet" placeholder implies the platform was idle; in fact it means
 * no *trade* completed today, which is a much narrower statement and one the
 * heading already makes. Absent is more honest than empty here.
 */
function TodayAtHq({ state }: { state: HqState }) {
  const events = buildToday(state);
  if (events.length === 0) return null;
  return (
    <section className="hq-today" aria-label="Today at HQ">
      <h2 className="hq-today-title">TODAY AT HQ</h2>
      <p className="hq-today-note">
        Completed paper trades since 00:00 UTC, from the permanent record. Other
        desks publish a latest reading rather than an event log, so they are not
        listed here.
      </p>
      <ol className="hq-today-list">
        {events.map((event) => (
          <li key={`${event.at}-${event.label}`} className="hq-today-row">
            <time
              className="hq-today-time"
              dateTime={new Date(event.at).toISOString()}
            >
              {new Date(event.at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
            <Portrait id={event.who} size={22} />
            <span className="hq-today-label">{event.label}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ReportControl({ meeting }: { meeting: ReturnType<typeof useReportMeeting> }) {
  const label =
    meeting.phase === "idle"
      ? "PROVIDE UPDATED REPORT"
      : meeting.phase === "settling"
        ? "CLEARING THE FLOOR…"
        : meeting.phase === "gathering"
          ? "GATHERING THE TEAM…"
          : meeting.phase === "meeting"
            ? "MEETING IN PROGRESS…"
            : meeting.phase === "leaving"
              ? "RETURNING TO DESKS…"
              : "REPORT OPEN";
  return (
    <div className="flex justify-center">
      <button
        type="button"
        className="hq-report-cta"
        onClick={meeting.start}
        disabled={meeting.busy}
        aria-disabled={meeting.busy}
        data-testid="hq-report-button"
      >
        {label}
      </button>
    </div>
  );
}

function useViewport(): Viewport {
  const [viewport, setViewport] = useState<Viewport>("mobile");

  useEffect(() => {
    const read = () => {
      const width = window.innerWidth;
      if (width >= FULL_DENSITY_MIN_WIDTH) return setViewport("desktop");
      if (width >= STAGE_MIN_WIDTH) return setViewport("tablet");
      return setViewport("mobile");
    };
    read();
    window.addEventListener("resize", read);
    return () => window.removeEventListener("resize", read);
  }, []);

  return viewport;
}

/**
 * The boards, laid out as responsive rows.
 *
 * Rendered on every viewport including mobile, where the room is not drawn at
 * all: the isometric scene is the charming half of HQ, and these are the half
 * that has to survive without it. Someone on a phone gets the same facts.
 *
 * Two rows rather than one long one. The first is what the platform is doing;
 * the second is what HQ has done about it. Keeping them apart matters more
 * than saving a row of space — the audit trail is the panel that answers "did
 * something act on production", and it should not be something a reader finds
 * by scrolling past six wallet figures.
 */
function Boards({ state }: { state: HqState }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <MissionBoard state={state} />
        <PerformanceLab
          wallet={state.sources.paperWallet}
          security={state.sources.tokenSecurity}
          now={state.now}
        />
        <ExecutionVault source={state.sources.executionPosture} now={state.now} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <InfrastructureBoard operations={state.sources.operations} now={state.now} />
        <IncidentBoard operations={state.sources.operations} now={state.now} />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AutonomousActivity operations={state.sources.operations} now={state.now} />
        <OwnerInbox operations={state.sources.operations} now={state.now} />
      </div>
    </div>
  );
}
