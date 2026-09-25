"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * THE CREW AT THE AIRLOCK — the homepage's animal astronauts on the sign-in
 * pages (2026-09-25, at the owner's request): floating in the background,
 * talking to whoever is signing in, with sound.
 *
 * They talk on a timer and when the form is used — a greeting, eyes covered
 * while the password is typed, a cheer on submit, sympathy on an error. Like
 * HQ's chatter, the lines claim NOTHING about the platform: a timer that said
 * "the wallet is up" would be making it up.
 *
 * Sound is synthesised here (Web Audio), so there is no file to ship: a soft
 * space hum with twinkles under it, a pop for each bubble, a whoosh for the
 * fly-by and an arpeggio for the cheer. Browsers refuse sound before the
 * first click or key press, so the first bubble asks for one. The speaker
 * button mutes it all, and the choice is remembered in this browser.
 */

type Mate = { id: string; src: string; lines: readonly string[]; pitch: number };

const MATES: readonly Mate[] = [
  { id: "lion", src: "/crew/lion.webp", pitch: 330, lines: ["Welcome back, captain!", "Roar-some to see you.", "Ready for launch?"] },
  { id: "panda", src: "/crew/panda.webp", pitch: 523, lines: ["Five minutes, then we sell!", "No rugs today, please.", "I brought snacks."] },
  { id: "penguin", src: "/crew/penguin.webp", pitch: 659, lines: ["It's cold out here. Sign in!", "Waddle, waddle… waiting.", "Nice to see you!"] },
  { id: "koala", src: "/crew/koala.webp", pitch: 392, lines: ["Take your time…", "Password ready?", "I'll just float here."] },
  { id: "tiger", src: "/crew/tiger.webp", pitch: 294, lines: ["Karthik's Lab is this way!", "Quiet pools only, remember.", "Grr… good to see you."] },
];

const SOUND_KEY = "memescope.loginCrewSound";
const EVERY_MS = 4800;
const SHOW_MS = 3400;

/* ── sound ─────────────────────────────────────────────────────────────── */

type Sfx = {
  start(): void;
  blip(pitch: number): void;
  whoosh(): void;
  cheer(): void;
  oops(): void;
  setMuted(muted: boolean): void;
  close(): void;
};

function createSfx(): Sfx | null {
  const Ctx =
    typeof window === "undefined"
      ? undefined
      : window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return null;
  const ctx = new Ctx();
  const master = ctx.createGain();
  master.gain.value = 0.9;
  master.connect(ctx.destination);
  let twinkle: ReturnType<typeof setInterval> | undefined;
  let started = false;

  function tone(freq: number, at: number, dur: number, vol: number, type: OscillatorType = "sine", glide?: number) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, at);
    if (glide) osc.frequency.exponentialRampToValueAtTime(glide, at + dur * 0.6);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(vol, at + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    osc.connect(gain).connect(master);
    osc.start(at);
    osc.stop(at + dur + 0.05);
  }

  return {
    start() {
      if (started) return;
      started = true;
      void ctx.resume();
      // The hum: two low, slightly detuned tones behind a filter, breathing
      // slowly. Quiet on purpose — it is a room, not a song.
      const pad = ctx.createGain();
      pad.gain.value = 0.035;
      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 420;
      pad.connect(filter).connect(master);
      for (const [freq, detune] of [[55, -6], [82.5, 5], [110, 3]] as const) {
        const osc = ctx.createOscillator();
        osc.type = "triangle";
        osc.frequency.value = freq;
        osc.detune.value = detune;
        osc.connect(pad);
        osc.start();
      }
      const lfo = ctx.createOscillator();
      const depth = ctx.createGain();
      lfo.frequency.value = 0.08;
      depth.gain.value = 0.02;
      lfo.connect(depth).connect(pad.gain);
      lfo.start();
      // Twinkles: a high, soft note now and then, like distant stars.
      const stars = [1568, 1760, 2093, 2349, 2637];
      twinkle = setInterval(() => {
        if (Math.random() < 0.55) {
          tone(stars[Math.floor(Math.random() * stars.length)]!, ctx.currentTime, 1.4, 0.018);
        }
      }, 1700);
    },
    blip(pitch) {
      const t = ctx.currentTime;
      tone(pitch, t, 0.16, 0.09, "triangle", pitch * 1.5);
      tone(pitch * 2, t + 0.07, 0.12, 0.04, "sine");
    },
    whoosh() {
      const t = ctx.currentTime;
      const buffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
      const noise = ctx.createBufferSource();
      noise.buffer = buffer;
      const band = ctx.createBiquadFilter();
      band.type = "bandpass";
      band.Q.value = 1.4;
      band.frequency.setValueAtTime(300, t);
      band.frequency.exponentialRampToValueAtTime(2400, t + 0.5);
      band.frequency.exponentialRampToValueAtTime(500, t + 0.95);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.07, t + 0.35);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 1);
      noise.connect(band).connect(gain).connect(master);
      noise.start(t);
      noise.stop(t + 1.05);
    },
    cheer() {
      const t = ctx.currentTime;
      [523, 659, 784, 1047].forEach((f, i) => tone(f, t + i * 0.09, 0.3, 0.08, "triangle"));
    },
    oops() {
      const t = ctx.currentTime;
      tone(392, t, 0.22, 0.07, "triangle", 262);
      tone(262, t + 0.2, 0.3, 0.06, "triangle", 196);
    },
    setMuted(muted) {
      master.gain.setTargetAtTime(muted ? 0 : 0.9, ctx.currentTime, 0.05);
    },
    close() {
      if (twinkle) clearInterval(twinkle);
      void ctx.close();
    },
  };
}

