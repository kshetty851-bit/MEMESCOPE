"use client";

/**
 * The newsroom TV (Karthik, 2026-10-20): an original, illustrated AI anchor in
 * a studio inside a small set, reading a bulletin written from this page. Her
 * mouth follows the voice's loudness; she blinks and sways. Sound only after a
 * tap (browsers block autoplay). Voice: OpenAI TTS via /newsroom/bulletin.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { API_V1, env } from "@/lib/env";

import type { Newsroom } from "./types";

type Segment = { label: string; text: string };
type Bulletin = { on_air: true; mode: "openai"; id: string; made_at: string; audio: string; segments: Segment[] }
  | { on_air: true; mode: "device"; segments: Segment[] }
  | { on_air: false; reason: string };

/** The device's best English voice. Devices ship robotic ones next to good
    ones: the neural "Natural"/"Online" voices (Edge), the downloaded
    "Enhanced"/"Premium" ones (Apple) and Google's own come first. */
function deviceVoice(): SpeechSynthesisVoice | null {
  const all = window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  const female = /aria|jenny|ava|emma|michelle|sonia|libby|natasha|samantha|allison|susan|serena|karen|moira|tessa|zoe|female/i;
  const score = (v: SpeechSynthesisVoice) =>
    (/natural|neural|online/i.test(v.name) ? 8 : 0)
    + (/enhanced|premium/i.test(v.name) ? 6 : 0)
    + (/^google/i.test(v.name) ? 4 : 0)
    + (female.test(v.name) ? 3 : 0)
    + (/en[-_](US|GB)/i.test(v.lang) ? 1 : 0)
    - (/compact|eloquence|novelty|zira|david|fred|albert|bahh|bells|boing|bubbles|cellos|jester|organ|trinoids|whisper|zarvox/i.test(v.name) ? 10 : 0);
  return [...all].sort((a, b) => score(b) - score(a))[0] ?? null;
}
type State = "idle" | "tuning" | "live" | "ended" | "off";

/** A three-note studio sting and a soft pad under the voice, made here: no licensed music. */
function sting(ctx: AudioContext): { stop: () => void } {
  const master = ctx.createGain();
  master.gain.value = 0.18;
  master.connect(ctx.destination);
  const t0 = ctx.currentTime;
  [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "triangle"; o.frequency.value = f;
    g.gain.setValueAtTime(0, t0 + i * 0.16);
    g.gain.linearRampToValueAtTime(0.9, t0 + i * 0.16 + 0.02);
    g.gain.exponentialRampToValueAtTime(0.001, t0 + i * 0.16 + (i === 3 ? 1.4 : 0.5));
    o.connect(g).connect(master); o.start(t0 + i * 0.16); o.stop(t0 + i * 0.16 + 1.5);
  });
  const pad = ctx.createGain();
  pad.gain.setValueAtTime(0, t0 + 1.2);
  pad.gain.linearRampToValueAtTime(0.05, t0 + 3);
  pad.connect(master);
  const voices = [130.81, 196, 246.94].map((f) => {
    const o = ctx.createOscillator(); o.type = "sine"; o.frequency.value = f;
    o.connect(pad); o.start(t0 + 1.2); return o;
  });
  return {
    stop: () => {
      const t = ctx.currentTime;
      pad.gain.cancelScheduledValues(t); pad.gain.setValueAtTime(pad.gain.value, t);
      pad.gain.linearRampToValueAtTime(0, t + 1.5);
      voices.forEach((o) => o.stop(t + 1.6));
    },
  };
}

