import { PointerParallax } from "@/components/space/parallax";
import {
  AsteroidArt,
  BluePlanetArt,
  CometArt,
  MeteorArt,
  MoonArt,
  ProbeArt,
  RedPlanetArt,
  RingedPlanetArt,
  RocketArt,
  SatelliteArt,
} from "@/components/space/objects";

/**
 * THE MEMESCOPE UNIVERSE — authenticated terminal.
 *
 * Phase 9 upgraded the *objects*, not the architecture. Every animation still
 * lives in `styles/universe.css`, still moves only `transform` and `opacity`,
 * and still runs on the compositor without waking React. What changed is that
 * the rocket is no longer a 14×4 rounded rectangle and the satellite is no
 * longer a bar with two pseudo-element stubs — they are illustrated SVGs, sized
 * and positioned by exactly the same rules that moved the slivers.
 *
 * DEPTH GROUPS
 *
 * The three `__depth` wrappers are the one structural addition, and they exist
 * to make parallax affordable: pointer offset is applied to three containers
 * rather than to twenty objects, so the whole effect costs three composited
 * transforms. Each group's own children keep their independent animations.
 *
 *   far   stars, nebulae      barely moves
 *   mid   planets, galaxy     slow
 *   near  traffic             most responsive
 *
 * RESTRAINT IS THE POINT HERE
 *
 * This is the terminal, not the homepage. No astronaut, no rover, no lunar
 * module, and the rocket is a distant speck on a three-minute cycle. Objects
 * are placed toward the edges — the margins a 50-row table leaves alone — and
 * when the table covers them, that is the correct outcome. The data is the hero.
 */
export function Universe() {
  return (
    <>
      <PointerParallax />

      <div className="universe" aria-hidden="true" role="presentation">
        {/* Layer 0 — deep space */}
        <div className="universe__canvas" />

        {/* --- FAR: sky ------------------------------------------------- */}
        <div className="universe__depth universe__depth--far">
          <div className="universe__nebula universe__nebula--violet" />
          <div className="universe__nebula universe__nebula--cyan" />
          <div className="universe__nebula universe__nebula--ember" />
          <div className="universe__stars universe__stars--far" />
          <div className="universe__stars universe__stars--mid" />
          <div className="universe__stars universe__stars--near" />
          <div className="universe__dust" />
        </div>

        {/* --- MID: bodies ---------------------------------------------- */}
        <div className="universe__depth universe__depth--mid">
          <div className="universe__galaxy" />
          {/* Entering from the right edge — the margin beside the tables. */}
          <div className="universe__body universe__body--red">
            <RedPlanetArt />
          </div>
          <div className="universe__body universe__body--ringed">
            <RingedPlanetArt />
          </div>
          <div className="universe__body universe__body--blue">
            <BluePlanetArt />
          </div>
          <div className="universe__body universe__body--moon">
            <MoonArt />
          </div>
          <div className="universe__orbit" />
        </div>

        {/* --- NEAR: traffic -------------------------------------------- */}
        <div className="universe__depth universe__depth--near">
          <div className="universe__asteroid universe__asteroid--one">
            <AsteroidArt />
          </div>
          <div className="universe__asteroid universe__asteroid--two">
            <AsteroidArt />
          </div>

          {/* Meteors: three trajectories on co-prime cycles. */}
          <div className="universe__meteor universe__meteor--a">
            <MeteorArt />
          </div>
          <div className="universe__meteor universe__meteor--b">
            <MeteorArt />
          </div>
          <div className="universe__meteor universe__meteor--c">
            <MeteorArt />
          </div>

          {/* A rare shower — three streaks arriving as one burst. */}
          <div className="universe__shower">
            <div className="universe__meteor">
              <MeteorArt />
            </div>
            <div className="universe__meteor">
              <MeteorArt />
            </div>
            <div className="universe__meteor">
              <MeteorArt />
            </div>
          </div>

          <div className="universe__rocket">
            <RocketArt />
          </div>
          <div className="universe__satellite">
            <SatelliteArt />
          </div>
          <div className="universe__probe">
            <ProbeArt />
          </div>
          <div className="universe__comet">
            <CometArt />
          </div>
        </div>

        {/* Layer 5 — the readability contract */}
        <div className="universe__scrim" />
      </div>
    </>
  );
}
