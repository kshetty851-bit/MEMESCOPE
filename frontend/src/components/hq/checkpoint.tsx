"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { Character, RigDefs, portraitViewBox } from "@/components/hq/character-rig";
import type { CharacterDefinition, Emotion, Pose } from "@/lib/hq/characters";
import {
  ROBOTS, STAGES, WHALE, coinKey, idleOf, liveIndex, lookOf, stoppedBy,
  type Checkpoint, type CheckpointEvent, type LiveBelt, type LiveCoin,
} from "@/lib/hq/checkpoint";
import {
  LEAD_LOOK, MANAGER, MANAGER_LOOK, TEAM_LEAD, award, banter, motivate, praiseBuy, praiseStop,
  reportLab, reportToday, reportWallets, scoldRug, solo, topStopper, voiceOf,
  type LabSummary, type WalletProfitRow,
  type Line,
} from "@/lib/hq/checkpoint-chatter";

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
    // Every 15s (2026-10-04): the homepage shows these counts "in real time".
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

function useLive(pool?: "10k") {
  return useQuery({
    queryKey: ["hq", "checkpoint", "live", pool ?? "real"],
    queryFn: () => api.get<LiveBelt>(`/real-wallet/checkpoint/live${pool ? `?pool=${pool}` : ""}`),
    refetchInterval: POLL_MS,
    staleTime: POLL_MS / 2,
  });
}

/** What Layla reads out: Karthik's Lab's public summary, and (signed-in
 *  viewers only — the endpoint refuses everyone else) the real wallets. */
