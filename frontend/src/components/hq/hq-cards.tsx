"use client";

import { EMPLOYEES, STATE_LABEL, employeesInZone, type EmployeeId } from "@/lib/hq/employees";
import { CHARACTERS } from "@/lib/hq/characters";
import { Portrait } from "@/components/hq/portrait";
import { FOCUSABLE_ZONES } from "@/lib/hq/zones";
import { CATS } from "@/lib/hq/cats";
import { SUPPORT_STAFF } from "@/lib/hq/support";
import { employeesInZone as staffOf } from "@/lib/hq/employees";
import { Panel } from "@/components/ui/panel";
import { useDayPhase, useHqMotion, useHqPaused } from "@/components/hq/use-hq-env";
import { UNKNOWN_HQ_STATE, type HqState } from "@/lib/hq/adapter";

// The cast is drawn here too, so the stylesheet has to come with it. It is
// still route-scoped — nothing outside /hq imports this module, and the bundle
// tests assert that transitively.
import "@/styles/hq.css";

/**
 * HQ ON A SMALL SCREEN.
 *
 * Not the isometric room shrunk down. The plan is explicit: squeezing an
 * eight-department room into 375px produces something nobody can read, and a
 * scene that cannot be read is worse than no scene, because it still costs the
 * bandwidth and the battery.
 *
 * So mobile gets the same information in the form small screens are good at —
 * a card stack. Every operational fact the room would carry is here as text.
 * This is also what a screen reader gets on desktop, and what a reduced-motion
 * reader can fall back to, so it is not a lesser path: it is the accessible
 * one.
 *
 * HQ-1 shows structure and `No data`. There are no statistics on these cards
 * and there must never be an invented one.
 *
 * WHAT MOBILE GETS FROM HQ-3, AND WHAT IT DOES NOT
 *
 * The day/night theme and a portrait that breathes. That is the whole list.
 * The ambient scheduler, the walk routes and the isometric room are never
 * imported here, let alone mounted: a phone would be paying for ten characters
 * pathing around a scene it is not drawing. The personality cues that survive
 * are the ones that were already static — the portrait and the personality
 * line.
 *
 * OPERATIONAL STATE IS TEXT HERE, AS IT IS EVERYWHERE
 *
 * The cards take the same normalized `HqState` the room does and print it. No
 * second interpretation of a backend field, no phone-specific thresholds — the
 * adapter decided, and both surfaces read the decision. A card carries strictly
 * more of the truth than the room does, because it has space for the sentence
 * explaining why the state reads the way it does.
 */

interface HqCardsProps {
  onSelectEmployee: (id: EmployeeId) => void;
  /** The normalized office. Defaults to all-UNKNOWN, never to healthy. */
  state?: HqState;
  /**
   * Whether to draw the office-activity summary card.
   *
   * False when the full Mission Board is on the same page — it says the same
   * thing and more, and two panels with the same heading is clutter rather
   * than emphasis.
   */
  showSummary?: boolean;
}

