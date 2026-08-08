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
        "alpha-landing relative isolate flex min-h-screen overflow-hidden px-5 py-8 text-ink",
        unlocking && "alpha-landing--unlock",
      )}
    >
      <SpaceBackground active={unlocking} />
      <div className="mx-auto grid w-full max-w-7xl items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(420px,0.82fr)]">
        <section className="alpha-copy mx-auto flex w-full max-w-2xl flex-col items-center text-center lg:items-start lg:text-left">
          <div className="alpha-logo flex flex-col items-center gap-5 lg:items-start">
            <LogoMark size={78} className="text-plasma" />
            <div>
              <h1 className="text-[clamp(2rem,11vw,2.65rem)] font-semibold leading-none tracking-[0.04em] text-ink sm:text-[clamp(2.7rem,9vw,5rem)] sm:tracking-[0.12em] lg:text-[clamp(2.7rem,7vw,5.6rem)] lg:tracking-[0.13em]">
                MEMESCOPE
              </h1>
              <p className="mt-4 text-sm tracking-[0.12em] text-ink-dim sm:text-lg sm:tracking-[0.22em]">
                Real-time Pump.fun Intelligence
              </p>
            </div>
          </div>

          <div className="mt-10 w-full max-w-sm">
            <AlphaAccess onUnlocking={setUnlocking} />
          </div>
        </section>

        <section className="alpha-hero relative mx-auto min-h-[420px] w-full max-w-[520px] lg:min-h-[680px]">
          <HeroMascot active={unlocking} />
        </section>
      </div>
      <div className="alpha-transition" aria-hidden />
    </main>
  );
}
