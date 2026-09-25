"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
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
 * Sound is synthesised here (Web Audio), so there is no file to ship: a pop
 * whenever an animal talks, a whoosh as the hamster flies past, a whoosh and a
 * cheer on submit, and a low note on an error. No background hum or twinkles
 * (removed at Karthik's request). Browsers refuse sound before the first click or key
 * press anyway. The speaker button mutes it all, and the choice is
 * remembered in this browser.
 */

type Mate = { id: string; src: string; lines: readonly string[]; pitch: number };

const MATES: readonly Mate[] = [
  { id: "lion", src: "/crew/lion.webp", pitch: 330, lines: ["Welcome back, captain!", "Roar-some to see you.", "Ready for launch?"] },
  { id: "panda", src: "/crew/panda.webp", pitch: 523, lines: ["Five minutes, then we sell!", "No rugs today, please.", "I brought snacks."] },
  { id: "penguin", src: "/crew/penguin.webp", pitch: 659, lines: ["It's cold out here. Sign in!", "Waddle, waddle… waiting.", "Nice to see you!"] },
  { id: "koala", src: "/crew/koala.webp", pitch: 392, lines: ["Take your time…", "Password ready?", "I'll just float here."] },
  { id: "tiger", src: "/crew/tiger.webp", pitch: 294, lines: ["Karthik's Lab is this way!", "Quiet pools only, remember.", "Grr… good to see you."] },
];

const EVERY_MS = 4800;
const SHOW_MS = 3400;

/* ── sound ─────────────────────────────────────────────────────────────── */

export type Sfx = {
  start(): void;
  blip(pitch: number): void;
  whoosh(): void;
  cheer(): void;
  oops(): void;
  setMuted(muted: boolean): void;
  close(): void;
};

export function createSfx(): Sfx | null {
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
      // No background sound at all: Karthik found the low hum felt like a
      // vibration and then asked for the twinkles to go too (2026-09-25).
      // What is left plays only when something happens on screen.
      if (started) return;
      started = true;
      void ctx.resume();
    },
    blip(pitch) {
      const t = ctx.currentTime;
      tone(pitch, t, 0.16, 0.18, "triangle", pitch * 1.5);
      tone(pitch * 2, t + 0.07, 0.12, 0.08, "sine");
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
      gain.gain.exponentialRampToValueAtTime(0.14, t + 0.35);
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
      void ctx.close();
    },
  };
}

/* ── the voice: bubbles and sound, shared by both crews ─────────────────── */

type Bubble = { mate: string; text: string; key: number };

function useCrewVoice(mates: readonly Mate[]) {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const sfx = useRef<Sfx | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Every line pops, timed ones included — Karthik asked for the characters'
  // sounds back (2026-09-25). The background hum and twinkles stay gone. There
  // is no mute button: a mute remembered from earlier kept him from hearing
  // them, so he asked for the button to go.
  const say = useCallback((mateId: string, text: string, holdMs = SHOW_MS, pop = true) => {
    const mate = mates.find((m) => m.id === mateId) ?? mates[0]!;
    setBubble({ mate: mate.id, text, key: Date.now() });
    if (pop) sfx.current?.blip(mate.pitch);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setBubble(null), holdMs);
  }, [mates]);

  // Sound can only start from a click or a key press.
  useEffect(() => {
    const wake = () => {
      if (!sfx.current) sfx.current = createSfx();
      sfx.current?.start();
      sfx.current?.setMuted(false);
    };
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    const hidden = () => sfx.current?.setMuted(document.hidden);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
      document.removeEventListener("visibilitychange", hidden);
      clearTimeout(hideTimer.current);
      sfx.current?.close();
      sfx.current = null;
    };
  }, []);

  return { bubble, say, sfx };
}

/** The animals a screen actually shows: phones hide some of each crew. */
function visibleMates(mates: readonly Mate[], prefix: string): readonly Mate[] {
  const shown = mates.filter((m) => {
    const el = document.querySelector<HTMLElement>(`.${prefix}__mate--${m.id}`);
    return el ? getComputedStyle(el).display !== "none" : false;
  });
  return shown.length ? shown : mates;
}

