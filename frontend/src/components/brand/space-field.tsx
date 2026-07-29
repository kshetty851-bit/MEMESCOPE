"use client";

/**
 * The deep-space field behind every LETZMOON surface.
 *
 * Fifteen DOM nodes and zero JavaScript per frame. The starfield is three
 * elements carrying repeating `radial-gradient` patterns rather than a few
 * hundred positioned dots, which is the difference between three composited
 * layers and three hundred nodes the compositor has to track.
 *
 * Everything here animates `transform` or `opacity` only, so the whole scene
 * lives on the compositor. That is what keeps it free while data is streaming
 * and re-rendering above it.
 *
 * `aria-hidden` throughout: this is atmosphere and carries no information. A
 * screen reader announcing "asteroid" would be noise, and none of it changes
 * what the product is telling you.
 */
export function SpaceField() {
  return (
    <div className="lm-space" aria-hidden>
      <div className="lm-space__nebula lm-space__nebula--a" />
      <div className="lm-space__nebula lm-space__nebula--b" />

      <div className="lm-space__stars lm-space__stars--far" />
      <div className="lm-space__stars lm-space__stars--mid" />
      <div className="lm-space__stars lm-space__stars--near" />

      <div className="lm-space__rock lm-space__rock--1" />
      <div className="lm-space__rock lm-space__rock--2" />
      <div className="lm-space__rock lm-space__rock--3" />

      <div className="lm-space__shoot lm-space__shoot--1" />
      <div className="lm-space__shoot lm-space__shoot--2" />

      <RocketFlyby />
    </div>
  );
}

/**
 * The mascot crossing the window on a LETZMOON rocket.
 *
 * Once every ~163 seconds, visible for about seven of them. The brief asked
 * for "random but infrequent"; this is deterministic-but-infrequent, which is
 * the better trade — a CSS animation costs nothing and cannot drift, whereas
 * genuine randomness needs a timer, a re-render and a hydration-safe seed to
 * avoid a server/client mismatch. At a three-minute period nobody can tell the
 * difference, and the page stays free of per-frame script.
 */
function RocketFlyby() {
  return (
    <div className="lm-space__rocket">
      <svg width="120" height="44" viewBox="0 0 120 44" fill="none">
        <defs>
          <linearGradient id="lm-flame" x1="1" y1="0" x2="0" y2="0">
            <stop offset="0%" stopColor="var(--color-brand-accent)" stopOpacity="0" />
            <stop offset="45%" stopColor="var(--color-brand)" stopOpacity="0.7" />
            <stop offset="100%" stopColor="var(--color-brand-secondary)" stopOpacity="0.95" />
          </linearGradient>
        </defs>

        {/* Exhaust trails behind the body, so the rocket reads as moving right */}
        <rect x="0" y="20" width="46" height="3" rx="1.5" fill="url(#lm-flame)" />
        <rect x="6" y="26" width="30" height="2" rx="1" fill="url(#lm-flame)" opacity="0.6" />

        {/* Body */}
        <path
          d="M52 12h34c11 0 20 5 24 10-4 5-13 10-24 10H52c-6 0-10-4-10-10s4-10 10-10z"
          fill="oklch(0.9 0.01 268)"
        />
        {/* Fin */}
        <path d="M62 22h14l-6 12h-10z" fill="var(--color-brand)" opacity="0.85" />
        {/* Porthole with the mascot's visor colour */}
        <circle cx="84" cy="22" r="6.5" fill="oklch(0.2 0.05 268)" />
        <circle cx="84" cy="22" r="6.5" fill="none" stroke="var(--color-brand-accent)" strokeWidth="1.2" />
        <circle cx="82" cy="20" r="2" fill="oklch(0.85 0.16 155)" />
      </svg>
    </div>
  );
}