export function HqCards({
  onSelectEmployee,
  state = UNKNOWN_HQ_STATE,
  showSummary = true,
}: HqCardsProps) {
  const motion = useHqMotion();
  const paused = useHqPaused();
  const phase = useDayPhase();

  return (
    <div
      className="flex flex-col gap-4"
      data-testid="hq-cards"
      data-hq-motion={motion ? "on" : "off"}
      data-hq-paused={paused ? "true" : "false"}
      data-hq-phase={phase}
    >
      {/* The office-activity summary.
          Suppressed when the full Mission Board is on the page, which it now
          always is: that board carries the same activity reading plus a row
          per subsystem, so rendering both put two panels headed "Mission
          Board" one above the other on a phone. Kept rather than deleted
          because it is still the right card for any surface that shows the
          cards without the boards. */}
      {showSummary ? (
        <Panel>
          <div className="flex flex-col gap-1 p-4">
            <h2 className="text-sm font-semibold text-[var(--color-ink)]">Mission Board</h2>
            <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
              Office activity{" "}
              <span className="font-medium text-[var(--color-ink)]" data-testid="hq-activity">
                {state.activity}
              </span>
            </p>
            <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
              {state.employees.nova.detail}
            </p>
          </div>
        </Panel>
      ) : null}

      {/* Operational departments only get full cards. The world-expansion
          spaces — pantry, lounge, conference room, deck, reception — have no
          operational staff and no state, so on a phone they compress into the
          two compact cards below rather than seven near-empty panels. */}
      {FOCUSABLE_ZONES.filter((zone) => staffOf(zone.id).length > 0).map((zone) => {
        const staff = employeesInZone(zone.id);
        return (
          <Panel key={zone.id}>
            <div className="flex flex-col gap-3 p-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                  {zone.label}
                </h2>
                <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                  {zone.summary}
                </p>
              </div>

              {staff.length === 0 ? null : (
                <ul className="flex flex-col gap-2">
                  {staff.map((employee, index) => (
                    <li
                      key={employee.id}
                      style={
                        {
                          // Staggered, so a column of portraits never breathes
                          // in unison. Same trick as the room.
                          "--hq-stagger": `${(index * 0.83).toFixed(2)}s`,
                        } as React.CSSProperties
                      }
                    >
                      <button
                        type="button"
                        onClick={() => onSelectEmployee(employee.id)}
                        className="flex w-full items-center justify-between gap-3 rounded-md border border-[var(--color-line)] px-3 py-2 text-left"
                        data-state={state.employees[employee.id].state}
                        aria-label={`${employee.name}, ${employee.role}. ${
                          STATE_LABEL[state.employees[employee.id].state]
                        }. ${state.employees[employee.id].detail}`}
                      >
                        <span className="flex items-center gap-3">
                          {/* A portrait rather than a miniature isometric
                              figure: at this size a full body is a smudge, but
                              a head still carries the hair, the build and the
                              accessory that identify someone. */}
                          <Portrait id={employee.id} size={40} />
                          <span className="flex flex-col">
                            <span className="text-sm text-[var(--color-ink)]">
                              {employee.name}
                            </span>
                            <span className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
                              {employee.role}
                            </span>
                            <span className="text-[11px] text-[var(--color-ink-3,var(--color-ink))] opacity-80">
                              {CHARACTERS[employee.id].personalityLine}
                            </span>
                            {/* Why the state reads the way it does. The room
                                has no space for this; a card does, and it is
                                the difference between a status and an
                                explanation. */}
                            <span className="text-[11px] text-[var(--color-ink-3,var(--color-ink))]">
                              {state.employees[employee.id].detail}
                            </span>
                          </span>
                        </span>
                        {/* Text, not a coloured dot. A status conveyed only by
                            colour is unreadable to a large minority of readers,
                            and `No data` is the state that matters most to
                            state plainly. */}
                        <span className="shrink-0 rounded border border-dashed border-[var(--color-line)] px-2 py-0.5 text-[11px] text-[var(--color-ink-3,var(--color-ink))]">
                          {STATE_LABEL[state.employees[employee.id].state]}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Panel>
        );
      })}

      <Panel>
        <div className="flex flex-col gap-1 p-4" data-testid="hq-around">
          <h2 className="text-sm font-semibold text-[var(--color-ink)]">Around the office</h2>
          <p className="text-xs text-[var(--color-ink-3,var(--color-ink))]">
            {FOCUSABLE_ZONES.filter((zone) => staffOf(zone.id).length === 0)
              .map((zone) => zone.label)
              .join(" · ")}
          </p>
        </div>
      </Panel>

      {/* The rest of the household. Names and roles as text — no chips, no
          states: nothing here is measured, and a phone reader deserves the
          same honesty about that as a desktop one. */}
      <Panel>
        <div className="flex flex-col gap-2 p-4" data-testid="hq-office-life">
          <h2 className="text-sm font-semibold text-[var(--color-ink)]">Office life</h2>
          <ul className="flex flex-col gap-1 text-xs">
            {SUPPORT_STAFF.map((npc) => (
              <li key={npc.id} className="flex justify-between gap-3">
                <span className="text-[var(--color-ink)]">{npc.name}</span>
                <span className="text-[var(--color-ink-3,var(--color-ink))]">{npc.role}</span>
              </li>
            ))}
            {CATS.map((cat) => (
              <li key={cat.id} className="flex justify-between gap-3">
                <span className="text-[var(--color-ink)]">{cat.name}</span>
                <span className="text-[var(--color-ink-3,var(--color-ink))]">Office cat</span>
              </li>
            ))}
          </ul>
        </div>
      </Panel>
    </div>
  );
}

/** Used by the page's accessible summary and by tests. */
export const HQ_EMPLOYEE_COUNT = EMPLOYEES.length;
