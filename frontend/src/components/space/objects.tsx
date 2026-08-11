import type { SVGProps } from "react";

/**
 * MEMESCOPE UNIVERSE — the illustrated objects.
 *
 * Phase 7 drew these as CSS primitives: the rocket was a 14×4 rounded rect, the
 * satellite a bar with two `::before`/`::after` panels. That was the right call
 * for the architecture and the wrong one for the identity — at any size where a
 * viewer could actually see them, they read as coloured slivers.
 *
 * These replace the slivers. **The animation architecture is unchanged** — each
 * is still one element positioned and moved by the same CSS keyframes, so the
 * scene still costs zero JavaScript per frame and still animates only
 * `transform` and `opacity`.
 *
 * WHY INLINE SVG RATHER THAN IMAGES
 *
 *   - No network request, no layout shift, nothing to preload.
 *   - Sharp from a 12px distant satellite to a 240px hero rocket.
 *   - Paths inside an `<svg>` do not participate in layout, so a twenty-path
 *     illustration is one box to the engine — the "don't build objects from
 *     hundreds of DOM nodes" rule is about *layout* nodes, and this respects it.
 *   - Colour flows from the design tokens, so nothing here can drift from the
 *     palette the way a baked PNG would.
 *
 * Every object is `aria-hidden` at the source. None of this is information.
 *
 * A note on the gradient ids below: they are static rather than `useId`-scoped,
 * so two instances of the same object share one `<defs>` id. That is deliberate
 * — every instance of a given object defines an *identical* gradient, so the
 * duplicate resolves to the same paint, and scoping them would turn these into
 * client components for no visual difference. If an object ever needs a
 * per-instance gradient, it needs `useId` at that point and not before.
 */

type Art = SVGProps<SVGSVGElement>;

const base = {
  "aria-hidden": true as const,
  focusable: "false" as const,
  xmlns: "http://www.w3.org/2000/svg",
};

/* ==========================================================================
   ROCKET — the hero of the homepage, and a distant speck in the terminal.
   ========================================================================== */

export function RocketArt(props: Art) {
  return (
    <svg viewBox="0 0 64 130" {...base} {...props}>
      <defs>
        <linearGradient id="ms-rk-body" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#e9edf5" />
          <stop offset="45%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#b9c2d4" />
        </linearGradient>
      </defs>

      {/* Nose */}
      <path d="M32 2c9 14 13 26 13 36H19c0-10 4-22 13-36z" fill="#e0483c" />
      {/* Fuselage */}
      <path d="M19 38h26v74a34 34 0 0 1-13 12 34 34 0 0 1-13-12V38z" fill="url(#ms-rk-body)" />
      {/* Fins */}
      <path d="M19 84 6 118l13-6V84z" fill="#e0483c" />
      <path d="M45 84l13 34-13-6V84z" fill="#e0483c" />
      <path d="M32 96v26l-6 6V108z" fill="#c93a30" opacity="0.55" />
      {/* Porthole */}
      <circle cx="32" cy="60" r="12" fill="#9aa6bd" />
      <circle cx="32" cy="60" r="9" fill="#3f9ad6" />
      <path d="M25 55a9 9 0 0 1 11-3l-11 8z" fill="#bfe3ff" opacity="0.7" />
      {/* Skirt */}
      <rect x="21" y="120" width="22" height="8" rx="2" fill="#8f99ad" />
    </svg>
  );
}

/**
 * The pad the hero rocket sits on.
 *
 * Drawn wider than the ship and slightly below it, so the ship reads as
 * *standing on* something rather than hovering above a decal. The lamps carry
 * a class rather than a fill, because whether the station is powered is a
 * sequence state and belongs in the stylesheet with the rest of the countdown.
 */
