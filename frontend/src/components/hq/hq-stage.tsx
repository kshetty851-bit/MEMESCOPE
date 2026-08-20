"use client";

import { useMemo } from "react";

import {
  GRID_COLS,
  GRID_ROWS,
  LAYER,
  ROOM_H,
  ROOM_W,
  TILE_H,
  depthOf,
  rectPolygon,
  toScreen,
} from "@/lib/hq/geometry";
import { EMPLOYEES, STATE_LABEL, type EmployeeId } from "@/lib/hq/employees";
import { CHARACTERS, SEATED_AWAY_POSES, STANDING_POSES } from "@/lib/hq/characters";
import { Character, RigDefs } from "@/components/hq/character-rig";
import { CatSprite } from "@/components/hq/cat-rig";
import { Desk, DeskInstruments } from "@/components/hq/desks";
import { OfficeProp, WallDecor, type FloorProp } from "@/components/hq/office-props";
import { FURNITURE, RUGS, type RugSpec } from "@/lib/hq/furniture";
import { CATS } from "@/lib/hq/cats";
import type { CatPose } from "@/lib/hq/cats";
import { SUPPORT_STAFF } from "@/lib/hq/support";
import { PacketOverflowBadge, TokenPacket, packetDockTile } from "@/components/hq/token-packet";
import type { TokenCaseFile } from "@/lib/hq/case-file";
import { ZONES, ZONE_BY_ID, type ZoneId } from "@/lib/hq/zones";
import type { ActorId } from "@/lib/hq/ambient-scheduler";
import type { ActorFrame } from "@/lib/hq/ambient";
import { UNKNOWN_HQ_STATE, type HqState, type OfficeActivity } from "@/lib/hq/adapter";
import { useDayPhase, useHqMotion, useHqPaused } from "@/components/hq/use-hq-env";
import type { EmployeeState } from "@/lib/hq/employees";
import type { Pose } from "@/lib/hq/characters";

import "@/styles/hq.css";

/**
 * THE ISOMETRIC ROOM.
 *
 * One SVG. Not a stack of positioned divs — SVG gives painter's-order control
 * through document order, which is exactly what an isometric scene needs, and
 * it scales to any container without the tile size becoming fractional.
 *
 * WHAT HQ-1 DRAWS
 *
 * Floor plates, walls, the station window, desks, screens, and ten *anchors*
 * where the characters will stand. The anchors are deliberately crude: a
 * coloured capsule with an initial. The point of this phase is to get the floor
 * plan and the layering right and have it reviewed before any character art
 * exists, because a beautiful character standing in the wrong department is a
 * more expensive mistake to find later.
 *
 * WHERE THE STATE COMES FROM
 *
 * A prop, and only a prop. The stage reads no backend field, issues no query
 * and interprets no health value: it is handed one already-normalized
 * `HqState` and draws it. That is what keeps the room and the mobile card
 * stack from ever disagreeing, and it is why this component still renders
 * standalone in a test with no query client anywhere near it.
 *
 * Its default is the all-UNKNOWN state. A stage that defaulted to anything
 * else would be claiming something on behalf of a backend nobody asked.
 *
 * WHAT MOVES, AND WHAT IT IS ALLOWED TO MEAN
 *
 * HQ-3 adds ambient life: people shift pose, walk short predefined routes,
 * visit the break room and occasionally speak to a colleague, and the room
 * lights itself for the time of day. None of it is a measurement. A walking
 * Byte does not mean the database is busy and a still Atlas does not mean risk
 * review is idle — every state chip still reads `No data`, which is the line
 * that carries the truth. Ambient motion is the bottom of the priority stack
 * the plan sets out, and HQ-4's real states will sit above it.
 */

/**
 * Vertical space above the floor's north corner.
 *
 * The walls, the station window and the mission board all sit at negative y —
 * they rise *from* the floor — so a viewBox starting at 0 clips them. Sized to
 * the tallest fixture with margin. Tightened once the walls came down to a
 * tile and a half: the surplus was empty sky above a shorter room, and every
 * unit of it shrank the office inside the frame. The characters are the point
 * and they are only ever as large as the fit-scale allows.
 */
const HEADROOM = 130;

interface HqStageProps {
  /** Which department is focused, or null for the overview. */
  focusedZone: ZoneId | null;
  onFocusZone: (zone: ZoneId | null) => void;
  /**
   * Any resident of the office: an employee, Maya, Sam, or a cat. The page
   * decides what the panel for each looks like; the stage only reports who
   * was picked.
   */
  onSelectEmployee: (id: ActorId) => void;
  /** Tablet drops ambient detail to keep the element count down. */
  density: "full" | "reduced";
  /** The normalized office, from `deriveHqState`. Never raw backend fields. */
  state?: HqState;
  /**
   * Current ambient frames for every actor, from the page's scheduler hook.
   * The stage renders whatever it is handed and runs no timers of its own —
   * which is what keeps it a pure drawing of two inputs: the office's real
   * state, and the office's staged life.
   */
  frames?: Partial<Record<ActorId, ActorFrame>>;
  /** Up to three case files, from the page's `useVisiblePackets`. */
  visibleCases?: TokenCaseFile[];
  /** A real overflow count, or null when none exists — never a guess. */
  caseOverflow?: number | null;
  onSelectCase?: (mint: string) => void;
}