function Mates({ mates, bubble, prefix, onTap }: {
  mates: readonly Mate[];
  bubble: Bubble | null;
  prefix: string;
  onTap?: (mate: Mate) => void;
}) {
  return (
    <>
      {mates.map((mate) => (
        <div key={mate.id} className={cn(`${prefix}__mate`, `${prefix}__mate--${mate.id}`)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={mate.src}
            alt=""
            draggable={false}
            className="login-crew__img"
            onClick={onTap ? () => onTap(mate) : undefined}
          />
          {bubble?.mate === mate.id ? (
            <span key={bubble.key} className="login-crew__bubble">
              {bubble.text}
            </span>
          ) : null}
        </div>
      ))}
    </>
  );
}

/* ── the airlock crew: the sign-in pages ───────────────────────────────── */

export function LoginCrew() {
  const { bubble, say, sfx } = useCrewVoice(MATES);
  const [mood, setMood] = useState<"shy" | "cheer" | "sad" | null>(null);
  const lastTyping = useRef(0);
  const turn = useRef(0);

  // Only animals on screen talk: a phone shows two of the five.
  const onScreen = useCallback(() => visibleMates(MATES, "login-crew"), []);
  const pick = useCallback(() => {
    const shown = onScreen();
    return shown[Math.floor(Math.random() * shown.length)]!;
  }, [onScreen]);

  // Idle chatter: a first line that asks for a tap, then someone every few
  // seconds, never the same animal twice running.
  useEffect(() => {
    const first = setTimeout(() => say(onScreen()[0]!.id, "Hi! Welcome back."), 900);
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
      sfx.current?.whoosh();
      sfx.current?.cheer();
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
      sfx.current?.oops();
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
  }, [pick, say, sfx]);

  // The fly-by's whoosh, in time with its pass across the top (see CSS).
  useEffect(() => {
    const pass = setInterval(() => {
      if (!document.hidden) sfx.current?.whoosh();
    }, 19_000);
    return () => clearInterval(pass);
  }, [sfx]);

  return (
    <>
      <div className="login-crew" aria-hidden data-mood={mood ?? undefined}>
        <Mates mates={MATES} bubble={bubble} prefix="login-crew" />
        <div className="login-crew__flyby">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/crew/hamster.webp" alt="" draggable={false} className="login-crew__img" />
        </div>
      </div>
    </>
  );
}

/* ── the dock crew: every page after sign-in ───────────────────────────── */

/**
 * The animals on every page after sign-in (2026-09-25). On a phone: three in
 * the bottom-right corner. On a wide screen they live in the sidebar: the
 * tiger and penguin beside MEMESCOPE at the top (`RailHeaderCrew`), and the
 * panda in the gap between HQ and Settings, reading the Solana news strip
 * under it (`DockCrew placement="rail"`). Their own lines follow the page and
 * claim nothing about it; the panda's news lines are other people's
 * headlines, labelled as such under it. One hide button tucks them all away.
 */
const DOCK: readonly Mate[] = [
  { id: "panda", src: "/crew/panda.webp", pitch: 523, lines: ["No rugs today, please.", "Snack break?", "I'm rooting for you!"] },
  { id: "penguin", src: "/crew/penguin.webp", pitch: 659, lines: ["Waddle, waddle… watching.", "Nice to see you!", "Stay cool out there."] },
  { id: "tiger", src: "/crew/tiger.webp", pitch: 294, lines: ["Grr… good to see you.", "Five minutes, then we sell!", "Tap me, I'm bored."] },
];
const PANDA = DOCK.filter((m) => m.id === "panda");
const TOP_PAIR = DOCK.filter((m) => m.id !== "panda");

/** Page-aware lines, by longest matching path. Nothing here states a figure. */
const PAGE_LINES: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["/karthik-lab", ["Welcome to your lab, captain!", "The checks live on the right →", "Quiet pools, five-minute holds.", "Judged on the 23rd — hang in there!"]],
  ["/real-wallet", ["Real money here — careful!", "Only you can press Start.", "I'm watching the wallet with you."]],
  ["/graduation-lab", ["Every arm vs its control!", "So many graduations…", "Deep pools, short holds."]],
  ["/hq", ["Say hi to the office!", "Everyone's at their desk.", "Want to see them dance? 🎵"]],
  ["/rafiqv2-lab", ["Six books, one engine.", "Rafiqv2 reporting in!"]],
  ["/breakouts", ["Namaste, NSE!", "Charts, charts, charts."]],
];
const DOCK_EVERY_MS = 9000;
const NEWS_EVERY_MS = 12_000;
const DOCK_KEY = "memescope.crewDock";
const DOCK_EVENT = "memescope-crew-dock";

