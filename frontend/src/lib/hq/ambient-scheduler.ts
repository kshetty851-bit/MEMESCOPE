import {
  AMBIENT_ROUTINES,
  pickRoutine as pickWeighted,
  visitsBreakRoom,
  type ActorFrame,
  type AmbientRoutine,
} from "./ambient";
import { CATS, CAT_ROUTINES, type CatId } from "./cats";
import { CHATTER_BY_ACTOR, CHATTER_EVERY } from "./chatter";
import { EMPLOYEES, type EmployeeId } from "./employees";
import { SUPPORT_ROUTINES, SUPPORT_STAFF, type SupportId } from "./support";
import { MAX_VISITORS, VISITORS, VISITOR_ROUTINES, type VisitorId } from "./visitors";
import type { DayPhase } from "./ambient";
import type { OfficeActivity } from "./adapter";

/**
 * THE OFFICE-LIFE SCHEDULER.
 *
 * One scheduler for everything that moves: the ten operational employees, the
 * two support staff, and the two cats. The world expansion was the moment a
 * second timer system became tempting — cats on their own interval, Maya on
 * hers, meetings on a third — and the moment it had to be refused, because
 * four uncoordinated clocks cannot promise the one thing the room must keep
 * promising: that it quietens as one when a tab hides, a reader asks for
 * stillness, or the office goes to HIGH_ALERT.
 *
 * WHAT DIFFERS BY CLASS
 *
 * Everything here is presentation, but the classes yield to different things.
 *
 *   core      Real system activity wins. `setOperational` names who is doing
 *             actual work; they are excluded from new routines and anyone
 *             mid-routine walks home. At most three are out at once — except
 *             for a meeting, which is its own bounded thing.
 *   support   Ambient only, capped at two activities, quieter at night and
 *             during alerts. No backend state can reach them by construction:
 *             the adapter does not know they exist.
 *   cat       Ambient only, capped at two moving. Cats do not attend
 *             meetings, do not react to system state, and cannot reach a
 *             control because no code path exists from a cat to anything.
 *
 * WHAT THE OFFICE'S MOOD CHANGES
 *
 * `setActivity` feeds the adapter's roll-up back in as *atmosphere*: at
 * HIGH_ALERT, meetings and the sillier routines are suppressed and core
 * employees start fewer errands — most of them are excluded anyway, because
 * an alerting department is an operational one. `setPhase` quietens the night
 * shift: fewer trips, no meetings, Sam gone home, Mochi asleep. Neither ever
 * *invents* activity; they only decline to start it.
 *
 * The rest — the single tick loop, the guards on reduced motion and hidden
 * tabs, one-frame-at-a-time playback so anyone can be interrupted mid-walk
 * and walk home along their authored return leg — is HQ-3's architecture,
 * unchanged in shape, widened in cast.
 */

export type ActorId = EmployeeId | SupportId | CatId | VisitorId;
export type ActorClass = "core" | "support" | "cat" | "visitor";

interface Playable {
  id: string;
  actor: ActorId;
  actorClass: ActorClass;
  weight: number;
  frames: ActorFrame[];
  cast: Array<{ actor: ActorId; frames: ActorFrame[] }>;
  meeting: boolean;
  suppressOnAlert: boolean;
  nightFactor: number;
}

const CLASS_OF = new Map<ActorId, ActorClass>([
  ...EMPLOYEES.map((e) => [e.id, "core"] as const),
  ...SUPPORT_STAFF.map((n) => [n.id, "support"] as const),
  ...CATS.map((c) => [c.id, "cat"] as const),
  ...VISITORS.map((v) => [v.id, "visitor"] as const),
]);

export function actorClass(id: ActorId): ActorClass {
  return CLASS_OF.get(id) ?? "core";
}

/** Default night quietness per class, when a routine does not say. */
const NIGHT_DEFAULT: Record<ActorClass, number> = {
  core: 0.5,
  support: 0.4,
  cat: 0.9,
  // Nobody from Finance comes up at three in the morning.
  visitor: 0,
};

