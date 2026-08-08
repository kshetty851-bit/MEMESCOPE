"use client";

import { useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { AlphaAccess } from "@/components/alpha/alpha-access";
import { HeroMascot } from "@/components/alpha/hero-mascot";
import { SpaceBackground } from "@/components/alpha/space-background";
import { cn } from "@/lib/utils";

export function LandingPage() {
  const [unlocking, setUnlocking] = useState(false);

  return (
    <main
      className={cn(
        "alpha-landing relative isolate min-h-screen overflow-hidden text-ink",
        unlocking && "alpha-landing--unlock",
      )}
    >
      <SpaceBackground active={unlocking} />
      <div className="alpha-cinematic" aria-hidden>
        <div className="alpha-cinematic__rim alpha-cinematic__rim--left" />
        <div className="alpha-cinematic__rim alpha-cinematic__rim--right" />
        <div className="alpha-cinematic__lens alpha-cinematic__lens--one" />
        <div className="alpha-cinematic__lens alpha-cinematic__lens--two" />
        <div className="alpha-cinematic__vignette" />
      </div>

      <section className="alpha-stage">
        <div className="alpha-stage__depth alpha-stage__depth--back" aria-hidden />
        <div className="alpha-stage__mascot">
          <HeroMascot active={unlocking} />
        </div>
        <div className="alpha-stage__depth alpha-stage__depth--front" aria-hidden />

        <div className="alpha-copy">
          <div className="alpha-logo">
            <LogoMark size={72} className="text-plasma" />
            <p className="alpha-kicker">Private Alpha</p>
          </div>
          <h1>MEMESCOPE</h1>
          <p className="alpha-subtitle">Real-time Pump.fun Intelligence</p>
        </div>

        <div className="alpha-panel">
          <AlphaAccess onUnlocking={setUnlocking} />
        </div>
      </section>
      <div className="alpha-transition" aria-hidden />
    </main>
  );
}