export function LaunchPadArt(props: Art) {
  return (
    <svg viewBox="0 0 220 96" {...base} {...props}>
      {/* Deck */}
      <path d="M46 26h128l16 26H30l16-26z" fill="#2f333c" />
      <rect x="30" y="50" width="160" height="12" rx="3" fill="#3c414c" />
      <rect x="30" y="50" width="160" height="4" rx="2" fill="#525968" opacity="0.8" />
      {/* Flame trench */}
      <ellipse cx="110" cy="30" rx="30" ry="9" fill="#14161c" />
      {/* Legs */}
      <g stroke="#3c414c" strokeWidth="7" strokeLinecap="round">
        <path d="M52 62 38 92M168 62l14 30M84 62l-6 30M136 62l6 30" />
      </g>
      {/* Gantry, leaning toward the ship */}
      <path d="M186 8h9v54h-9z" fill="#454b58" />
      <path d="M186 8h9v54h-9z" fill="none" stroke="#5b6373" strokeWidth="1.5" />
      <path d="M160 20h27M164 34h23" stroke="#5b6373" strokeWidth="5" strokeLinecap="round" />
      <circle cx="190.5" cy="4" r="4" className="home-universe__pad-lamp" fill="#e0483c" />
      {/* Console lamps */}
      <g className="home-universe__pad-lamp">
        <circle cx="60" cy="56" r="3.2" fill="#3f9ad6" />
        <circle cx="110" cy="56" r="3.2" fill="#3f9ad6" />
        <circle cx="160" cy="56" r="3.2" fill="#3f9ad6" />
      </g>
    </svg>
  );
}

/** Engine flame. Separate so it can be shown, hidden and pulsed on its own. */
export function RocketFlame(props: Art) {
  return (
    <svg viewBox="0 32 40 58" {...base} {...props}>
      <path d="M20 90C8 66 4 50 8 34c4 10 8 14 12 16 4-2 8-6 12-16 4 16 0 32-12 56z" fill="#f7a23b" />
      <path d="M20 78C13 62 11 51 13 40c3 7 5 10 7 11 2-1 4-4 7-11 2 11 0 22-7 38z" fill="#ffd76e" />
    </svg>
  );
}

/* ==========================================================================
   SATELLITES
   ========================================================================== */

/** Solar-panel satellite, as in the reference's upper left. */
export function SatelliteArt(props: Art) {
  return (
    <svg viewBox="0 0 120 56" {...base} {...props}>
      {/* Panels */}
      <g fill="#2b62b8" stroke="#8fb4e8" strokeWidth="1.5">
        <rect x="2" y="14" width="34" height="26" rx="2" />
        <rect x="84" y="14" width="34" height="26" rx="2" />
      </g>
      <g stroke="#8fb4e8" strokeWidth="1" opacity="0.8">
        <path d="M13 14v26M24.5 14v26M95 14v26M106.5 14v26M2 27h34M84 27h34" />
      </g>
      {/* Booms + body */}
      <path d="M36 27h12M72 27h12" stroke="#b8c2d6" strokeWidth="2.5" />
      <rect x="48" y="16" width="24" height="24" rx="4" fill="#dbe2ee" stroke="#98a3b8" strokeWidth="1.5" />
      <rect x="53" y="21" width="14" height="6" rx="1.5" fill="#7f8b9f" />
      {/* Dish */}
      <ellipse cx="60" cy="47" rx="11" ry="5" fill="#e6ebf3" stroke="#98a3b8" strokeWidth="1.2" />
      <path d="M60 40v7" stroke="#98a3b8" strokeWidth="1.5" />
      <circle cx="60" cy="39" r="2" fill="#e0483c" />
    </svg>
  );
}

