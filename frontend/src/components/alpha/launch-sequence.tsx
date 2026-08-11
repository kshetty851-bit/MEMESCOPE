"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";

import {
  COUNTDOWN_TICK,
  LAUNCH_TIMELINE,
  REDUCED_TIMELINE,
  type LaunchPhase,
  type LaunchStep,
  type ScenePhase,
} from "@/lib/launch";

/**
 * Walks the launch timeline with one timer at a time.
 *
 * Deliberately not a state-management library and not a reducer: the sequence
 * is linear, has no branches and cannot be re-entered, so an index into an
 * array is the whole model. Twelve renders across the entire sequence — the
 * scene animation itself is CSS and costs React nothing per frame.
 */
export function useLaunchSequence(
  active: boolean,
  reduced: boolean,
  onEnter: () => void,
): { phase: LaunchPhase; count: number | null } {
  const [step, setStep] = useState(0);
  // The callback navigates. Holding it in a ref keeps it out of the effect's
  // dependencies, so a re-created handler cannot restart the countdown.
  const enter = useRef(onEnter);
  enter.current = onEnter;

  /*
     Chosen once, when the sequence starts, and never re-read.

     `reduced` is live — it tracks the OS setting and can change at any moment.
     If it changed mid-flight the timeline array would swap under an index
     pointing into the old one, `timeline[step]` would be `undefined`, and the
     effect would return without scheduling anything or navigating. The visitor
     would be authenticated, holding a valid session cookie, and parked on the
     launch screen forever.

     Vanishingly unlikely and completely silent, which is exactly the kind of
     bug worth one ref to make impossible.
  */
  const frozen = useRef<readonly LaunchStep[] | null>(null);
  if (active && !frozen.current) {
    frozen.current = reduced ? REDUCED_TIMELINE : LAUNCH_TIMELINE;
  }
  const timeline = frozen.current ?? (reduced ? REDUCED_TIMELINE : LAUNCH_TIMELINE);

  useEffect(() => {
    if (!active) return;

    const current = timeline[step];
    // Past the end, or an index that cannot be resolved: enter regardless.
    // Being stuck outside the product is a worse failure than a cut cinematic.
    if (!current || current.phase === "enter") {
      enter.current();
      return;
    }

    const timer = window.setTimeout(() => setStep((previous) => previous + 1), current.ms);
    return () => window.clearTimeout(timer);
  }, [active, step, timeline]);

  if (!active) return { phase: "idle", count: null };

  const current = timeline[step] ?? timeline.at(-1);
  return { phase: current?.phase ?? "idle", count: current?.count ?? null };
}

/**
 * THE MISSION CARD.
 *
 * Sits above the scene and below nothing. It is `pointer-events: none` — the
 * form beneath it is already locked by the sequence, and an overlay that can
 * swallow a click is a bug waiting for a slow network.
 *
 * Screen readers get the two milestones as words and never the digits: a
 * five-step countdown announced at 700ms intervals is noise, and the
 * information a non-sighted visitor needs is "you are in", not "three".
 */
export function LaunchOverlay({
  phase,
  count,
}: {
  phase: ScenePhase;
  count: number | null;
}) {
  const showing =
    phase === "approved" ||
    phase === "countdown" ||
    phase === "ignition" ||
    phase === "unlock" ||
    phase === "enter";

  return (
    <>
      <p role="status" className="sr-only">
        {phase === "approved" ? "Access approved. Launching." : null}
        {phase === "unlock" || phase === "enter" ? "MEMESCOPE unlocked. Entering." : null}
      </p>

      {showing ? (
        <div
          className="launch-card"
          // The digit's animation is exactly one beat long, timed off the same
          // constant React counts on rather than a number retyped into CSS.
          style={{ "--launch-tick": `${COUNTDOWN_TICK}ms` } as CSSProperties}
          aria-hidden
        >
          {phase === "approved" ? (
            <p className="launch-card__banner">Access approved</p>
          ) : null}

          {phase === "countdown" ? (
            <>
              <p className="launch-card__kicker">Launching in</p>
              {/* Keyed by the digit so each number gets its own scale-in
                  rather than the browser tweening one glyph into the next. */}
              <p key={count} className="launch-card__count" data-numeric>
                {count}
              </p>
            </>
          ) : null}

          {phase === "ignition" ? <p className="launch-card__banner">Ignition</p> : null}

          {phase === "unlock" || phase === "enter" ? (
            <p className="launch-card__banner launch-card__banner--unlock">
              MEMESCOPE unlocked
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