function pageLines(pathname: string): readonly string[] {
  const hit = PAGE_LINES.filter(([p]) => pathname === p || pathname.startsWith(`${p}/`))
    .sort((a, b) => b[0].length - a[0].length)[0];
  return hit?.[1] ?? [];
}

/** One hide switch for every dock animal, remembered, and shared between the
 *  rail's two groups so hiding one hides both. */
function useDockHidden(): [boolean, (next: boolean) => void] {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const read = () => {
      try {
        setHidden(window.localStorage.getItem(DOCK_KEY) === "hidden");
      } catch {
        // Shown by default.
      }
    };
    read();
    window.addEventListener(DOCK_EVENT, read);
    return () => window.removeEventListener(DOCK_EVENT, read);
  }, []);
  const set = useCallback((next: boolean) => {
    setHidden(next);
    try {
      window.localStorage.setItem(DOCK_KEY, next ? "hidden" : "shown");
    } catch {
      // Kept for this visit only.
    }
    window.dispatchEvent(new Event(DOCK_EVENT));
  }, []);
  return [hidden, set];
}

/** The phone-corner crew is hidden on a wide screen (the rail has its own), so
 *  it must stay quiet there too, or an invisible crew pops over the rail's. */
function floatingShown(): boolean {
  const el = document.querySelector<HTMLElement>(".dock-crew--floating");
  return !!el && getComputedStyle(el).display !== "none";
}

export interface Headline {
  title: string;
  source: string;
  url: string;
  published_at: string | null;
}

/** Solana headlines from the API's news broadcast; refreshed every 3 minutes. */
function useSolanaNews(enabled: boolean): Headline[] {
  const news = useQuery({
    queryKey: ["news", "solana"],
    queryFn: () => api.get<{ items: Headline[] }>("/news/solana", { skipAuthRetry: true }),
    enabled,
    refetchInterval: 180_000,
    staleTime: 120_000,
    retry: false,
  });
  return news.data?.items ?? [];
}