/** Dish-forward comms probe, as in the reference's mid-right. */
export function ProbeArt(props: Art) {
  return (
    <svg viewBox="0 0 96 72" {...base} {...props}>
      <ellipse cx="40" cy="26" rx="30" ry="18" fill="#eef2f8" stroke="#9aa6bd" strokeWidth="1.5" transform="rotate(-18 40 26)" />
      <ellipse cx="40" cy="26" rx="18" ry="10" fill="#cfd8e6" opacity="0.7" transform="rotate(-18 40 26)" />
      <circle cx="40" cy="26" r="4" fill="#e0483c" />
      <path d="M44 34 62 54" stroke="#9aa6bd" strokeWidth="3" />
      <rect x="58" y="50" width="22" height="16" rx="3" fill="#dbe2ee" stroke="#98a3b8" strokeWidth="1.5" />
      <rect x="80" y="53" width="14" height="10" rx="1.5" fill="#2b62b8" stroke="#8fb4e8" strokeWidth="1.2" />
    </svg>
  );
}

/* ==========================================================================
   PLANETS — four bodies at different depths.
   ========================================================================== */

/** Saturn-like ringed planet. */
export function RingedPlanetArt(props: Art) {
  return (
    <svg viewBox="0 0 200 140" {...base} {...props}>
      <ellipse cx="100" cy="70" rx="92" ry="26" fill="none" stroke="#e0b464" strokeWidth="7" opacity="0.85" />
      <ellipse cx="100" cy="70" rx="78" ry="19" fill="none" stroke="#f0d49a" strokeWidth="3" opacity="0.6" />
      <circle cx="100" cy="70" r="44" fill="#d9b273" />
      <path d="M60 54h80M58 70h84M62 86h76" stroke="#c49a5c" strokeWidth="5" opacity="0.55" strokeLinecap="round" />
      <path d="M100 26a44 44 0 0 0-31 75 44 44 0 0 1 43-72 44 44 0 0 0-12-3z" fill="#f0d3a1" opacity="0.35" />
      <ellipse cx="100" cy="70" rx="92" ry="26" fill="none" stroke="#e0b464" strokeWidth="7" opacity="0.5" strokeDasharray="150 400" />
    </svg>
  );
}

/** Mars-like body — the reference's large red planet. */
export function RedPlanetArt(props: Art) {
  return (
    <svg viewBox="0 0 160 160" {...base} {...props}>
      <circle cx="80" cy="80" r="76" fill="#c9482c" />
      <circle cx="80" cy="80" r="76" fill="url(#ms-pl-shade)" />
      <defs>
        <radialGradient id="ms-pl-shade" cx="0.34" cy="0.3" r="0.85">
          <stop offset="0%" stopColor="#ff8b5e" stopOpacity="0.55" />
          <stop offset="60%" stopColor="#000000" stopOpacity="0" />
          <stop offset="100%" stopColor="#2b0a04" stopOpacity="0.6" />
        </radialGradient>
      </defs>
      <g fill="#a5361f" opacity="0.85">
        <ellipse cx="54" cy="52" rx="16" ry="12" />
        <ellipse cx="104" cy="46" rx="10" ry="8" />
        <ellipse cx="118" cy="96" rx="14" ry="10" />
        <ellipse cx="62" cy="112" rx="11" ry="8" />
        <ellipse cx="86" cy="78" rx="7" ry="6" />
      </g>
    </svg>
  );
}

/** Icy blue world — the reference's small striped planets. */
export function BluePlanetArt(props: Art) {
  return (
    <svg viewBox="0 0 120 120" {...base} {...props}>
      <circle cx="60" cy="60" r="56" fill="#2f7fc4" />
      <g stroke="#8fd0f5" strokeWidth="5" opacity="0.75" strokeLinecap="round">
        <path d="M20 40h80M14 58h92M20 76h80M32 94h56" />
      </g>
      <circle cx="60" cy="60" r="56" fill="url(#ms-pl-blue)" />
      <defs>
        <radialGradient id="ms-pl-blue" cx="0.33" cy="0.3" r="0.85">
          <stop offset="0%" stopColor="#cfefff" stopOpacity="0.45" />
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#03203c" stopOpacity="0.6" />
        </radialGradient>
      </defs>
    </svg>
  );
}