export function HqStage({
  focusedZone,
  onFocusZone,
  onSelectEmployee,
  density,
  state = UNKNOWN_HQ_STATE,
  frames = {},
  visibleCases = [],
  caseOverflow = null,
  onSelectCase = () => {},
}: HqStageProps) {
  const motion = useHqMotion();
  const paused = useHqPaused();
  const phase = useDayPhase();
  const ambient = frames;

  // The still life is memoised; the cast is not. Furniture never moves, but a
  // walker's depth follows their current tile, so people and furniture are
  // merged and re-sorted per render — the deterministic isometric ordering the
  // earlier phases deferred. Sixty-odd nodes; the sort is nothing.
  const painted = useMemo(
    () => buildScene(density, state.activity, visibleCases.length),
    [density, state.activity, visibleCases.length],
  );
  // Packets never travel during HIGH_ALERT: the room's own readability wins,
  // per the brief — a token gliding across the floor is not what a reader
  // needs while the office is telling them something is actually wrong. The
  // packets themselves stay visible and clickable; only the transition stops.
  const packetMotion = motion && state.activity !== "HIGH_ALERT";
  const scene = [...painted, ...buildCast(ambient, state, focusedZone, onSelectEmployee)].sort(
    (a, b) => a.depth - b.depth,
  );

  return (
    <div
      className="hq"
      data-hq-motion={motion ? "on" : "off"}
      data-hq-paused={paused ? "true" : "false"}
      data-hq-phase={phase}
      data-hq-activity={state.activity}
    >
      <div className="hq-stage">
        <svg
          className="hq-room"
          viewBox={`0 ${-HEADROOM} ${ROOM_W} ${ROOM_H + HEADROOM + TILE_H}`}
          role="img"
          aria-label={roomDescription(state)}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* No <title>. It is the SVG equivalent of a tooltip and the browser
              rendered it as a grey "MEMESCOPE HQ floor plan" badge floating
              over the room whenever a pointer crossed the scene. The
              accessible name is already carried by `role="img"` +
              `aria-label` above, which is both richer and silent. */}
          <RigDefs />

          {/* The planet in the void beyond the deck. Behind everything,
              including the floor: it is scenery outside the hull. */}
          {density === "full" ? <VoidPlanet /> : null}

          {/* Walls first: they sit behind everything and never overlap. */}
          <BackWalls />
          {density === "full" ? <WallArt /> : null}
          {density === "full" ? <StationWindow /> : null}
          {density === "full" ? <SpaceTraffic /> : null}

          {/* Floor plates, one per department. */}
          {ZONES.map((zone) => (
            <polygon
              key={zone.id}
              className={`hq-plate hq-plate--${zone.surface}`}
              points={rectPolygon(zone.rect)}
              data-zone={zone.id}
              opacity={focusedZone && focusedZone !== zone.id ? 0.45 : 1}
            />
          ))}

          {/* Clipped to the floor plates: the grid must not draw lines
              across the open space beyond the hull. */}
          <clipPath id="hq-floor-clip">
            {ZONES.map((zone) => (
              <polygon key={`clip-${zone.id}`} points={rectPolygon(zone.rect)} />
            ))}
          </clipPath>
          {density === "full" ? (
            <g clipPath="url(#hq-floor-clip)">
              <GridLines />
            </g>
          ) : null}

          {/* The deck's railing and airlock, and the conference room's glass.
              Architecture rather than furniture: they belong to the rooms, not
              to the depth-sorted contents. */}
          <DeckRailing />
          <ConferenceGlass />
          <VaultShell />
          <CirculationSpine />

          {/* Department signage, on the floor and under the furniture.

              Under, deliberately: a sign painted on the floor *should* be
              occluded by a desk standing on it, and lifting these above the
              cast would put ten labels through the middle of the people. What
              changed is that they now read as signs — a plate behind the word,
              at full contrast — rather than as the faint grey captions of a
              debug floor plan. */}
          {ZONES.filter((zone) => zone.id !== "walkway").map((zone) => {
            // The south corner, not the centre and not the north one. A
            // department's centre is exactly where its staff stand, and its
            // north corner is where their desks and mounted screens are. The
            // south vertex is the boundary with the next department: always
            // clear floor, and it reads as a caption beneath the room it names.
            //
            // A full-width band is the exception: its centre is the room's
            // centre, which is always the busiest tile. Those label at a
            // quarter across instead. A rule rather than a special case, so a
            // future full-width zone gets the same treatment for free.
            const fullWidth = zone.rect.cols === GRID_COLS;
            const corner = toScreen({
              col: zone.rect.col + zone.rect.cols * (fullWidth ? 0.25 : 0.5),
              row: zone.rect.row + zone.rect.rows,
            });
            // Sized from the string rather than measured: this is a cartoon
            // sign, and an approximation that is always slightly generous
            // reads better than a box that occasionally clips a descender.
            const width = zone.label.length * 7.2 + 22;
            return (
              <g key={`label-${zone.id}`} className="hq-zone-sign">
                <rect
                  className="hq-zone-sign-plate"
                  x={corner.x - width / 2}
                  y={corner.y - 20}
                  width={width}
                  height={18}
                  rx={9}
                />
                <text className="hq-zone-label" x={corner.x} y={corner.y - 7.5}>
                  {zone.label}
                </text>
              </g>
            );
          })}

          {/* Everything with depth — furniture and cast together, painted
              back to front. One list, one ordering rule: a person behind a
              bookshelf paints behind it, the same person two steps later
              paints in front. */}
          {scene.map((item) => item.node)}

          {/* Token case packets, above every desk and every character —
              always the topmost readable layer, since a case in progress is
              exactly what a reader clicked into this room to find. Docked
              packets are grouped by employee so two sharing Rex's desk stack
              rather than overlap. */}
          {visibleCases.length > 0 || caseOverflow ? (
            <g className="hq-packets">
              {(() => {
                const perDock = new Map<string, number>();
                return visibleCases.map((file) => {
                  const dock = packetDockTile(file.currentStage);
                  const key = `${dock.col},${dock.row}`;
                  const stackIndex = perDock.get(key) ?? 0;
                  perDock.set(key, stackIndex + 1);
                  return (
                    <TokenPacket
                      key={file.mint}
                      file={file}
                      motion={packetMotion}
                      onSelect={onSelectCase}
                      stackIndex={stackIndex}
                    />
                  );
                });
              })()}
              {caseOverflow ? <PacketOverflowBadge count={caseOverflow} /> : null}
            </g>
          ) : null}

          {/* Transparent hit areas for department focus, above the floor and
              below nothing that matters — clicks on a person are handled by the
              person, because their group paints later.

              Reachable by keyboard and named for a screen reader, exactly as
              the employee anchors are. They were mouse-only: every member of
              staff could be tabbed to and heard, while the departments they
              work in could not, so half the room was unreachable without a
              pointer. `aria-pressed` carries the focused state, because
              "Mission Control" and "Mission Control, currently focused" are
              different things to someone who cannot see the dimming. */}
          {ZONES.filter((zone) => zone.id !== "walkway").map((zone) => (
            <polygon
              key={`hit-${zone.id}`}
              points={rectPolygon(zone.rect)}
              fill="transparent"
              style={{ cursor: "pointer" }}
              role="button"
              tabIndex={0}
              aria-label={`${zone.label}. ${zone.summary}`}
              aria-pressed={focusedZone === zone.id}
              onClick={() => onFocusZone(focusedZone === zone.id ? null : zone.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onFocusZone(focusedZone === zone.id ? null : zone.id);
                }
              }}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------ */

/**
 * A rug: a field and an inset border, no pattern. A busy floor would compete
 * with the status chips standing on it, and the chips have to win.
 */
function Rug({ rect }: { rect: RugSpec }) {
  const inset = {
    col: rect.col + 0.35,
    row: rect.row + 0.35,
    cols: rect.cols - 0.7,
    rows: rect.rows - 0.7,
  };
  return (
    <g className={rect.warm ? "hq-rug hq-rug--warm" : "hq-rug"} aria-hidden="true">
      <polygon className="hq-rug-field" points={rectPolygon(rect)} />
      <polygon className="hq-rug-inner" points={rectPolygon(inset)} />
    </g>
  );
}

/**
 * Everyone who lives here, as depth-sorted scene nodes.
 *
 * Employees carry operational state and a full nameplate; support staff carry
 * a name and a role — deliberately no state chip, because "No data" on Maya
 * would claim she was measured; cats carry only themselves. All three are the
 * same pattern: an anchor at a home point, a walker offset to the current
 * frame's tile, a focusable group with a text description.
 */
function buildCast(
  ambient: Partial<Record<ActorId, ActorFrame>>,
  state: HqState,
  focusedZone: ZoneId | null,
  onSelect: (id: ActorId) => void,
): Painted[] {
  const items: Painted[] = [];
  const dimOthers = focusedZone !== null;

  EMPLOYEES.forEach((employee, index) => {
    const frame = ambient[employee.id];
    const tile = frame?.tile ?? employee.desk;
    items.push({
      depth: depthOf(tile, LAYER.employee),
      node: (
        <EmployeeAnchor
          key={employee.id}
          employee={employee}
          index={index}
          frame={frame}
          reading={state.employees[employee.id]}
          dimmed={focusedZone !== null && focusedZone !== employee.zone}
          onSelect={onSelect}
        />
      ),
    });
  });

  for (const npc of SUPPORT_STAFF) {
    const frame = ambient[npc.id];
    const tile = frame?.tile ?? npc.home;
    items.push({
      depth: depthOf(tile, LAYER.employee),
      node: (
        <SupportAnchor key={npc.id} npc={npc} frame={frame} dimmed={dimOthers} onSelect={onSelect} />
      ),
    });
  }

  for (const cat of CATS) {
    const frame = ambient[cat.id];
    const tile = frame?.tile ?? cat.home;
    items.push({
      // One layer above the people, so a cat sitting beside a seated figure
      // paints in front of their chair rather than inside it.
      depth: depthOf(tile, LAYER.overlay),
      node: <CatAnchor key={cat.id} cat={cat} frame={frame} dimmed={dimOthers} onSelect={onSelect} />,
    });
  }

  return items;
}

/**
 * Figures are drawn 36% larger than their HQ-2 geometry. The floor grew from
 * 16×12 to 22×14 tiles and the fit-scale shrank with it; the cast must not
 * shrink into decorations, so they take some of that space back. One constant
 * on a wrapper group — the rig's own geometry is untouched.
 *
 * Raised from 1.16 in the composition pass. At 1.16 the people were smaller
 * than the desks they stood at, which is the single clearest way to make a
 * workplace read as furniture with figurines placed on it rather than as a
 * room with staff in it. Chunky proportions are the house style; the cast
 * should be the first thing the eye lands on.
 */
const FIGURE_SCALE = 1.36;

/**
 * A short line above someone's head.
 *
 * SVG rather than an HTML overlay: the stage is one `<svg>` with its own
 * fit-scale, and a positioned div would need the tile→screen maths duplicated
 * outside it and would drift the moment the room resized. Inside the figure's
 * own group it simply travels with the person.
 *
 * Width is measured in characters rather than by the browser, because reading
 * layout during a paint is what turns ten simultaneous bubbles into a
 * reflow storm. `report.ts` caps a line at 64 characters and a test enforces
 * it, so the estimate cannot be badly wrong.
 *
 * `aria-hidden`: the words are already in the report panel and the transcript,
 * as text, in reading order. Announcing them again from a moving graphic would
 * be the same fact twice, the second time out of order.
 */
function SpeechBubble({ text }: { text: string }) {
  const width = Math.min(230, Math.max(74, text.length * 6.4 + 20));
  return (
    <g className="hq-bubble" transform={`translate(${-width / 2} -74)`} aria-hidden="true">
      <rect
        width={width}
        height={30}
        rx={9}
        className="hq-bubble-body"
      />
      <path d={`M ${width / 2 - 6} 30 L ${width / 2} 39 L ${width / 2 + 6} 30 Z`} className="hq-bubble-body" />
      <text x={width / 2} y={19.5} textAnchor="middle" className="hq-bubble-text">
        {text}
      </text>
    </g>
  );
}

function keySelect(onSelect: (id: ActorId) => void, id: ActorId) {
  return (event: React.KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id);
    }
  };
}

function EmployeeAnchor({
  employee,
  index,
  frame,
  reading,
  dimmed,
  onSelect,
}: {
  employee: (typeof EMPLOYEES)[number];
  index: number;
  frame: ActorFrame | undefined;
  reading: HqState["employees"][EmployeeId];
  dimmed: boolean;
  onSelect: (id: ActorId) => void;
}) {
  const point = toScreen(employee.desk);
  const character = CHARACTERS[employee.id];
  // Ambient first when there is one: an employee who has just been called
  // back to work is mid-walk-home, and the walk is the frame. Otherwise the
  // real state picks the posture, falling back to the resting pose.
  const pose = (frame?.pose as Pose) ?? OPERATIONAL_POSE[reading.state] ?? character.defaultPose;

  const away = frame?.tile
    ? { x: toScreen(frame.tile).x - point.x, y: toScreen(frame.tile).y - point.y }
    : null;
  // Away from the desk, a desk-bound pose stands up — except the lounge
  // poses, which sit on the furniture that exists at the destination.
  const stance =
    away !== null && !STANDING_POSES.has(pose) && !SEATED_AWAY_POSES.has(pose)
      ? ("standing" as const)
      : undefined;

  return (
    <g
      className="hq-anchor"
      data-state={reading.state}
      data-employee={employee.id}
      data-pose={pose}
      data-away={away ? "true" : "false"}
      transform={`translate(${point.x} ${point.y})`}
      opacity={dimmed ? 0.4 : 1}
      style={
        {
          "--hq-anchor-color": `var(--hq-${employee.palette})`,
          // Staggered so the resting figures never breathe in unison, which
          // is what turns ten idle people into one machine.
          "--hq-stagger": `${(index * 0.73).toFixed(2)}s`,
        } as React.CSSProperties
      }
      role="button"
      tabIndex={0}
      /* The accessible name carries the operational state and the sentence
         behind it — never the pose. Ambient motion is decoration and must not
         reach a screen reader; the state and its reason are the facts, and
         they are text. */
      aria-label={`${employee.name}, ${employee.role}. ${STATE_LABEL[reading.state]}. ${reading.detail}`}
      onClick={() => onSelect(employee.id)}
      onKeyDown={keySelect(onSelect, employee.id)}
    >
      <g
        className="hq-walker"
        style={away ? { transform: `translate(${away.x}px, ${away.y}px)` } : undefined}
      >
        {frame?.speech ? <SpeechBubble text={frame.speech} /> : null}
        <g transform={`scale(${FIGURE_SCALE})`}>
          <Character character={character} pose={pose} stance={stance} egg={(frame as { egg?: never } | undefined)?.egg} />
        </g>
        {frame?.carry === "trolley" ? <Trolley /> : null}
        {frame?.carry === "box" ? <CarriedBox /> : null}
        {/* Name and a state dot, above the head — the only band in this scene
            that is reliably empty.

            It used to be a two-line plate carrying the state as a word, and
            ten of those floating over the room was the single loudest reason
            the office read as SVG objects on a plan rather than a place: the
            labels competed with the people wearing them. The dot keeps the
            state legible at a glance and the full sentence still lives one
            click away in the employee panel, where there is room to say it
            properly. */}
        <rect className="hq-nameplate" x={-30} y={-126} width={60} height={15} rx={7.5} />
        <circle className="hq-anchor-dot" cx={-20} cy={-118.5} r={3.2} />
        <text className="hq-anchor-name" x={4} y={-115}>
          {employee.name}
        </text>
      </g>
    </g>
  );
}

function SupportAnchor({
  npc,
  frame,
  dimmed,
  onSelect,
}: {
  npc: (typeof SUPPORT_STAFF)[number];
  frame: ActorFrame | undefined;
  dimmed: boolean;
  onSelect: (id: ActorId) => void;
}) {
  const point = toScreen(npc.home);
  const pose = (frame?.pose as Pose) ?? npc.look.defaultPose;
  const away = frame?.tile
    ? { x: toScreen(frame.tile).x - point.x, y: toScreen(frame.tile).y - point.y }
    : null;

  return (
    <g
      className="hq-anchor hq-anchor--support"
      data-support={npc.id}
      data-pose={pose}
      transform={`translate(${point.x} ${point.y})`}
      opacity={dimmed ? 0.4 : 1}
      role="button"
      tabIndex={0}
      /* Name, role, and what they are doing. Deliberately no state word from
         the operational vocabulary: support staff are not measured, and a
         chip reading "No data" would claim somebody tried to measure them. */
      aria-label={`${npc.name}, ${npc.role}. ${frame?.detail ?? npc.restingDetail}`}
      onClick={() => onSelect(npc.id)}
      onKeyDown={keySelect(onSelect, npc.id)}
    >
      <g
        className="hq-walker"
        style={away ? { transform: `translate(${away.x}px, ${away.y}px)` } : undefined}
      >
        <g transform={`scale(${FIGURE_SCALE})`}>
          <Character character={npc.look} pose={pose} />
        </g>
        {frame?.carry === "trolley" ? <Trolley /> : null}
        {frame?.carry === "box" ? <CarriedBox /> : null}
        {/* Support staff carry the same pill as the cast, minus the state
            dot: they have no operational state to report, and inventing a
            neutral one for them would put a status light on somebody who is
            not a subsystem. Their role stays on the click panel. */}
        <rect className="hq-nameplate" x={-30} y={-126} width={60} height={15} rx={7.5} />
        <text className="hq-anchor-name hq-anchor-name--centred" x={0} y={-115}>
          {npc.name}
        </text>
      </g>
    </g>
  );
}

function CatAnchor({
  cat,
  frame,
  dimmed,
  onSelect,
}: {
  cat: (typeof CATS)[number];
  frame: ActorFrame | undefined;
  dimmed: boolean;
  onSelect: (id: ActorId) => void;
}) {
  const point = toScreen(cat.home);
  const pose = (frame?.pose as CatPose) ?? cat.restingPose;
  const away = frame?.tile
    ? { x: toScreen(frame.tile).x - point.x, y: toScreen(frame.tile).y - point.y }
    : null;

  return (
    <g
      className="hq-anchor hq-anchor--cat"
      data-cat={cat.id}
      data-pose={pose}
      transform={`translate(${point.x} ${point.y})`}
      opacity={dimmed ? 0.5 : 1}
      role="button"
      tabIndex={0}
      aria-label={`${cat.name}, office cat. ${frame?.detail ?? cat.restingDetail}`}
      onClick={() => onSelect(cat.id)}
      onKeyDown={keySelect(onSelect, cat.id)}
    >
      <g
        className="hq-walker hq-walker--cat"
        style={away ? { transform: `translate(${away.x}px, ${away.y}px)` } : undefined}
      >
        <CatSprite cat={cat} pose={pose} />
      </g>
    </g>
  );
}

/** Maya's trolley, drawn beside her while a cleaning round is under way. */
function Trolley() {
  return (
    <g className="hq-trolley" aria-hidden="true" transform="translate(24 0)">
      <ellipse className="hq-prop-shadow" cx={0} cy={2} rx={16} ry={4.5} />
      <polygon className="hq-counter-front" points="-14,-26 10,-14 10,2 -14,-10" />
      <polygon className="hq-counter-side" points="10,-14 16,-17 16,-1 10,2" />
      <polygon className="hq-white" points="-14,-26 -8,-29 16,-17 10,-14" />
      <rect className="hq-cloth" x={-11} y={-24} width={7} height={5} rx={1} />
      <rect className="hq-bin" x={2} y={-24} width={8} height={7} rx={1.5} />
      <circle className="hq-chair-stem" cx={-9} cy={2} r={2.6} />
      <circle className="hq-chair-stem" cx={9} cy={7} r={2.6} />
      <path className="hq-device-stroke" d="M-14 -26 q-6 -4 -6 -12" />
    </g>
  );
}

/** Sam's supply box, carried against the hip. */
function CarriedBox() {
  return (
    <g className="hq-carried-box" aria-hidden="true" transform="translate(15 -34)">
      <polygon className="hq-box" points="-8,-4 0,0 8,-4 0,-8" />
      <polygon className="hq-box" points="-8,-4 0,0 0,8 -8,4" />
      <polygon className="hq-box-dark" points="0,0 8,-4 8,4 0,8" />
    </g>
  );
}

interface Painted {
  depth: number;
  node: React.ReactNode;
}

/**
 * How far a desk sits in front of the person at it, in tiles.
 *
 * Equal on both axes, which in a 2:1 projection means *straight down the
 * screen* — directly between the character and the reader, which is where a
 * desk goes.
 *
 * It used to be `row + 0.6` and nothing on the column, which moves down *and
 * to the left*. Every desk therefore sat off one shoulder with its monitor
 * floating beside the person rather than on the surface in front of them, and
 * the room read as furniture and people occupying the same floor rather than
 * as anybody working at anything. One of the two numbers was missing; that was
 * the whole bug.
 */
const DESK_FORWARD = 0.42;

/**
 * Build the furniture, then sort by depth.
 *
 * Sorting rather than relying on JSX order because the desks are generated from
 * the roster: if someone reorders `EMPLOYEES` for readability, the room must
 * not start rendering desks through each other.
 */
function buildScene(
  density: "full" | "reduced",
  activity: OfficeActivity,
  caseCount = 0,
): Painted[] {
  const items: Painted[] = [];

  for (const employee of EMPLOYEES) {
    // Nova gets a console, not a desk: she stands at it. A seated Nova among
    // nine seated colleagues would read as the eleventh analyst.
    if (employee.id === "nova") {
      const console_ = toScreen({ col: employee.desk.col + DESK_FORWARD, row: employee.desk.row + DESK_FORWARD });
      items.push({
        depth: depthOf(employee.desk, LAYER.screen),
        node: (
          <DeskInstruments key="instruments-nova" x={console_.x + 24} y={console_.y + 4} theme="mission" />
        ),
      });
      continue;
    }

    const { col, row } = employee.desk;
    const theme = CHARACTERS[employee.id].deskTheme;
    const point = toScreen({ col: col + DESK_FORWARD, row: row + DESK_FORWARD });
    items.push({
      depth: depthOf({ col, row }, LAYER.desk),
      node: <Desk key={`desk-${employee.id}`} x={point.x} y={point.y} theme={theme} />,
    });
    items.push({
      depth: depthOf({ col, row }, LAYER.screen),
      node: (
        <DeskInstruments
          key={`instruments-${employee.id}`}
          /* Offset onto the right half of the desk. Centred, the monitor sat
             directly behind the person who is meant to be looking at it, and
             since a character always paints over their own desk the screen was
             invisible on every one of the ten workstations. */
          x={point.x + 24}
          y={point.y + 4}
          theme={theme}
        />
      ),
    });
  }

  // Rugs, under everything. Two of them: one anchoring the trading floor and
  // one warming the break room. They are the cheapest way to stop a large grey
  // carpet reading as a void, and they do the job the reference's patterned rug
  // does — give the eye somewhere to rest between clusters of furniture.
  for (const rug of RUGS) {
    items.push({
      depth: depthOf({ col: Math.floor(rug.col), row: Math.floor(rug.row) }, LAYER.rug),
      node: <Rug key={`rug-${rug.col}-${rug.row}`} rect={rug} />,
    });
  }

  // The office furniture, from the shared placement module — the same data
  // the ambient layer blocks walking against, so the drawing and the
  // collision rules cannot drift apart. Sorted into the same depth list as
  // the desks, so a bookshelf behind someone paints behind them.
  for (const prop of FURNITURE) {
    const point = toScreen(prop.tile);
    items.push({
      depth: depthOf(
        { col: Math.floor(prop.tile.col), row: Math.floor(prop.tile.row) },
        prop.kind === "floor-mat" ? LAYER.rug : LAYER.furniture,
      ),
      node: (
        <OfficeProp
          key={`prop-${prop.kind}-${prop.tile.col}-${prop.tile.row}`}
          x={point.x}
          y={point.y}
          kind={prop.kind as FloorProp}
        />
      ),
    });
  }

  // The Mission Board and the Vault are drawn at every density. They are not
  // ambient detail — one is the room's focal point and the other is the line
  // between simulated and real money. A tablet may lose the starfield and the
  // grid; it may not lose either of these.
  {
    // Col 9.6 rather than 9.3: the board grew east as it got wider, and this
    // keeps its west edge clear of Nova, who stands at col 8 row 1 and paints
    // in front of anything on the wall behind her.
    const board = toScreen({ col: 9.6, row: 0 });
    items.push({
      depth: depthOf({ col: 9, row: 0 }, LAYER.rug),
      node: (
        <MissionBoardShell
          key="board"
          x={board.x}
          y={board.y}
          activity={activity}
          caseCount={caseCount}
        />
      ),
    });

    // The vault door. Placed at the sealed room's near corner so it faces the
    // office: the Execution Vault is the one department that is meant to look
    // shut, and a floor plate alone cannot say that.
    const vault = toScreen({ col: 13, row: 5.4 });
    items.push({
      depth: depthOf({ col: 13, row: 5 }, LAYER.overlay),
      node: <VaultDoor key="vault" x={vault.x} y={vault.y} />,
    });
  }

  if (density === "full") {
    // Ambient detail only, from here down.
    const corner = toScreen({ col: 15.4, row: 0.6 });
    items.push({
      depth: depthOf({ col: 15, row: 0 }, LAYER.furniture),
      node: <OfficeProp key="prop-corner-plant" x={corner.x} y={corner.y} kind="plant-large" />,
    });
  }

  return items.sort((a, b) => a.depth - b.depth);
}

/**
 * Where the break room's furniture stands.
 *
 * The same tiles the ambient routines walk to, which is not a coincidence
 * worth leaving implicit: a test asserts every break-room destination in
 * `ambient.ts` has a fixture within a tile of it, so a moved sofa cannot leave
 * Byte standing at nothing.
 */
/**
 * Where the office furniture stands.
 *
 * Placed by hand against the floor plan rather than scattered, because the
 * constraint that matters is not "where does a bookshelf look nice" but
 * "which tiles are still free". Ten desks and twelve walk routes already claim
 * a lot of this room, and a plant standing in the middle of Byte's route to
 * the coffee machine is a person walking through a plant.
 *
 * A test asserts every one of these is clear of the desks and of every
 * ambient waypoint, so the floor plan can be rearranged without someone having
 * to re-check twenty-five positions by eye.
 *
 * Each department's props are also its identity: case files and a checklist
 * board in Risk, a server rack and a printer in Ops, bookshelves in the
 * Performance Lab. Hidden the labels and the rooms still tell you what they
 * are, which is the requirement.
 */
/**
 * The conference room's glass: a west pane facing the vault corridor with a
 * doorway gap at row 1, and mullion posts along the south face where it meets
 * the deck. Translucent fills over whatever is behind them — glass the reader
 * can see through is the entire point of a glass meeting room.
 */
function ConferenceGlass() {
  const height = 74;
  const westTop = toScreen({ col: 16, row: 2 });
  const westBottom = toScreen({ col: 16, row: 4 });
  const southWest = toScreen({ col: 16, row: 4 });
  const southEast = toScreen({ col: 22, row: 4 });
  return (
    <g className="hq-conference-glass" aria-hidden="true">
      <polygon
        className="hq-glass-pane"
        points={`${westTop.x},${westTop.y} ${westBottom.x},${westBottom.y} ${westBottom.x},${westBottom.y - height} ${westTop.x},${westTop.y - height}`}
      />
      <polygon
        className="hq-glass-pane"
        points={`${southWest.x},${southWest.y} ${southEast.x},${southEast.y} ${southEast.x},${southEast.y - height} ${southWest.x},${southWest.y - height}`}
      />
      {[0, 1, 2, 3, 4, 5, 6].map((post) => {
        const at = toScreen({ col: 16 + post, row: 4 });
        return (
          <rect key={post} className="hq-glass-post" x={at.x - 1.4} y={at.y - height} width={2.8} height={height} />
        );
      })}
      <rect
        className="hq-glass-post"
        x={westTop.x - 1.4}
        y={westTop.y - height}
        width={2.8}
        height={height}
      />
    </g>
  );
}

/**
 * The office's circulation spine.
 *
 * A runner down the middle of the walkway, and a matching entry strip at
 * reception, so the route a visitor takes — in at the south door, along the
 * spine, up to Mission Control — is something the eye can follow rather than
 * something you have to work out from the floor plan.
 *
 * Painted on the floor and under everything else, which is what a runner is.
 * It moves nothing: the walkway was always the room's only full-width lane,
 * and every authored walk route already uses it. This just makes that legible.
 *
 * A true unobstructed corridor from reception straight up to Mission Control
 * does not exist and could not be added without relocating desks — of the
 * sixteen columns, only col 4 is anywhere near clear, and it runs up the far
 * west wall rather than through the middle of the building.
 */
function CirculationSpine() {
  const walkway = ZONE_BY_ID.get("walkway")!.rect;
  const reception = ZONE_BY_ID.get("reception")!.rect;

  // The walkway runner, inset half a tile from each edge so the floor still
  // shows at the department boundaries.
  const wNorth = walkway.row + 0.28;
  const wSouth = walkway.row + walkway.rows - 0.28;
  const a = toScreen({ col: walkway.col, row: wNorth });
  const b = toScreen({ col: walkway.col + walkway.cols, row: wNorth });
  const c = toScreen({ col: walkway.col + walkway.cols, row: wSouth });
  const d = toScreen({ col: walkway.col, row: wSouth });

  // The entry strip: from the reception doors north to the spine's south edge,
  // over the columns the reception furniture already frames.
  const eWest = reception.col + 3.4;
  const eEast = reception.col + 5.6;
  const e1 = toScreen({ col: eWest, row: walkway.row + walkway.rows });
  const e2 = toScreen({ col: eEast, row: walkway.row + walkway.rows });
  const e3 = toScreen({ col: eEast, row: reception.row + 0.6 });
  const e4 = toScreen({ col: eWest, row: reception.row + 0.6 });

  return (
    <g className="hq-spine" aria-hidden="true">
      <polygon
        className="hq-spine-runner"
        points={`${a.x},${a.y} ${b.x},${b.y} ${c.x},${c.y} ${d.x},${d.y}`}
      />
      <polygon
        className="hq-spine-runner hq-spine-runner--entry"
        points={`${e1.x},${e1.y} ${e2.x},${e2.y} ${e3.x},${e3.y} ${e4.x},${e4.y}`}
      />
    </g>
  );
}

/**
 * The Execution Vault's shell.
 *
 * The vault used to be a floor plate with a bank door standing on it, which
 * read as a safe someone had left in the middle of the office rather than as
 * a room you cannot get into. It is the one department that has to look shut,
 * so it gets actual walls: solid panels down the west and south faces — the
 * two that front the working floor — in cold metal against the warm wood
 * everywhere else.
 *
 * The south wall breaks at the door's bay so the door reads as the way in
 * rather than as decoration bolted to a blank wall.
 *
 * Drawing only. There is no control here and nothing clickable: the Vault is
 * read-only visualisation, and walls do not change that.
 */
function VaultShell() {
  const rect = ZONE_BY_ID.get("vault")!.rect;
  const west = rect.col;
  const east = rect.col + rect.cols;
  const north = rect.row;
  const south = rect.row + rect.rows;
  const height = 82;

  const westTop = toScreen({ col: west, row: north });
  const westBottom = toScreen({ col: west, row: south });
  // The door bay: the southern-most tile of the west face, left open.
  const doorFrom = toScreen({ col: west, row: south - 1 });

  const southWest = toScreen({ col: west, row: south });
  const southEast = toScreen({ col: east, row: south });

  return (
    <g className="hq-vault-shell" aria-hidden="true">
      {/* West wall, stopping short of the door bay. */}
      <polygon
        className="hq-vault-wall"
        points={`${westTop.x},${westTop.y} ${doorFrom.x},${doorFrom.y} ${doorFrom.x},${doorFrom.y - height} ${westTop.x},${westTop.y - height}`}
      />
      {/* South wall, full width. */}
      <polygon
        className="hq-vault-wall hq-vault-wall--south"
        points={`${southWest.x},${southWest.y} ${southEast.x},${southEast.y} ${southEast.x},${southEast.y - height} ${southWest.x},${southWest.y - height}`}
      />
      {/* Corner posts, so the two faces read as one box rather than two flats. */}
      {[westTop, southWest, southEast, westBottom].map((post, index) => (
        <rect
          key={index}
          className="hq-vault-post"
          x={post.x - 2}
          y={post.y - height}
          width={4}
          height={height}
        />
      ))}
      {/* A warning stripe along the top edge of the south wall. */}
      <polygon
        className="hq-vault-stripe"
        points={`${southWest.x},${southWest.y - height} ${southEast.x},${southEast.y - height} ${southEast.x},${southEast.y - height + 5} ${southWest.x},${southWest.y - height + 5}`}
      />
    </g>
  );
}

/**
 * The deck's edge. A hull-coloured lip and railing posts along the east and
 * south sides — the two that face open space — and the airlock frame at the
 * west end where the walkway enters. Glass panels between posts, because a
 * railing you cannot see space through defeats the deck.
 */
function DeckRailing() {
  // Derived from the deck's own rect rather than written out again. The
  // railing used to hardcode rows 4-8, so extending the deck south left its
  // handrail floating across the middle of the floor — the kind of drift that
  // is invisible in a test and obvious in a screenshot.
  const deck = ZONE_BY_ID.get("deck")!.rect;
  const north = deck.row;
  const south = deck.row + deck.rows;
  const west = deck.col;
  const east = deck.col + deck.cols;

  const posts: Array<ReturnType<typeof toScreen>> = [];
  for (let row = north; row <= south; row += 1) posts.push(toScreen({ col: east, row }));
  for (let col = west; col <= east - 1; col += 1) posts.push(toScreen({ col, row: south }));

  const railTopEast = toScreen({ col: east, row: north });
  const railBottom = toScreen({ col: east, row: south });
  const railWest = toScreen({ col: west, row: south });
  const height = 26;

  const air = toScreen({ col: 16, row: 6 });
  const airSouth = toScreen({ col: 16, row: 7 });

  return (
    <g className="hq-deck-edge" aria-hidden="true">
      <polygon
        className="hq-deck-glass"
        points={`${railTopEast.x},${railTopEast.y} ${railBottom.x},${railBottom.y} ${railBottom.x},${railBottom.y - height} ${railTopEast.x},${railTopEast.y - height}`}
      />
      <polygon
        className="hq-deck-glass"
        points={`${railBottom.x},${railBottom.y} ${railWest.x},${railWest.y} ${railWest.x},${railWest.y - height} ${railBottom.x},${railBottom.y - height}`}
      />
      {posts.map((post, index) => (
        <rect key={index} className="hq-rail-post" x={post.x - 1.6} y={post.y - height} width={3.2} height={height} />
      ))}
      <polyline
        className="hq-rail-top"
        points={`${railTopEast.x},${railTopEast.y - height} ${railBottom.x},${railBottom.y - height} ${railWest.x},${railWest.y - height}`}
      />

      {/* The airlock: a heavy frame around the doorway tile, in the vault's
          cold metal so the boundary between inside and outside reads. */}
      <polygon
        className="hq-airlock"
        points={`${air.x - 5},${air.y - 2} ${airSouth.x - 5},${airSouth.y - 2} ${airSouth.x - 5},${airSouth.y - 64} ${air.x - 5},${air.y - 78}`}
      />
      <polygon
        className="hq-airlock-inner"
        points={`${air.x - 1},${air.y - 6} ${airSouth.x - 1},${airSouth.y - 6} ${airSouth.x - 1},${airSouth.y - 58} ${air.x - 1},${air.y - 70}`}
      />
      <circle className="hq-led" cx={air.x - 3} cy={(air.y + airSouth.y) / 2 - 66} r={1.8} />
    </g>
  );
}

/**
 * A planet in the open space past the deck. Scenery, unmistakably: it sits in
 * the corner no zone covers, drawn before the walls so nothing inside the
 * office can ever overlap it, in colours no status uses.
 */
function VoidPlanet() {
  const at = toScreen({ col: 20.5, row: 12 });
  return (
    <g className="hq-void-planet" aria-hidden="true">
      <circle className="hq-planet-body" cx={at.x} cy={at.y} r={46} />
      <ellipse className="hq-planet-band" cx={at.x} cy={at.y - 10} rx={44} ry={9} />
      <ellipse className="hq-planet-band" cx={at.x} cy={at.y + 14} rx={40} ry={7} />
      <ellipse className="hq-planet-ring" cx={at.x} cy={at.y} rx={68} ry={16} />
      <circle className="hq-star" cx={at.x - 90} cy={at.y - 60} r={1.6} />
      <circle className="hq-star" cx={at.x + 70} cy={at.y - 90} r={1.2} />
      <circle className="hq-star" cx={at.x + 40} cy={at.y + 60} r={1.4} />
      <circle className="hq-star" cx={at.x - 60} cy={at.y + 40} r={1} />
    </g>
  );
}

/**
 * AMBIENT SPACE TRAFFIC.
 *
 * A satellite, a meteor and a distant craft crossing behind the station
 * window. Pure CSS: three elements on long keyframes whose visible portion is
 * a few percent of a very long cycle, so each one appears roughly once every
 * minute or two and never twice together.
 *
 * The rarity is the whole design. Something crossing the window every ten
 * seconds stops being weather and starts being a notification — and in a room
 * whose entire purpose is to report system state, nothing decorative may ever
 * be mistaken for an alert. None of these is ever coloured with a status hue.
 */
function SpaceTraffic() {
  const anchor = toScreen({ col: 3, row: 0 });
  const x = anchor.x;
  const y = anchor.y - 116;
  return (
    <g className="hq-traffic" aria-hidden="true">
      <g className="hq-traffic-satellite">
        <rect className="hq-craft" x={x - 70} y={y - 2} width={5} height={3} rx={1} />
        <rect className="hq-craft" x={x - 73} y={y - 1} width={2} height={1} />
        <rect className="hq-craft" x={x - 64} y={y - 1} width={2} height={1} />
      </g>
      <line className="hq-meteor" x1={x - 60} y1={y - 24} x2={x - 48} y2={y - 16} />
      {/* The tiny spacecraft. The fourth easter egg, and the only one that is
          not a person. */}
      <path className="hq-craft hq-traffic-craft" d={`M${x - 70} ${y + 14} l7 -2.5 l-7 -2.5 l2 2.5 Z`} />
    </g>
  );
}

/**
 * THE MISSION BOARD.
 *
 * Mounted on the back wall, in the wall's own plane, spanning three and a half
 * tiles — the largest single object in the room and the only one the whole
 * office can see. It used to float in mid-air above the floor as a flat
 * rectangle, which made the most authoritative surface in the product look
 * like a tooltip.
 *
 * The panel is skewed into the wall; the writing on it is not. Text sheared
 * along an isometric axis is barely legible at this size, and legibility of
 * the roll-up beats geometric purity every time — it is the one thing in this
 * room a reader is entitled to be able to read.
 */
function MissionBoardShell({
  x,
  y,
  activity,
  caseCount,
}: {
  x: number;
  y: number;
  activity: OfficeActivity;
  /** How many token cases are currently visible in the room — a real count,
      never a per-subsystem verdict. HQ-5's one addition to this board. */
  caseCount: number;
}) {
  // Enlarged in the composition pass. At span 3.6 / height 66 the board was
  // the same visual weight as a desk monitor, which made the room's focal
  // point compete with its furniture instead of anchoring it. It is the one
  // surface here that speaks for the whole office, so it is allowed to be the
  // biggest thing on the wall.
  const span = 5.1;
  const ax = 64 * span;
  const ay = 32 * span;
  const base = y - 30;
  const height = 96;
  const frame = `${x},${base} ${x + ax},${base + ay} ${x + ax},${base + ay - height} ${x},${base - height}`;
  const t = 0.045;
  const ix = x + ax * t;
  const iy = base + ay * t;
  const iax = ax * (1 - t * 2);
  const iay = ay * (1 - t * 2);
  const ih = height - 9;
  const screen = `${ix},${iy - 4} ${ix + iax},${iy + iay - 4} ${ix + iax},${iy + iay - 4 - ih} ${ix},${iy - 4 - ih}`;

  const midX = ix + iax / 2;
  const midY = iy + iay / 2 - 4 - ih / 2;

  return (
    <g className="hq-mission-board">
      <polygon className="hq-board-frame" points={frame} />
      <polygon className="hq-board-screen" points={screen} />
      <text className="hq-board-title" x={midX} y={midY - 10}>
        MEMESCOPE MISSION BOARD
      </text>
      {/* The office's own roll-up, and nothing else. Still no per-subsystem
          rows: those are HQ-5's, and inventing one here would be a fabricated
          claim on the most authoritative surface in the product. `UNKNOWN` is
          a real answer and the one this shows until the adapter has a reading. */}
      <text className="hq-board-value" x={midX} y={midY + 14}>
        Office activity {activity}
      </text>
      {caseCount > 0 ? (
        <text className="hq-board-cases" x={midX} y={midY + 34}>
          {caseCount} case{caseCount === 1 ? "" : "s"} in view
        </text>
      ) : null}
    </g>
  );
}

/**
 * The Real Wallet vault door.
 *
 * A sealed cartoon bank door with a locking wheel and a single small terminal
 * beside it. The rest of the office is warm wood and blue chairs; this is cold
 * metal, and the contrast is the point — a reader should be able to tell at a
 * glance which part of this company handles simulated money and which part
 * would handle real money.
 *
 * It is a drawing. There is no control here, no affordance, and nothing that
 * can be clicked to change anything: the Vault stays read-only visualisation
 * for as long as it exists.
 */
function VaultDoor({ x, y }: { x: number; y: number }) {
  return (
    <g className="hq-vault-door" aria-hidden="true">
      <ellipse className="hq-prop-shadow" cx={x} cy={y + 6} rx={40} ry={16} />
      <polygon
        className="hq-vault-frame"
        points={`${x - 40},${y - 4} ${x},${y + 16} ${x + 40},${y - 4} ${x + 40},${y - 78} ${x},${y - 98} ${x - 40},${y - 78}`}
      />
      <polygon
        className="hq-vault-face"
        points={`${x - 32},${y - 8} ${x},${y + 8} ${x + 32},${y - 8} ${x + 32},${y - 72} ${x},${y - 88} ${x - 32},${y - 72}`}
      />
      <ellipse className="hq-vault-wheel" cx={x} cy={y - 42} rx={17} ry={17} />
      <ellipse className="hq-vault-hub" cx={x} cy={y - 42} rx={5} ry={5} />
      {[0, 45, 90, 135].map((angle) => (
        <rect
          key={angle}
          className="hq-vault-spoke"
          x={x - 19}
          y={y - 43.4}
          width={38}
          height={2.8}
          rx={1.4}
          transform={`rotate(${angle} ${x} ${y - 42})`}
        />
      ))}
      {/* One small terminal, dark. It reports; it does not offer. */}
      <rect className="hq-bezel" x={x + 22} y={y - 34} width={13} height={10} rx={1.5} />
      <rect className="hq-screen" x={x + 24} y={y - 32} width={9} height={6} rx={1} />
      <text className="hq-desk-plate" x={x} y={y - 12}>
        SEALED
      </text>
    </g>
  );
}

/**
 * The two back walls, and the strip where they meet the floor.
 *
 * Shorter than they were. At 2.2 tiles the walls were the largest and
 * brightest shapes in the frame and the room read as a beige canyon with some
 * furniture at the bottom; the reference gives its walls perhaps a third of
 * the height and spends the rest of the picture on the office. Everything
 * interesting is on the floor, so the walls get out of its way.
 *
 * The two planes carry different fills. A single flat colour across both makes
 * the corner disappear, and with it the reader's sense that this is a room
 * with a near side and a far side.
 *
 * The baseboard is four small polygons and it does more for "this is an
 * interior" than any amount of wall decoration — it is the line that tells you
 * where the floor stops.
 */
function BackWalls() {
  const nw = toScreen({ col: 0, row: 0 });
  const n = toScreen({ col: GRID_COLS, row: 0 });
  const w = toScreen({ col: 0, row: GRID_ROWS });
  const height = TILE_H * 1.5;
  const skirt = 7;
  return (
    <g>
      <polygon
        className="hq-wall"
        points={`${nw.x},${nw.y} ${n.x},${n.y} ${n.x},${n.y - height} ${nw.x},${nw.y - height}`}
      />
      <polygon
        className="hq-wall hq-wall--side"
        points={`${nw.x},${nw.y} ${w.x},${w.y} ${w.x},${w.y - height} ${nw.x},${nw.y - height}`}
      />
      <polygon
        className="hq-baseboard"
        points={`${nw.x},${nw.y} ${n.x},${n.y} ${n.x},${n.y - skirt} ${nw.x},${nw.y - skirt}`}
      />
      <polygon
        className="hq-baseboard"
        points={`${nw.x},${nw.y} ${w.x},${w.y} ${w.x},${w.y - skirt} ${nw.x},${nw.y - skirt}`}
      />
    </g>
  );
}

/**
 * What hangs on the walls.
 *
 * Framed space photography, a chart print, and the company's own name over
 * Mission Control. The brief asks for MEMESCOPE identity carried by the
 * technology rather than by making the office cold, and a sign on the wall is
 * the cheapest half of that.
 *
 * The chart print is the one piece of decoration that could be mistaken for
 * information, so it is drawn as an abstract rising line with no axis, no
 * label and no number — a picture of a chart, the way an office has a picture
 * of a mountain.
 */
function WallArt() {
  const wallTop = (col: number, row: number, lift: number) => {
    const point = toScreen({ col, row });
    return { x: point.x, y: point.y - lift };
  };
  const north = (col: number, lift: number) => wallTop(col, 0, lift);
  const west = (row: number, lift: number) => wallTop(0, row, lift);

  // The wall stands 1.5 tiles tall, so a frame hangs at roughly two thirds of
  // that: high enough to clear the furniture in front of it, low enough to
  // read as hung by a person rather than fixed to a ceiling.
  return (
    <g>
      {/* The north wall, west to east: a print, the station window (drawn
          separately), the company sign, then the Mission Board from col 9.3.
          Nova stands at col 8, in the gap between the sign and the board —
          her nameplate used to be printed straight across the board's title. */}
      <WallDecor {...north(1.1, 58)} kind="art-space" facing="north" span={0.6} height={26} />
      <WallDecor {...north(5.3, 62)} kind="sign" facing="north" span={1.4} height={30} />
      <WallDecor {...north(13.6, 56)} kind="art-chart" facing="north" span={0.62} height={26} />
      {/* The conference room's own display, over the table. Dark panel, the
          abstract chart mark — the room's screens obey the same rule as every
          screen in HQ: shapes, never values. */}
      <WallDecor {...north(17.3, 66)} kind="art-chart" facing="north" span={2.3} height={42} />
      <WallDecor {...west(2.2, 58)} kind="art-space" facing="west" span={0.68} height={28} />
      <WallDecor {...west(5.0, 56)} kind="art-chart" facing="west" span={0.62} height={26} />
      <WallDecor {...west(8.0, 58)} kind="art-space" facing="west" span={0.6} height={26} />
      <WallDecor {...west(10.6, 56)} kind="art-chart" facing="west" span={0.62} height={26} />
    </g>
  );
}

/**
 * The station window.
 *
 * A frame with a handful of static stars. It deliberately does not reimplement
 * the starfield — `universe.css` already owns that, and a second one would be a
 * second thing to keep in sync. HQ-11 can place the existing space objects
 * behind this frame; for now the frame establishes the sightline.
 */
function StationWindow() {
  const anchor = toScreen({ col: 3, row: 0 });
  const stars: Array<readonly [number, number]> = [
    [-52, -118],
    [-18, -142],
    [26, -110],
    [58, -134],
    [8, -96],
  ];
  return (
    <g>
      <rect
        className="hq-window"
        x={anchor.x - 80}
        y={anchor.y - 156}
        width={160}
        height={80}
        rx={6}
      />
      {stars.map(([dx, dy], index) => (
        <circle
          key={index}
          className="hq-star"
          cx={anchor.x + dx}
          cy={anchor.y + dy + 40}
          r={1.6}
          style={{ animationDelay: `${index * 1.3}s` }}
        />
      ))}
    </g>
  );
}

function GridLines() {
  const lines: React.ReactNode[] = [];
  for (let col = 0; col <= GRID_COLS; col += 1) {
    const a = toScreen({ col, row: 0 });
    const b = toScreen({ col, row: GRID_ROWS });
    lines.push(
      <line key={`c${col}`} className="hq-grid-line" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />,
    );
  }
  for (let row = 0; row <= GRID_ROWS; row += 1) {
    const a = toScreen({ col: 0, row });
    const b = toScreen({ col: GRID_COLS, row });
    lines.push(
      <line key={`r${row}`} className="hq-grid-line" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />,
    );
  }
  return <g>{lines}</g>;
}

/* ------------------------------------------------------------------------ */

/**
 * Posture for a real state.
 *
 * One entry, and that is the point. `busy` is the only operational state whose
 * difference from its neighbours is worth a different drawing; everything else
 * is carried by the state chip and the accessible name, which are text and
 * therefore actually readable.
 */
const OPERATIONAL_POSE: Partial<Record<EmployeeState, Pose>> = {
  busy: "looking_at_screen",
};

/** The text a screen reader gets instead of the scene. */
function roomDescription(state: HqState): string {
  const departments = ZONES.filter((zone) => zone.id !== "walkway")
    .map((zone) => zone.label)
    .join(", ");
  const staff = EMPLOYEES.map(
    (employee) => `${employee.name}: ${STATE_LABEL[state.employees[employee.id].state]}`,
  ).join(", ");
  const others = [
    ...SUPPORT_STAFF.map((npc) => `${npc.name} (${npc.role})`),
    ...CATS.map((cat) => `${cat.name} (office cat)`),
  ].join(", ");
  return `MEMESCOPE HQ floor plan. Departments: ${departments}. Office activity ${state.activity}. ${staff}. Also around: ${others}.`;
}
