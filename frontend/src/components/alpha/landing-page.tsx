"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { Wordmark, WordmarkSubtitle } from "@/components/brand/wordmark";
import { Crew, EnterHq } from "@/components/alpha/crew";
import { AlphaAccess } from "@/components/alpha/alpha-access";
import { HeroMascot, type MascotState } from "@/components/alpha/hero-mascot";
import { HomepageIntelligence } from "@/components/alpha/homepage-intelligence";
import { LaunchOverlay, useLaunchSequence } from "@/components/alpha/launch-sequence";
import { HomeUniverse } from "@/components/space/home-universe";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { ALPHA_ACCESS } from "@/lib/env";
import { atOrAfter, type GatePhase, type ScenePhase } from "@/lib/launch";
import { cn } from "@/lib/utils";

/**
 * THE ALPHA GATE — now a launch.
 *
 * The layout is unchanged and stays unchanged: a two-column grid whose copy
 * and access panel are siblings that cannot collide at any width, with the
 * scene behind both rather than beside them. That was the fix for a set of
 * real contrast failures and none of this touches it.
 *
 * What is new is that the page owns a sequence. An accepted code no longer
 * means "wait 1.7 seconds, then navigate" — it starts a timeline that the
 * mascot, the universe and the overlay all read from, and navigation happens
 * when that timeline reaches its last step.
 *
 * Three pieces of state, and no more:
 *
 *   gate      what the form last reported: idle, validating, or denied
 *   approved  a latch. Once set it never clears, so nothing can re-enter the
 *             sequence or resubmit a code while the rocket is in the air.
 *   phase     where the timeline is, once approved
 *
 * A returning visitor never sees any of it: `AlphaAccess` asks the server
 * whether the session is already live and redirects before the form paints.
 * That behaviour predates this and is exactly why no new persistence was
 * added for "have they seen the cinematic" — an authenticated visitor is not
 * on this page long enough to have the question asked.
 */
export function LandingPage() {
  const router = useRouter();
  const reduced = useReducedMotion();

  const [gate, setGate] = useState<GatePhase>("idle");
  const [approved, setApproved] = useState(false);
  const [sceneOnly, setSceneOnly] = useState(false);

  const enter = useCallback(() => {
    router.push(ALPHA_ACCESS.dashboardPath);
  }, [router]);

  const { phase: launch, count } = useLaunchSequence(approved, reduced, enter);

  useEffect(() => {
    setSceneOnly(new URLSearchParams(window.location.search).get("scene") === "1");
  }, []);

  // A refusal is a moment, not a mode: the mascot's shake and the form's error
  // are different lifetimes, and only the error should persist until the next
  // keystroke.
  useEffect(() => {
    if (gate !== "denied") return;
    const timer = window.setTimeout(() => setGate("idle"), 700);
    return () => window.clearTimeout(timer);
  }, [gate]);

  const phase: ScenePhase = approved ? launch : gate;

  const mascot: MascotState = atOrAfter(phase, "ignition")
    ? "watching"
    : atOrAfter(phase, "approved")
      ? "approved"
      : phase === "denied"
        ? "denied"
        : "idle";

  return (
    <main
      data-phase={phase}
      // Latched, like the scene's own flags: once the code is accepted the
      // interface stands down and cannot come back mid-flight.
      data-sequence={atOrAfter(phase, "approved") ? "" : undefined}
      className={cn(
        "alpha-landing relative isolate min-h-dvh overflow-x-hidden text-ink",
        (phase === "unlock" || phase === "enter" || (reduced && approved)) &&
          "alpha-landing--unlock",
        sceneOnly && "alpha-landing--scene-only",
      )}
    >
      <HomeUniverse phase={phase} />

      <section className="relative mx-auto flex min-h-dvh w-full max-w-[80rem] flex-col px-6 py-8 lg:px-10">
        {/* `data-alpha-content` marks what `?scene=1` hides — a capture mode for
            brand shots that shows the scene without the interface. It is also
            what fades out under the countdown, so the mission has the frame. */}
        <header data-alpha-content className="relative z-10 flex items-center gap-3">
          <LogoMark size={22} className="text-accent" />
          <Wordmark className="text-xs tracking-[0.18em]" />
          <span className="ml-3 rounded-sm border border-line-control px-1.5 py-0.5 text-label font-medium uppercase text-ink-3">
            Private alpha
          </span>
        </header>

        {/* The mascot lives behind the grid, not beside it. Below `lg` it is out
            of the idle composition — a figure behind a login form on a 375px
            screen is a contrast problem, not a brand moment — and the scene CSS
            brings it back, repositioned, the moment it has something to react
            to. */}
        <div className="alpha-mascot-mount pointer-events-none absolute" aria-hidden>
          <HeroMascot state={mascot} />
        </div>

        <div
          data-alpha-content
          className="relative z-10 grid flex-1 items-center gap-10 py-10 lg:grid-cols-[minmax(0,1fr)_23rem] lg:gap-16"
        >
          <div className="max-w-xl">
            {/* The wordmark *is* the headline, at hero scale. It used to be the
                product name set as an ordinary `<h1>`, which meant the brand
                appeared twice on the page in two different shapes — once in
                the header as a lockup and once here as text. One mark. */}
            <h1 className="hero-mark">
              <Wordmark title="MEMESCOPE" className="text-[clamp(2.4rem,7vw,4.6rem)]" />
            </h1>
            <WordmarkSubtitle className="mt-4" />
            <p className="mt-6 text-[clamp(1.125rem,2vw,1.5rem)] font-medium leading-snug tracking-tight text-ink">
              Not a scanner. A command centre.
            </p>
            <p className="mt-3 max-w-md text-sm leading-relaxed text-ink-2">
              Real-time Pump.fun intelligence, run by ten specialists who each
              watch one subsystem. Every launch tracked, scored deterministically,
              and published — winners and losers alike.
            </p>
          </div>

          <AlphaAccess
            onPhase={(next) => (next === "approved" ? setApproved(true) : setGate(next))}
          />
        </div>
      </section>

      <LaunchOverlay phase={phase} count={count} />

      <div className="alpha-transition" aria-hidden />

      {/*
        THE CREW COMES FIRST, AND THAT ORDERING IS THE FIX.

        This sat *after* `HomepageIntelligence`, which is 4,753px tall on a
        1440x900 desktop — so the team section began at y=5,653 on a 6,600px
        page. It was rendered, it was correct, and no one was ever going to
        scroll to it. "Deployed" and "visible" turned out to be different
        claims, and only the first one had been checked.

        The order now tells the product's story in the order it happens: this
        is who we are, this is the door they work behind, and *then* the live
        intelligence for anyone who wants the detail.
      */}
      <Crew />
      <EnterHq />
      <HomepageIntelligence />
    </main>
  );
}
