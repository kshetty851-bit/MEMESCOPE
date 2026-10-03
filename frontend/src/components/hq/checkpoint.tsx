"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { Character, RigDefs, portraitViewBox } from "@/components/hq/character-rig";
import type { CharacterDefinition, Emotion, Pose } from "@/lib/hq/characters";
import {
  DEFAULT_FLOOR, ROBOTS, STAGES, WHALE, atFloor, coinKey, idleOf, jobOf, liveIndex, lookOf,
  stoppedBy,
  type Checkpoint, type CheckpointEvent, type CheckpointFloor, type LiveBelt, type LiveCoin,
} from "@/lib/hq/checkpoint";

/**
 * THE CHECKPOINT (Karthik, 2026-10-02: "show this 30 checks as 30 agents look
 * like robots and name them, give them their own big office with all
 * animations"; then "i want real time token checks").
 *
 * Its own office beside HQ's, not more staff in it: the main floor's
 * invariants (four standing, unique accessories, routes on the grid) were
 * written for a dozen people, and thirty robots would break every one.
 *
 * LIVE, from the records: every coin that graduated in the last ten minutes
 * sits at the check it has reached (`/real-wallet/checkpoint/live`, polled
 * every few seconds). A coin that appears rolls in from Hatch and steps along
 * to where its records put it, each robot it passes flashing green; the robot
 * that decides it scans while it waits, then stamps STOP or passes it on.
 * Each robot's all-time count is the refusal codes it owns
 * (`/real-wallet/checkpoint`).
 */

const STEP_MS = 140;
/** How long a fresh stop or buy keeps its stamp and its coin on the belt. */
const FRESH_MS = 6000;
const POLL_MS = 4000;

type BotState = "idle" | "scan" | "pass" | "stop" | "asleep";

interface Track {
  coin: LiveCoin;
  target: number;
  shown: number;
  /** When `shown` last moved, and when it reached `target` (or decided there). */
  movedAt: number;
  settledAt: number;
}

