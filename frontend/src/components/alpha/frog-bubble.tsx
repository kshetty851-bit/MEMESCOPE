import type { ScenePhase } from "@/lib/launch";

/**
 * THE FROG'S SPEECH BUBBLE during the launch (2026-09-25).
 *
 * It had a voice for a while — a speech synthesiser, beeps, a slide-whistle
 * woo-hoo and a blast-off roar — and Karthik asked for the launch to be
 * silent, so it is text only: the line over the frog's head while it is on
 * screen (approved through ignition), the digits set big like it is shouting
 * them. `aria-hidden`: the launch overlay already announces the sequence to
 * screen readers.
 */
const BUBBLE: Partial<Record<ScenePhase, string>> = {
  approved: "Access approved, Captain! 🫡 Launching in…",
  ignition: "WOO-HOO! 🚀",
};

export function FrogBubble({ phase, count }: { phase: ScenePhase; count: number | null }) {
  const text = phase === "countdown" && count ? `${count}!` : BUBBLE[phase];
  if (!text) return null;
  return (
    <span key={`${phase}-${count ?? ""}`} className="frog-bubble" data-count={phase === "countdown" ? "" : undefined} aria-hidden>
      {text}
    </span>
  );
}
