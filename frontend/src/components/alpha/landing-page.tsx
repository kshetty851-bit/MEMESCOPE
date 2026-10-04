"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { Wordmark, WordmarkSubtitle } from "@/components/brand/wordmark";
import { AlphaAccess } from "@/components/alpha/alpha-access";
import { HeroMascot, type MascotState } from "@/components/alpha/hero-mascot";
import { Journey } from "@/components/alpha/journey";
import { SiteFooter, WhatRunsHere } from "@/components/alpha/what-runs-here";
import { HomeUniverse } from "@/components/space/home-universe";
import { FloatingCrew, PerchedCrew } from "@/components/space/space-crew";
import { SpaceAudioToggle } from "@/components/space/space-audio-toggle";
import { SpaceFacts } from "@/components/space/space-facts";
import { ALPHA_ACCESS } from "@/lib/env";
import type { GatePhase } from "@/lib/launch";
import { cn } from "@/lib/utils";

/** The moon landing, as a lazy chunk: not in the page's first load. */
const loadMoonIntro = () => import("@/components/moon-intro/moon-intro");
/** The Checkpoint office, loaded after the page so HQ's drawings stay out of
 *  the homepage's first download. */
const CheckpointPublic = dynamic(
  () => import("@/components/hq/checkpoint").then((m) => m.CheckpointPublic),
  { ssr: false },
);
const MoonIntro = dynamic(loadMoonIntro, { ssr: false });

/**
 * THE ALPHA GATE — now a landing.
 *
 * The layout is unchanged and stays unchanged: a two-column grid whose copy
 * and access panel are siblings that cannot collide at any width, with the
 * scene behind both rather than beside them. That was the fix for a set of
 * real contrast failures and none of this touches it.
 *
 * An accepted code mounts `MoonIntro` (components/moon-intro), a full-screen
 * cockpit ride to the moon that owns its own clock and calls `enter` when it
 * lands. The page behind it stays in its idle state.
 *
 * Two pieces of state, and no more:
 *
 *   gate      what the form last reported: idle, validating, or denied
 *   approved  a latch. Once set it never clears, so nothing can re-enter the
 *             intro or resubmit a code while it plays.
 *
 * A returning visitor never sees any of it: `AlphaAccess` asks the server
 * whether the session is already live and redirects before the form paints.
 * That behaviour predates this and is exactly why no new persistence was
 * added for "have they seen the cinematic" — an authenticated visitor is not
 * on this page long enough to have the question asked.
 */
