"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import {
  ROBOTS, STAGES, coinKey, liveIndex, stoppedBy,
  type Checkpoint, type CheckpointEvent, type LiveBelt, type LiveCoin, type Robot,
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

function useCheckpoint() {
  return useQuery({
    queryKey: ["hq", "checkpoint"],
    queryFn: () => api.get<Checkpoint>("/real-wallet/checkpoint"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

function useLive() {
  return useQuery({
    queryKey: ["hq", "checkpoint", "live"],
    queryFn: () => api.get<LiveBelt>("/real-wallet/checkpoint/live"),
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
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
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
  return ROBOTS[i]!.name;
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

function Coin({ label, extra, state }: { label: string | null; extra: number; state: "move" | "stop" | "deliver" }) {
  return (
    <span data-state={state}
          className="cp-coin absolute -top-2 left-1/2 z-10 -ml-[24px] flex h-[22px] min-w-[48px] items-center justify-center rounded-full bg-[var(--color-score-elite)] px-1.5 font-bold text-[var(--color-canvas)]">
      {(label ?? "?").slice(0, 7)}{extra > 0 ? ` +${extra}` : ""}
    </span>
  );
}

export function CheckpointOffice({ data, live, now: nowProp, motionOverride }: {
  data: Checkpoint | undefined;
  live: LiveBelt | undefined;
  now?: number;
  /** Tests pass false; the page asks the browser. */
  motionOverride?: boolean;
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
            30 robots check every coin before the real wallet buys it — live, as each coin graduates.
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

      <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,4fr)_minmax(0,8fr)]">
        {STAGES.map((stage) => (
          <Hall key={stage.id} stage={stage} stateOf={stateOf} data={data} onBelt={onBelt}
                stamp={stamp} recentStops={recentStops} onPick={setPicked} picked={picked} />
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

function Hall({ stage, stateOf, data, onBelt, stamp, recentStops, onPick, picked }: {
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
                    aria-pressed={picked === i} aria-label={`${r.name}: ${r.job}`}
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
              <RobotFigure robot={r} index={i} />
              <span className="cp-desk" aria-hidden="true">
                <span className="cp-led" /><span className="cp-led" /><span className="cp-led" />
              </span>
              <span className={`mt-0.5 text-[11px] font-medium ${picked === i ? "text-ink" : "text-ink-2"}`}>{r.name}</span>
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
        {stage.id === "safety" ? <SleepingRobot /> : null}
      </div>
      <div className="cp-belt h-2.5 w-full" aria-hidden="true" />
    </div>
  );
}

export function CheckpointLive() {
  const q = useCheckpoint();
  const live = useLive();
  return <CheckpointOffice data={q.data} live={live.data} />;
}
