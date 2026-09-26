"use client";

import { PointerParallax } from "@/components/space/parallax";
import { Planets } from "@/components/space/planets";
import {
  CometArt,
  LaunchPadArt,
  LunarModuleArt,
  MeteorArt,
  MoonArt,
  RocketArt,
  RoverArt,
  SatelliteArt,
} from "@/components/space/objects";

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
          <div className="home-universe__nebula home-universe__nebula--violet" />
          <div className="home-universe__nebula home-universe__nebula--cyan" />
          <div className="home-universe__galaxy" />
          <div className="universe__stars universe__stars--far" />
          <div className="universe__stars universe__stars--mid" />
          <div className="universe__stars universe__stars--near" />
          <div className="universe__dust" />
        </div>

        {/* Karthik's wandering planets: in front of the stars, behind the
            rocket, the frog and everything else in the scene. */}
        <Planets />

        {/* --- MID: orbital traffic --------------------------------------
            The drawn red, ringed and blue planets that stood here were removed
            (Karthik, 2026-09-25): beside the cartoon planets above they read
            as clutter. */}
        <div className="universe__depth universe__depth--mid">
          <div className="home-universe__satellite">
            <SatelliteArt />
          </div>
        </div>

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

          {/* ONE astronaut, low-left and small.
              The frog in its suit is MEMESCOPE's astronaut and the hero of this
              screen; a second full-size figure beside it read as clutter and
              overlapped both the mascot and the access panel. This one is a
              distant companion, not a second lead. */}
          <div className="home-universe__astronaut home-universe__astronaut--one">
            {/* The zebra from the space crew (2026-09-24), in the slot and
                on the float the plain astronaut had. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/crew/zebra.webp" alt="" draggable={false} decoding="async" />
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

        {/* --- THE LAUNCH STATION --------------------------------------
            After the surface, so the pad stands on the ground rather than
            behind it. One set of coordinates, held in custom properties on the
            scene root, keeps the pad and the ship aligned. */}
        <div className="home-universe__station">
          <div className="home-universe__pad">
            <LaunchPadArt />
          </div>
        </div>

        <div className="home-universe__rocket">
          <div className="home-universe__rocket-ship">
            <RocketArt />
          </div>
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
