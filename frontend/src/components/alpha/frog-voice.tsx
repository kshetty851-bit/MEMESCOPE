"use client";

import { useEffect, useRef } from "react";

import { createSfx, readSound, type Sfx } from "@/components/space/login-crew";
import type { ScenePhase } from "@/lib/launch";

/**
 * THE FROG CALLS THE LAUNCH (2026-09-25, Karthik: "access approved, launching
 * in 5 4 3 2 1 in a cute cartoon voice, and a woohoo cheer — make it funny").
 *
 * The voice is the browser's own speech synthesiser — a male voice, pitched
 * up and a little fast, which is the cartoon — so there is no audio file.
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

// Karthik, 2026-09-25: "funnier, a male voice" — and, after trying it, no name.
const SAY: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved, Captain! Launching in…",
  ignition: "Woo-hoo-hoo!",
  launching: "Ribbit! Hold on to your helmet!",
  flight: "Are we there yet? Are we there yet?",
  approach: "Ooh, shiny!",
  unlock: "Welcome home, Boss! Ribbit!",
};

const DIGITS = ["", "one!", "two!", "three!", "four!", "five!"];

const BUBBLE: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved, Captain! 🫡 Launching in…",
  ignition: "WOO-HOO-HOO! 🚀 Ribbit!",
};

/**
 * A male voice, picked by name because the API has no gender field. Fred and
 * Ralph are macOS's old novelty voices — the funniest if present — then the
 * ordinary male voices on Mac, Chrome, Windows and Android. Pitched up and
 * sped up a touch, a man's voice becomes a cartoon frog; a woman's at the same
 * settings reads as a chipmunk, which is what it was before.
 */
const MALE = /\b(fred|ralph|daniel|alex|aaron|arthur|oliver|rishi|google uk english male|guy|david|mark|ryan|george|james|thomas)\b/i;

function speak(text: string) {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  if (!synth || typeof SpeechSynthesisUtterance === "undefined") return;
  // A late line never queues behind an earlier one: the frog says what the
  // screen shows now, cutting off whatever it was still finishing.
  synth.cancel();
  const line = new SpeechSynthesisUtterance(text);
  const voices = synth.getVoices();
  const english = voices.filter((v) => v.lang.startsWith("en"));
  line.voice = english.find((v) => MALE.test(v.name)) ?? english[0] ?? null;
  line.pitch = 1.5;
  line.rate = 1.2;
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
      speak(DIGITS[count] ?? String(count));
      sfx.current?.beep(count === 1 ? 1320 : 880);
      return;
    }
    const line = SAY[phase];
    if (line) speak(line);
    if (phase === "ignition") sfx.current?.blastoff();
  }, [phase, count]);

  const text = phase === "countdown" && count ? `${count}!` : BUBBLE[phase];
  if (!text) return null;
  return (
    <span key={`${phase}-${count ?? ""}`} className="frog-bubble" data-count={phase === "countdown" ? "" : undefined} aria-hidden>
      {text}
    </span>
  );
}