function readSound(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) !== "off";
  } catch {
    return true;
  }
}

/* ── the crew ──────────────────────────────────────────────────────────── */

type Bubble = { mate: string; text: string; key: number };

export function LoginCrew() {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const [mood, setMood] = useState<"shy" | "cheer" | "sad" | null>(null);
  const [soundOn, setSoundOn] = useState(true);
  const sfx = useRef<Sfx | null>(null);
  const soundRef = useRef(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastTyping = useRef(0);
  const turn = useRef(0);

  const say = useCallback((mateId: string, text: string, holdMs = SHOW_MS) => {
    const mate = MATES.find((m) => m.id === mateId) ?? MATES[0]!;
    setBubble({ mate: mate.id, text, key: Date.now() });
    if (soundRef.current) sfx.current?.blip(mate.pitch);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setBubble(null), holdMs);
  }, []);

  // Only animals on screen talk: a phone shows two of the five.
  const onScreen = useCallback(() => {
    const shown = MATES.filter((m) => {
      const el = document.querySelector<HTMLElement>(`.login-crew__mate--${m.id}`);
      return el ? getComputedStyle(el).display !== "none" : false;
    });
    return shown.length ? shown : MATES;
  }, []);
  const pick = useCallback(() => {
    const shown = onScreen();
    return shown[Math.floor(Math.random() * shown.length)]!;
  }, [onScreen]);

  // Remembered sound choice, read after mount so the server render matches.
  useEffect(() => {
    const on = readSound();
    setSoundOn(on);
    soundRef.current = on;
  }, []);

  // Sound can only start from a click or a key press.
  useEffect(() => {
    const wake = () => {
      if (!sfx.current) sfx.current = createSfx();
      sfx.current?.start();
      sfx.current?.setMuted(!soundRef.current);
    };
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    const hidden = () => sfx.current?.setMuted(document.hidden || !soundRef.current);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
      document.removeEventListener("visibilitychange", hidden);
      sfx.current?.close();
      sfx.current = null;
    };
  }, []);

  // Idle chatter: a first line that asks for a tap, then someone every few
  // seconds, never the same animal twice running.
  useEffect(() => {
    const first = setTimeout(() => say(onScreen()[0]!.id, "Hi! Tap anywhere to hear us."), 900);
    const every = setInterval(() => {
      if (document.hidden) return;
      const shown = onScreen();
      turn.current = (turn.current + 1 + Math.floor(Math.random() * Math.max(1, shown.length - 1))) % shown.length;
      const mate = shown[turn.current]!;
      say(mate.id, mate.lines[Math.floor(Math.random() * mate.lines.length)]!);
    }, EVERY_MS);
    return () => {
      clearTimeout(first);
      clearInterval(every);
      clearTimeout(hideTimer.current);
    };
  }, [onScreen, say]);

  // Reactions to the form: read from the document, so the pages need no
  // wiring and the crew cannot change how a form behaves.
  useEffect(() => {
    const onFocus = (event: FocusEvent) => {
      const el = event.target as HTMLInputElement | null;
      if (el?.type === "password") {
        setMood("shy");
        say(pick().id, "I'm not looking! 🙈");
      }
    };
    const onBlur = (event: FocusEvent) => {
      if ((event.target as HTMLInputElement | null)?.type === "password") setMood(null);
    };
    const onInput = (event: Event) => {
      const el = event.target as HTMLInputElement | null;
      if (!el || el.type === "password") return;
      const now = Date.now();
      if (now - lastTyping.current < 4000) return;
      lastTyping.current = now;
      say(pick().id, Math.random() < 0.5 ? "Ooh, typing…" : "Keep going!");
    };
    const onSubmit = () => {
      setMood("cheer");
      say("penguin", "Launching! 🚀", 2600);
      if (soundRef.current) {
        sfx.current?.whoosh();
        sfx.current?.cheer();
      }
      setTimeout(() => setMood(null), 1800);
    };
    // An error banner (`role="alert"`) appearing is the one signal every
    // auth page shares.
    const alerts = new MutationObserver((records) => {
      const added = records.some((r) =>
        [...r.addedNodes].some((n) => n instanceof HTMLElement && n.getAttribute("role") === "alert"),
      );
      if (!added) return;
      setMood("sad");
      say("koala", "Hmm… try that again?");
      if (soundRef.current) sfx.current?.oops();
      setTimeout(() => setMood(null), 2200);
    });
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onBlur);
    document.addEventListener("input", onInput);
    document.addEventListener("submit", onSubmit);
    alerts.observe(document.body, { childList: true, subtree: true });
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onBlur);
      document.removeEventListener("input", onInput);
      document.removeEventListener("submit", onSubmit);
      alerts.disconnect();
    };
  }, [pick, say]);

  // The fly-by's whoosh, in time with its pass across the top (see CSS).
  useEffect(() => {
    const pass = setInterval(() => {
      if (soundRef.current && !document.hidden) sfx.current?.whoosh();
    }, 19_000);
    return () => clearInterval(pass);
  }, []);

  function toggleSound() {
    const next = !soundOn;
    setSoundOn(next);
    soundRef.current = next;
    if (!sfx.current) sfx.current = createSfx();
    sfx.current?.start();
    sfx.current?.setMuted(!next);
    try {
      window.localStorage.setItem(SOUND_KEY, next ? "on" : "off");
    } catch {
      // A private window keeps the choice for this visit only.
    }
    if (next) say("penguin", "Sound on!", 1800);
  }

  return (
    <>
      <div className="login-crew" aria-hidden data-mood={mood ?? undefined}>
        {MATES.map((mate) => (
          <div key={mate.id} className={cn("login-crew__mate", `login-crew__mate--${mate.id}`)}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={mate.src} alt="" draggable={false} className="login-crew__img" />
            {bubble?.mate === mate.id ? (
              <span key={bubble.key} className="login-crew__bubble">
                {bubble.text}
              </span>
            ) : null}
          </div>
        ))}
        <div className="login-crew__flyby">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/crew/hamster.webp" alt="" draggable={false} className="login-crew__img" />
        </div>
      </div>
      <button
        type="button"
        onClick={toggleSound}
        aria-pressed={soundOn}
        aria-label={soundOn ? "Mute the crew" : "Turn the crew's sound on"}
        className="login-crew__sound"
      >
        {soundOn ? "🔊" : "🔈"}
      </button>
    </>
  );
}
