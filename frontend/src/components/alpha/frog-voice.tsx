"use client";

import { useEffect, useRef } from "react";

import { createSfx, readSound, type Sfx } from "@/components/space/login-crew";
import type { ScenePhase } from "@/lib/launch";

/**
 * THE FROG CALLS THE LAUNCH (2026-09-25, Karthik: "access approved, launching
 * in 5 4 3 2 1 in a cute cartoon voice, and a woohoo cheer — make it funny").
 *
 * The voice is the browser's own speech synthesiser — a male voice, a touch
 * higher and slower than normal — so there is no audio file.
 * Every line is tied to a step of the launch timeline, so the frog cannot
 * say "three" while the screen shows four. A beep marks each digit and
 * lift-off gets a roar, a party horn and a cheer.
 *
 * Silent when the crew is muted (the same remembered switch), and quiet by
 * construction otherwise: nothing here plays until a code has been accepted,
 * which is itself a click or a key press.
 *
 * The bubble shows the line while the frog is on screen (approved through
 * ignition); after that it has leaned back to watch the rocket, and the rest
 * is voice only. `aria-hidden`: the launch overlay already announces the
 * sequence to screen readers.
 */

// Karthik, 2026-09-25: "funnier, a male voice" — then no name, then "too
// fast and robotic, and the woo-hoo has no emotion". A speech synthesiser
// cannot cheer, so ignition is a sound effect now, not a spoken line.
const SAY: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved, Captain! Launching in…",
  launching: "Ribbit! Hold on to your helmet!",
  flight: "Are we there yet?",
  unlock: "Welcome home, Boss!",
};

/** Lines that must land on their step, cutting off whatever came before. */
const ON_THE_BEAT = new Set<ScenePhase>(["approved", "countdown"]);

const DIGITS = ["", "One!", "Two!", "Three!", "Four!", "Five!"];

const BUBBLE: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved, Captain! 🫡 Launching in…",
  ignition: "WOO-HOO! 🚀",
};

/**
 * A male voice, picked by name because the API has no gender field. The
 * neural voices some browsers ship ("Natural", "Neural", "Enhanced",
 * "Premium") sound far less robotic, so a male one of those wins; then the
 * ordinary male voices on Mac, Chrome, Windows and Android.
 */
const MALE = /\b(daniel|alex|aaron|arthur|oliver|rishi|google uk english male|guy|davis|david|mark|ryan|george|james|thomas|andrew|brian|christopher|eric|roger|steffan|william)\b/i;
const NATURAL = /natural|neural|enhanced|premium/i;

function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const english = voices.filter((v) => v.lang.startsWith("en"));
  return (
    english.find((v) => MALE.test(v.name) && NATURAL.test(v.name)) ??
    english.find((v) => MALE.test(v.name)) ??
    english[0] ??
    null
  );
}

function speak(text: string, interrupt: boolean) {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  if (!synth || typeof SpeechSynthesisUtterance === "undefined") return;
  // The countdown must say what the screen shows, so it cuts off anything
  // still playing. After lift-off nothing is on a beat, so each line is
  // allowed to finish.
  if (interrupt) synth.cancel();
  const line = new SpeechSynthesisUtterance(text);
  line.voice = pickVoice(synth.getVoices());
  // Close to natural: a touch higher and a touch slower than the default
  // reads as a friendly cartoon without the chipmunk warble.
  line.pitch = 1.25;
  line.rate = 0.95;
  line.volume = 1;
  synth.speak(line);
}

export function FrogVoice({ phase, count }: { phase: ScenePhase; count: number | null }) {
  const sfx = useRef<Sfx | null>(null);

  // Unlock sound on the gesture that submits the code, as browsers require;
  // iOS also wants speech primed inside a gesture, so a silent line is spoken.
  useEffect(() => {
    const wake = () => {
      if (!readSound()) return;
      if (!sfx.current) sfx.current = createSfx();
      sfx.current?.start();
      if (typeof SpeechSynthesisUtterance !== "undefined" && window.speechSynthesis && !window.speechSynthesis.speaking) {
        const primer = new SpeechSynthesisUtterance(" ");
        primer.volume = 0;
        window.speechSynthesis.speak(primer);
      }
    };
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    return () => {
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
      sfx.current?.close();
      sfx.current = null;
    };
  }, []);

  useEffect(() => {
    if (!readSound()) return;
    if (phase === "countdown" && count) {
      speak(DIGITS[count] ?? String(count), true);
      sfx.current?.beep(count === 1 ? 1320 : 880);
      return;
    }
    const line = SAY[phase];
    if (line) speak(line, ON_THE_BEAT.has(phase));
    if (phase === "ignition") {
      window.speechSynthesis?.cancel();
      sfx.current?.woohoo();
      sfx.current?.blastoff();
    }
  }, [phase, count]);

  const text = phase === "countdown" && count ? `${count}!` : BUBBLE[phase];
  if (!text) return null;
  return (
    <span key={`${phase}-${count ?? ""}`} className="frog-bubble" data-count={phase === "countdown" ? "" : undefined} aria-hidden>
      {text}
    </span>
  );
}