function ago(iso: string | null, now: number): string {
  if (!iso) return "";
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function shortTitle(title: string, max = 64): string {
  return title.length <= max ? title : `${title.slice(0, max - 1).trimEnd()}…`;
}

/** The live strip under the panda: one headline at a time, rotating, linked. */
function NewsStrip({ items, index }: { items: Headline[]; index: number }) {
  const item = items.length ? items[index % items.length]! : null;
  return (
    <div className="dock-news" aria-live="off">
      <p className="dock-news__label">
        <span className="dock-news__dot" aria-hidden /> Solana news · live
      </p>
      {item ? (
        <>
          <a href={item.url} target="_blank" rel="noreferrer" className="dock-news__title">
            {item.title}
          </a>
          <p className="dock-news__meta">
            {item.source}
            {item.published_at ? ` · ${ago(item.published_at, Date.now())}` : ""}
          </p>
        </>
      ) : (
        <p className="dock-news__meta">Tuning in…</p>
      )}
    </div>
  );
}

export function DockCrew({
  pathname,
  placement = "floating",
}: {
  pathname: string;
  /** "rail": the panda and the news in the desktop sidebar. "floating": the
   *  phone corner, all three animals. */
  placement?: "floating" | "rail";
}) {
  const rail = placement === "rail";
  const mates = rail ? PANDA : DOCK;
  const { bubble, say, sfx } = useCrewVoice(mates);
  const [hidden, setDock] = useDockHidden();
  const [hop, setHop] = useState<string | null>(null);
  const [newsIndex, setNewsIndex] = useState(0);
  const newsRef = useRef(0);
  const news = useSolanaNews(rail && !hidden);
  const turn = useRef(0);
  const path = useRef(pathname);
  path.current = pathname;

  const line = useCallback((mate: Mate) => {
    const pool = [...pageLines(path.current), ...mate.lines];
    return pool[Math.floor(Math.random() * pool.length)]!;
  }, []);

  // On a phone, a page-aware hello on every page change, then chatter. In the
  // rail the top pair says hello (`RailHeaderCrew`) and the panda reads news.
  useEffect(() => {
    if (hidden || rail) return;
    const lines = pageLines(pathname);
    const hello = setTimeout(() => {
      if (floatingShown()) say("penguin", lines[0] ?? "Hi again!");
    }, 1200);
    return () => clearTimeout(hello);
  }, [hidden, rail, pathname, say]);

  useEffect(() => {
    if (hidden || rail) return;
    const every = setInterval(() => {
      if (document.hidden || !floatingShown()) return;
      const shown = visibleMates(DOCK, "dock-crew");
      turn.current = (turn.current + 1 + Math.floor(Math.random() * Math.max(1, shown.length - 1))) % shown.length;
      const mate = shown[turn.current]!;
      say(mate.id, line(mate));
    }, DOCK_EVERY_MS);
    return () => clearInterval(every);
  }, [hidden, rail, line, say]);

  // The panda reads the news: the next headline every few seconds, short.
  useEffect(() => {
    if (hidden || !rail || news.length === 0) return;
    const read = (i: number) => say("panda", `📰 ${shortTitle(news[i % news.length]!.title)}`, 6000);
    const first = setTimeout(() => read(newsRef.current), 1500);
    const every = setInterval(() => {
      if (document.hidden) return;
      newsRef.current += 1;
      setNewsIndex(newsRef.current);
      read(newsRef.current);
    }, NEWS_EVERY_MS);
    return () => {
      clearTimeout(first);
      clearInterval(every);
    };
  }, [hidden, rail, news, say]);

  if (hidden) {
    return (
      <button type="button" className={cn("dock-crew__paw", `dock-crew__paw--${placement}`)} aria-label="Bring the crew back" onClick={() => setDock(false)}>
        🐾
      </button>
    );
  }

  return (
    <div className={cn(rail && "dock-rail")}>
      <div className={cn("dock-crew", `dock-crew--${placement}`)} data-hop={hop ?? undefined}>
        <div className="dock-crew__row" aria-hidden>
          <Mates
            mates={mates}
            bubble={bubble}
            prefix="dock-crew"
            onTap={(mate) => {
              setHop(mate.id);
              setTimeout(() => setHop(null), 700);
              sfx.current?.whoosh();
              const headline = rail && news.length ? news[newsIndex % news.length] : null;
              say(mate.id, headline ? `📰 ${shortTitle(headline.title)}` : line(mate), headline ? 6000 : SHOW_MS);
            }}
          />
        </div>
        <div className="dock-crew__controls">
          <button type="button" className="dock-crew__button" aria-label="Hide the crew" onClick={() => setDock(true)}>
            ×
          </button>
        </div>
      </div>
      {rail ? <NewsStrip items={news} index={newsIndex} /> : null}
    </div>
  );
}

/**
 * The tiger and the penguin at the top of the sidebar, beside MEMESCOPE. They
 * say hello on each page and chat now and then; tap one and it talks. Hidden
 * with the rest of the crew.
 */
export function RailHeaderCrew({ pathname }: { pathname: string }) {
  const { bubble, say, sfx } = useCrewVoice(TOP_PAIR);
  const [hidden] = useDockHidden();
  const [hop, setHop] = useState<string | null>(null);
  const turn = useRef(0);
  const path = useRef(pathname);
  path.current = pathname;

  const line = useCallback((mate: Mate) => {
    const pool = [...pageLines(path.current), ...mate.lines];
    return pool[Math.floor(Math.random() * pool.length)]!;
  }, []);

  useEffect(() => {
    if (hidden) return;
    const lines = pageLines(pathname);
    const hello = setTimeout(() => say("penguin", lines[0] ?? "Hi again!"), 1200);
    return () => clearTimeout(hello);
  }, [hidden, pathname, say]);

  useEffect(() => {
    if (hidden) return;
    const every = setInterval(() => {
      if (document.hidden) return;
      turn.current = (turn.current + 1) % TOP_PAIR.length;
      const mate = TOP_PAIR[turn.current]!;
      say(mate.id, line(mate));
    }, DOCK_EVERY_MS + 2000);
    return () => clearInterval(every);
  }, [hidden, line, say]);

  if (hidden) return null;
  return (
    <div className="rail-top-crew" data-hop={hop ?? undefined} aria-hidden>
      <Mates
        mates={TOP_PAIR}
        bubble={bubble}
        prefix="rail-top-crew"
        onTap={(mate) => {
          setHop(mate.id);
          setTimeout(() => setHop(null), 700);
          sfx.current?.whoosh();
          say(mate.id, line(mate));
        }}
      />
    </div>
  );
}
