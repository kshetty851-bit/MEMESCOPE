"use client";

import type { CaseStageStatus } from "@/lib/hq/case-file";
import type { CaseOverallState, TokenCaseFile } from "@/lib/hq/case-file";
import { EMPLOYEE_BY_ID } from "@/lib/hq/employees";
import { toScreen } from "@/lib/hq/geometry";
import type { EmployeeId } from "@/lib/hq/employees";

/**
 * THE TOKEN CASE PACKET.
 *
 * A small dossier icon rather than "a coin bouncing around the office" — the
 * brief is explicit that the office's cartoon warmth must not turn a case
 * into a toy. It is a rounded tag: a two-letter mark from the symbol, a
 * status dot in the same status vocabulary the employee state chips already
 * use, and nothing else. No numbers are drawn on it — consistent with every
 * other instrument in the room, a figure here would look measured whether or
 * not it was.
 *
 * WHERE IT SITS
 *
 * Docked beside whichever employee's desk corresponds to the case's current
 * stage — never animated through a stage the case has no evidence for. The
 * `decision` stage has no desk of its own (§10's panel lists it as a row
 * between Atlas and Rex, not a department); it docks at Rex's desk, one step
 * ahead of `execution`, because that is the real next stop in the pipeline
 * and it is the honest place to put a case still waiting on evidence nobody
 * has published.
 *
 * MOVEMENT
 *
 * A CSS `transform` from the anchor's own screen position, exactly the
 * `.hq-walker` pattern the cast already uses — so a case moving from Radar's
 * desk to Luna's is one compositor-only transition, not a hand-authored path.
 * Reduced motion removes the transition and the packet simply appears at its
 * current dock, which is why the same component serves both.
 */

const STAGE_ANCHOR: Record<keyof TokenCaseFile["stages"], EmployeeId> = {
  discovery: "radar",
  scoring: "luna",
  market: "dex",
  safety: "atlas",
  decision: "rex",
  execution: "rex",
};

/** Small per-employee offsets so packets from different stages never overlap
 * an employee's own desk instruments or nameplate, and two packets docked at
 * the same desk (decision → execution) still read as distinct. */
const DOCK_OFFSET: Partial<Record<EmployeeId, { x: number; y: number }>> = {
  rex: { x: -46, y: -18 },
};
const DEFAULT_OFFSET = { x: -46, y: -46 };

export function packetDockTile(stage: keyof TokenCaseFile["stages"]) {
  const employee = EMPLOYEE_BY_ID.get(STAGE_ANCHOR[stage])!;
  return employee.desk;
}

function statusClass(status: CaseStageStatus): string {
  switch (status) {
    case "PASSED":
      return "hq-packet--passed";
    case "FAILED":
      return "hq-packet--failed";
    case "PENDING":
      return "hq-packet--pending";
    // An unverifiable token gets its own mark rather than borrowing the
    // passed one. A packet that reached Atlas and could not be cleared must
    // never animate as a pass — see `case-file.ts`.
    case "UNKNOWN":
      return "hq-packet--unknown";
    case "UNAVAILABLE":
      return "hq-packet--unavailable";
  }
}

function mark(symbol: string | null, mint: string): string {
  const from = symbol ?? mint;
  return from.slice(0, 3).toUpperCase();
}

export interface TokenPacketProps {
  file: TokenCaseFile;
  motion: boolean;
  onSelect: (mint: string) => void;
  /**
   * How many other visible packets share this same dock. `decision` and
   * `execution` both anchor at Rex, so with three visible packets two could
   * legitimately land on the same desk at once — this stacks them instead
   * of letting them overlap.
   */
  stackIndex?: number;
}

export function TokenPacket({ file, motion, onSelect, stackIndex = 0 }: TokenPacketProps) {
  const employee = EMPLOYEE_BY_ID.get(STAGE_ANCHOR[file.currentStage])!;
  const base = DOCK_OFFSET[employee.id] ?? DEFAULT_OFFSET;
  const offset = { x: base.x, y: base.y - stackIndex * 26 };
  const anchor = toScreen(employee.desk);
  const status = file.stages[file.currentStage].status;
  const label = `${file.symbol ?? file.mint.slice(0, 6)}, case file. ${file.overallState}. Currently at ${file.currentStage}: ${status}.`;

  return (
    <g
      className={`hq-packet ${statusClass(status)}`}
      data-packet-stage={file.currentStage}
      data-motion={motion ? "on" : "off"}
      transform={`translate(${anchor.x + offset.x} ${anchor.y + offset.y})`}
      role="button"
      tabIndex={0}
      aria-label={label}
      onClick={() => onSelect(file.mint)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(file.mint);
        }
      }}
    >
      <rect className="hq-packet-body" x={-16} y={-11} width={32} height={22} rx={5} />
      <circle className="hq-packet-dot" cx={11} cy={-6} r={3} />
      <text className="hq-packet-mark" x={-2} y={4} textAnchor="middle">
        {mark(file.symbol, file.mint)}
      </text>
    </g>
  );
}

/**
 * The overflow badge: a real count of real recent cases beyond the three
 * shown, or nothing at all. Docked near Nova's console — the mission-wide
 * summary position — rather than at any one employee's desk, since it
 * describes the whole pipeline's throughput and not one stage.
 */
export function PacketOverflowBadge({ count }: { count: number }) {
  const anchor = toScreen({ col: 8, row: 1 });
  return (
    <g
      className="hq-packet-overflow"
      transform={`translate(${anchor.x + 58} ${anchor.y - 30})`}
      aria-hidden="true"
    >
      <rect className="hq-packet-body hq-packet-body--overflow" x={-16} y={-11} width={32} height={22} rx={11} />
      <text className="hq-packet-mark" x={0} y={4} textAnchor="middle">
        +{count}
      </text>
    </g>
  );
}

export type { CaseOverallState };
