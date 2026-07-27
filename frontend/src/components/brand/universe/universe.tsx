"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  Asteroids,
  CelestialBody,
  CryptoGlyphs,
  DataStreams,
  DistantGalaxies,
  Nebula,
  OrbitalStation,
  ParticleField,
  Satellites,
  StarField,
} from "@/components/brand/universe/layers";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import {
  getUniverseActivity,
  onUniverseActivity,
  onUniverseEvent,
  type UniverseEvent,
} from "@/lib/universe-events";
import { cn } from "@/lib/utils";

/**
 * THE UNIVERSE
 *
 * The view through the observation window. Six parallax planes, from deep
 * stars that barely move to foreground debris that drifts perceptibly, so the
 * scene has depth without anything ever competing with the interface.
 *
 * Three hard rules, because a background that costs frames is a bug:
 *   1. Zero per-frame JavaScript. All motion is CSS on `transform`/`opacity`.
 *   2. Layers are memoised — geometry is generated once, never on re-render.
 *   3. The whole thing is `.ambient`, so Command mode and reduced-motion
 *      remove it outright rather than merely slowing it down.
 *
 * Parallax follows the pointer through two CSS variables written at most once
 * per frame by a single passive listener. That is the only JS that runs, and
 * it is disabled on touch, in Command mode and under reduced motion.
 */

const MAX_EVENTS = 6;

export function Universe({
  /** Calmer, cheaper variant for auth and error screens. */
  minimal = false,
  parallax = true,
  className,
}: {
  minimal?: boolean;
  parallax?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const root = useRef<HTMLDivElement>(null);

  const [activity, setActivity] = useState(getUniverseActivity);
  const [events, setEvents] = useState<UniverseEvent[]>([]);
  const [goldWash, setGoldWash] = useState(0);

  // --- Live activity -------------------------------------------------------
  useEffect(() => onUniverseActivity(setActivity), []);

  // --- Event reactions -----------------------------------------------------
  useEffect(
    () =>
      onUniverseEvent((event) => {
        setEvents((current) => [...current.slice(-(MAX_EVENTS - 1)), event]);

        if (event.type === "elite") {
          // The moon catches the Core's golden pulse, then lets it go.
          setGoldWash(1);
          window.setTimeout(() => setGoldWash(0), 2600);
        }
      }),
    [],
  );

  // Retire finished animations so the DOM does not grow without bound.
  useEffect(() => {
    if (events.length === 0) return;
    const timer = window.setTimeout(() => setEvents((current) => current.slice(1)), 4200);
    return () => window.clearTimeout(timer);
  }, [events]);

  // --- Pointer parallax ----------------------------------------------------
  useEffect(() => {
    if (!parallax || reduced || typeof window === "undefined") return;
    if (window.matchMedia("(pointer: coarse)").matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) return; // coalesce to one write per frame
      frame = requestAnimationFrame(() => {
        frame = 0;
        const x = event.clientX / window.innerWidth - 0.5;
        const y = event.clientY / window.innerHeight - 0.5;
        root.current?.style.setProperty("--px", x.toFixed(4));
        root.current?.style.setProperty("--py", y.toFixed(4));
      });
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [parallax, reduced]);

  // Geometry is expensive to generate and never needs to change with events.
  const deep = useMemo(() => <StarField count={minimal ? 120 : 240} />, [minimal]);
  const mid = useMemo(
    () => (
      <>
        <DistantGalaxies />
        <Satellites />
        <Asteroids />
      </>
    ),
    [],
  );

  return (
    <div
      ref={root}
      aria-hidden
      className={cn(
        // `.ambient`: Command mode and reduced motion remove the sky entirely.
        "ambient pointer-events-none fixed inset-0 -z-10 overflow-hidden",
        className,
      )}
      style={{ ["--px" as string]: 0, ["--py" as string]: 0 }}
    >
      {/* Plane 1 — deep stars. Barely parallax; they are effectively at infinity. */}
      <div
        className="absolute inset-[-2%] will-change-transform"
        style={{ transform: "translate3d(calc(var(--px) * -6px), calc(var(--py) * -6px), 0)" }}
      >
        {deep}
      </div>

      {/* Plane 2 — nebula. */}
      <div
        className="absolute inset-[-6%] will-change-transform"
        style={{ transform: "translate3d(calc(var(--px) * -14px), calc(var(--py) * -14px), 0)" }}
      >
        <Nebula />
      </div>

      {/* Plane 3 — galaxies, satellites, debris. */}
      <div
        className="absolute inset-[-4%] will-change-transform"
        style={{ transform: "translate3d(calc(var(--px) * -24px), calc(var(--py) * -24px), 0)" }}
      >
        {mid}
      </div>

      {/* Plane 4 — the planet. Large mass, small movement. */}
      {!minimal && (
        <div
          className="absolute inset-0 will-change-transform"
          style={{ transform: "translate3d(calc(var(--px) * -18px), calc(var(--py) * -12px), 0)" }}
        >
          <CelestialBody goldWash={goldWash} />
        </div>
      )}

      {/* Plane 5 — station, glyphs, data streams. */}
      {!minimal && (
        <div
          className="absolute inset-0 will-change-transform"
          style={{ transform: "translate3d(calc(var(--px) * -40px), calc(var(--py) * -30px), 0)" }}
        >
          <OrbitalStation />
          <CryptoGlyphs />
          <DataStreams density={activity} />
        </div>
      )}

      {/* Plane 6 — foreground motes. Most movement, least contrast. */}
      <div
        className="absolute inset-[-3%] will-change-transform"
        style={{ transform: "translate3d(calc(var(--px) * -60px), calc(var(--py) * -46px), 0)" }}
      >
        <ParticleField density={activity} />
      </div>

      {/* --- Event layer ---------------------------------------------------
          Every reaction is single-shot and unmounts itself. */}
      {events.map((event) => (
        <UniverseReaction key={event.id} event={event} />
      ))}

      {/* Vignette: keeps the sky off the edges of the UI, where it would
          fight the chrome. Always last, always on top of the scene. */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_72%_60%_at_50%_45%,transparent,var(--color-void)_92%)]" />
    </div>
  );
}

/* ------------------------------------------------------------- Reactions -- */

function UniverseReaction({ event }: { event: UniverseEvent }) {
  if (event.type === "discovery") {
    // A launch from the planet's limb: Scout has found something down there.
    return (
      <div
        className="absolute bottom-[16%] right-[26%] h-[42vh] w-px origin-bottom"
        style={{ animation: "rocket 3.6s var(--ease-precise) forwards" }}
      >
        <div
          className="size-full"
          style={{
            background:
              "linear-gradient(to top, transparent, var(--color-scout) 55%, transparent)",
          }}
        />
        <span
          className="absolute -top-1 left-1/2 size-1.5 -translate-x-1/2 rounded-full"
          style={{
            background: "var(--color-scout)",
            boxShadow: "0 0 10px var(--color-scout)",
          }}
        />
      </div>
    );
  }

  const tone =
    event.type === "whale"
      ? "var(--color-titan)"
      : event.type === "threat"
        ? "var(--color-danger)"
        : "var(--color-apex)";

  return (
    <div
      className="absolute left-1/2 top-1/2 aspect-square w-[36vw] -translate-x-1/2 -translate-y-1/2 rounded-full border"
      style={{
        borderColor: tone,
        animation: "wave 3.2s var(--ease-instrument) forwards",
      }}
    />
  );
}