/** Cratered moon. */
export function MoonArt(props: Art) {
  return (
    <svg viewBox="0 0 120 120" {...base} {...props}>
      <circle cx="60" cy="60" r="56" fill="#c3c7ce" />
      <g fill="#a3a8b2">
        <circle cx="44" cy="44" r="12" />
        <circle cx="80" cy="62" r="9" />
        <circle cx="54" cy="86" r="7" />
        <circle cx="90" cy="34" r="5" />
        <circle cx="32" cy="72" r="6" />
      </g>
      <circle cx="60" cy="60" r="56" fill="url(#ms-pl-moon)" />
      <defs>
        <radialGradient id="ms-pl-moon" cx="0.33" cy="0.3" r="0.85">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.35" />
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#1a1c22" stopOpacity="0.55" />
        </radialGradient>
      </defs>
    </svg>
  );
}

/* ==========================================================================
   TRAVELLERS
   ========================================================================== */

export function AsteroidArt(props: Art) {
  return (
    <svg viewBox="0 0 60 48" {...base} {...props}>
      <path
        d="M14 6c8-5 20-7 30-1 9 6 14 15 12 24-2 8-11 14-22 15-11 1-22-4-27-13C2 22 6 11 14 6z"
        fill="#5d5f66"
      />
      <g fill="#46484e">
        <circle cx="24" cy="20" r="5" />
        <circle cx="40" cy="30" r="4" />
        <circle cx="18" cy="33" r="3" />
      </g>
    </svg>
  );
}

/** Comet: nucleus plus a long soft tail, drawn as one object. */
export function CometArt(props: Art) {
  return (
    <svg viewBox="0 0 260 60" {...base} {...props}>
      <defs>
        <linearGradient id="ms-cm-tail" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0%" stopColor="#cfe6ff" stopOpacity="0.85" />
          <stop offset="55%" stopColor="#8fb6ff" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#8fb6ff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M240 30 20 14c40 10 40 22 0 32z" fill="url(#ms-cm-tail)" />
      <circle cx="242" cy="30" r="7" fill="#eaf5ff" />
      <circle cx="242" cy="30" r="12" fill="#bfe0ff" opacity="0.35" />
    </svg>
  );
}

/** Meteor: a burning head with a flame trail, as in the reference. */
export function MeteorArt(props: Art) {
  return (
    <svg viewBox="0 0 200 60" {...base} {...props}>
      <defs>
        <linearGradient id="ms-mt-trail" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0%" stopColor="#ffb648" />
          <stop offset="45%" stopColor="#ff7a2f" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#ff7a2f" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M168 30 10 18c30 8 30 16 0 24z" fill="url(#ms-mt-trail)" />
      <path d="M186 30c0 9-8 16-18 16s-18-7-18-16 8-16 18-16 18 7 18 16z" fill="#6b5a4e" />
      <g fill="#4f4239">
        <circle cx="168" cy="26" r="3.5" />
        <circle cx="176" cy="35" r="2.5" />
      </g>
    </svg>
  );
}

/* ==========================================================================
   HOMEPAGE-ONLY OBJECTS
   ========================================================================== */

/** Floating astronaut. Homepage only — never over a data table. */
export function AstronautArt(props: Art) {
  return (
    <svg viewBox="0 0 120 150" {...base} {...props}>
      {/* Limbs behind the torso */}
      <g fill="#eef1f6" stroke="#b6bfcd" strokeWidth="2.5" strokeLinejoin="round">
        <path d="M34 74 14 92l8 10 20-16z" />
        <path d="M86 74l20 12-6 12-22-14z" />
        <path d="M44 118l-6 26h14l6-24z" />
        <path d="M72 118l8 24h14l-8-26z" />
      </g>
      {/* Torso */}
      <rect x="34" y="52" width="52" height="70" rx="20" fill="#f7f9fc" stroke="#b6bfcd" strokeWidth="2.5" />
      {/* Chest panel */}
      <rect x="48" y="72" width="24" height="16" rx="3" fill="#cfd7e4" stroke="#98a3b8" strokeWidth="1.5" />
      <g fill="#3f9ad6">
        <rect x="51" y="75" width="6" height="4" rx="1" />
        <rect x="60" y="75" width="6" height="4" rx="1" />
        <rect x="51" y="81" width="6" height="4" rx="1" />
      </g>
      <path d="M40 62h40" stroke="#e0483c" strokeWidth="2" opacity="0.65" />
      {/* Helmet */}
      <circle cx="60" cy="36" r="30" fill="#f7f9fc" stroke="#b6bfcd" strokeWidth="2.5" />
      <circle cx="60" cy="36" r="22" fill="#141c2b" />
      <path d="M44 26a22 22 0 0 1 22-8 22 22 0 0 0-18 22z" fill="#5aa9e0" opacity="0.5" />
      {/* Backpack edge */}
      <rect x="28" y="60" width="10" height="34" rx="4" fill="#dfe5ee" stroke="#b6bfcd" strokeWidth="2" />
    </svg>
  );
}

