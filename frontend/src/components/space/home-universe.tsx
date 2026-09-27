"use client";

import { HumanAstronautArt } from "@/components/space/astronaut";
import { MeteorStrikes } from "@/components/space/meteor-strikes";
import { PointerParallax } from "@/components/space/parallax";
import { Planets } from "@/components/space/planets";
import { SpaceTravel } from "@/components/space/travel";
import {
  CometArt,
  LunarModuleArt,
  MeteorArt,
  MoonArt,
  RoverArt,
} from "@/components/space/objects";
import { SkyTraffic } from "@/components/space/sky-traffic";

/**
 * THE HOMEPAGE UNIVERSE — the cinematic version.
 *
 * Same architecture as the terminal's `Universe`: CSS keyframes on composited
 * transforms, one shared pointer listener, no per-object state or timers. What
 * differs is *composition* and *permission* — this screen has no data to
 * protect, so it gets the astronauts, the lunar surface, the rover and a hero
 * rocket the terminal is deliberately denied.
 *
 * THE ROCKET STAYS ON ITS PAD
 *
 * The launch that used to play here after an accepted code is gone: the moon
 * intro (components/moon-intro) now takes over the whole screen instead. This
 * scene is only ever the idle sky, and it runs no JavaScript per frame.
 */
export function HomeUniverse() {
  return (
    <>
      <PointerParallax />

      <div
        className="home-universe"
        aria-hidden="true"
        role="presentation"
      >
        <div className="home-universe__canvas" />

        {/* --- FAR ------------------------------------------------------ */}
        <div className="universe__depth universe__depth--far">
          {/* The Milky Way and a rose nebula (Karthik, 2026-09-27). */}
          <div className="home-universe__milkyway" />
          <div className="home-universe__nebula home-universe__nebula--violet" />
          <div className="home-universe__nebula home-universe__nebula--cyan" />
          <div className="home-universe__nebula home-universe__nebula--rose" />
          <div className="home-universe__galaxy" />
          {/* Stars streaming past: the feeling of travelling. */}
          <SpaceTravel />
          <div className="universe__stars universe__stars--far" />
          <div className="universe__stars universe__stars--mid" />
          <div className="universe__stars universe__stars--near" />
          <div className="universe__dust" />
        </div>

        {/* Karthik's wandering planets: in front of the stars, behind the
            rocket, the frog and everything else in the scene. */}
        <Planets />
        {/* Now and then a meteor strikes one of them. */}
        <MeteorStrikes />

        {/* --- MID: small rockets, satellites and aliens crossing now and
            then (Karthik, 2026-09-27). The old drawn satellite, the rocket
            and its launch station went the same day, as did the zebra. */}
        <SkyTraffic />

        {/* --- NEAR: traffic and figures -------------------------------- */}
        <div className="universe__depth universe__depth--near">
          <div className="home-universe__meteor home-universe__meteor--a">
            <MeteorArt />
          </div>
          <div className="home-universe__meteor home-universe__meteor--b">
            <MeteorArt />
          </div>
          <div className="home-universe__comet">
            <CometArt />
          </div>

          {/* A human astronaut, tumbling slowly across the sky. */}
          <div className="home-universe__spacewalker">
            <HumanAstronautArt />
          </div>
        </div>

        {/* --- FOREGROUND: the lunar surface ---------------------------- */}
        <div className="home-universe__surface">
          <div className="home-universe__module">
            <LunarModuleArt />
          </div>
          <div className="home-universe__rover">
            <RoverArt />
          </div>
          <div className="home-universe__ground" />
        </div>

        {/* --- THE DESTINATION: the moon, small and far off ------------ */}
        <div className="home-universe__destination">
          <MoonArt />
        </div>

        <div className="home-universe__scrim" />
      </div>
    </>
  );
}