export function LandingPage() {
  const router = useRouter();

  const [gate, setGate] = useState<GatePhase>("idle");
  const [approved, setApproved] = useState(false);
  const [sceneOnly, setSceneOnly] = useState(false);

  const enter = useCallback(() => {
    router.push(ALPHA_ACCESS.dashboardPath);
  }, [router]);

  // The server already said yes; warm the dashboard while the intro plays.
  useEffect(() => {
    if (approved) router.prefetch(ALPHA_ACCESS.dashboardPath);
  }, [approved, router]);

  // Fetch the intro's chunk once the page is idle, so an accepted code cuts
  // straight to black instead of waiting on the download (~10 KB gzipped).
  useEffect(() => {
    const warm = () => void loadMoonIntro();
    // Safari has no requestIdleCallback; a plain delay does the same job.
    if (typeof window.requestIdleCallback !== "function") {
      const timer = window.setTimeout(warm, 2000);
      return () => window.clearTimeout(timer);
    }
    const id = window.requestIdleCallback(warm, { timeout: 4000 });
    return () => window.cancelIdleCallback(id);
  }, []);

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

  const mascot: MascotState = gate === "denied" ? "denied" : "idle";

  return (
    <main
      data-phase={gate}
      className={cn(
        "alpha-landing relative isolate min-h-dvh overflow-x-hidden text-ink",
        sceneOnly && "alpha-landing--scene-only",
      )}
    >
      <HomeUniverse />
      <FloatingCrew />

      <section className="relative mx-auto flex min-h-dvh w-full max-w-[80rem] flex-col px-6 py-8 lg:px-10">
        {/* `data-alpha-content` marks what `?scene=1` hides — a capture mode for
            brand shots that shows the scene without the interface. */}
        <header data-alpha-content className="relative z-10 flex items-center gap-3">
          <LogoMark size={22} className="text-accent" />
          <Wordmark className="text-xs tracking-[0.18em]" />
          <span className="ml-3 rounded-sm border border-line-control px-1.5 py-0.5 text-label font-medium uppercase text-ink-3">
            Private alpha
          </span>
          {/* Off until asked for, every visit — see the component. It sits in
              the header rather than over the scene so it cannot be mistaken
              for part of the launch sequence. */}
          <SpaceAudioToggle className="ml-auto" />
        </header>
        {/* Space knowledge (Karthik, 2026-09-27). Under the header below lg,
            where the frog is not shown; bottom left, beside the frog, above. */}
        <SpaceFacts className="relative z-10 mt-3 lg:hidden" />

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
          // Top-aligned on desktop: centred copy ends mid-frame, right where the
          // launch station stands (see home-universe.css, 2026-09-24).
          className="relative z-10 grid flex-1 items-center gap-10 py-10 lg:grid-cols-[minmax(0,1fr)_23rem] lg:items-start lg:gap-16 lg:pt-14"
        >
          <div className="max-w-xl">
            {/* The wordmark *is* the headline, at hero scale. It used to be the
                product name set as an ordinary `<h1>`, which meant the brand
                appeared twice on the page in two different shapes — once in
                the header as a lockup and once here as text. One mark. */}
            <h1 className="hero-mark">
              {/* The animals sit ON the letters: the host shrink-wraps the
                  wordmark so their em offsets land on the glyphs. */}
              <span className="crew-perch-host text-[clamp(2.4rem,7vw,4.6rem)]">
                <Wordmark title="MEMESCOPE" className="text-[clamp(2.4rem,7vw,4.6rem)]" />
                <PerchedCrew />
              </span>
            </h1>
            {/* Restyled 2026-09-27 (Karthik: "more stylish and neat"). Same words. */}
            <div className="hero-kicker">
              <span className="hero-kicker__rule" aria-hidden />
              <WordmarkSubtitle className="hero-kicker__text" />
              <span className="hero-kicker__live">
                <span aria-hidden />
                Live
              </span>
            </div>
            <p className="hero-tagline">
              Every pump.fun graduation,{" "}
              <span className="hero-tagline__em">tested before it&apos;s traded.</span>
            </p>
            <p className="hero-lede">
              MEMESCOPE watches around <b>1,500 graduations a day</b>, runs each strategy{" "}
              <b>on paper</b> against a fair comparison, and lets <b>real money</b> follow
              only what earns it.
            </p>
          </div>

          <AlphaAccess
            onPhase={(next) => (next === "approved" ? setApproved(true) : setGate(next))}
          />
        </div>

        <SpaceFacts toFrog className="space-facts--by-frog hidden lg:block" />
      </section>

      {approved && <MoonIntro onComplete={enter} />}

      {/*
        THE CHECKPOINT, WHERE THE CREW WAS (Karthik, 2026-10-04: "remove the
        memescope team on homepage before login, and show this 30 agents and
        their real time work"). First after the hero, for the reason the crew
        was: what sits below the intelligence is never scrolled to.
      */}
      <section className="relative mx-auto w-full max-w-[80rem] px-4 py-10 lg:px-10" aria-labelledby="checkpoint-heading">
        <h2 id="checkpoint-heading" className="text-2xl font-semibold text-ink">
          30 checks, live
        </h2>
        <p className="mt-1 max-w-[70ch] text-sm text-ink-2">
          Every new pump.fun coin walks past these thirty before the real wallet may buy it.
          This is them at work right now.
        </p>
        <div className="mt-4">
          <CheckpointPublic />
        </div>
      </section>
      <WhatRunsHere />
      <Journey />
      <SiteFooter />
    </main>
  );
}
