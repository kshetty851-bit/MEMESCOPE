"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { HqCards } from "@/components/hq/hq-cards";
import { Portrait } from "@/components/hq/portrait";
import { useAmbient } from "@/components/hq/use-ambient";
import { useDayPhase, useHqMotion } from "@/components/hq/use-hq-env";
import { useHqState } from "@/components/hq/use-hq-state";
import type { HqState } from "@/lib/hq/adapter";
import { useTokenCaseFile, useVisiblePackets } from "@/components/hq/use-token-cases";
import { CaseFilePanel } from "@/components/hq/case-file-panel";
import { RecentCases } from "@/components/hq/recent-cases";
import { ExecutionVault, MissionBoard, PerformanceLab } from "@/components/hq/hq-boards";
import { CAT_BY_ID, type CatId } from "@/lib/hq/cats";
import { SUPPORT_BY_ID, type SupportId } from "@/lib/hq/support";
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
  const frames = useAmbient(
    motion && viewport !== "mobile",
    state.operational,
    state.activity,
    phase,
  );

  const employee = selected ? EMPLOYEE_BY_ID.get(selected as EmployeeId) : null;
  const reading = employee && selected ? state.employees[selected as EmployeeId] : null;
  const supportNpc = !employee && selected ? SUPPORT_BY_ID.get(selected as SupportId) : null;
  const cat = !employee && !supportNpc && selected ? CAT_BY_ID.get(selected as CatId) : null;
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
      {supportNpc || cat ? (
        <Panel>
          <div className="flex flex-col gap-3 p-4" data-testid="hq-life-panel">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                  {supportNpc?.name ?? cat?.name}
                </h2>
                <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                  {supportNpc?.role ?? cat?.title}
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
                  cat?.restingDetail}
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
 * The three boards, laid out as one responsive row.
 *
 * Rendered on every viewport including mobile, where the room is not drawn at
 * all: the isometric scene is the charming half of HQ, and these are the half
 * that has to survive without it. Someone on a phone gets the same facts.
 */
function Boards({ state }: { state: HqState }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <MissionBoard state={state} />
      <PerformanceLab
        wallet={state.sources.paperWallet}
        security={state.sources.tokenSecurity}
        now={state.now}
      />
      <ExecutionVault source={state.sources.executionPosture} now={state.now} />
    </div>
  );
}