function useCheckpoint(floorUsd: CheckpointFloor) {
  return useQuery({
    queryKey: ["hq", "checkpoint", floorUsd],
    queryFn: () => api.get<Checkpoint>(atFloor("/real-wallet/checkpoint", floorUsd)),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

function useLive(floorUsd: CheckpointFloor) {
  return useQuery({
    queryKey: ["hq", "checkpoint", "live", floorUsd],
    queryFn: () => api.get<LiveBelt>(atFloor("/real-wallet/checkpoint/live", floorUsd)),
    refetchInterval: POLL_MS,
    staleTime: POLL_MS / 2,
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

function useClock(ms: number): number {
  // 0 until mounted: the idle moods follow the clock, and the server's
  // clock is never the browser's, so a real time here breaks hydration.
  const [now, setNow] = useState(0);
  useEffect(() => {
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

/**
 * Each coin's place on the belt. Coins already there on the first reading
 * start where they are; a coin that appears later starts at Hatch and steps
 * along. A change of status where the coin stands (checking → stopped)
 * restamps it.
 */
export function useLiveBelt(coins: LiveCoin[] | undefined, motion: boolean) {
  const [tracks, setTracks] = useState<Record<string, Track>>({});
  const seen = useRef(false);
  useEffect(() => {
    if (!coins) return;
    const first = !seen.current;
    seen.current = true;
    const t = Date.now();
    setTracks((prev) => {
      const next: Record<string, Track> = {};
      for (const coin of coins) {
        const key = coinKey(coin);
        const target = liveIndex(coin);
        const old = prev[key];
        const start = old ? old.shown : first || !motion ? target : 0;
        const restamp = old && old.coin.status !== coin.status && old.shown === target;
        next[key] = {
          coin, target, shown: Math.min(start, Math.max(target, 0)),
          movedAt: old?.movedAt ?? t,
          settledAt: restamp ? t : old?.settledAt ?? (start === target ? (first ? 0 : t) : 0),
        };
      }
      return next;
    });
  }, [coins, motion]);
  useEffect(() => {
    if (!motion) return;
    const id = window.setInterval(() => {
      setTracks((prev) => {
        let moved = false;
        const t = Date.now();
        const next = { ...prev };
        for (const [key, tr] of Object.entries(prev)) {
          if (tr.target >= 0 && tr.shown < tr.target) {
            const shown = tr.shown + 1;
            next[key] = { ...tr, shown, movedAt: t, settledAt: shown === tr.target ? t : 0 };
            moved = true;
          }
        }
        return moved ? next : prev;
      });
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [motion]);
  return Object.values(tracks);
}

function since(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  return s < 90 ? `${s}s ago` : `${Math.round(s / 60)} min ago`;
}

function who(coin: LiveCoin): string {
  const i = liveIndex(coin);
  if (coin.status === "bought") return "Bought";
  if (i < 0) return coin.status === "stopped" ? "Wallet gate" : "Checking";
  return `${ROBOTS[i]!.first} · ${ROBOTS[i]!.name}`;
}

/** One person, drawn with HQ's own character rig, feeling what their check
 *  is doing: curious while a coin is in front of them, cheering when it
 *  passes, cross when they stop it, and their own moods in between. */
function PersonFigure({ index, state, now }: { index: number; state: BotState; now: number }) {
  const look = lookOf(index);
  const mood: { emotion: Emotion; pose: Pose } =
    state === "stop" ? { emotion: "angry", pose: "standing" }
    : state === "pass" ? { emotion: "happy", pose: "cheering" }
    : state === "scan" ? { emotion: "surprised", pose: "holding_tablet" }
    : idleOf(index, now);
  const box = portraitViewBox(look as CharacterDefinition, "bust");
  const [x, y, w, h] = box.split(" ").map(Number) as [number, number, number, number];
  return (
    <svg viewBox={box} width={64} height={72} aria-hidden="true" className="cp-person overflow-visible">
      <g className="cp-body">
        <circle className="cp-halo" cx={x + w / 2} cy={y + h / 2} r={w * 0.55} />
        <Character character={look} pose={mood.pose} stance="standing" emotion={mood.emotion} />
      </g>
    </svg>
  );
}

function SleepingWhale() {
  const box = portraitViewBox(WHALE as CharacterDefinition, "bust");
  return (
    <div className="flex w-[76px] flex-col items-center pt-1 opacity-75" data-testid="cp-asleep"
         title="Walt · Whale — 'no single holder owns too much'. Switched off: it needs a paid data plan.">
      <div className="cp-bot relative" data-state="asleep">
        <svg viewBox={box} width={64} height={72} aria-hidden="true" className="cp-person overflow-visible">
          <g className="cp-body"><Character character={WHALE} emotion="tired" /></g>
        </svg>
        <span className="cp-zz absolute -right-1 top-0 text-[11px] font-bold text-ink-3">z</span>
        <span className="cp-zz absolute right-2 -top-2 text-[9px] font-bold text-ink-3 [animation-delay:1s]">z</span>
      </div>
      <div className="mt-0.5 text-[11px] font-semibold text-ink-3">Walt</div>
      <div className="text-[10px] text-ink-3">Whale · asleep</div>
    </div>
  );
}

function Coin({ label, extra, state }: { label: string | null; extra: number; state: "move" | "stop" | "deliver" }) {
  return (
    <span data-state={state}
          className="cp-coin absolute -top-2 left-1/2 z-10 -ml-[24px] flex h-[22px] min-w-[48px] items-center justify-center rounded-full bg-[var(--color-score-elite)] px-1.5 font-bold text-[var(--color-canvas)]">
      {(label ?? "?").slice(0, 7)}{extra > 0 ? ` +${extra}` : ""}
    </span>
  );
}

export function CheckpointOffice({
  data, live, now: nowProp, motionOverride, floorUsd = DEFAULT_FLOOR,
}: {
  data: Checkpoint | undefined;
  live: LiveBelt | undefined;
  now?: number;
  /** Tests pass false; the page asks the browser. */
  motionOverride?: boolean;
  /** The pool rule drawn: Karthik's Lab passes his book's $50k (2026-10-03). */
  floorUsd?: CheckpointFloor;
}) {
  const motionPref = useMotion();
  const motion = motionOverride ?? motionPref;
  const clock = useClock(1000);
  const now = nowProp ?? clock;
  const tracks = useLiveBelt(live?.coins, motion);
  const [picked, setPicked] = useState<number | null>(null);

  const fresh = (t: number) => t > 0 && now - t < FRESH_MS;
  const stateOf = (i: number): BotState => {
    let state: BotState = "idle";
    for (const tr of tracks) {
      if (tr.shown === i && tr.shown < tr.target) return "scan";
      if (tr.shown === i && tr.target === i) {
        if (tr.coin.status === "checking") state = "scan";
        else if (fresh(tr.settledAt)) return tr.coin.status === "stopped" ? "stop" : "pass";
      }
      if (tr.shown === i + 1 && tr.shown <= tr.target && now - tr.movedAt < 500 && state === "idle") {
        state = "pass";
      }
    }
    return state;
  };
  const onBelt = (i: number) => tracks.filter((tr) => tr.shown === i && (
    tr.shown < tr.target || tr.coin.status === "checking" || fresh(tr.settledAt)));
  const stamp = (i: number) => {
    const tr = tracks.find((t) => t.shown === i && t.target === i && t.coin.status !== "checking"
      && fresh(t.settledAt));
    return tr ? tr.coin.status : null;
  };
  const recentStops = (i: number) => tracks.filter(
    (tr) => tr.target === i && tr.shown === i && tr.coin.status === "stopped").length;

  const coins = live?.coins ?? [];
  const checking = coins.filter((c) => c.status === "checking").length;
  const totalStopped = Object.values(data?.stopped_by ?? {}).reduce((a, b) => a + b, 0);
  const bought = data?.feed.filter((e: CheckpointEvent) => e.kind === "bought").length ?? 0;
  const binned = data?.feed.filter((e: CheckpointEvent) => e.kind === "stopped").length ?? 0;
  const robot = picked !== null ? ROBOTS[picked] : null;

  return (
    <section className="cp overflow-hidden rounded-xl border border-line" aria-label="The Checkpoint"
             data-testid="checkpoint">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-ink">The Checkpoint</h2>
          <p className="text-xs text-ink-3">
            30 people check every coin before the real wallet buys it — live, as each coin graduates.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs tabular-nums">
          <span className="flex items-center gap-1.5 text-up">
            <span className="relative inline-flex h-2 w-2">
              <span className="cp-live-dot absolute inset-0 rounded-full bg-up" />
              <span className="relative h-2 w-2 rounded-full bg-up" />
            </span>
            Live
          </span>
          <span className="text-ink-2"><b className="text-ink">{coins.length}</b> graduated in 10 min</span>
          <span className="text-ink-2"><b className="text-warn">{checking}</b> being checked now</span>
          {data ? (
            <span className="text-ink-2"><b className="text-down">{totalStopped.toLocaleString("en-US")}</b> stops on record</span>
          ) : null}
        </div>
      </header>

      {/* The rig's shared gradients, once for all thirty-one figures. */}
      <svg width="0" height="0" aria-hidden="true" className="absolute"><RigDefs /></svg>
      <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,4fr)_minmax(0,8fr)]">
        {STAGES.map((stage) => (
          <Hall key={stage.id} stage={stage} stateOf={stateOf} data={data} onBelt={onBelt}
                stamp={stamp} recentStops={recentStops} onPick={setPicked} picked={picked} now={now}
                floorUsd={floorUsd} />
        ))}
      </div>

      <div className="border-t border-line px-4 py-3" data-testid="cp-live-list">
        <div className="mb-1.5 text-[11px] uppercase tracking-wider text-ink-3">Latest coins</div>
        {coins.length ? (
          <ul className="grid gap-1 text-xs sm:grid-cols-2">
            {coins.slice(0, 8).map((c) => (
              <li key={coinKey(c)} className="flex items-baseline gap-2">
                <span className={`h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full ${
                  c.status === "bought" ? "bg-up" : c.status === "stopped" ? "bg-down" : "bg-warn"}`} />
                <b className="text-ink">{c.symbol ?? "?"}</b>
                <span className="text-ink-2">{who(c)}</span>
                <span className="min-w-0 truncate text-ink-3">{c.note}</span>
                <span className="ml-auto shrink-0 tabular-nums text-ink-3">{since(c.graduated_at, now)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-ink-3">No graduations in the last 10 minutes — waiting for the next one.</p>
        )}
      </div>

      <footer className="grid gap-3 border-t border-line px-4 py-3 sm:grid-cols-[1fr_auto_auto]">
        <div className="min-h-[3rem] text-xs" data-testid="cp-detail">
          {robot ? (
            <>
              <div className="text-sm font-semibold text-ink">
                {robot.first} · {robot.name} <span className="font-normal text-ink-3">· {STAGES.find((s) => s.id === robot.stage)!.title}</span>
              </div>
              <div className="text-ink-2">{jobOf(robot, floorUsd)}</div>
              <div className="mt-0.5 text-ink-3">
                {stoppedBy(robot, data) === null
                  ? "Guards every buy. Its refusals aren't recorded, so it shows no count."
                  : `Stopped ${stoppedBy(robot, data)!.toLocaleString("en-US")} coins on record.`}
              </div>
            </>
          ) : (
            <span className="text-ink-3">Tap anyone to see what they check and how many coins they stopped.</span>
          )}
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-up/40 bg-up/[0.06] px-3 py-2 text-xs">
          <span className="text-lg font-semibold tabular-nums text-up">{bought}</span>
          <span className="text-ink-2">into the wallet<br /><span className="text-ink-3">recently</span></span>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-down/40 bg-down/[0.06] px-3 py-2 text-xs">
          <span className="text-lg font-semibold tabular-nums text-down">{binned}</span>
          <span className="text-ink-2">rug blocks &amp; safety stops<br /><span className="text-ink-3">recently</span></span>
        </div>
      </footer>
    </section>
  );
}

function Hall({ stage, stateOf, data, onBelt, stamp, recentStops, onPick, picked, now, floorUsd }: {
  now: number;
  floorUsd: CheckpointFloor;
  stage: (typeof STAGES)[number];
  stateOf: (i: number) => BotState;
  data: Checkpoint | undefined;
  onBelt: (i: number) => Track[];
  stamp: (i: number) => LiveCoin["status"] | null;
  recentStops: (i: number) => number;
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
          const here = onBelt(i);
          const stamped = stamp(i);
          const recent = recentStops(i);
          return (
            <button key={r.id} type="button" onClick={() => onPick(i)}
                    className="cp-bot relative flex w-[76px] flex-col items-center rounded-lg pt-1"
                    data-state={stateOf(i)} data-testid={`cp-bot-${r.id}`}
                    aria-pressed={picked === i} aria-label={`${r.first} (${r.name}): ${jobOf(r, floorUsd)}`}
                    style={{ "--cp-delay": `${(i * 0.37) % 3}s` } as React.CSSProperties}>
              {here.length ? (
                <Coin label={here[0]!.coin.symbol} extra={here.length - 1}
                      state={stamped === "stopped" ? "stop" : stamped === "bought" ? "deliver" : "move"} />
              ) : null}
              {stamped && stamped !== "checking" ? (
                <span className={`cp-stamp absolute right-0 top-5 z-20 rounded border-2 px-1 text-[9px] font-black tracking-wider ${
                  stamped === "stopped" ? "border-down text-down" : "border-up text-up"}`}>
                  {stamped === "stopped" ? "STOP" : "BUY ✓"}
                </span>
              ) : null}
              {stamped === "stopped" ? (
                <span className="cp-bubble" data-testid={`cp-bubble-${r.id}`}>{r.stopLine}</span>
              ) : stamped === "bought" ? (
                <span className="cp-bubble cp-bubble-yes">All 30 said yes!</span>
              ) : null}
              <PersonFigure index={i} state={stateOf(i)} now={now} />
              <span className="cp-desk" aria-hidden="true">
                <span className="cp-led" /><span className="cp-led" /><span className="cp-led" />
              </span>
              <span className={`mt-0.5 text-[11px] font-semibold ${picked === i ? "text-ink" : "text-ink-2"}`}>{r.first}</span>
              <span className="text-[10px] text-ink-3">{r.name}</span>
              <span className="text-[10px] tabular-nums text-ink-3">
                {count === null ? "guard" : `${count.toLocaleString("en-US")} stopped`}
              </span>
              {recent ? (
                <span className="absolute left-1 top-1 rounded-full bg-down/90 px-1 text-[9px] font-bold tabular-nums text-[var(--color-canvas)]"
                      title={`${recent} stopped here in the last 10 minutes`}>
                  {recent}
                </span>
              ) : null}
            </button>
          );
        })}
        {stage.id === "safety" ? <SleepingWhale /> : null}
      </div>
      <div className="cp-belt h-2.5 w-full" aria-hidden="true" />
    </div>
  );
}

/** `floorUsd`: the pool rule to draw. HQ and the Real wallet pass nothing and
 *  keep the main wallet's $75k; Karthik's Lab passes his book's $50k. */
export function CheckpointLive({ floorUsd = DEFAULT_FLOOR }: { floorUsd?: CheckpointFloor } = {}) {
  const q = useCheckpoint(floorUsd);
  const live = useLive(floorUsd);
  return <CheckpointOffice data={q.data} live={live.data} floorUsd={floorUsd} />;
}