function normalize(routine: AmbientRoutine): Playable {
  return {
    id: routine.id,
    actor: routine.employee,
    actorClass: "core",
    weight: routine.weight,
    frames: routine.frames,
    cast: (routine.cast ?? []).map((member) => ({ actor: member.employee, frames: member.frames })),
    meeting: routine.meeting ?? false,
    suppressOnAlert: (routine.suppressOnAlert ?? false) || (routine.meeting ?? false),
    nightFactor: routine.nightFactor ?? NIGHT_DEFAULT.core,
  };
}

const PLAYABLES: Playable[] = [
  ...AMBIENT_ROUTINES.map(normalize),
  ...SUPPORT_ROUTINES.map((routine) => ({
    id: routine.id,
    actor: routine.actor as ActorId,
    actorClass: "support" as const,
    weight: routine.weight,
    frames: routine.frames,
    cast: [],
    meeting: false,
    suppressOnAlert: routine.suppressOnAlert ?? false,
    nightFactor: routine.nightFactor ?? NIGHT_DEFAULT.support,
  })),
  ...VISITOR_ROUTINES.map((routine) => ({
    id: routine.id,
    actor: routine.actor as ActorId,
    actorClass: "visitor" as const,
    weight: routine.weight,
    frames: routine.frames,
    cast: (routine.cast ?? []).map((member) => ({
      actor: member.actor as ActorId,
      frames: member.frames,
    })),
    meeting: false,
    suppressOnAlert: routine.suppressOnAlert ?? true,
    nightFactor: routine.nightFactor ?? NIGHT_DEFAULT.visitor,
  })),
  ...CAT_ROUTINES.map((routine) => ({
    id: routine.id,
    actor: routine.actor as ActorId,
    actorClass: "cat" as const,
    weight: routine.weight,
    frames: routine.frames,
    cast: (routine.cast ?? []).map((member) => ({
      actor: member.actor as ActorId,
      frames: member.frames,
    })),
    meeting: false,
    suppressOnAlert: routine.suppressOnAlert ?? false,
    nightFactor: routine.nightFactor ?? NIGHT_DEFAULT.cat,
  })),
];

const PLAYABLES_BY_ACTOR = new Map<ActorId, Playable[]>();
for (const playable of PLAYABLES) {
  const list = PLAYABLES_BY_ACTOR.get(playable.actor) ?? [];
  list.push(playable);
  PLAYABLES_BY_ACTOR.set(playable.actor, list);
}

export const ALL_ACTORS: ActorId[] = [
  ...EMPLOYEES.map((e) => e.id),
  ...SUPPORT_STAFF.map((n) => n.id),
  ...CATS.map((c) => c.id),
  ...VISITORS.map((v) => v.id),
];

/* ── caps ──────────────────────────────────────────────────────────────── */

/** Core employees out at once, meetings aside. Three of ten is a staffed office. */
const MAX_CORE = 3;
/**
 * Absolute ceiling on core employees away simultaneously, meetings included.
 * A four-person meeting plus one errand is a company; a four-person meeting
 * plus three errands is an evacuation.
 */
const MAX_CORE_TOTAL = 5;
/** Support activities at once. */
const MAX_SUPPORT = 2;
/** Cats mid-routine at once — both may be, there are only two. */
const MAX_CATS = 2;
/** The break area must never look like the whole company clocked off. */
const MAX_IN_BREAK = 2;

/** Gap between one start and the next. Sparse on purpose. */
const GAP_MIN_MS = 4_000;
const GAP_MAX_MS = 11_000;

