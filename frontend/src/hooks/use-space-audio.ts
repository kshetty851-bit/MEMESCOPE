"use client";

import { useCallback, useSyncExternalStore } from "react";

import { audioContextCtor, createSpaceAudio, type SpaceAudio } from "@/lib/space-audio";

/**
 * WHO OWNS THE DRONE.
 *
 * Module scope, not a component ref, and that is the whole point of this file.
 * The control appears on the launch screen and again in the dashboard topbar,
 * which live in different layouts — so a ref-owned AudioContext would be
 * disposed the moment you entered the terminal, cutting the music off at
 * exactly the moment the visitor is going somewhere to look at it, and the
 * second button would then disagree with the first about whether sound was on.
 *
 * Module state survives client navigation, so one context is created at most
 * once per page load, both buttons read the same snapshot, and crossing from
 * the launch screen into the dashboard does not interrupt the sound.
 *
 * This follows `use-space.ts` and `use-nav-rail.ts`: an external store read
 * through `useSyncExternalStore`. It does NOT follow their persistence, and
 * that is deliberate — see `space-audio-toggle.tsx` for why a remembered "on"
 * is a promise the browser will not let us keep.
 */

let audio: SpaceAudio | null = null;
let playing = false;

const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether a soundtrack is possible at all here. */
export function spaceAudioSupported(): boolean {
  return typeof window !== "undefined" && audioContextCtor() !== null;
}

/**
 * Must be called from a user gesture — the AudioContext is constructed here,
 * inside the click, because that is the only place a browser will let it run.
 * Returns the state it settled on.
 */
export async function toggleSpaceAudio(): Promise<boolean> {
  if (playing) {
    audio?.stop();
    playing = false;
    emit();
    return false;
  }

  if (!audio) {
    const Ctor = audioContextCtor();
    if (!Ctor) return false;
    audio = createSpaceAudio(new Ctor());
  }

  try {
    await audio.start();
    playing = true;
  } catch {
    // A browser that refused the resume. Report off, because off is what the
    // visitor can hear.
    playing = false;
  }
  emit();
  return playing;
}

export function useSpaceAudio() {
  const on = useSyncExternalStore(
    subscribe,
    () => playing,
    () => false, // never playing during SSR; there has been no gesture
  );
  const toggle = useCallback(() => toggleSpaceAudio(), []);
  return { on, toggle };
}