/** Six-wheeled lunar rover. */
export function RoverArt(props: Art) {
  return (
    <svg viewBox="0 0 180 100" {...base} {...props}>
      {/* Dish mast */}
      <path d="M30 52V26" stroke="#b6bfcd" strokeWidth="3" />
      <ellipse cx="30" cy="22" rx="14" ry="6" fill="#eef2f8" stroke="#9aa6bd" strokeWidth="1.5" />
      <circle cx="30" cy="20" r="2.5" fill="#e0483c" />
      {/* Body */}
      <path d="M46 44h96a8 8 0 0 1 8 8v18H38V52a8 8 0 0 1 8-8z" fill="#eef1f6" stroke="#9aa6bd" strokeWidth="2.5" />
      <rect x="96" y="50" width="40" height="14" rx="2" fill="#8fb4e8" stroke="#6d8cbb" strokeWidth="1.5" />
      <rect x="50" y="50" width="26" height="10" rx="2" fill="#cfd7e4" />
      {/* Wheels */}
      <g fill="#3d4149" stroke="#9aa6bd" strokeWidth="2">
        <circle cx="56" cy="78" r="13" />
        <circle cx="94" cy="78" r="13" />
        <circle cx="132" cy="78" r="13" />
      </g>
      <g fill="#7c828d">
        <circle cx="56" cy="78" r="4" />
        <circle cx="94" cy="78" r="4" />
        <circle cx="132" cy="78" r="4" />
      </g>
    </svg>
  );
}

/** Lunar module — a stationary anchor that makes the surface feel inhabited. */
export function LunarModuleArt(props: Art) {
  return (
    <svg viewBox="0 0 200 180" {...base} {...props}>
      {/* Legs */}
      <g stroke="#c8892f" strokeWidth="6" strokeLinecap="round" fill="none">
        <path d="M64 108 34 158M136 108l30 50M78 116 62 158M122 116l16 42" />
        <path d="M22 158h24M154 158h24" strokeWidth="7" />
      </g>
      {/* Ladder */}
      <g stroke="#c8892f" strokeWidth="4">
        <path d="M92 116v42M112 116v42M92 126h20M92 138h20M92 150h20" />
      </g>
      {/* Body */}
      <path d="M62 52h76a10 10 0 0 1 10 10v46a8 8 0 0 1-8 8H60a8 8 0 0 1-8-8V62a10 10 0 0 1 10-10z" fill="#eef1f6" stroke="#9aa6bd" strokeWidth="3" />
      <rect x="70" y="66" width="24" height="20" rx="3" fill="#8fb4e8" stroke="#6d8cbb" strokeWidth="1.5" />
      <rect x="106" y="66" width="24" height="20" rx="3" fill="#8fb4e8" stroke="#6d8cbb" strokeWidth="1.5" />
      {/* Antenna */}
      <path d="M100 52V22" stroke="#b6bfcd" strokeWidth="3" />
      <circle cx="100" cy="18" r="6" fill="#dfe5ee" stroke="#9aa6bd" strokeWidth="2" />
    </svg>
  );
}