export function NewsTV({ data }: { data?: Newsroom }) {
  const [state, setState] = useState<State>("idle");
  const [seg, setSeg] = useState(0);
  const [b, setB] = useState<{ segments: Segment[] } | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const bed = useRef<{ stop: () => void } | null>(null);
  const face = useRef<SVGGElement | null>(null);
  const raf = useRef(0);

  // Some browsers load their voice list lazily: ask early so it is ready by the tap.
  useEffect(() => { window.speechSynthesis?.getVoices(); }, []);
  useEffect(() => () => { window.speechSynthesis?.cancel(); cancelAnimationFrame(raf.current); audio.current?.pause(); void ctx.current?.close(); }, []);

  const watch = useCallback(async () => {
    setState("tuning");
    const c = ctx.current ?? new AudioContext();
    ctx.current = c;
    await c.resume();
    let got: Bulletin;
    try {
      got = await (await fetch(`${API_V1}/newsroom/bulletin`, { cache: "no-store" })).json();
    } catch {
      setState("off"); return;
    }
    if (!got.on_air) { setState("off"); return; }
    setB(got);
    if (got.mode === "device") { speak(c, got.segments); return; }
    audio.current?.pause();
    const el = new Audio();          // a media element can feed only one analyser source
    audio.current = el;
    el.crossOrigin = "anonymous";
    el.src = `${env.NEXT_PUBLIC_API_URL}${got.audio}`;
    const an = c.createAnalyser();
    an.fftSize = 512;
    c.createMediaElementSource(el).connect(an).connect(c.destination);
    const buf = new Uint8Array(an.fftSize);
    const lengths = got.segments.map((s) => s.text.length);
    const total = lengths.reduce((a, n) => a + n, 0);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += (v - 128) ** 2;
      const level = Math.min(1, Math.sqrt(sum / buf.length) / 28);
      face.current?.style.setProperty("--open", level.toFixed(3));
      if (el.duration) {
        let at = (el.currentTime / el.duration) * total, i = 0;
        while (i < lengths.length - 1 && at > (lengths[i] ?? 0)) { at -= lengths[i] ?? 0; i += 1; }
        setSeg(i);
      }
      raf.current = requestAnimationFrame(tick);
    };
    bed.current = sting(c);
    el.onended = () => {
      cancelAnimationFrame(raf.current);
      face.current?.style.setProperty("--open", "0");
      bed.current?.stop();
      bed.current = null;
      setState("ended");
    };
    setState("live");
    window.setTimeout(() => { void el.play(); tick(); }, 1300);   // after the sting
  }, []);

  /** Free voice: one utterance per segment, so the lower third is exact; the
      mouth flaps while the device is speaking (no audio stream to measure). */
  const speak = (c: AudioContext, segments: Segment[]) => {
    const synth = window.speechSynthesis;
    const voice = deviceVoice();
    // The mouth follows the synthesiser itself, not its start/boundary events:
    // some phones never send them.
    let heard = false;
    const flap = (t: number) => {
      const on = synth.speaking && !synth.paused;
      heard ||= on;
      if (heard && !synth.speaking && !synth.pending) { done(); return; }   // end events can go missing too
      const open = on ? 0.2 + 0.6 * Math.abs(Math.sin(t / 70)) * (0.6 + 0.4 * Math.sin(t / 230)) : 0;
      face.current?.style.setProperty("--open", open.toFixed(3));
      raf.current = requestAnimationFrame(flap);
    };
    let over = false;
    const done = () => {
      if (over) return;
      over = true;
      cancelAnimationFrame(raf.current);
      face.current?.style.setProperty("--open", "0");
      bed.current?.stop();
      bed.current = null;
      setState("ended");
    };
    segments.forEach((s, i) => {
      const u = new SpeechSynthesisUtterance(s.text);
      if (voice) u.voice = voice;
      u.lang = voice?.lang ?? "en-US";
      u.rate = 0.97;
      u.onstart = () => setSeg(i);
      u.onend = () => { if (i === segments.length - 1) done(); };
      u.onerror = () => { if (i === segments.length - 1) done(); };
      window.setTimeout(() => synth.speak(u), 1300);
    });
    bed.current = sting(c);
    setState("live");
    raf.current = requestAnimationFrame(flap);
  };

  const stop = () => {
    window.speechSynthesis?.cancel();
    audio.current?.pause();
    cancelAnimationFrame(raf.current);
    face.current?.style.setProperty("--open", "0");
    bed.current?.stop();
    bed.current = null;
    setState("ended");
  };

  const coins = data?.market?.coins ?? [];
  const btc = coins.find((c) => c.symbol === "BTC");
  const o = data?.ours;
  const crawl = [
    o ? `${o.graduations_24h.toLocaleString()} pump.fun graduations in 24h` : null,
    o?.rug_rate_24h != null ? `${o.rug_rate_24h}% lost 80%+ in hour one` : null,
    btc?.price != null ? `BTC $${Math.round(btc.price).toLocaleString()}` : null,
    data?.fear_greed ? `Fear & Greed ${data.fear_greed.value}` : null,
  ].filter(Boolean).join("   •   ");
  const label = b && state === "live" ? b.segments[seg]?.label : "MemeScope News";
  const talking = state === "live";

  return (
    <aside className={cn("np-tv", talking && "is-live")} aria-label="MemeScope News TV, AI presenter">
      <span className="np-tv__antenna" aria-hidden />
      <div className="np-tv__set">
        <div className="np-tv__screen">
          <svg viewBox="0 0 320 200" className="np-tv__studio" role="img"
               aria-label={talking ? `AI anchor reading: ${label}` : "AI news anchor in the studio"}>
            <defs>
              <linearGradient id="tv-bg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#0f2a33" /><stop offset="1" stopColor="#0d0d0b" />
              </linearGradient>
              <linearGradient id="tv-desk" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#2a2a24" /><stop offset="1" stopColor="#161613" />
              </linearGradient>
            </defs>
            <rect width="320" height="200" fill="url(#tv-bg)" />
            {/* skyline through the studio window */}
            <g fill="#0b1f26">
              <rect x="0" y="92" width="26" height="70" /><rect x="28" y="70" width="20" height="92" />
              <rect x="50" y="100" width="30" height="62" /><rect x="236" y="78" width="24" height="84" />
              <rect x="262" y="96" width="28" height="66" /><rect x="292" y="62" width="28" height="100" />
            </g>
            <g fill="#c6ff3a" opacity="0.5" className="np-tv__windows">
              <rect x="33" y="80" width="3" height="3" /><rect x="40" y="96" width="3" height="3" />
              <rect x="58" y="110" width="3" height="3" /><rect x="242" y="88" width="3" height="3" />
              <rect x="300" y="74" width="3" height="3" /><rect x="268" y="108" width="3" height="3" />
            </g>
            <rect x="96" y="30" width="128" height="4" rx="2" fill="#49d8ff" opacity="0.35" />
            <text x="18" y="52" className="np-tv__wall">MEMESCOPE</text>
            <text x="18" y="64" className="np-tv__wall np-tv__wall--sub">NEWS · LIVE</text>
            {/* the anchor: an original character, framed shoulders-up */}
            <g className="np-tv__anchor"><g transform="translate(160 200) scale(1.32) translate(-160 -196)">
              {/* hair, back layer down to the shoulders */}
              <path d="M128 86 C124 52 196 48 192 88 C196 112 198 132 192 146 C184 150 176 146 172 138 L148 138 C144 146 136 150 128 146 C122 132 124 110 128 86 Z" fill="#24150f" />
              {/* blazer, blouse, lapels */}
              <path d="M102 200 C104 156 126 140 160 138 C194 140 216 156 218 200 Z" fill="#1d4f5c" />
              <path d="M147 139 L160 168 L173 139 Z" fill="#efe8d8" />
              <path d="M140 141 L160 176 L148 200 L132 200 Z M180 141 L160 176 L172 200 L188 200 Z" fill="#163e48" />
              <rect x="152" y="116" width="16" height="26" rx="6" fill="#c79c79" />
              <path d="M152 128 q8 6 16 0 v6 q-8 5 -16 0 z" fill="#b38665" />
              <g ref={face} className="np-tv__face">
                <path d="M136 88 C136 66 184 66 184 88 C184 106 174 120 160 121 C146 120 136 106 136 88 Z" fill="#dcb391" />
                <ellipse cx="146" cy="101" rx="5" ry="3" fill="#e5937e" opacity="0.35" />
                <ellipse cx="174" cy="101" rx="5" ry="3" fill="#e5937e" opacity="0.35" />
                {/* fringe swept to one side */}
                <path d="M132 90 C130 58 170 50 188 70 C192 78 190 88 186 92 C180 78 168 72 150 76 C142 78 136 84 132 90 Z" fill="#2e1b13" />
                <path d="M150 76 C160 70 176 72 186 84" stroke="#4a2e22" strokeWidth="1.4" fill="none" opacity="0.7" />
                <path d="M143 84 q5 -3 10 -0.5 M167 83.5 q5 -2.5 10 0.5" stroke="#2e1b13" strokeWidth="1.8" fill="none" strokeLinecap="round" />
                <g className="np-tv__eyes">
                  <path d="M143 91 q5 -4.5 10 0 q-5 3.6 -10 0 z" fill="#fbf7ef" />
                  <path d="M167 91 q5 -4.5 10 0 q-5 3.6 -10 0 z" fill="#fbf7ef" />
                  <circle cx="148" cy="90.6" r="2.3" fill="#4a2e1f" /><circle cx="172" cy="90.6" r="2.3" fill="#4a2e1f" />
                  <circle cx="148.8" cy="89.8" r="0.8" fill="#fff" /><circle cx="172.8" cy="89.8" r="0.8" fill="#fff" />
                  <path d="M142.5 90.6 q5.5 -5 11 0 M166.5 90.6 q5.5 -5 11 0" stroke="#1a100b" strokeWidth="1.3" fill="none" strokeLinecap="round" />
                </g>
                <path d="M160 93 q-2.5 7 -0.5 9 q1.5 0.8 3 0" stroke="#b78a69" strokeWidth="1.2" fill="none" strokeLinecap="round" />
                <g transform="translate(160 109)">
                  <ellipse className="np-tv__mouth" rx="5.4" ry="1.3" fill="#5c1f24" />
                  <path d="M-6.5 -0.6 q3 -2.6 6.5 -1 q3.5 -1.6 6.5 1 q-6.5 1.4 -13 0 z" fill="#b4505a" />
                  <path d="M-6.5 0.6 q6.5 4.4 13 0" stroke="#b4505a" strokeWidth="1.6" fill="none" strokeLinecap="round" />
                </g>
                <circle cx="135.5" cy="101" r="1.8" fill="#c6ff3a" /><circle cx="184.5" cy="101" r="1.8" fill="#c6ff3a" />
              </g>
            </g></g>
            {/* desk */}
            <path d="M40 160 H280 L296 200 H24 Z" fill="url(#tv-desk)" />
            <rect x="40" y="158" width="240" height="3" fill="#c6ff3a" />
            <rect x="196" y="150" width="34" height="10" rx="1" fill="#efe8d8" opacity="0.85" transform="rotate(-6 213 155)" />
          </svg>
          <span className="np-tv__live" aria-hidden><i /> LIVE</span>
          <span className="np-tv__ai np-mono" aria-hidden>AI presenter</span>
          <div className="np-tv__lower">
            <span className="np-tv__bug">MSN</span>
            <span className="np-tv__label">{label}</span>
          </div>
          <div className="np-tv__crawl np-mono" aria-hidden><span>{crawl}   •   {crawl}</span></div>
          {state !== "live" ? (
            <div className={cn("np-tv__cover", state === "tuning" && "is-static")}>
              {state === "tuning" ? <span className="np-mono">Tuning in…</span>
                : state === "off" ? <span className="np-mono">Off air — back soon</span>
                : (
                  <button type="button" className="np-tv__play" onClick={() => {
                    // iPhones only allow speech started inside the tap: unlock it now, speak later.
                    window.speechSynthesis?.speak(new SpeechSynthesisUtterance(""));
                    void watch();
                  }}>
                    ▶ {state === "ended" ? "Watch again" : "Watch live"}
                  </button>
                )}
            </div>
          ) : null}
          <span className="np-tv__glass" aria-hidden />
        </div>
        <div className="np-tv__panel" aria-hidden>
          <i /><i /><span />
        </div>
      </div>
      <div className="np-tv__controls">
        {talking ? <button type="button" onClick={stop}>■ Stop</button> : <span className="np-mono np-dim">News, read aloud by an AI presenter</span>}
      </div>
    </aside>
  );
}