export interface AmbientScheduler {
  start(): void;
  stop(): void;
  destroy(): void;
  /** Employees doing real work: excluded, and walked home if mid-routine. */
  setOperational(ids: Iterable<EmployeeId>): void;
  /** The office roll-up, as atmosphere. HIGH_ALERT quietens the ambient layer. */
  setActivity(activity: OfficeActivity): void;
  /** Day phase. Night runs fewer routines; it never runs different claims. */
  setPhase(phase: DayPhase): void;
  readonly running: boolean;
  readonly wanted: boolean;
  readonly animating: ActorId[];
  /** Whether a conference meeting is currently in progress. Read by tests. */
  readonly meetingActive: boolean;
  /**
   * Stop starting ambient routines and let everyone mid-route finish or yield.
   *
   * The report meeting takes over the floor, and the brief is explicit that it
   * must not do so by teleporting people out of a walk. So this does not halt:
   * it stops *starting*, walks anyone mid-routine home along their own
   * authored return leg, and resolves once the floor is clear — which is when
   * the meeting may begin.
   *
   * Idempotent. A second call while suspended returns the same promise, which
   * is the whole of the double-click protection at this layer.
   */
  suspendForReport(): Promise<void>;
  /** Hand the floor back. No-op if the scheduler was never suspended. */
  resumeAfterReport(): void;
  /** True between `suspendForReport` and `resumeAfterReport`. */
  readonly reportMode: boolean;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function documentHidden(): boolean {
  return typeof document !== "undefined" && document.hidden === true;
}

export type AmbientEmit = (actor: ActorId, frame: ActorFrame | null) => void;

export function createAmbientScheduler(
  emit: AmbientEmit,
  random: () => number = Math.random,
): AmbientScheduler {
  interface Run {
    routineId: string;
    meeting: boolean;
    frames: ActorFrame[];
    index: number;
    handle: ReturnType<typeof setTimeout> | null;
    onDone: () => void;
  }

  const active = new Map<ActorId, Run>();
  let inBreak = 0;
  let meeting = false;
  let operational: ReadonlySet<EmployeeId> = new Set();
  let activity: OfficeActivity = "UNKNOWN";
  let phase: DayPhase = "day";
  let tickHandle: ReturnType<typeof setTimeout> | null = null;

  let wanted = false;
  let running = false;
  let reportMode = false;
  let settling: Promise<void> | null = null;
  let onFloorClear: (() => void) | null = null;

  /**
   * How many employees a routine sends into the pantry or lounge. Counted per
   * person rather than per routine: the two-person lounge chat occupies two
   * of the break area's slots, exactly as two solo coffee trips would.
   */
  function breakVisitors(playable: Playable): number {
    let count = 0;
    if (playable.actorClass === "core" && visitsBreakRoom(playable)) count += 1;
    for (const member of playable.cast) {
      if (actorClass(member.actor) === "core" && visitsBreakRoom(member)) count += 1;
    }
    return count;
  }

  function busyOf(kind: ActorClass, options: { meetings?: boolean } = {}): number {
    let count = 0;
    for (const [actor, run] of active) {
      if (actorClass(actor) !== kind) continue;
      if (run.meeting && options.meetings === false) continue;
      count += 1;
    }
    return count;
  }

  function free(id: ActorId): boolean {
    if (active.has(id)) return false;
    if (actorClass(id) === "core" && operational.has(id as EmployeeId)) return false;
    return true;
  }

  /**
   * Whether a picked routine actually starts this tick.
   *
   * `nightFactor` cannot work as a weight multiplier: weights are relative
   * within one actor's own list, so scaling all of Sam's routines by 0.1
   * changes nothing about how often Sam starts one — a lesson a test taught
   * before this comment existed. It has to gate the start itself: at night, a
   * factor of 0.1 means nine of ten picks are quietly dropped.
   */
  function startsTonight(playable: Playable): boolean {
    if (phase !== "night") return true;
    if (playable.nightFactor >= 1) return true;
    return random() < playable.nightFactor;
  }

  /** Routines this actor could start right now, given the office around them. */
  function available(id: ActorId): Playable[] {
    const routines = PLAYABLES_BY_ACTOR.get(id) ?? [];
    return routines
      .filter((playable) => {
        if (activity === "HIGH_ALERT" && playable.suppressOnAlert) return false;
        if (playable.meeting && meeting) return false;
        // A factor of zero is a ban, checked here so a banned routine can
        // never even be picked; fractional factors gate the start instead.
        if (phase === "night" && playable.nightFactor <= 0) return false;
        for (const member of playable.cast) {
          if (!free(member.actor)) return false;
        }
        const coreJoining =
          (playable.actorClass === "core" ? 1 : 0) +
          playable.cast.filter((member) => actorClass(member.actor) === "core").length;
        if (coreJoining > 0) {
          // Meetings are exempt from the everyday cap — they are their own
          // bounded thing — but nothing is exempt from the absolute ceiling.
          if (
            !playable.meeting &&
            busyOf("core", { meetings: false }) + coreJoining > MAX_CORE
          ) {
            return false;
          }
          if (busyOf("core") + coreJoining > MAX_CORE_TOTAL) return false;
        }
        if (inBreak + breakVisitors(playable) > MAX_IN_BREAK) return false;
        return true;
      });
  }

  function step(id: ActorId) {
    const run = active.get(id);
    if (!run) return;
    run.index += 1;
    const frame = run.frames[run.index];
    if (!frame) {
      finish(id);
      return;
    }
    emit(id, frame);
    run.handle = setTimeout(() => step(id), frame.hold);
  }

  /**
   * Occasionally give a routine a line.
   *
   * ── COUNTED, NOT RANDOM, AND THAT IS THE POINT ────────────────────────
   *
   * The obvious implementation rolls `random()` per start. It also breaks
   * every test that scripts the RNG to force a particular routine, because a
   * chatter roll shifts the stream underneath the selection that follows it —
   * which is exactly what happened: two meeting tests started failing the
   * moment this existed, and neither had anything to do with speech.
   *
   * So chatter consumes no randomness at all. Every third qualifying start
   * speaks, and which line it is rotates. Deterministic, testable, and it
   * cannot perturb anything else in the scheduler.
   *
   * The line lands on the first frame long enough to read it — a bubble on a
   * 620ms walking step is a flicker. Cats do not speak.
   */
  let chatterCount = 0;
  function withChatter(id: ActorId, frames: ActorFrame[]): ActorFrame[] {
    if (actorClass(id) === "cat") return frames;
    const lines = CHATTER_BY_ACTOR.get(id);
    if (!lines || lines.length === 0) return frames;
    const index = frames.findIndex((frame) => frame.hold >= 3_000);
    if (index < 0) return frames;
    const turn = chatterCount;
    chatterCount += 1;
    if (turn % CHATTER_EVERY !== 0) return frames;
    const next = [...frames];
    next[index] = { ...next[index]!, speech: lines[(turn / CHATTER_EVERY) % lines.length]! };
    return next;
  }

  function begin(id: ActorId, routine: Playable, frames: ActorFrame[], onDone: () => void) {
    active.set(id, {
      routineId: routine.id,
      meeting: routine.meeting,
      frames: routine.meeting ? frames : withChatter(id, frames),
      index: -1,
      handle: null,
      onDone,
    });
    step(id);
  }

  function finish(id: ActorId) {
    const run = active.get(id);
    if (!run) return;
    if (run.handle) clearTimeout(run.handle);
    active.delete(id);
    emit(id, null);
    run.onDone();
    // The report meeting waits for an empty floor rather than for a timeout:
    // a fixed delay would either cut a walk short or make the button feel
    // broken, depending on who happened to be crossing the room.
    if (active.size === 0 && onFloorClear) {
      const notify = onFloorClear;
      onFloorClear = null;
      notify();
    }
  }

  /**
   * Cut a routine short, walking home if there is a walk home to do.
   *
   * Employees walk home along the `returning_to_desk` leg their route was
   * authored with; cats' routes end in `cat_walk` legs and are simply cut to
   * rest, because a cat that changes plans mid-room is a cat. Everyone in the
   * same routine leaves together — half a meeting gesturing at empty chairs
   * is worse than the meeting ending.
   */
  function yieldHome(id: ActorId) {
    const run = active.get(id);
    if (!run) return;

    for (const [other, otherRun] of active) {
      if (other === id || otherRun.routineId !== run.routineId) continue;
      cutToReturn(other, otherRun);
    }
    cutToReturn(id, run);
  }

  function cutToReturn(id: ActorId, run: Run) {
    if (run.handle) clearTimeout(run.handle);
    const rest = run.frames.slice(run.index + 1);
    const home = rest.findIndex((frame) => frame.pose === "returning_to_desk" || frame.pose === "cat_walk");
    if (home < 0) {
      finish(id);
      return;
    }
    run.frames = rest.slice(home);
    run.index = -1;
    run.handle = null;
    step(id);
  }

  function run(playable: Playable) {
    const cast: Array<{ actor: ActorId; frames: ActorFrame[] }> = [
      { actor: playable.actor, frames: playable.frames },
      ...playable.cast,
    ];

    const breaking = breakVisitors(playable);
    if (breaking > 0) inBreak += breaking;
    if (playable.meeting) meeting = true;

    let outstanding = cast.length;
    const done = () => {
      outstanding -= 1;
      if (outstanding > 0) return;
      if (breaking > 0) inBreak = Math.max(0, inBreak - breaking);
      if (playable.meeting) meeting = false;
    };

    for (const member of cast) begin(member.actor, playable, member.frames, done);
  }

  function tick() {
    if (!running) return;
    if (reportMode) {
      // Keep the one timer chain alive but start nothing: the scheduler is
      // still the only clock, it is simply not spending it. Rebuilding the
      // chain on resume would be a second place that decides the cadence.
      tickHandle = setTimeout(tick, GAP_MIN_MS);
      return;
    }

    // At HIGH_ALERT the ambient layer starts far less: the office should read
    // as focused, not frozen. Two thirds of ticks pass in silence.
    const muted = activity === "HIGH_ALERT" && random() < 0.66;

    if (!muted) {
      const pool = ALL_ACTORS.filter((id) => {
        if (!free(id)) return false;
        const kind = actorClass(id);
        if (kind === "support" && busyOf("support") >= MAX_SUPPORT) return false;
        if (kind === "cat" && busyOf("cat") >= MAX_CATS) return false;
        // One guest, ever. Counted rather than hoped for: a lobby that fills
        // up is a different, worse office.
        if (kind === "visitor" && busyOf("visitor") >= MAX_VISITORS) return false;
        return true;
      });
      if (pool.length > 0) {
        const who = pool[Math.floor(random() * pool.length)]!;
        const routine = pickWeighted(available(who), random);
        if (routine && startsTonight(routine)) run(routine);
      }
    }

    tickHandle = setTimeout(tick, GAP_MIN_MS + random() * (GAP_MAX_MS - GAP_MIN_MS));
  }

  function halt() {
    running = false;
    if (tickHandle) {
      clearTimeout(tickHandle);
      tickHandle = null;
    }
    for (const [id, entry] of active) {
      if (entry.handle) clearTimeout(entry.handle);
      emit(id, null);
    }
    active.clear();
    inBreak = 0;
    meeting = false;
  }

  function resume() {
    if (running || !wanted) return;
    if (prefersReducedMotion()) return;
    if (documentHidden()) return;
    running = true;
    tickHandle = setTimeout(tick, GAP_MIN_MS);
  }

  const onVisibility = () => {
    if (documentHidden()) halt();
    else resume();
  };

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
  }

