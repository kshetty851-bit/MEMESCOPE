"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { audioContextCtor, createSpaceAudio, type SpaceAudio } from "@/lib/space-audio";
import { cn } from "@/lib/utils";

/**
 * The switch for the drone in `lib/space-audio`.
 *
 * OFF, ALWAYS, ON EVERY VISIT. Not a lapse — the browser will not start audio
 * without a gesture, so a remembered "on" could not be honoured on arrival
 * anyway, and the only way to make it appear to work would be to wait for the
 * visitor's first unrelated click and play sound at them then. One deliberate
 * click each visit is the honest version.
 *
 * The AudioContext is built on that first click rather than on mount: a
 * context created before a gesture is born suspended, Safari counts it against
 * the page either way, and a visitor who never touches this should not be
 * charged an audio graph for a page they are only reading.
 */

function WaveIcon({ on }: { on: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    >
      {/* The speaker cone, always present. */}
      <path d="M3 6.2v3.6h2.2L8 12V4L5.2 6.2H3Z" />
      {on ? (
        // Two arcs radiating — drawn only when sound is actually running.
        <>
          <path d="M10.3 5.9a3 3 0 0 1 0 4.2" />
          <path d="M12.1 4.2a5.5 5.5 0 0 1 0 7.6" />
        </>
      ) : (
        <path d="M10.6 6.4 13.4 9.6M13.4 6.4 10.6 9.6" />
      )}
    </svg>
  );
}

export function SpaceAudioToggle({ className }: { className?: string }) {
  const [on, setOn] = useState(false);
  const [available, setAvailable] = useState(true);
  const audio = useRef<SpaceAudio | null>(null);

  // Never leave oscillators running behind a navigation.
  useEffect(() => {
    return () => {
      audio.current?.dispose();
      audio.current = null;
    };
  }, []);

  useEffect(() => {
    setAvailable(audioContextCtor() !== null);
  }, []);

  const toggle = useCallback(async () => {
    if (on) {
      audio.current?.stop();
      setOn(false);
      return;
    }

    if (!audio.current) {
      const Ctor = audioContextCtor();
      if (!Ctor) {
        setAvailable(false);
        return;
      }
      // Built inside the gesture, which is the only place it may be resumed.
      audio.current = createSpaceAudio(new Ctor());
    }

    try {
      await audio.current.start();
      setOn(true);
    } catch {
      // A browser that refuses the resume: leave the control saying "off",
      // because that is the truth of what the visitor can hear.
      setOn(false);
    }
  }, [on]);

  if (!available) return null;

  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? "Turn the ambient soundtrack off" : "Turn the ambient soundtrack on"}
      title={on ? "Sound on" : "Ambient sound"}
      onClick={() => void toggle()}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-label uppercase",
        "transition-colors duration-[var(--duration-instant)]",
        on
          ? "border-accent/40 bg-accent/10 text-accent"
          : "border-line-control text-ink-3 hover:border-line-strong hover:text-ink",
        className,
      )}
    >
      <WaveIcon on={on} />
      {/* The icon carries the state; the word only says what the control is. */}
      <span className="hidden sm:inline">Sound</span>
    </button>
  );
}
