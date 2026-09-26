"use client";

import "./moon-intro.css";

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

import { Cockpit } from "./cockpit";
import { createSoundboard, type SoundName, type Soundboard } from "./soundboard";
import { createSpaceScene } from "./space-scene";
import {
  MOMENTS,
  REDUCED_TIMELINE,
  SHAKE,
  SHORT_TIMELINE,
  TIMELINE,
  phaseAt,
  phaseStart,
  type IntroPhase,
  type Timeline,
} from "./timeline";

/**
 * THE MOON INTRO — the master clock.
 *
 * One rAF loop turns elapsed seconds into a `Frame` for the canvas and writes
 * `--mi-t`/`--mi-p`/`data-phase` straight onto `.mi-root`. React re-renders
 * only when the phase changes or a moment passes. Each moment fires its sound
 * and shake kick once, as the clock crosses it; a skip marks the moments it
 * jumps over as passed without firing them.
 */
type Mode = "full" | "short" | "reduced";

export const SOUND_KEY = "memescope.moonIntro.sound";
export const SEEN_KEY = "memescope.moonIntro.seen";

const TIMELINES: Record<Mode, Timeline> = {
  full: TIMELINE,
  short: SHORT_TIMELINE,
  reduced: REDUCED_TIMELINE,
};

const SOUNDS: Record<string, SoundName> = {
  "seatbelt.buckle": "click",
  "ignition.beeps.0": "beep",
  "ignition.beeps.1": "beep",
  "ignition.beeps.2": "beep",
  "warp.velocity.0": "whoosh",
  "warp.velocity.1": "static",
  "warp.velocity.2": "static",
  "warp.velocity.3": "static",
  "approach.nearMiss": "alarm",
  "landing.touchdown": "thud",
  ...Object.fromEntries(MOMENTS.cockpit.switches.map((_, i) => [`cockpit.switches.${i}`, "switch"])),
};

const KICKS: Record<string, number> = {
  "cockpit.lockIn": SHAKE.lockIn,
  "approach.nearMiss": SHAKE.nearMiss,
  "landing.touchdown": SHAKE.touchdown,
};

type Moment = { key: string; time: number };

/** The short cut flies no rocks (the space scene skips them), so it has no near miss either. */
const NOT_IN_SHORT = new Set(["approach.asteroids", "approach.nearMiss", "approach.repaired"]);

/** Every moment on this cut, as an absolute time, in firing order. */
function momentsOf(timeline: Timeline, mode: Mode): Moment[] {
  const out: Moment[] = [];
  let start = 0;
  for (const [phase, seconds] of timeline) {
    const marks = MOMENTS[phase as Exclude<IntroPhase, "done">] as Record<string, number | readonly number[]>;
    for (const [name, at] of Object.entries(marks)) {
      if (typeof at === "number") out.push({ key: `${phase}.${name}`, time: start + at * seconds });
      else at.forEach((a, i) => out.push({ key: `${phase}.${name}.${i}`, time: start + a * seconds }));
    }
    start += seconds;
  }
  return out
    .filter((m) => mode !== "short" || !NOT_IN_SHORT.has(m.key))
    .sort((a, b) => a.time - b.time);
}

/** Engine level: up from the throttle through ignition, full in warp, fading across approach. */
function throttleAt(phase: IntroPhase, p: number): number {
  const on = MOMENTS.ignition.throttle;
  if (phase === "ignition") return p < on ? 0 : ((p - on) / (1 - on)) * 0.6;
  if (phase === "warp") return 0.6 + 0.4 * p;
  if (phase === "approach") return 1 - p;
  return 0;
}

function pickMode(): Mode {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return "reduced";
  try {
    if (window.sessionStorage.getItem(SEEN_KEY) === "1") return "short";
  } catch {}
  return "full";
}

function storedSound(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) === "on";
  } catch {
    return false;
  }
}