  return {
    start() {
      wanted = true;
      resume();
    },
    stop() {
      wanted = false;
      halt();
    },
    destroy() {
      wanted = false;
      halt();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    },
    setOperational(ids) {
      operational = new Set(ids);
      for (const id of [...active.keys()]) {
        if (actorClass(id) === "core" && operational.has(id as EmployeeId)) yieldHome(id);
      }
    },
    setActivity(next) {
      activity = next;
      if (next !== "HIGH_ALERT") return;
      // Meetings do not survive the office going to HIGH_ALERT: everyone in
      // one is walked back to their desk. Coffee runs already underway are
      // left to finish — a person mid-walk with a mug is not a problem.
      for (const [id, entry] of [...active]) {
        if (entry.meeting) yieldHome(id);
      }
    },
    setPhase(next) {
      phase = next;
    },
    suspendForReport() {
      if (settling) return settling;
      reportMode = true;
      settling = new Promise<void>((resolve) => {
        // Everyone mid-routine yields along their own return leg. `yieldHome`
        // takes whole routines, so a meeting in progress leaves together
        // rather than stranding half a table.
        for (const id of [...active.keys()]) yieldHome(id);
        if (active.size === 0) {
          resolve();
          return;
        }
        onFloorClear = resolve;
      });
      return settling;
    },
    resumeAfterReport() {
      reportMode = false;
      settling = null;
      onFloorClear = null;
    },
    get reportMode() {
      return reportMode;
    },
    get running() {
      return running;
    },
    get wanted() {
      return wanted;
    },
    get animating() {
      return [...active.keys()];
    },
    get meetingActive() {
      return meeting;
    },
  };
}
