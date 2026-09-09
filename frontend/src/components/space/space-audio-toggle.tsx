"use client";

import { useEffect, useState } from "react";

import { useSpaceAudio, spaceAudioSupported } from "@/hooks/use-space-audio";
import { cn } from "@/lib/utils";

/**
 * The switch for the drone in `lib/space-audio`. It owns no audio itself —
 * `use-space-audio` holds the one instance at module scope so this can appear
 * on the launch screen and in the dashboard topbar at once, agreeing with
 * itself and playing through the navigation between them.
 *
 * OFF ON EVERY VISIT, and nothing is persisted. Not a lapse: the browser will
 * not start audio without a gesture, so a remembered "on" could not be
 * honoured on arrival anyway. The only way to make it appear to work would be
 * to wait for the visitor's first unrelated click and play sound at them then,
 * which is precisely the behaviour the autoplay rules exist to prevent. One
 * deliberate click per visit is the honest version.
 */

function WaveIcon({ on }: { on: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0"
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

export function SpaceAudioToggle({
  className,
  label = true,
}: {
  className?: string;
  /** The topbar is tight on room; there the icon speaks for itself. */
  label?: boolean;
}) {
  const { on, toggle } = useSpaceAudio();
  // Checked after mount, never during render: `window` does not exist on the
  // server and a mismatch here would be a hydration error on the landing page.
  const [supported, setSupported] = useState(true);
  useEffect(() => setSupported(spaceAudioSupported()), []);

  if (!supported) return null;

  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? "Turn the ambient soundtrack off" : "Turn the ambient soundtrack on"}
      title={on ? "Sound on" : "Ambient sound"}
      onClick={() => void toggle()}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 text-label uppercase",
        "transition-colors duration-[var(--duration-instant)]",
        on
          ? "border-accent/40 bg-accent/10 text-accent"
          : "border-line-control text-ink-3 hover:border-line-strong hover:text-ink",
        className,
      )}
    >
      <WaveIcon on={on} />
      {/* The icon carries the state; the word only says what the control is. */}
      {label ? <span className="hidden sm:inline">Sound</span> : null}
    </button>
  );
}