export default function MoonIntro({ onComplete }: { onComplete: () => void }) {
  const [mode] = useState(pickMode);
  const timeline = TIMELINES[mode];
  const [moments] = useState(() => momentsOf(timeline, mode));
  const [phase, setPhase] = useState<IntroPhase>(() => phaseAt(timeline, 0).phase);
  const [passed, setPassed] = useState<ReadonlySet<string>>(() => new Set());
  const [soundOn, setSoundOn] = useState(storedSound);

  const reducedLive = useReducedMotion();
  const still = mode === "reduced" || reducedLive;

  const rootRef = useRef<HTMLDivElement>(null);
  const shakeRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const soundRef = useRef<Soundboard | null>(null);
  const live = useRef({ onComplete, soundOn, still });
  live.current = { onComplete, soundOn, still };
  const clock = useRef({
    t: 0,
    last: null as number | null,
    next: 0,
    phase: phase as IntroPhase,
    kick: 0,
    kickAt: 0,
    throttle: -1,
    done: false,
  });

  /** Mark every moment up to `t` passed; fire sounds and kicks unless `silent`. */
  const advance = useCallback(
    (t: number, silent: boolean) => {
      const c = clock.current;
      const start = c.next;
      while (c.next < moments.length && moments[c.next]!.time <= t) {
        const { key } = moments[c.next++]!;
        if (silent || mode === "reduced") continue;
        const sound = SOUNDS[key];
        if (sound) soundRef.current?.play(sound);
        const kick = KICKS[key];
        if (kick) {
          c.kick = kick;
          c.kickAt = t;
        }
      }
      if (c.next > start) setPassed(new Set(moments.slice(0, c.next).map((m) => m.key)));
    },
    [moments, mode],
  );

  const skip = useCallback(() => {
    const c = clock.current;
    const { phase: now } = phaseAt(timeline, c.t);
    if (now === "reveal" || now === "done") return;
    const reveal = phaseStart(timeline, "reveal") ?? 0;
    const length = timeline.find(([name]) => name === "reveal")?.[1] ?? 0;
    c.t = reveal + MOMENTS.reveal.dolly * length;
    c.kick = 0;
    advance(c.t, true);
  }, [timeline, advance]);

  // The clock, the canvas and the soundboard: one lifetime.
  useEffect(() => {
    const root = rootRef.current!;
    const wrap = shakeRef.current!;
    const c = clock.current;
    c.last = null;

    try {
      window.sessionStorage.setItem(SEEN_KEY, "1");
    } catch {}

    const mobile = window.matchMedia?.("(max-width: 767px)").matches ?? false;
    const scene = createSpaceScene(canvasRef.current!, { mobile });
    const sound = createSoundboard();
    soundRef.current = sound;
    const applyMute = () => sound.setMuted(!live.current.soundOn || document.hidden);
    applyMute();

    // Stored "on" still needs a gesture before the browser allows audio.
    const gesture = () => {
      if (live.current.soundOn) sound.unlock();
    };
    const onKey = (e: KeyboardEvent) => {
      gesture();
      const onButton = (e.target as Element | null)?.closest?.("button");
      if (e.key === "Escape" || (!onButton && (e.key === " " || e.key === "Enter"))) {
        if (e.key !== "Escape") e.preventDefault();
        skip();
      }
    };
    const onResize = () => scene.resize();
    window.addEventListener("pointerdown", gesture);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", applyMute);

    root.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });

    let raf = 0;
    const tick = (now: number) => {
      const dt = c.last === null ? 0 : Math.min(0.1, Math.max(0, (now - c.last) / 1000));
      c.last = now;
      c.t += dt;
      advance(c.t, false);
      const at = phaseAt(timeline, c.t);
      if (at.phase !== c.phase) {
        c.phase = at.phase;
        setPhase(at.phase);
      }
      root.style.setProperty("--mi-t", c.t.toFixed(3));
      root.style.setProperty("--mi-p", at.p.toFixed(3));
      root.dataset.phase = at.phase;

      // Shake: the phase's hum plus a decaying kick, from cheap sine noise.
      let amp = 0;
      if (!live.current.still && at.phase !== "reveal" && at.phase !== "done") {
        amp = SHAKE.base[at.phase] + c.kick * Math.exp(-(c.t - c.kickAt) * 7);
      }
      const x = amp * 0.5 * (Math.sin(c.t * 53.1) + Math.sin(c.t * 31.7 + 1.3));
      const y = amp * 0.5 * (Math.sin(c.t * 47.9 + 2.1) + Math.sin(c.t * 29.3 + 0.4));
      wrap.style.transform = amp ? `translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,0)` : "";

      if (mode !== "reduced") {
        const level = Math.round(throttleAt(at.phase, at.p) * 20) / 20;
        if (level !== c.throttle) {
          c.throttle = level;
          sound.setThrottle(level);
        }
      }

      scene.update({ t: c.t, dt, phase: at.phase, p: at.p, mode });
      if (at.phase === "done") {
        if (!c.done) {
          c.done = true;
          live.current.onComplete();
        }
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    if (!c.done) raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointerdown", gesture);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", applyMute);
      scene.destroy();
      sound.destroy();
      soundRef.current = null;
      c.throttle = -1;
    };
  }, [timeline, mode, advance, skip]);

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    live.current.soundOn = next;
    try {
      window.localStorage.setItem(SOUND_KEY, next ? "on" : "off");
    } catch {}
    const sound = soundRef.current;
    if (next) sound?.unlock();
    sound?.setMuted(!next || document.hidden);
  };

  const onRootClick = (e: MouseEvent) => {
    if ((e.target as Element).closest("button")) return;
    skip();
  };

  return (
    // Clicking anywhere skips; the keyboard equivalents (Esc/Space/Enter) are on window.
    <div
      ref={rootRef}
      className="mi-root"
      aria-label="Landing sequence"
      role="region"
      data-mode={mode}
      onClick={onRootClick}
    >
      <div ref={shakeRef} className="mi-shake">
        <canvas ref={canvasRef} className="mi-canvas" aria-hidden="true" />
        <Cockpit
          phase={phase}
          mode={mode}
          passed={passed}
          soundOn={soundOn}
          onToggleSound={toggleSound}
          onSkip={skip}
        />
      </div>
    </div>
  );
}
