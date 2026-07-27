/**
 * UNIVERSE LAYERS
 *
 * Every layer is deterministic (seeded, never `Math.random()`) so the sky is
 * identical on server and client and does not reshuffle on re-render.
 *
 * Performance contract for everything in this file:
 *   - static SVG geometry, generated once and memoised by the parent
 *   - motion only via `transform` and `opacity`, which the compositor handles
 *     without layout or paint
 *   - no per-frame JavaScript anywhere
 */

export function seeded(seed: number) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

/* ---------------------------------------------------------------- Stars -- */

export function StarField({ count = 220, seed = 7 }: { count?: number; seed?: number }) {
  const random = seeded(seed);
  const stars = Array.from({ length: count }, () => ({
    x: random() * 100,
    y: random() * 100,
    r: 0.04 + random() * 0.11,
    o: 0.25 + random() * 0.6,
    // Only a tenth of stars twinkle. All of them would read as static noise.
    twinkle: random() > 0.9,
    delay: random() * 9,
  }));

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      className="absolute inset-0 size-full"
      aria-hidden
    >
      {stars.map((star, index) => (
        <circle key={index} cx={star.x} cy={star.y} r={star.r} fill="#fff" opacity={star.o}>
          {star.twinkle && (
            <animate
              attributeName="opacity"
              values={`${star.o};${star.o * 0.25};${star.o}`}
              dur="6s"
              begin={`${star.delay}s`}
              repeatCount="indefinite"
            />
          )}
        </circle>
      ))}
    </svg>
  );
}

/* --------------------------------------------------------------- Nebula -- */

