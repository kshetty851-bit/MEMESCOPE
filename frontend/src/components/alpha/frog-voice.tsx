"use client";

import { useEffect, useRef } from "react";

import { createSfx, readSound, type Sfx } from "@/components/space/login-crew";
import type { ScenePhase } from "@/lib/launch";

/**
 * THE FROG CALLS THE LAUNCH (2026-09-25, Karthik: "access approved, launching
 * in 5 4 3 2 1 in a cute cartoon voice, and a woohoo cheer — make it funny").
 *
 * The voice is the browser's own speech synthesiser at its highest pitch and a
 * little fast — chipmunk territory, which is the cartoon — so there is no
 * audio file. Every line is tied to a step of the launch timeline, so the
 * frog cannot say "three" while the screen shows four. A beep marks each
 * digit and lift-off gets a roar, a party horn and a cheer.
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

const SAY: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved! Launching in…",
  ignition: "Woo-hoo!",
  launching: "Wheeeee! Hold on to your helmets!",
  flight: "Are we there yet?",
  unlock: "Welcome home, Karthik!",
};

const DIGITS = ["", "one", "two", "three", "four", "five"];

const BUBBLE: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved! Launching in…",
  ignition: "WOO-HOO! 🚀",
};

function speak(text: string) {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
  if (!synth || typeof SpeechSynthesisUtterance === "undefined") return;
  // A late line never queues behind an earlier one: the frog says what the
  // screen shows now, cutting off whatever it was still finishing.
  synth.cancel();
  const line = new SpeechSynthesisUtterance(text);
  const voices = synth.getVoices();
  line.voice =
    voices.find((v) => /samantha|google us english|aria|jenny|karen|zira/i.test(v.name)) ??
    voices.find((v) => v.lang.startsWith("en")) ??
    null;
  line.pitch = 2;
  line.rate = 1.25;
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
