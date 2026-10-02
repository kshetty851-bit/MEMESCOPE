"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api-client";
import {
  ROBOTS, STAGES, robotIndexFor, stoppedBy,
  type Checkpoint, type CheckpointEvent, type Robot,
} from "@/lib/hq/checkpoint";

/**
 * THE CHECKPOINT (Karthik, 2026-10-02: "show this 30 checks as 30 agents look
 * like robots and name them, give them their own big office with all
 * animations ... make it more attractive and live").
 *
 * Its own office beside HQ's, not more staff in it: the main floor's
 * invariants (four standing, unique accessories, routes on the grid) were
 * written for a dozen people, and thirty robots would break every one.
 *
 * LIVE means the records: each robot's counter is the refusals it owns
 * (`/real-wallet/checkpoint`), and the belt replays the latest real coins —
 * a bought one passes all thirty into the wallet; a stopped one halts at the
 * robot that refused it and drops into the rug bin.
 */

const STEP_MS = 150;
const HOLD_MS = 1700;
const GAP_MS = 500;

type Phase = "move" | "hold";
type BotState = "idle" | "scan" | "pass" | "stop" | "asleep";

function useCheckpoint() {
  return useQuery({
    queryKey: ["hq", "checkpoint"],
    queryFn: () => api.get<Checkpoint>("/real-wallet/checkpoint"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

function useMotion(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    const q = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    setOk(!q?.matches);
  }, []);
  return ok;
}

/** Walks each event along the robots, oldest first, round and round. */
export function useConveyor(events: CheckpointEvent[], motion: boolean) {
  const key = events.map((e) => e.at).join("|");
  const [state, setState] = useState<{ e: number; step: number; phase: Phase }>(
    { e: 0, step: 0, phase: "move" });
  useEffect(() => {
    if (!events.length || !motion) return;
    let e = 0;
    let step = 0;
    let hold = false;
    let timer = 0;
    const run = () => {
      const target = robotIndexFor(events[e]!);
      if (!hold && step < target) {
        step += 1;
        setState({ e, step, phase: "move" });
        timer = window.setTimeout(run, STEP_MS);
      } else if (!hold) {
        hold = true;
        setState({ e, step: target, phase: "hold" });
        timer = window.setTimeout(run, HOLD_MS);
      } else {
        hold = false;
        step = 0;
        e = (e + 1) % events.length;
        setState({ e, step: 0, phase: "move" });
        timer = window.setTimeout(run, GAP_MS);
      }
    };
    setState({ e: 0, step: 0, phase: "move" });
    timer = window.setTimeout(run, STEP_MS);
    return () => window.clearTimeout(timer);
    // `key` stands for `events`: a refetch with the same coins keeps its place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, motion]);
  return state;
}

function ago(iso: string, now: number): string {
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  return `${h}h ${min % 60}m ago`;
}

/** One robot. `look` varies the antenna and head so no two neighbours match. */
function RobotFigure({ robot, index }: { robot: Robot; index: number }) {
  const look = index % 3;
  const round = index % 2 === 0 ? 7 : 4;
  const glyph = robot.name.slice(0, 2).toUpperCase();
  return (
    <svg viewBox="0 0 56 68" width="64" height="78" aria-hidden="true" className="overflow-visible">
      <polygon className="cp-beam" points="20,26 36,26 48,68 8,68" />
      <g className="cp-body">
        <circle className="cp-halo" cx="28" cy="32" r="27" />
        {look === 0 ? (
          <>
            <line x1="28" y1="11" x2="28" y2="4" stroke="var(--cp-metal-hi)" strokeWidth="1.6" />
            <circle className="cp-tip" cx="28" cy="3.5" r="2.6" />
          </>
        ) : look === 1 ? (
          <>
            <line x1="22" y1="11" x2="19" y2="4" stroke="var(--cp-metal-hi)" strokeWidth="1.4" />
            <line x1="34" y1="11" x2="37" y2="4" stroke="var(--cp-metal-hi)" strokeWidth="1.4" />
            <circle className="cp-tip" cx="19" cy="3.8" r="2" />
            <circle className="cp-tip" cx="37" cy="3.8" r="2" />
          </>
        ) : (
          <>
            <line x1="28" y1="11" x2="28" y2="6" stroke="var(--cp-metal-hi)" strokeWidth="1.6" />
            <path d="M21 6 Q28 -1 35 6 Z" className="cp-metal" />
            <circle className="cp-tip" cx="28" cy="5" r="1.8" />
          </>
        )}
        <rect className="cp-metal" x="8" y="16" width="5" height="9" rx="2" />
        <rect className="cp-metal" x="43" y="16" width="5" height="9" rx="2" />
        <rect className="cp-chassis" x="12" y="10" width="32" height="21" rx={round} />
        <rect className="cp-visor" x="16" y="14" width="24" height="11" rx="5" />
        <g className="cp-eyes">
          <circle className="cp-eye" cx="23" cy="19.5" r="2.6" />
          <circle className="cp-eye" cx="33" cy="19.5" r="2.6" />
        </g>
        <rect className="cp-chassis-dark" x="24" y="27" width="8" height="1.5" rx="0.75" />
        <rect className="cp-metal" x="25" y="31" width="6" height="3" />
        <rect className="cp-chassis-dark" x="8" y="36" width="5" height="14" rx="2.5" />
        <rect className="cp-chassis-dark" x="43" y="36" width="5" height="14" rx="2.5" />
        <rect className="cp-chassis" x="14" y="34" width="28" height="22" rx="6" />
        <rect className="cp-screen" x="18" y="38" width="20" height="11" rx="2" strokeWidth="0.8" />
        <text x="28" y="46" textAnchor="middle" fontSize="7" fontWeight="700"
              fill="var(--cp-chassis)" fontFamily="ui-monospace, monospace">
          {glyph}
        </text>
        <rect className="cp-metal" x="17" y="56" width="22" height="5" rx="2" />
        <circle className="cp-metal" cx="21" cy="63" r="3" />
        <circle className="cp-metal" cx="35" cy="63" r="3" />
      </g>
    </svg>
  );
}

function SleepingRobot() {
  return (
    <div className="flex w-[76px] flex-col items-center pt-1 opacity-70" data-testid="cp-asleep"
         title="Whale — 'no single holder owns too much'. Switched off: it needs a paid data plan.">
      <div className="cp-bot relative" data-state="asleep" style={{ "--cp-chassis": "var(--color-neutral)" } as React.CSSProperties}>
        <RobotFigure robot={{ id: "whale", name: "Whale", stage: "safety", job: "", codes: [] }}
                     index={1} />
        <span className="cp-zz absolute -right-1 top-0 text-[10px] font-bold text-ink-3">z</span>
      </div>
      <div className="mt-0.5 text-[11px] font-medium text-ink-3">Whale</div>
      <div className="text-[10px] text-ink-3">asleep · off</div>
    </div>
  );
}

function Coin({ event, state }: { event: CheckpointEvent; state: "move" | "stop" | "deliver" }) {
  return (
    <span data-state={state}
          className="cp-coin absolute -top-2 left-1/2 z-10 -ml-[22px] flex h-[22px] min-w-[44px] items-center justify-center rounded-full bg-[var(--color-score-elite)] px-1.5 text-[9px] font-bold text-[var(--color-canvas)]">
      {(event.symbol ?? "?").slice(0, 7)}
    </span>
  );
}

export function CheckpointOffice({ data, now = Date.now(), motionOverride }: {
  data: Checkpoint | undefined;
  now?: number;
  /** Tests pass false; the page asks the browser. */
  motionOverride?: boolean;
}) {
  const motionPref = useMotion();
  const motion = motionOverride ?? motionPref;
  const events = useMemo(() => [...(data?.feed ?? [])].reverse(), [data]);
  const belt = useConveyor(events, motion);
  const [picked, setPicked] = useState<number | null>(null);

  // Without motion, the newest coin sits where it ended.
  const live = motion
    ? belt
    : events.length
      ? { e: events.length - 1, step: robotIndexFor(events[events.length - 1]!), phase: "hold" as Phase }
      : { e: 0, step: 0, phase: "move" as Phase };
  const event = events[live.e];
  const target = event ? robotIndexFor(event) : -1;

  const stateOf = (i: number): BotState => {
    if (!event) return "idle";
    if (live.phase === "hold" && i === target) return event.kind === "stopped" ? "stop" : "pass";
    if (i < live.step) return "pass";
    if (i === live.step && live.phase === "move") return "scan";
    return "idle";
  };

  const totalStopped = Object.values(data?.stopped_by ?? {}).reduce((a, b) => a + b, 0);
  const bought = data?.feed.filter((e) => e.kind === "bought").length ?? 0;
  const binned = data?.feed.filter((e) => e.kind === "stopped").length ?? 0;
  const robot = picked !== null ? ROBOTS[picked] : null;
  const caption = event
    ? event.kind === "bought"
      ? `${event.symbol ?? "A coin"} passed all 30 and was bought · ${ago(event.at, now)}`
      : `${event.symbol ?? "A coin"} stopped by ${ROBOTS[target]!.name} · ${ago(event.at, now)}`
    : "Waiting for the first coin";

  return (
    <section className="cp overflow-hidden rounded-xl border border-line" aria-label="The Checkpoint"
             data-testid="checkpoint">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-ink">The Checkpoint</h2>
          <p className="text-xs text-ink-3">
            30 robots check every coin before the real wallet buys it. The belt replays the latest
            real coins.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs tabular-nums">
          <span className="flex items-center gap-1.5 text-up">
            <span className="relative inline-flex h-2 w-2">
              <span className="cp-live-dot absolute inset-0 rounded-full bg-up" />
              <span className="relative h-2 w-2 rounded-full bg-up" />
            </span>
            Live
          </span>
          {data ? (
            <>
              <span className="text-ink-2"><b className="text-ink">{data.safety_checked.toLocaleString("en-US")}</b> safety checks</span>
              <span className="text-ink-2"><b className="text-up">{data.safety_allowed.toLocaleString("en-US")}</b> passed</span>
              <span className="text-ink-2"><b className="text-down">{totalStopped.toLocaleString("en-US")}</b> stops on record</span>
            </>
          ) : null}
        </div>
      </header>

      <div className="px-4 pt-3 text-sm text-ink-2" aria-live="polite" data-testid="cp-caption">
        <span className="text-ink-3">Now on the belt: </span>{caption}
      </div>

      {/* Four a row in the first two halls, eight in the third. */}
      <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,4fr)_minmax(0,8fr)]">
        {STAGES.map((stage) => (
          <Hall key={stage.id} stage={stage} stateOf={stateOf} data={data}
                coinAt={event ? live.step : -1}
                coin={event ? { event, state: live.phase === "hold"
                  ? (event.kind === "stopped" ? "stop" : "deliver") : "move" } : null}
                stamp={live.phase === "hold" && event ? { at: target, kind: event.kind } : null}
                onPick={setPicked} picked={picked} />
        ))}
      </div>

      <footer className="grid gap-3 border-t border-line px-4 py-3 sm:grid-cols-[1fr_auto_auto]">
        <div className="min-h-[3rem] text-xs" data-testid="cp-detail">
          {robot ? (
            <>
              <div className="text-sm font-semibold text-ink">
                {robot.name} <span className="font-normal text-ink-3">· {STAGES.find((s) => s.id === robot.stage)!.title}</span>
              </div>
              <div className="text-ink-2">{robot.job}</div>
              <div className="mt-0.5 text-ink-3">
                {stoppedBy(robot, data) === null
                  ? "Guards every buy. Its refusals aren't recorded, so it shows no count."
                  : `Stopped ${stoppedBy(robot, data)!.toLocaleString("en-US")} coins on record.`}
              </div>
            </>
          ) : (
            <span className="text-ink-3">Tap a robot to see what it checks and how many coins it stopped.</span>
          )}
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-up/40 bg-up/[0.06] px-3 py-2 text-xs">
          <span className="text-lg font-semibold tabular-nums text-up">{bought}</span>
          <span className="text-ink-2">into the wallet<br /><span className="text-ink-3">last 24h</span></span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-down/40 bg-down/[0.06] px-3 py-2 text-xs">
          <span className="text-lg font-semibold tabular-nums text-down">{binned}</span>
          <span className="text-ink-2">in the rug bin<br /><span className="text-ink-3">last 24h</span></span>
        </div>
      </footer>
    </section>
  );
}

function Hall({ stage, stateOf, data, coinAt, coin, stamp, onPick, picked }: {
  stage: (typeof STAGES)[number];
  stateOf: (i: number) => BotState;
  data: Checkpoint | undefined;
  coinAt: number;
  coin: { event: CheckpointEvent; state: "move" | "stop" | "deliver" } | null;
  stamp: { at: number; kind: CheckpointEvent["kind"] } | null;
  onPick: (i: number) => void;
  picked: number | null;
}) {
  const members = ROBOTS.map((r, i) => ({ r, i })).filter(({ r }) => r.stage === stage.id);
  return (
    <div className="cp-hall relative flex flex-col overflow-hidden rounded-lg border" data-stage={stage.id}>
      <div className="cp-hall-light h-0.5 w-full" />
      <span className="cp-hall-number" aria-hidden="true">{STAGES.indexOf(stage) + 1}</span>
      <div className="px-3 pt-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink">{stage.title}</div>
        <div className="text-[11px] text-ink-3">{stage.blurb}</div>
      </div>
      <div className="flex flex-1 flex-wrap content-start justify-center gap-x-1 gap-y-3 px-2 pb-2 pt-4">
        {members.map(({ r, i }) => {
          const count = stoppedBy(r, data);
          return (
            <button key={r.id} type="button" onClick={() => onPick(i)}
                    className="cp-bot relative flex w-[76px] flex-col items-center rounded-lg pt-1"
                    data-state={stateOf(i)} data-testid={`cp-bot-${r.id}`}
                    aria-pressed={picked === i} aria-label={`${r.name}: ${r.job}`}
                    style={{ "--cp-delay": `${(i * 0.37) % 3}s` } as React.CSSProperties}>
              {coin && coinAt === i ? <Coin event={coin.event} state={coin.state} /> : null}
              {stamp && stamp.at === i ? (
                <span className={`cp-stamp absolute right-0 top-5 z-20 rounded border-2 px-1 text-[9px] font-black tracking-wider ${
                  stamp.kind === "stopped" ? "border-down text-down" : "border-up text-up"}`}>
                  {stamp.kind === "stopped" ? "STOP" : "BUY ✓"}
                </span>
              ) : null}
              <RobotFigure robot={r} index={i} />
              {/* Its desk: three lights that blink at their own pace. */}
              <span className="cp-desk" aria-hidden="true">
                <span className="cp-led" /><span className="cp-led" /><span className="cp-led" />
              </span>
              <span className={`mt-0.5 text-[11px] font-medium ${picked === i ? "text-ink" : "text-ink-2"}`}>{r.name}</span>
              <span className="text-[10px] tabular-nums text-ink-3">
                {count === null ? "guard" : `${count.toLocaleString("en-US")} stopped`}
              </span>
            </button>
          );
        })}
        {stage.id === "safety" ? <SleepingRobot /> : null}
      </div>
      <div className="cp-belt h-2.5 w-full" aria-hidden="true" />
    </div>
  );
}

export function CheckpointLive() {
  const q = useCheckpoint();
  return <CheckpointOffice data={q.data} />;
}