export function Nebula() {
  // Pure CSS gradients — cheaper than any SVG filter and blurred by nature.
  return (
    <div className="absolute inset-0" aria-hidden>
      <div
        className="motion-loop absolute -left-[15%] top-[-10%] size-[70vw] rounded-full opacity-[0.16] blur-[90px]"
        style={{
          background:
            "radial-gradient(circle, var(--color-oracle), transparent 65%)",
          animation: "drift 90s var(--ease-precise) infinite",
        }}
      />
      <div
        className="motion-loop absolute right-[-20%] top-[15%] size-[60vw] rounded-full opacity-[0.13] blur-[100px]"
        style={{
          background:
            "radial-gradient(circle, var(--color-plasma-deep), transparent 65%)",
          animation: "drift 120s var(--ease-precise) infinite reverse",
        }}
      />
      <div
        className="motion-loop absolute bottom-[-25%] left-[25%] size-[55vw] rounded-full opacity-[0.1] blur-[110px]"
        style={{
          background: "radial-gradient(circle, var(--color-titan), transparent 65%)",
          animation: "drift 150s var(--ease-precise) infinite",
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------- Galaxies -- */

export function DistantGalaxies() {
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
      <defs>
        <radialGradient id="galaxy-a">
          <stop offset="0%" stopColor="var(--color-oracle)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <radialGradient id="galaxy-b">
          <stop offset="0%" stopColor="var(--color-plasma)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
      </defs>
      <ellipse cx="18" cy="72" rx="7" ry="1.6" fill="url(#galaxy-a)" transform="rotate(-24 18 72)" />
      <ellipse cx="82" cy="26" rx="5" ry="1.1" fill="url(#galaxy-b)" transform="rotate(18 82 26)" />
    </svg>
  );
}

/* -------------------------------------------------------------- Planet --- */

export function CelestialBody({ goldWash = 0 }: { goldWash?: number }) {
  const random = seeded(31);
  const craters = Array.from({ length: 14 }, () => {
    // Keep craters inside the disc.
    const angle = random() * Math.PI * 2;
    const radius = random() * 0.82;
    return {
      x: 50 + Math.cos(angle) * radius * 48,
      y: 50 + Math.sin(angle) * radius * 48,
      r: 1.4 + random() * 5,
      o: 0.05 + random() * 0.09,
    };
  });

  return (
    <div
      className="absolute -bottom-[22vw] -right-[14vw] size-[52vw] max-h-[760px] max-w-[760px]"
      aria-hidden
    >
      <svg viewBox="0 0 100 100" className="size-full">
        <defs>
          <radialGradient id="moon-body" cx="35%" cy="30%">
            <stop offset="0%" stopColor="oklch(0.42 0.02 265)" />
            <stop offset="60%" stopColor="oklch(0.26 0.018 265)" />
            <stop offset="100%" stopColor="oklch(0.14 0.014 265)" />
          </radialGradient>
          {/* Terminator: the unlit limb, which is what sells it as a sphere
              rather than a flat circle. */}
          <radialGradient id="moon-shadow" cx="30%" cy="26%">
            <stop offset="55%" stopColor="transparent" />
            <stop offset="100%" stopColor="oklch(0.09 0.012 265)" stopOpacity="0.95" />
          </radialGradient>
          <radialGradient id="moon-rim" cx="32%" cy="28%">
            <stop offset="78%" stopColor="transparent" />
            <stop offset="97%" stopColor="var(--color-plasma)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          <radialGradient id="moon-gold" cx="32%" cy="28%">
            <stop offset="0%" stopColor="var(--color-apex)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
        </defs>

        <circle cx="50" cy="50" r="48" fill="url(#moon-body)" />
        {craters.map((crater, index) => (
          <circle
            key={index}
            cx={crater.x}
            cy={crater.y}
            r={crater.r}
            fill="oklch(0.1 0.01 265)"
            opacity={crater.o}
          />
        ))}
        <circle cx="50" cy="50" r="48" fill="url(#moon-shadow)" />
        <circle cx="50" cy="50" r="48" fill="url(#moon-rim)" />

        {/* Elite reflection: the moon catches the Core's golden pulse. */}
        <circle
          cx="50"
          cy="50"
          r="48"
          fill="url(#moon-gold)"
          opacity={goldWash}
          style={{ transition: "opacity 1.8s var(--ease-precise)" }}
        />
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------- Station --- */

export function OrbitalStation() {
  return (
    <div
      className="motion-loop absolute left-[8%] top-[18%] w-[110px] opacity-45"
      style={{ animation: "station-drift 140s var(--ease-precise) infinite" }}
      aria-hidden
    >
      <svg viewBox="0 0 120 60" className="w-full">
        {/* Solar arrays */}
        <rect x="2" y="20" width="30" height="18" fill="var(--color-titan)" opacity="0.22" />
        <rect x="88" y="20" width="30" height="18" fill="var(--color-titan)" opacity="0.22" />
        <path d="M2 20v18M12 20v18M22 20v18M32 20v18M88 20v18M98 20v18M108 20v18M118 20v18"
              stroke="var(--color-line-bright)" strokeWidth="0.5" opacity="0.5" />
        {/* Truss + hull */}
        <rect x="32" y="28" width="56" height="3" fill="var(--color-line-bright)" opacity="0.6" />
        <rect x="48" y="21" width="24" height="17" rx="4" fill="oklch(0.24 0.02 265)" stroke="var(--color-line-bright)" strokeWidth="0.6" />
        <circle cx="60" cy="29.5" r="2.6" fill="var(--color-plasma)" opacity="0.7" />
        {/* Beacon */}
        <circle cx="72" cy="24" r="1.2" fill="var(--color-danger)">
          <animate attributeName="opacity" values="1;0.1;1" dur="3.4s" repeatCount="indefinite" />
        </circle>
      </svg>
    </div>
  );
}

export function Satellites() {
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
      {[
        { r: 34, dur: 180, size: 0.5, tone: "var(--color-plasma)" },
        { r: 44, dur: 260, size: 0.35, tone: "var(--color-scout)" },
      ].map((sat, index) => (
        <g
          key={index}
          className="motion-loop"
          style={{
            animation: `orbit ${sat.dur}s linear infinite${index ? " reverse" : ""}`,
            transformOrigin: "50% 50%",
          }}
        >
          <circle cx={50 + sat.r} cy="50" r={sat.size} fill={sat.tone} opacity="0.85" />
        </g>
      ))}
    </svg>
  );
}

/* -------------------------------------------------------- Crypto glyphs -- */

const GLYPHS: Record<string, string> = {
  // Simplified marks — recognisable at 40px, no vendor logo files needed.
  btc: "M14.2 10.6c1.5-.5 2.4-1.7 2.2-3.5-.3-2.4-2.3-3.2-5-3.4V.5h-2.1v3.1H7.6V.5H5.5v3.1H1.3v2.3s1.5 0 1.5 0c.7 0 .9.4.9.8v8.6c0 .4-.2.6-.6.6H1.6l-.4 2.5h4.3v3.1h2.1v-3.1h1.7v3.1h2.1v-3.2c3.3-.2 5.5-1.1 5.8-4.2.2-2.5-1-3.6-2.9-4.1zM6.9 6.3h2.4c1.6 0 3.3.2 3.3 2.1 0 1.8-1.5 2.1-3.2 2.1H6.9V6.3zm0 11.1v-4.6h2.8c2 0 3.9.3 3.9 2.3 0 2-2.1 2.3-4 2.3H6.9z",
  eth: "M10 0L4 10l6 3.5L16 10 10 0zM4 11.3l6 8.7 6-8.7-6 3.5-6-3.5z",
  sol: "M4.3 14.4a.8.8 0 0 1 .6-.25h13.4c.4 0 .6.5.3.8l-2.6 2.6a.8.8 0 0 1-.6.25H2c-.4 0-.6-.5-.3-.8l2.6-2.6zM4.3 2.4a.8.8 0 0 1 .6-.25h13.4c.4 0 .6.5.3.8l-2.6 2.6a.8.8 0 0 1-.6.25H2c-.4 0-.6-.5-.3-.8l2.6-2.6zM15.7 8.4a.8.8 0 0 0-.6-.25H1.7c-.4 0-.6.5-.3.8l2.6 2.6c.16.16.38.25.6.25h13.4c.4 0 .6-.5.3-.8l-2.6-2.6z",
};

export function CryptoGlyphs() {
  const items = [
    { id: "btc", x: 74, y: 62, size: 46, dur: 68, delay: 0 },
    { id: "eth", x: 12, y: 46, size: 38, dur: 84, delay: 12 },
    { id: "sol", x: 58, y: 20, size: 34, dur: 96, delay: 26 },
  ];

  return (
    <div className="absolute inset-0" aria-hidden>
      {items.map((item) => (
        <div
          key={item.id}
          className="motion-loop absolute"
          style={{
            left: `${item.x}%`,
            top: `${item.y}%`,
            width: item.size,
            height: item.size,
            animation: `float-glyph ${item.dur}s var(--ease-precise) infinite`,
            animationDelay: `-${item.delay}s`,
          }}
        >
          <svg viewBox="0 0 20 20" className="size-full">
            {/* Holographic containment ring + mark. Deliberately faint: these
                are set dressing, not branding. */}
            <circle cx="10" cy="10" r="9.4" fill="none" stroke="var(--color-plasma)"
                    strokeWidth="0.25" strokeDasharray="1 2.4" opacity="0.5" />
            <path d={GLYPHS[item.id]} fill="var(--color-plasma)" opacity="0.24" />
          </svg>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- Asteroids -- */

export function Asteroids({ seed = 91 }: { seed?: number }) {
  const random = seeded(seed);
  const rocks = Array.from({ length: 7 }, () => ({
    x: random() * 100,
    y: random() * 100,
    s: 0.25 + random() * 0.5,
    dur: 120 + random() * 120,
    delay: random() * 60,
    rot: random() * 360,
  }));

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
      {rocks.map((rock, index) => (
        <g
          key={index}
          className="motion-loop"
          style={{
            animation: `asteroid ${rock.dur}s linear infinite`,
            animationDelay: `-${rock.delay}s`,
          }}
        >
          <polygon
            points="0,-1 0.8,-0.4 0.7,0.6 -0.2,1 -0.9,0.3 -0.8,-0.5"
            transform={`translate(${rock.x} ${rock.y}) scale(${rock.s}) rotate(${rock.rot})`}
            fill="oklch(0.4 0.02 265)"
            opacity="0.5"
          />
        </g>
      ))}
    </svg>
  );
}

/* ---------------------------------------------------------- Data streams -- */

export function DataStreams({ density = 0.4 }: { density?: number }) {
  const random = seeded(53);
  const count = 3 + Math.round(density * 6);
  const streams = Array.from({ length: count }, () => ({
    y: 8 + random() * 84,
    dur: 14 + random() * 18,
    delay: random() * 20,
    tone: random() > 0.6 ? "var(--color-scout)" : "var(--color-plasma)",
  }));

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
      {streams.map((stream, index) => (
        <line
          key={index}
          x1="-10"
          y1={stream.y}
          x2="6"
          y2={stream.y}
          stroke={stream.tone}
          strokeWidth="0.12"
          opacity="0.55"
          className="motion-loop"
          style={{
            animation: `stream ${stream.dur}s linear infinite`,
            animationDelay: `-${stream.delay}s`,
          }}
        />
      ))}
    </svg>
  );
}

/* ------------------------------------------------------------- Particles -- */

export function ParticleField({ density = 0.4, seed = 17 }: { density?: number; seed?: number }) {
  const random = seeded(seed);
  // Scales with market activity: a quiet chain gets a calm sky.
  const count = 18 + Math.round(density * 46);
  const motes = Array.from({ length: count }, () => ({
    x: random() * 100,
    y: random() * 100,
    r: 0.05 + random() * 0.12,
    dur: 50 + random() * 70,
    delay: random() * 60,
  }));

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden>
      {motes.map((mote, index) => (
        <circle
          key={index}
          cx={mote.x}
          cy={mote.y}
          r={mote.r}
          fill="var(--color-plasma)"
          opacity="0.5"
          className="motion-loop"
          style={{
            animation: `mote ${mote.dur}s linear infinite`,
            animationDelay: `-${mote.delay}s`,
          }}
        />
      ))}
    </svg>
  );
}
