"use client";

import type { CSSProperties } from "react";

import { PointerParallax } from "@/components/space/parallax";
import {
  AstronautArt,
  BluePlanetArt,
  CometArt,
  LaunchPadArt,
  LunarModuleArt,
  MeteorArt,
  MoonArt,
  RedPlanetArt,
  RingedPlanetArt,
  RocketArt,
  RocketFlame,
  RoverArt,
  SatelliteArt,
} from "@/components/space/objects";
import { atOrAfter, launchDurations, type ScenePhase } from "@/lib/launch";

/**
 * THE HOMEPAGE UNIVERSE — the cinematic version.
 *
 * Same architecture as the terminal's `Universe`: CSS keyframes on composited
 * transforms, one shared pointer listener, no per-object state or timers. What
 * differs is *composition* and *permission* — this screen has no data to
 * protect, so it gets the astronauts, the lunar surface, the rover and a hero
 * rocket the terminal is deliberately denied.
 *
 * THE LAUNCH BELONGS TO THE VISITOR NOW
 *
 * It used to fire on its own: three `setTimeout`s and a `sessionStorage` flag
 * that played the sequence once, unprompted, about two seconds after the page
 * settled. That is gone, and its removal is most of this file's diff. A rocket
 * that leaves before anyone has typed anything cannot be the reward for typing
 * something. The pad now holds the ship until the server accepts a code, and
 * the whole sequence is driven by the `phase` prop.
 *
 * Still zero JavaScript per frame. React writes four attributes and a handful
 * of custom properties; every pixel of motion below is CSS.
 *
 *   data-launch     the exact phase, for the moments that are instants
 *   data-sequence   latched from `approved` — the mission is underway
 *   data-lit        latched from `ignition`  — the engine is burning
 *   data-flying     latched from `launching` — the ship and camera are moving
 *
 * The latched flags exist because CSS cannot say "this attribute or any state
 * after it", and an engine that unlit itself between two phases would be a
 * very expensive-looking bug.
 */
export function HomeUniverse({ phase = "idle" }: { phase?: ScenePhase }) {
  const flying = atOrAfter(phase, "launching");

  return (
    <>
      <PointerParallax />

      <div
        className="home-universe"
        style={launchDurations() as CSSProperties}
        data-launch={phase}
        data-sequence={atOrAfter(phase, "approved") ? "" : undefined}
        data-lit={atOrAfter(phase, "ignition") ? "" : undefined}
        data-flying={flying ? "" : undefined}
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

        {/* --- MID: the planetary system -------------------------------- */}
        <div className="universe__depth universe__depth--mid">
          <div className="home-universe__body home-universe__body--red">
            <RedPlanetArt />
          </div>
          <div className="home-universe__body home-universe__body--ringed">
            <RingedPlanetArt />
          </div>
          <div className="home-universe__body home-universe__body--blue">
            <BluePlanetArt />
          </div>
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
            <AstronautArt />
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
            behind it. Split in two: the pad and its ground plume recede with
            the camera, the ship does not. They are siblings rather than parent
            and child because a rocket nested inside something the camera is
            pushing down would have to out-fly its own container to appear to
            move at all. One set of coordinates, held in custom properties on
            the scene root, keeps the two aligned anyway. */}
        <div className="home-universe__station">
          <div className="home-universe__pad">
            <LaunchPadArt />
          </div>
          <span className="home-universe__plume" />
        </div>

        <div className="home-universe__rocket">
          <div className="home-universe__rocket-ship">
            <RocketArt />
            <span className="home-universe__lights" />
            <span className="home-universe__flame">
              <RocketFlame />
            </span>
          </div>
        </div>

        {/* --- THE DESTINATION -----------------------------------------
            Outside every depth group on purpose. The camera moves the scene
            past the viewer; the place the viewer is going has to hold still in
            the frame and grow, which it cannot do inside a layer that is
            itself being pushed. */}
        <div className="home-universe__destination">
          <MoonArt />
        </div>
        {/* Limb darkening. Without it the planet filling the viewport is a flat
            grey wall, and the last thing a visitor sees before a dark terminal
            should not be the brightest frame of the sequence. */}
        <span className="home-universe__atmosphere" />
        <span className="home-universe__portal" />

        <div className="home-universe__scrim" />
      </div>
    </>
  );
}