function useMoneyReports(): { lab?: LabSummary; wallets?: WalletProfitRow[] } {
  const lab = useQuery({
    queryKey: ["hq", "checkpoint", "lab-summary"],
    queryFn: () => api.get<LabSummary>("/labs/graduation/karthik/summary"),
    refetchInterval: 60_000, staleTime: 30_000, retry: false,
  });
  const wallets = useQuery({
    queryKey: ["hq", "checkpoint", "wallets-profit"],
    queryFn: () => api.get<{ wallets: WalletProfitRow[] }>("/real-wallet/wallets-profit"),
    // A visitor without the site code is refused once, then not asked again.
    refetchInterval: (query) => (query.state.status === "error" ? false : 60_000),
    staleTime: 30_000, retry: false,
  });
  return { lab: lab.data, wallets: wallets.data?.wallets };
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
function PersonFigure({ index, state, now, talking }: {
  index: number; state: BotState; now: number; talking?: Emotion;
}) {
  const look = lookOf(index);
  const mood: { emotion: Emotion; pose: Pose } =
    state === "stop" ? { emotion: "angry", pose: "standing" }
    : state === "pass" ? { emotion: "happy", pose: "cheering" }
    : state === "scan" ? { emotion: "surprised", pose: "holding_tablet" }
    : talking ? { emotion: talking, pose: "talking_briefly" }
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

/** How long each line stays up. */
const TALK_MS = 4_500;
const VOICES_KEY = "memescope.checkpointVoices";
/** macOS's joke voices (an organ, bells, a whisper...): a person never sounds like these. */
const NOVELTY_VOICES =
  /albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|fred|junior|ralph|kathy|grandma|grandpa|eddy|flo|reed|rocko|sandy|shelley/i;

/**
 * The office's talk (2026-10-04). The manager reacts to REAL events as they
 * land on the belt — a stop, a buy, a bought coin that rugged — and between
 * them hands out the award (from the stop counts on record), nudges people,
 * or two neighbours chat. One line at a time, every few seconds.
 */
function useChatter(tracks: Track[], data: Checkpoint | undefined, on: boolean,
                    money: { lab?: LabSummary; wallets?: WalletProfitRow[] } = {}): Line | null {
  const [line, setLine] = useState<Line | null>(null);
  const queue = useRef<Line[]>([]);
  const heard = useRef<Set<string> | null>(null);
  const scolded = useRef<Set<string>>(new Set());
  const tick = useRef(0);

  // Real events, each once. What was already on the belt when the page opened
  // is not news.
  useEffect(() => {
    const settled = tracks.filter((t) => t.coin.status !== "checking" && t.shown === t.target);
    if (heard.current === null) {
      heard.current = new Set(settled.map((t) => coinKey(t.coin)));
      return;
    }
    for (const t of settled) {
      const key = coinKey(t.coin);
      if (heard.current.has(key)) continue;
      heard.current.add(key);
      const seed = Date.now() / 1000;
      if (t.coin.status === "bought") queue.current.push(praiseBuy(t.coin.symbol, seed));
      // A stop the records pin on no one (the wallet gate's) has no one to praise.
      else if (ROBOTS[t.target]) queue.current.push(praiseStop(t.target, t.coin.symbol, seed));
    }
  }, [tracks]);

  useEffect(() => {
    for (const r of data?.rugged_buys ?? []) {
      const key = `${r.symbol}|${r.at}`;
      if (scolded.current.has(key)) continue;
      scolded.current.add(key);
      queue.current.push(scoldRug(r.symbol, Date.parse(r.at) / 1000));
    }
  }, [data]);

  useEffect(() => {
    if (!on) return;
    const id = window.setInterval(() => {
      tick.current += 1;
      const seed = Math.floor(Date.now() / 1000);
      let next = queue.current.shift() ?? null;
      // Layla's money round, every sixth line: the lab, then the real wallets
      // (signed-in viewers only), then today's score.
      if (!next && tick.current % 6 === 0) {
        const round = Math.floor(tick.current / 6) % 3;
        next = (round === 1 ? reportWallets(money.wallets, seed) : round === 2 ? reportToday(money.wallets, seed) : null)
          ?? reportLab(money.lab, seed);
      }
      if (!next && tick.current % 7 === 0) next = award(data, seed) ?? motivate(seed);
      else if (!next && tick.current % 5 === 0) next = motivate(seed);
      else if (!next && tick.current % 3 === 0) next = solo(seed);
      else if (!next) {
        const [ask, answer] = banter(seed);
        next = ask;
        queue.current.unshift(answer);
      }
      setLine(next);
    }, TALK_MS);
    return () => window.clearInterval(id);
  }, [on, data, money.lab, money.wallets]);

  return line;
}

/** Speak each new line aloud, in that person's own voice, when voices are on. */
/**
 * Browsers let a page speak only after the visitor has touched it (a tap, a
 * click, a key). Voices are ON by default (Karthik, 2026-10-04), so the first
 * such touch anywhere on the page unlocks them — on iOS it must speak inside
 * that touch, hence the silent first word.
 */
function useSpeechUnlocked(): boolean {
  const [unlocked, setUnlocked] = useState(false);
  useEffect(() => {
    const nav = navigator as Navigator & { userActivation?: { hasBeenActive: boolean } };
    if (nav.userActivation?.hasBeenActive) { setUnlocked(true); return; }
    const unlock = () => {
      try {
        if ("speechSynthesis" in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(" "));
      } catch { /* no speech here */ }
      setUnlocked(true);
    };
    const events = ["pointerdown", "keydown", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, unlock, { once: true, passive: true }));
    return () => events.forEach((e) => window.removeEventListener(e, unlock));
  }, []);
  return unlocked;
}

/** Speak each new line aloud, in that person's own voice, when voices are on. */
function useVoice(line: Line | null, voices: boolean, unlocked: boolean) {
  useEffect(() => {
    if (!voices || !unlocked || !line || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    if (document.visibilityState !== "visible") return;
    const synth = window.speechSynthesis;
    const english = synth.getVoices().filter((v) => v.lang.toLowerCase().startsWith("en")
      && !NOVELTY_VOICES.test(v.name));
    const u = new SpeechSynthesisUtterance(line.text.replace(/[^\p{L}\p{N}\p{P}\s]/gu, ""));
    const { pitch, rate } = voiceOf(line.who);
    u.pitch = pitch;
    u.rate = rate;
    const slot = line.who === "manager" ? 0 : line.who === "lead" ? 1 : line.who + 2;
    if (english.length) u.voice = english[slot % english.length]!;
    synth.cancel();
    synth.speak(u);
  }, [line, voices, unlocked]);
}

/** ON unless this browser turned them off (default flipped 2026-10-04). */
function useVoicesSetting(): [boolean, () => void] {
  const [on, setOn] = useState(true);
  useEffect(() => {
    try { setOn(window.localStorage.getItem(VOICES_KEY) !== "off"); } catch { /* private mode */ }
  }, []);
  const toggle = () => setOn((was) => {
    const next = !was;
    try { window.localStorage.setItem(VOICES_KEY, next ? "on" : "off"); } catch { /* private mode */ }
    if (!next && typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    return next;
  });
  return [on, toggle];
}

/** One person at the managers' desk: their figure and what they are saying. */
function DeskPerson({ look, first, title, blurb, speaking, now, idleSeed, testId }: {
  look: typeof MANAGER_LOOK; first: string; title: string; blurb: string;
  speaking: Line | null; now: number; idleSeed: number; testId: string;
}) {
  const box = portraitViewBox(look as CharacterDefinition, "bust");
  const idle = idleOf(idleSeed, now);
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3" data-testid={testId}>
      <svg viewBox={box} width={56} height={64} aria-hidden="true" className="cp-person shrink-0 overflow-visible">
        <g className="cp-body">
          <Character character={look}
                     pose={speaking ? "talking_briefly" : idle.pose === "stretching" ? "standing" : idle.pose}
                     emotion={speaking ? speaking.mood : "neutral"} />
        </g>
      </svg>
      <div className="min-w-0">
        <div className="text-[12px] font-semibold text-ink">
          {first} <span className="font-normal text-ink-3">· {title}</span>
        </div>
        {speaking ? (
          <div key={speaking.text} className="cp-say mt-1" data-testid={`${testId}-bubble`}>{speaking.text}</div>
        ) : (
          <div className="text-[11px] text-ink-3">{blurb}</div>
        )}
      </div>
    </div>
  );
}

/** Marco, the floor manager, and Layla, his team leader, above the halls. */
function ManagerDesk({ talk, data, now }: { talk: Line | null; data: Checkpoint | undefined; now: number }) {
  const top = topStopper(data);
  return (
    <div className="cp-manager mx-4 mt-3 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border px-3 py-2"
         data-testid="cp-manager">
      <DeskPerson look={MANAGER_LOOK} first={MANAGER.first} title={MANAGER.name} testId="cp-manager-marco"
                  blurb="Watches all thirty: praises every catch, scolds every rug that gets through."
                  speaking={talk?.who === "manager" ? talk : null} now={now} idleSeed={7} />
      <DeskPerson look={LEAD_LOOK} first={TEAM_LEAD.first} title={TEAM_LEAD.name} testId="cp-manager-lead"
                  blurb="Reads out the profit and loss, cheers the wins, rallies after the losses."
                  speaking={talk?.who === "lead" ? talk : null} now={now} idleSeed={19} />
      {top ? (
        <div className="hidden shrink-0 rounded-md border border-line px-2 py-1 text-right text-[11px] sm:block">
          <div className="uppercase tracking-wider text-ink-3">Award</div>
          <div className="font-semibold text-ink">
            🏆 {ROBOTS[top.index]!.first} · {top.count.toLocaleString("en-US")} stops
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function CheckpointOffice({ data, live, now: nowProp, motionOverride, money = {}, mode = "real" }: {
  /** "pool10k" (2026-10-05): the same thirty checking for the Pool Lab's $10k
   *  paper book — Diego's floor is $10,000 and a buy is the book's. */
  mode?: "real" | "pool10k";
  data: Checkpoint | undefined;
  live: LiveBelt | undefined;
  /** What Layla reads out (`useMoneyReports`); none in tests. */
  money?: { lab?: LabSummary; wallets?: WalletProfitRow[] };
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
  const [voices, toggleVoices] = useVoicesSetting();
  const unlocked = useSpeechUnlocked();
  const talk = useChatter(tracks, data, motionOverride !== false, money);
  useVoice(talk, voices, unlocked);

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
            {mode === "pool10k"
              ? "The same 30 people checking every coin for the $10k paper book — live, as each coin graduates."
              : "30 people check every coin before the real wallet buys it — live, as each coin graduates."}
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
          <button type="button" onClick={toggleVoices} aria-pressed={voices}
                  className={`rounded-md border px-2 py-0.5 text-[11px] ${voices ? "border-accent text-accent" : "border-line text-ink-3"}`}
                  data-testid="cp-voices">
            {!voices ? "🔈 Voices off" : unlocked ? "🔊 Voices on" : "🔊 Tap anywhere to hear them"}
          </button>
        </div>
      </header>

      {/* The rig's shared gradients, once for all thirty-one figures. */}
      <svg width="0" height="0" aria-hidden="true" className="absolute"><RigDefs /></svg>
      <ManagerDesk talk={talk} data={data} now={now} />
      <div className="grid gap-3 p-4 xl:grid-cols-[minmax(0,4fr)_minmax(0,4fr)_minmax(0,8fr)]">
        {STAGES.map((stage) => (
          <Hall key={stage.id} stage={stage} stateOf={stateOf} data={data} onBelt={onBelt}
                stamp={stamp} recentStops={recentStops} onPick={setPicked} picked={picked} now={now}
                talk={talk} mode={mode} />
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
              <div className="text-ink-2">{jobOf(robot, mode)}</div>
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

function Hall({ stage, stateOf, data, onBelt, stamp, recentStops, onPick, picked, now, talk, mode }: {
  now: number;
  mode: "real" | "pool10k";
  talk: Line | null;
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
                    aria-pressed={picked === i} aria-label={`${r.first} (${r.name}): ${jobOf(r, mode)}`}
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
              ) : talk?.who === i ? (
                <span className="cp-bubble cp-bubble-talk" data-testid={`cp-talk-${r.id}`}>{talk.text}</span>
              ) : null}
              <PersonFigure index={i} state={stateOf(i)} now={now}
                            talking={talk?.who === i ? talk.mood : undefined} />
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

/** A person's check in words; Diego's floor follows the office's mode. */
function jobOf(r: (typeof ROBOTS)[number], mode: "real" | "pool10k"): string {
  return mode === "pool10k" && r.id === "depth" ? "The pool holds at least $10,000" : r.job;
}

/** The office for the Pool Lab's $10k paper book (2026-10-05). */
export function CheckpointPool10k({ money }: { money?: { lab?: LabSummary } }) {
  const live = useLive("10k");
  return <CheckpointOffice data={undefined} live={live.data} money={money} mode="pool10k" />;
}

export function CheckpointLive() {
  const q = useCheckpoint();
  const live = useLive();
  const money = useMoneyReports();
  return <CheckpointOffice data={q.data} live={live.data} money={money} />;
}

/**
 * THE ROSTER (Karthik, 2026-10-04: "below display their rules and achievements
 * so far and change in real time"). Each person's check in plain words and how
 * many coins it has stopped, from the same records as the office above. The
 * wallet gate's people own no refusal codes (their refusals are not recorded),
 * so they show what they do rather than a count nobody kept.
 */
export function CheckpointRoster() {
  const { data } = useCheckpoint();
  const stops = data ? Object.values(data.stopped_by).reduce((a, b) => a + b, 0) : null;
  const rugBlocks = data
    ? ROBOTS.filter((r) => r.stage === "rule")
        .reduce((n, r) => n + (stoppedBy(r, data) ?? 0), 0)
    : null;
  const num = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-US"));
  return (
    <section className="cp mt-4 overflow-hidden rounded-xl border border-line p-4" data-testid="cp-roster">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-ink">Their rules, and what they have stopped</h3>
        <span className="flex items-center gap-1.5 text-[11px] text-ink-3">
          <span className="cp-live-dot inline-block h-1.5 w-1.5 rounded-full bg-up" aria-hidden="true" />
          updates every 15 seconds
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ["Coins stopped", num(stops), "text-down"],
          ["Rug blocks", num(rugBlocks), "text-down"],
          ["Safety-checked", num(data?.safety_checked), "text-ink"],
          ["Passed all checks", num(data?.safety_allowed), "text-up"],
        ].map(([label, value, tone]) => (
          <div key={label} className="rounded-lg border border-line bg-ink/[0.02] p-3">
            <div className="text-[10px] uppercase tracking-wider text-ink-3">{label}</div>
            <div className={`mt-0.5 text-xl font-semibold tabular-nums ${tone}`}>{value}</div>
          </div>
        ))}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {STAGES.map((stage) => (
          <div key={stage.id} className="cp-hall rounded-lg border p-3" data-stage={stage.id}>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">{stage.title}</div>
            <div className="text-[11px] text-ink-3">{stage.blurb}</div>
            <ul className="mt-2 divide-y divide-line/60">
              {ROBOTS.filter((r) => r.stage === stage.id).map((r) => {
                const n = stoppedBy(r, data);
                return (
                  <li key={r.id} className="flex items-start justify-between gap-3 py-1.5" data-testid={`cp-roster-${r.id}`}>
                    <div className="min-w-0">
                      <div className="text-[12px] font-semibold text-ink">
                        {r.first} <span className="font-normal text-ink-3">· {r.name}</span>
                      </div>
                      <div className="text-[11px] leading-snug text-ink-2">{r.job}</div>
                    </div>
                    <div className="shrink-0 text-right text-[11px] tabular-nums">
                      {n == null ? (
                        <span className="text-ink-3">on duty</span>
                      ) : (
                        <span className={n > 0 ? "font-semibold text-down" : "text-ink-3"}>
                          {n.toLocaleString("en-US")} stopped
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

/** The homepage's view: the office at work, then the roster under it. */
export function CheckpointPublic() {
  return (
    <>
      <CheckpointLive />
      <CheckpointRoster />
    </>
  );
}
